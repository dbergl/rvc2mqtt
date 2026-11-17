"""
Unit tests for the virtual inverter entity.
"""
import json
import os
import queue
import unittest
from unittest.mock import MagicMock
import context  # add rvc2mqtt package to the python path using local reference
import rvc2mqtt
from rvc2mqtt.rvc import RVC_Decoder
from rvc2mqtt.entity.virtual_inverter import VirtualInverter


def _make_mock():
    mock = MagicMock()
    mock.make_device_topic_string.return_value = 'test/topic'
    mock.TOPIC_BASE = 'rvc2mqtt'
    mock.client_id = 'bridge'
    mock.get_bridge_ha_name.return_value = 'bridge'
    mock.bridge_state_topic = 'rvc2mqtt/bridge/state'
    mock.make_ha_auto_discovery_config_topic.side_effect = (
        lambda id, comp, sub=None: f'homeassistant/{comp}/{id}/{sub}/config')
    return mock


def _make_entity(extra: dict = None, now: float = 1000.0):
    mock = _make_mock()
    data = {
        'name': 'VIRTUAL_INVERTER',
        'type': 'virtual_inverter',
        'instance': 1,
        'instance_name': 'renogy',
        'status_topic': 'rvc/state/inverter',
        'command_topic': 'rvc/set/inverter',
    }
    if extra:
        data.update(extra)
    entity = VirtualInverter(data, mock)
    clock = {'now': now}
    entity._clock = lambda: clock['now']
    entity.set_rvc_send_queue(queue.Queue())
    return entity, mock, clock


def _registered(mock) -> dict:
    """topic -> (callback, retain_ok) from mock.register calls."""
    out = {}
    for c in mock.register.call_args_list:
        args, kwargs = c
        topic, func = args[0], args[1]
        retain_ok = kwargs.get('retain_ok', args[2] if len(args) > 2 else False)
        out[topic] = (func, retain_ok)
    return out


def _published(mock) -> list:
    """[(topic, payload, retain)] from mock.client.publish calls."""
    out = []
    for c in mock.client.publish.call_args_list:
        args, kwargs = c
        out.append((args[0], args[1], kwargs.get('retain', False)))
    return out


class Test_Construction(unittest.TestCase):

    def test_defaults(self):
        e, mock, _ = _make_entity()
        self.assertEqual(e.rvc_instance, 1)
        self.assertEqual(e.source_topic_base, 'modbus/inverter')
        self.assertEqual(e.interval, 1.0)
        self.assertIsNone(e.stale_timeout)  # disabled: connected/LWT is the liveness signal
        self.assertEqual(e.source_id, '42')
        self.assertEqual(e.topic_base, 'rvc/state/inverter')
        self.assertEqual(e.command_topic, 'rvc/set/inverter/enable')
        self.assertEqual(e.onoff_set_topic, 'modbus/inverter/set/onoff')
        self.assertEqual(e.connected_topic, 'modbus/inverter/connected')

    def test_default_field_topics(self):
        e, _, _ = _make_entity()
        self.assertEqual(e.field_topics['status'], ('modbus/inverter/state/status', 1.0))
        self.assertEqual(e.field_topics['enabled'], ('modbus/inverter/state/onoff', 1.0))
        self.assertEqual(e.field_topics['fault'], ('modbus/inverter/state/fault', 1.0))
        self.assertEqual(e.field_topics['ac_in_voltage'],
                         ('modbus/inverter/state/AC_Input_Voltage', 0.1))
        self.assertEqual(e.field_topics['ac_in_frequency'],
                         ('modbus/inverter/state/AC_Input_Frequency', 0.01))
        self.assertEqual(e.field_topics['battery_type'],
                         ('modbus/inverter/state/battery_type', 1.0))
        self.assertEqual(e.field_topics['battery_capacity'],
                         ('modbus/inverter/state/BattCapacity', 1.0))
        for f in ('ac_in_current', 'ac_out_voltage', 'ac_out_current',
                  'ac_out_frequency', 'dc_voltage', 'dc_current'):
            self.assertNotIn(f, e.field_topics)

    def test_state_topics_registered_with_retain_ok(self):
        e, mock, _ = _make_entity()
        reg = _registered(mock)
        for topic, _scale in e.field_topics.values():
            self.assertIn(topic, reg)
            self.assertTrue(reg[topic][1], f"{topic} must be retain_ok=True")
        self.assertTrue(reg['modbus/inverter/connected'][1])
        self.assertIn('rvc/set/inverter/enable', reg)
        self.assertFalse(reg['rvc/set/inverter/enable'][1])

    def test_fields_string_form_joins_base_with_scale_1(self):
        e, _, _ = _make_entity({'fields': {'dc_voltage': 'state/battery_voltage'}})
        self.assertEqual(e.field_topics['dc_voltage'],
                         ('modbus/inverter/state/battery_voltage', 1.0))

    def test_fields_mapping_form_with_scale(self):
        e, _, _ = _make_entity({'fields': {'dc_voltage': {'topic': 'state/bv', 'scale': 0.1}}})
        self.assertEqual(e.field_topics['dc_voltage'], ('modbus/inverter/state/bv', 0.1))

    def test_fields_absolute_topic_used_verbatim(self):
        e, _, _ = _make_entity({'fields': {'dc_voltage': 'modbus/inverter/state/x'}})
        self.assertEqual(e.field_topics['dc_voltage'][0], 'modbus/inverter/state/x')

    def test_fields_null_unmaps_default(self):
        e, _, _ = _make_entity({'fields': {'ac_in_voltage': None}})
        self.assertNotIn('ac_in_voltage', e.field_topics)

    def test_unknown_field_raises(self):
        with self.assertRaises(ValueError):
            _make_entity({'fields': {'bogus': 'state/x'}})

    def test_bad_interval_raises(self):
        with self.assertRaises(ValueError):
            _make_entity({'interval': 0})
        with self.assertRaises(ValueError):
            _make_entity({'stale_timeout': -1})
        with self.assertRaises(ValueError):
            _make_entity({'stale_timeout': 0})

    def test_stale_timeout_null_means_disabled(self):
        e, _, _ = _make_entity({'stale_timeout': None})
        self.assertIsNone(e.stale_timeout)

    def test_custom_source_base_and_source_id(self):
        e, _, _ = _make_entity({'source_topic_base': 'mb/inv/', 'source_id': 'A0'})
        self.assertEqual(e.source_topic_base, 'mb/inv')
        self.assertEqual(e.field_topics['status'][0], 'mb/inv/state/status')
        self.assertEqual(e.source_id, 'A0')


class Test_Ingest(unittest.TestCase):

    def _feed(self, e, mock, topic, payload):
        _registered(mock)[topic][0](topic, payload)

    def test_status_int_parsed_and_timestamps(self):
        e, mock, clock = _make_entity(now=50.0)
        self._feed(e, mock, 'modbus/inverter/state/status', '5')
        self.assertEqual(e.values['status'], 5)
        self.assertEqual(e.last_status_update, 50.0)

    def test_enabled_bool_forms(self):
        e, mock, _ = _make_entity()
        for p, want in (('1', True), ('0', False), ('on', True), ('OFF', False),
                        ('true', True), ('False', False)):
            self._feed(e, mock, 'modbus/inverter/state/onoff', p)
            self.assertEqual(e.values['enabled'], want, p)

    def test_enabled_updates_status_timestamp(self):
        e, mock, clock = _make_entity(now=7.0)
        self._feed(e, mock, 'modbus/inverter/state/onoff', '1')
        self.assertEqual(e.last_status_update, 7.0)

    def test_numeric_scaled(self):
        e, mock, _ = _make_entity()
        self._feed(e, mock, 'modbus/inverter/state/AC_Input_Voltage', '1208')
        self.assertAlmostEqual(e.values['ac_in_voltage'], 120.8)

    def test_bad_payload_keeps_previous(self):
        e, mock, _ = _make_entity()
        self._feed(e, mock, 'modbus/inverter/state/status', '4')
        self._feed(e, mock, 'modbus/inverter/state/status', 'banana')
        self.assertEqual(e.values['status'], 4)
        self._feed(e, mock, 'modbus/inverter/state/onoff', 'maybe')
        self.assertIsNone(e.values['enabled'])
        self._feed(e, mock, 'modbus/inverter/state/AC_Input_Voltage', '')
        self.assertIsNone(e.values['ac_in_voltage'])

    def test_non_finite_numeric_payloads_ignored(self):
        e, mock, _ = _make_entity(now=1000.0)
        e.initialize()
        e.Logger = MagicMock()
        for payload in ('nan', 'inf', '-inf', '1e999'):
            self._feed(e, mock, 'modbus/inverter/state/AC_Input_Voltage', payload)
            self.assertIsNone(e.values['ac_in_voltage'], payload)
        self.assertEqual(e.Logger.warning.call_count, 4)
        self._feed(e, mock, 'modbus/inverter/state/status', '5')
        e.tick(1000.0)
        frames = _drain(e.send_queue)
        self.assertEqual([f['dgn'] for f in frames], ['1FFD4', '1FFD7', '1FFD7', '1FFCA', '1FFC6', '1FEE8', '1FECA'])

    def test_connected_topic(self):
        e, mock, _ = _make_entity()
        self.assertTrue(e.connected)
        self._feed(e, mock, 'modbus/inverter/connected', 'offline')
        self.assertFalse(e.connected)
        self._feed(e, mock, 'modbus/inverter/connected', 'online')
        self.assertTrue(e.connected)

    def test_connected_repeated_payload_not_logged(self):
        e, mock, _ = _make_entity()
        e.Logger = MagicMock()
        # Already connected=True; an "online" payload repeats the current
        # state and should not log a transition.
        self._feed(e, mock, 'modbus/inverter/connected', 'online')
        e.Logger.info.assert_not_called()
        self._feed(e, mock, 'modbus/inverter/connected', 'offline')
        self.assertEqual(e.Logger.info.call_count, 1)
        self._feed(e, mock, 'modbus/inverter/connected', 'offline')
        self.assertEqual(e.Logger.info.call_count, 1)


SPEC = os.path.join(os.path.dirname(rvc2mqtt.__file__), 'rvc-spec.yml')


def _decoder():
    d = RVC_Decoder()
    d.load_rvc_spec(SPEC)
    return d


def _decode(frame: dict) -> dict:
    d = _decoder()
    arb = d._rvc_to_can_frame(frame)
    return d.rvc_decode(arb, bytes(frame["data"]).hex().upper())


class Test_StatusMapping(unittest.TestCase):

    def _with_status(self, code, fault=None):
        e, _, _ = _make_entity()
        e.values['status'] = code
        e.values['fault'] = fault
        return e

    def test_table(self):
        expected = {0: 0, 1: 0, 2: 0, 3: 5, 4: 2, 5: 1, 6: 5, 7: 5, 10: 0, 11: 0}
        for code, want in expected.items():
            self.assertEqual(self._with_status(code).rvc_status(), want, code)

    def test_unknown_and_none_are_disabled(self):
        self.assertEqual(self._with_status(None).rvc_status(), 0)
        self.assertEqual(self._with_status(8).rvc_status(), 0)
        self.assertEqual(self._with_status(99).rvc_status(), 0)

    def test_fault_forces_disabled(self):
        self.assertEqual(self._with_status(5, fault=True).rvc_status(), 0)
        self.assertEqual(self._with_status(5, fault=False).rvc_status(), 1)

    def test_unknown_code_warns_once(self):
        e = self._with_status(42)
        e.Logger = MagicMock()
        e.rvc_status()
        e.rvc_status()
        self.assertEqual(e.Logger.warning.call_count, 1)


class Test_Frames(unittest.TestCase):

    def test_frame_set_with_source_id(self):
        e, _, _ = _make_entity({'source_id': 'A5'})
        frames = e.build_frames()
        self.assertEqual([f['dgn'] for f in frames], ['1FFD4', '1FFD7', '1FFD7', '1FFCA', '1FFC6', '1FEE8', '1FECA'])
        for f in frames:
            self.assertEqual(f['source_id'], 'A5')
            self.assertEqual(len(f['data']), 8)

    def test_inverter_status_inverting_enabled(self):
        e, _, _ = _make_entity()
        e.values.update(status=5, enabled=True)
        msg = _decode(e.build_frames()[0])
        self.assertEqual(msg['name'], 'INVERTER_STATUS')
        self.assertEqual(msg['instance'], 1)
        self.assertEqual(msg['status_definition'], 'invert')
        self.assertEqual(msg['inverter_enabled'], '01')
        self.assertEqual(msg['pass-through_enabled'], '00')
        self.assertEqual(msg['load_sense_enabled'], '11')
        self.assertEqual(msg['battery_temperature_sensor_present'], '11')
        self.assertEqual(msg['generator_support_enabled'], '11')
        self.assertEqual(msg['data'][6:], 'FFFFFFFFFF')  # bytes 3-7 (byte 3 = 0xFF incl. gen support bits)

    def test_inverter_status_passthru_disabled(self):
        e, _, _ = _make_entity()
        e.values.update(status=4, enabled=False)
        msg = _decode(e.build_frames()[0])
        self.assertEqual(msg['status_definition'], 'ac passthru')
        self.assertEqual(msg['inverter_enabled'], '00')
        self.assertEqual(msg['pass-through_enabled'], '01')

    def test_inverter_status_unknown_enabled_is_11(self):
        e, _, _ = _make_entity()
        e.values.update(status=0)
        msg = _decode(e.build_frames()[0])
        self.assertEqual(msg['inverter_enabled'], '11')

    def test_ac_status_input_frame(self):
        e, _, _ = _make_entity()
        e.values.update(ac_in_voltage=120.8)
        msg = _decode(e.build_frames()[1])
        self.assertEqual(msg['name'], 'INVERTER_AC_STATUS_1')
        self.assertEqual(msg['instance'], 1)
        self.assertEqual(msg['line_definition'], 1)
        self.assertEqual(msg['input_output_definition'], 'input')
        self.assertEqual(msg['rms_voltage'], 120.8)
        self.assertEqual(msg['rms_current'], 'n/a')
        self.assertEqual(msg['frequency'], 0xFFFF)  # decoder returns raw 0xFFFF for Hz n/a
        self.assertEqual(msg['data'][14:], 'FF')

    def test_ac_status_input_frame_with_current_mapped(self):
        e, mock, _ = _make_entity({'fields': {'ac_in_current': {'topic': 'state/AC_Input_Current', 'scale': 0.01}}})
        _registered(mock)['modbus/inverter/state/AC_Input_Voltage'][0](
            'modbus/inverter/state/AC_Input_Voltage', '1208')
        _registered(mock)['modbus/inverter/state/AC_Input_Current'][0](
            'modbus/inverter/state/AC_Input_Current', '1250')
        msg = _decode(e.build_frames()[1])
        self.assertEqual(msg['input_output_definition'], 'input')
        self.assertEqual(msg['rms_voltage'], 120.8)
        self.assertEqual(msg['rms_current'], 12.5)
        self.assertEqual(msg['frequency'], 0xFFFF)  # input frequency stays n/a

    def test_ac_in_current_does_not_leak_into_output_frame(self):
        e, mock, _ = _make_entity({'fields': {'ac_in_current': 'state/ic'}})
        _registered(mock)['modbus/inverter/state/ic'][0]('modbus/inverter/state/ic', '5')
        msg = _decode(e.build_frames()[2])
        self.assertEqual(msg['input_output_definition'], 'output')
        self.assertEqual(msg['rms_current'], 'n/a')

    def test_ac_status_input_frame_carries_frequency(self):
        e, mock, _ = _make_entity()
        _registered(mock)['modbus/inverter/state/AC_Input_Frequency'][0](
            'modbus/inverter/state/AC_Input_Frequency', '5998')
        msg = _decode(e.build_frames()[1])
        self.assertEqual(msg['input_output_definition'], 'input')
        self.assertEqual(msg['frequency'], 59.98)

    def test_ac_in_frequency_does_not_leak_into_output_frame(self):
        e, _, _ = _make_entity()
        e.values.update(ac_in_frequency=60.0)
        msg = _decode(e.build_frames()[2])
        self.assertEqual(msg['input_output_definition'], 'output')
        self.assertEqual(msg['frequency'], 0xFFFF)

    def test_charger_ac_status_frame(self):
        e, mock, _ = _make_entity({'fields': {'ac_in_current': {'topic': 'state/AC_Input_Current', 'scale': 0.01}}})
        reg = _registered(mock)
        reg['modbus/inverter/state/AC_Input_Voltage'][0]('modbus/inverter/state/AC_Input_Voltage', '1208')
        reg['modbus/inverter/state/AC_Input_Current'][0]('modbus/inverter/state/AC_Input_Current', '1250')
        reg['modbus/inverter/state/AC_Input_Frequency'][0]('modbus/inverter/state/AC_Input_Frequency', '5998')
        frame = e.build_frames()[3]
        self.assertEqual(frame['dgn'], '1FFCA')
        msg = _decode(frame)
        self.assertEqual(msg['name'], 'CHARGER_AC_STATUS_1')
        self.assertEqual(msg['instance'], 1)
        self.assertEqual(msg['line_definition'], 1)
        self.assertEqual(msg['input_output_definition'], 'input')
        self.assertEqual(msg['rms_voltage'], 120.8)
        self.assertEqual(msg['rms_current'], 12.5)
        self.assertEqual(msg['frequency'], 59.98)
        self.assertEqual(msg['data'][14:], 'FF')

    def test_charger_ac_status_frame_all_not_available(self):
        e, _, _ = _make_entity()
        msg = _decode(e.build_frames()[3])
        self.assertEqual(msg['name'], 'CHARGER_AC_STATUS_1')
        self.assertEqual(msg['rms_voltage'], 'n/a')
        self.assertEqual(msg['rms_current'], 'n/a')
        self.assertEqual(msg['frequency'], 0xFFFF)

    def test_ac_status_output_frame(self):
        e, _, _ = _make_entity()
        e.values.update(ac_out_voltage=119.5, ac_out_current=3.8, ac_out_frequency=60.0)
        msg = _decode(e.build_frames()[2])
        self.assertEqual(msg['input_output_definition'], 'output')
        self.assertEqual(msg['rms_voltage'], 119.5)
        self.assertEqual(msg['rms_current'], 3.8)
        self.assertEqual(msg['frequency'], 60.0)

    def test_ac_status_all_unmapped_still_sent(self):
        e, _, _ = _make_entity()
        msg = _decode(e.build_frames()[2])
        self.assertEqual(msg['rms_voltage'], 'n/a')
        self.assertEqual(msg['rms_current'], 'n/a')

    def test_dc_status_frame(self):
        e, _, _ = _make_entity()
        e.values.update(dc_voltage=52.0, dc_current=-12.5)
        msg = _decode(e.build_frames()[5])
        self.assertEqual(msg['name'], 'INVERTER_DC_STATUS')
        self.assertEqual(msg['instance'], 1)
        self.assertEqual(msg['dc_voltage'], 52.0)
        self.assertEqual(msg['dc_amperage'], -12.5)
        self.assertEqual(msg['data'][10:], 'FFFFFF')

    def test_dc_status_not_available(self):
        e, _, _ = _make_entity()
        msg = _decode(e.build_frames()[5])
        self.assertEqual(msg['dc_voltage'], 'n/a')
        self.assertEqual(msg['dc_amperage'], 'n/a')


def _drain(q: queue.Queue) -> list:
    out = []
    while not q.empty():
        out.append(q.get())
    return out


class Test_ChargerConfig(unittest.TestCase):
    """CHARGER_CONFIGURATION_STATUS (1FFC6): battery type + bank size, rest n/a."""

    def _frame(self, e):
        frame = e.build_frames()[4]
        self.assertEqual(frame['dgn'], '1FFC6')
        return frame, _decode(frame)

    def _feed(self, e, mock, topic, payload):
        _registered(mock)[topic][0](topic, payload)

    def test_battery_type_mapping(self):
        # SRNE register 4424 code -> RV-C battery type (byte 3 bits 4-7)
        for code, want in ((2, 'flooded'), (3, 'gel'), (1, 'agm'),
                           (4, 'lithium iron phosphate'),
                           (5, 'lithium iron phosphate'),
                           (6, 'lithium iron phosphate')):
            e, mock, _ = _make_entity()
            self._feed(e, mock, 'modbus/inverter/state/battery_type', str(code))
            _frame, msg = self._frame(e)
            self.assertEqual(msg['name'], 'CHARGER_CONFIGURATION_STATUS')
            self.assertEqual(msg['instance'], 1)
            self.assertEqual(msg['battery_type_definition'], want, code)

    def test_battery_type_without_rvc_equivalent_is_not_available(self):
        # 0 UserDef, 12/13 Li-Ion: RV-C has no code, so send all-ones.
        for code in (0, 12, 13):
            e, mock, _ = _make_entity()
            e.Logger = MagicMock()
            self._feed(e, mock, 'modbus/inverter/state/battery_type', str(code))
            _frame, msg = self._frame(e)
            self.assertEqual(msg['battery_type'], 15, code)
            e.Logger.warning.assert_not_called()

    def test_unknown_battery_type_code_warns_once(self):
        e, mock, _ = _make_entity()
        e.Logger = MagicMock()
        self._feed(e, mock, 'modbus/inverter/state/battery_type', '9')
        _frame, msg = self._frame(e)
        self._frame(e)
        self.assertEqual(msg['battery_type'], 15)
        self.assertEqual(e.Logger.warning.call_count, 1)

    def test_no_battery_type_value_is_not_available(self):
        e, _, _ = _make_entity()
        _frame, msg = self._frame(e)
        self.assertEqual(msg['battery_type'], 15)

    def test_bank_size_from_capacity(self):
        e, mock, _ = _make_entity()
        self._feed(e, mock, 'modbus/inverter/state/BattCapacity', '210')
        _frame, msg = self._frame(e)
        self.assertEqual(msg['battery_bank_size'], 210)

    def test_bank_size_not_available(self):
        e, _, _ = _make_entity()
        _frame, msg = self._frame(e)
        self.assertEqual(msg['battery_bank_size'], 0xFFFF)

    def test_fixed_bytes(self):
        e, mock, _ = _make_entity()
        self._feed(e, mock, 'modbus/inverter/state/battery_type', '4')
        self._feed(e, mock, 'modbus/inverter/state/BattCapacity', '210')
        frame, msg = self._frame(e)
        data = bytes(frame['data'])
        self.assertEqual(len(data), 8)
        self.assertEqual(data[1], 0xFF)          # charging algorithm n/a
        self.assertEqual(data[2], 0xFF)          # charger mode n/a
        self.assertEqual(data[3] & 0x0F, 0b0011)  # sensor n/a (11), installation line 1 (00)
        self.assertEqual(data[3] >> 4, 3)        # lithium iron phosphate
        self.assertEqual(data[6:], b'\xff\xff')  # max charging current n/a
        self.assertEqual(msg['charger_installation_line_definition'], 1)


class Test_DmRv(unittest.TestCase):
    """DM_RV (1FECA) diagnostic frame: all-clear while healthy, red lamp + fault while faulted."""

    def _dm_rv(self, e):
        frame = e.build_frames()[6]
        self.assertEqual(frame['dgn'], '1FECA')
        return frame, _decode(frame)

    def test_running_sends_on_normal_all_clear(self):
        e, _, _ = _make_entity()
        e.values.update(status=5, enabled=True)
        frame, msg = self._dm_rv(e)
        self.assertEqual(bytes(frame['data']).hex().upper(), '0542FFFFFFFFFFFF')
        self.assertEqual(msg['operating_status_definition'], 'on normal')
        self.assertEqual(msg['red_lamp_status'], '00')
        self.assertEqual(msg['yellow_lamp_status'], '00')
        self.assertEqual(msg['dsa'], 66)
        self.assertEqual(msg['fmi_definition'], 'failure mode not available')

    def test_passthru_counts_as_on_normal(self):
        e, _, _ = _make_entity()
        e.values.update(status=4, enabled=True)
        _, msg = self._dm_rv(e)
        self.assertEqual(msg['operating_status_definition'], 'on normal')

    def test_disabled_sends_off_normal(self):
        e, _, _ = _make_entity()
        e.values.update(status=10, enabled=False)
        frame, msg = self._dm_rv(e)
        self.assertEqual(bytes(frame['data']).hex().upper(), '0442FFFFFFFFFFFF')
        self.assertEqual(msg['operating_status_definition'], 'off normal')
        self.assertEqual(msg['red_lamp_status'], '00')

    def test_fault_flag_sends_off_fault_red_lamp(self):
        e, _, _ = _make_entity()
        e.values.update(status=5, enabled=True, fault=True)
        frame, msg = self._dm_rv(e)
        self.assertEqual(bytes(frame['data']).hex().upper(), '404200000BFFFFFF')
        self.assertEqual(msg['operating_status_definition'], 'off fault')
        self.assertEqual(msg['red_lamp_status'], '01')
        self.assertEqual(msg['fmi_definition'], 'failure not identifiable')

    def test_status_11_counts_as_fault(self):
        e, _, _ = _make_entity()
        e.values.update(status=11)
        _, msg = self._dm_rv(e)
        self.assertEqual(msg['operating_status_definition'], 'off fault')
        self.assertEqual(msg['red_lamp_status'], '01')

    def test_source_id_carried(self):
        e, _, _ = _make_entity({'source_id': 'A5'})
        e.values.update(status=5)
        frame, _ = self._dm_rv(e)
        self.assertEqual(frame['source_id'], 'A5')

    def test_dm_rv_from_other_sources_not_swallowed(self):
        """DM_RV from real nodes must flow on to the entities that watch it."""
        e, _, _ = _make_entity()
        msg = {'name': 'DM_RV', 'dgn': '1FECA', 'source_id': '9c', 'dsa': 66}
        self.assertFalse(e.process_rvc_msg(msg))


class Test_Tick(unittest.TestCase):

    def _ready(self, now=100.0, extra=None):
        e, mock, clock = _make_entity(extra, now=now)
        e.initialize()
        # a fresh status arrived "now"
        _registered(mock)['modbus/inverter/state/status'][0]('modbus/inverter/state/status', '5')
        return e, mock, clock

    def test_nothing_before_first_status(self):
        e, _, _ = _make_entity(now=100.0)
        e.initialize()
        e.tick(100.0)
        e.tick(200.0)
        self.assertEqual(_drain(e.send_queue), [])

    def test_first_tick_sends_full_set(self):
        e, _, _ = self._ready(100.0)
        e.tick(100.0)
        frames = _drain(e.send_queue)
        self.assertEqual([f['dgn'] for f in frames], ['1FFD4', '1FFD7', '1FFD7', '1FFCA', '1FFC6', '1FEE8', '1FECA'])

    def test_respects_interval(self):
        e, _, _ = self._ready(100.0)
        e.tick(100.0)
        _drain(e.send_queue)
        e.tick(100.5)
        self.assertEqual(_drain(e.send_queue), [])
        e.tick(101.0)
        self.assertEqual(len(_drain(e.send_queue)), 7)

    def test_custom_interval(self):
        e, mock, clock = _make_entity({'interval': 5.0}, now=100.0)
        e.initialize()
        _registered(mock)['modbus/inverter/state/status'][0]('modbus/inverter/state/status', '4')
        e.tick(100.0)
        _drain(e.send_queue)
        e.tick(104.9)
        self.assertEqual(_drain(e.send_queue), [])
        e.tick(105.0)
        self.assertEqual(len(_drain(e.send_queue)), 7)

    def test_steady_state_keeps_transmitting_by_default(self):
        """modbus2mqtt publishes on change only: an unchanged-but-healthy
        inverter must keep being announced on RV-C indefinitely."""
        e, _, _ = self._ready(100.0)
        e.tick(100.0)
        self.assertEqual(len(_drain(e.send_queue)), 7)
        e.tick(131.0)   # >30 s with no MQTT traffic
        self.assertEqual(len(_drain(e.send_queue)), 7)
        e.tick(3700.0)  # an hour later, still nothing changed
        self.assertEqual(len(_drain(e.send_queue)), 7)

    def test_silent_when_stale_opt_in(self):
        e, _, clock = self._ready(100.0, {'stale_timeout': 30.0})
        e.tick(100.0)
        _drain(e.send_queue)
        e.tick(131.0)  # > stale_timeout (30 s) since last status
        self.assertEqual(_drain(e.send_queue), [])

    def test_resumes_after_fresh_status(self):
        e, mock, clock = self._ready(100.0, {'stale_timeout': 30.0})
        e.tick(131.0)
        self.assertEqual(_drain(e.send_queue), [])
        clock['now'] = 131.5
        _registered(mock)['modbus/inverter/state/onoff'][0]('modbus/inverter/state/onoff', '1')
        e.tick(132.0)
        self.assertEqual(len(_drain(e.send_queue)), 7)

    def test_silent_when_offline(self):
        e, mock, _ = self._ready(100.0)
        _registered(mock)['modbus/inverter/connected'][0]('modbus/inverter/connected', 'offline')
        e.tick(100.0)
        self.assertEqual(_drain(e.send_queue), [])
        _registered(mock)['modbus/inverter/connected'][0]('modbus/inverter/connected', 'online')
        e.tick(101.0)
        self.assertEqual(len(_drain(e.send_queue)), 7)

    def test_silence_transition_logged_once(self):
        e, _, _ = self._ready(100.0, {'stale_timeout': 30.0})
        e.Logger = MagicMock()
        e.tick(100.0)
        e.tick(131.0)
        e.tick(132.0)
        e.tick(133.0)
        self.assertEqual(e.Logger.info.call_count, 1)


def _cmd(instance=1, enable='01'):
    """A decoded INVERTER_COMMAND dict as produced by RVC_Decoder."""
    return {'name': 'INVERTER_COMMAND', 'dgn': '1FFD3', 'instance': instance,
            'inverter_enable': enable, 'load_sense_enable': '00',
            'pass-through_enable': '01', 'inverter_enable_on_startup': '01',
            'source_id': '9F'}


def _onoff_publishes(mock):
    return [(t, p) for (t, p, _r) in _published(mock) if t == 'modbus/inverter/set/onoff']


class Test_Command(unittest.TestCase):

    def test_rvc_enable_writes_1(self):
        e, mock, _ = _make_entity()
        self.assertTrue(e.process_rvc_msg(_cmd(enable='01')))
        self.assertEqual(_onoff_publishes(mock), [('modbus/inverter/set/onoff', '1')])

    def test_rvc_disable_writes_0(self):
        e, mock, _ = _make_entity()
        self.assertTrue(e.process_rvc_msg(_cmd(enable='00')))
        self.assertEqual(_onoff_publishes(mock), [('modbus/inverter/set/onoff', '0')])

    def test_rvc_no_change_bits_do_not_write(self):
        e, mock, _ = _make_entity()
        self.assertTrue(e.process_rvc_msg(_cmd(enable='11')))
        self.assertTrue(e.process_rvc_msg(_cmd(enable='10')))
        self.assertEqual(_onoff_publishes(mock), [])

    def test_other_instance_not_handled(self):
        e, mock, _ = _make_entity()
        self.assertFalse(e.process_rvc_msg(_cmd(instance=2)))
        self.assertEqual(_onoff_publishes(mock), [])

    def test_onoff_publish_is_not_retained(self):
        e, mock, _ = _make_entity()
        e.process_rvc_msg(_cmd(enable='01'))
        retained = [r for (t, _p, r) in _published(mock) if t == 'modbus/inverter/set/onoff']
        self.assertEqual(retained, [False])

    def test_own_status_dgns_swallowed(self):
        e, mock, _ = _make_entity()
        e.values.update(status=5, enabled=True)
        for frame in e.build_frames():
            self.assertTrue(e.process_rvc_msg(_decode(frame)))
        self.assertEqual(_onoff_publishes(mock), [])

    def test_other_instance_status_not_swallowed(self):
        e, _, _ = _make_entity()
        msg = {'name': 'INVERTER_STATUS', 'dgn': '1FFD4', 'instance': 2}
        self.assertFalse(e.process_rvc_msg(msg))

    def test_unrelated_dgn_not_handled(self):
        e, _, _ = _make_entity()
        self.assertFalse(e.process_rvc_msg({'name': 'DC_SOURCE_STATUS_1', 'instance': 1}))

    def test_mqtt_enable_topic(self):
        e, mock, _ = _make_entity()
        cb = _registered(mock)['rvc/set/inverter/enable'][0]
        for payload, want in (('on', '1'), ('OFF', '0'), ('1', '1'), ('0', '0'),
                              ('true', '1'), ('false', '0')):
            mock.client.publish.reset_mock()
            cb('rvc/set/inverter/enable', payload)
            self.assertEqual(_onoff_publishes(mock), [('modbus/inverter/set/onoff', want)], payload)

    def test_mqtt_enable_bad_payload_warns_no_write(self):
        e, mock, _ = _make_entity()
        e.Logger = MagicMock()
        _registered(mock)['rvc/set/inverter/enable'][0]('rvc/set/inverter/enable', 'maybe')
        self.assertEqual(_onoff_publishes(mock), [])
        e.Logger.warning.assert_called_once()


def _state_publishes(mock):
    return [(t, p, r) for (t, p, r) in _published(mock) if t.startswith('rvc/state/inverter/')]


class Test_Mirror(unittest.TestCase):

    def _feed(self, e, mock, topic, payload):
        _registered(mock)[topic][0](topic, payload)

    def test_status_mirrors_code_and_definition(self):
        e, mock, _ = _make_entity()
        self._feed(e, mock, 'modbus/inverter/state/status', '5')
        pubs = _state_publishes(mock)
        self.assertIn(('rvc/state/inverter/status', 1, True), pubs)
        # Matches the real inverter entity's .title() casing (inverter.py
        # publishes status_definition via new_message.get(...).title()).
        self.assertIn(('rvc/state/inverter/status_definition', 'Invert', True), pubs)

    def test_onoff_and_fault_mirror(self):
        e, mock, _ = _make_entity()
        self._feed(e, mock, 'modbus/inverter/state/onoff', '1')
        self._feed(e, mock, 'modbus/inverter/state/fault', '0')
        pubs = _state_publishes(mock)
        self.assertIn(('rvc/state/inverter/onoff', 'on', True), pubs)
        self.assertIn(('rvc/state/inverter/fault', 'off', True), pubs)

    def test_fault_changes_mirrored_status(self):
        e, mock, _ = _make_entity()
        self._feed(e, mock, 'modbus/inverter/state/status', '5')
        mock.client.publish.reset_mock()
        self._feed(e, mock, 'modbus/inverter/state/fault', '1')
        pubs = _state_publishes(mock)
        self.assertIn(('rvc/state/inverter/status', 0, True), pubs)
        self.assertIn(('rvc/state/inverter/status_definition', 'Disabled', True), pubs)

    def test_numeric_mirror_topics(self):
        e, mock, _ = _make_entity({'fields': {
            'ac_in_current': {'topic': 'state/ic', 'scale': 0.01},
            'ac_out_voltage': 'state/ov', 'ac_out_current': 'state/oc',
            'ac_out_frequency': 'state/of', 'dc_voltage': 'state/dv', 'dc_current': 'state/dc'}})
        self._feed(e, mock, 'modbus/inverter/state/AC_Input_Voltage', '1208')
        self._feed(e, mock, 'modbus/inverter/state/AC_Input_Frequency', '5998')
        self._feed(e, mock, 'modbus/inverter/state/ic', '1250')
        self._feed(e, mock, 'modbus/inverter/state/ov', '119.5')
        self._feed(e, mock, 'modbus/inverter/state/oc', '3.8')
        self._feed(e, mock, 'modbus/inverter/state/of', '60')
        self._feed(e, mock, 'modbus/inverter/state/dv', '52')
        self._feed(e, mock, 'modbus/inverter/state/dc', '-12.5')
        self._feed(e, mock, 'modbus/inverter/state/BattCapacity', '210')
        pubs = {t: p for (t, p, _r) in _state_publishes(mock)}
        self.assertEqual(pubs['rvc/state/inverter/battery_capacity'], 210.0)
        self.assertEqual(pubs['rvc/state/inverter/line1/input/rms_voltage'], 120.8)
        self.assertEqual(pubs['rvc/state/inverter/line1/input/rms_current'], 12.5)
        self.assertEqual(pubs['rvc/state/inverter/line1/input/frequency'], 59.98)
        self.assertEqual(pubs['rvc/state/inverter/line1/output/rms_voltage'], 119.5)
        self.assertEqual(pubs['rvc/state/inverter/line1/output/rms_current'], 3.8)
        self.assertEqual(pubs['rvc/state/inverter/line1/output/frequency'], 60.0)
        self.assertEqual(pubs['rvc/state/inverter/dc_voltage'], 52.0)
        self.assertEqual(pubs['rvc/state/inverter/dc_amperage'], -12.5)

    def test_battery_type_mirrors_rvc_definition(self):
        e, mock, _ = _make_entity()
        self._feed(e, mock, 'modbus/inverter/state/battery_type', '4')
        pubs = {t: p for (t, p, _r) in _state_publishes(mock)}
        self.assertEqual(pubs['rvc/state/inverter/battery_type'], 'Lithium Iron Phosphate')
        mock.client.publish.reset_mock()
        self._feed(e, mock, 'modbus/inverter/state/battery_type', '0')
        pubs = {t: p for (t, p, _r) in _state_publishes(mock)}
        self.assertEqual(pubs['rvc/state/inverter/battery_type'], 'Unknown')

    def test_unchanged_value_not_republished(self):
        e, mock, _ = _make_entity()
        self._feed(e, mock, 'modbus/inverter/state/status', '5')
        mock.client.publish.reset_mock()
        self._feed(e, mock, 'modbus/inverter/state/status', '5')
        self.assertEqual(_state_publishes(mock), [])

    def test_unmapped_fields_never_published(self):
        e, mock, _ = _make_entity()
        self._feed(e, mock, 'modbus/inverter/state/status', '5')
        topics = [t for (t, _p, _r) in _state_publishes(mock)]
        self.assertNotIn('rvc/state/inverter/dc_voltage', topics)
        self.assertNotIn('rvc/state/inverter/line1/output/rms_voltage', topics)


class Test_HADiscovery(unittest.TestCase):

    def _configs(self, mock):
        out = {}
        for (t, p, _r) in _published(mock):
            if t.startswith('homeassistant/'):
                out[t] = json.loads(p)
        return out

    def test_core_components(self):
        e, mock, _ = _make_entity()
        e.publish_ha_discovery_config()
        cfgs = self._configs(mock)
        uid = e.unique_device_id
        self.assertIn(f'homeassistant/switch/{uid}/enable/config', cfgs)
        self.assertIn(f'homeassistant/sensor/{uid}/status/config', cfgs)
        self.assertIn(f'homeassistant/binary_sensor/{uid}/fault/config', cfgs)
        self.assertIn(f'homeassistant/sensor/{uid}/ac_in_voltage/config', cfgs)
        self.assertIn(f'homeassistant/sensor/{uid}/ac_in_frequency/config', cfgs)
        hz = cfgs[f'homeassistant/sensor/{uid}/ac_in_frequency/config']
        self.assertEqual(hz['state_topic'], 'rvc/state/inverter/line1/input/frequency')
        self.assertEqual(hz['device_class'], 'frequency')
        self.assertEqual(hz['unit_of_measurement'], 'Hz')
        bt = cfgs[f'homeassistant/sensor/{uid}/battery_type/config']
        self.assertEqual(bt['state_topic'], 'rvc/state/inverter/battery_type')
        self.assertEqual(bt['device_class'], 'enum')
        self.assertEqual(sorted(bt['options']),
                         sorted(['Flooded', 'Gel', 'Agm', 'Lithium Iron Phosphate', 'Unknown']))
        cap = cfgs[f'homeassistant/sensor/{uid}/battery_capacity/config']
        self.assertEqual(cap['state_topic'], 'rvc/state/inverter/battery_capacity')
        self.assertEqual(cap['unit_of_measurement'], 'Ah')
        self.assertEqual(cap['suggested_display_precision'], 0)
        self.assertNotIn('suggested_display_precision', hz)
        sw = cfgs[f'homeassistant/switch/{uid}/enable/config']
        self.assertEqual(sw['command_topic'], 'rvc/set/inverter/enable')
        self.assertEqual(sw['state_topic'], 'rvc/state/inverter/onoff')
        self.assertEqual(sw['payload_on'], 'on')
        self.assertEqual(sw['unique_id'], uid + '_enable')
        self.assertEqual(sw['availability_topic'], 'rvc2mqtt/bridge/state')
        self.assertEqual(sw['device']['identifiers'], uid)
        status = cfgs[f'homeassistant/sensor/{uid}/status/config']
        # Title-cased to match the mirrored status_definition value and the
        # real inverter entity's .title() casing.
        self.assertEqual(sorted(status['options']),
                         sorted(['Disabled', 'Invert', 'Ac Passthru', 'Waiting To Invert', 'Unknown']))

    def test_numeric_sensors_only_for_mapped_fields(self):
        e, mock, _ = _make_entity({'fields': {'dc_voltage': 'state/dv', 'ac_in_voltage': None}})
        e.publish_ha_discovery_config()
        cfgs = self._configs(mock)
        uid = e.unique_device_id
        self.assertIn(f'homeassistant/sensor/{uid}/dc_voltage/config', cfgs)
        self.assertNotIn(f'homeassistant/sensor/{uid}/ac_in_voltage/config', cfgs)
        dv = cfgs[f'homeassistant/sensor/{uid}/dc_voltage/config']
        self.assertEqual(dv['state_topic'], 'rvc/state/inverter/dc_voltage')
        self.assertEqual(dv['device_class'], 'voltage')
        self.assertEqual(dv['unit_of_measurement'], 'V')

    def test_initialize_publishes_discovery(self):
        e, mock, _ = _make_entity()
        e.initialize()
        self.assertTrue(self._configs(mock))


# ---- shore breaker size / charge rate (1FF95 / 1FF96) ----------------------

SB_TOPIC = 'modbus/inverter/state/max_ac_input_current'
CL_TOPIC = 'modbus/inverter/state/current'
SB_SET = 'modbus/inverter/set/max_ac_input_current'
SB_FIELDS = {'shore_breaker_size': {'topic': 'state/max_ac_input_current', 'scale': 0.1}}
CL_FIELDS = {'charge_current_limit': {'topic': 'state/current', 'scale': 0.1}}


def _sb_entity(extra: dict = None, now: float = 1000.0, charge=False, sync=False):
    data = {'fields': dict(SB_FIELDS)}
    if charge:
        data['fields'].update(CL_FIELDS)
        data['charger_rated_current'] = 40
    if sync:
        data['shore_breaker_g12_sync'] = True
    if extra:
        data.update(extra)
    e, mock, clock = _make_entity(data, now=now)
    e.initialize()
    # the source is live: a status has arrived
    _feed(mock, 'modbus/inverter/state/status', '5')
    mock.client.publish.reset_mock()
    return e, mock, clock


def _feed(mock, topic, payload):
    _registered(mock)[topic][0](topic, payload)


def _cmd2(amps=0x19, instance=1, source='9C', byte1=0xFF):
    """A decoded CHARGER_CONFIGURATION_COMMAND_2 as the G12 relays it."""
    data = bytes([instance, byte1, 0xFF, amps, 0xFF, 0xFF, 0xFF, 0xFF])
    msg = _decode({'dgn': '1FF95', 'data': data, 'source_id': source})
    assert msg['name'] == 'CHARGER_CONFIGURATION_COMMAND_2'
    return msg


def _sb_writes(mock, topic=SB_SET):
    return [(t, p) for (t, p, _r) in _published(mock) if t == topic]


def _g12_frames(e):
    return [f for f in _drain(e.send_queue) if f['dgn'] == '1FED9']


class Test_ShoreBreakerConfig(unittest.TestCase):

    def test_defaults_are_off(self):
        e, _, _ = _make_entity()
        self.assertNotIn('shore_breaker_size', e.field_topics)
        self.assertNotIn('charge_current_limit', e.field_topics)
        self.assertEqual(e.charger_config_2_instance, 1)
        self.assertEqual(e.shore_breaker_set_topic, SB_SET)
        self.assertEqual((e.shore_breaker_min, e.shore_breaker_max), (5, 30))
        self.assertIs(e.shore_breaker_g12_sync, False)
        self.assertEqual(e.shore_breaker_settle, 2.0)
        self.assertIsNone(e.charger_rated_current)

    def test_charge_limit_needs_rated_current(self):
        with self.assertRaises(ValueError):
            _make_entity({'fields': dict(CL_FIELDS)})
        with self.assertRaises(ValueError):
            _make_entity({'fields': dict(CL_FIELDS), 'charger_rated_current': 0})

    def test_bad_limits_and_settle_raise(self):
        with self.assertRaises(ValueError):
            _make_entity({'shore_breaker_min': 31, 'shore_breaker_max': 30})
        with self.assertRaises(ValueError):
            _make_entity({'shore_breaker_settle': -1})

    def test_state_ingest_and_target(self):
        e, mock, _ = _sb_entity()
        self.assertIsNone(e._shore_breaker_target())
        _feed(mock, SB_TOPIC, '150')
        self.assertAlmostEqual(e.values['shore_breaker_size'], 15.0)
        self.assertEqual(e._shore_breaker_target(), 15)
        _feed(mock, SB_TOPIC, '320')
        self.assertEqual(e._shore_breaker_target(), 30)
        _feed(mock, SB_TOPIC, '10')
        self.assertEqual(e._shore_breaker_target(), 5)

    def test_mirror(self):
        e, mock, _ = _sb_entity(charge=True)
        _feed(mock, SB_TOPIC, '150')
        _feed(mock, CL_TOPIC, '200')
        pubs = {t: p for (t, p, _r) in _state_publishes(mock)}
        self.assertEqual(pubs['rvc/state/inverter/shore_breaker_size'], 15.0)
        self.assertEqual(pubs['rvc/state/inverter/charge_current_limit'], 20.0)


class Test_ChargerConfig2Frame(unittest.TestCase):

    def test_both_values_at_instance_3(self):
        e, mock, _ = _sb_entity({'charger_config_2_instance': 3}, charge=True)
        _feed(mock, SB_TOPIC, '150')
        _feed(mock, CL_TOPIC, '150')
        frame = e._charger_config_2_frame()
        self.assertEqual(frame['dgn'], '1FF96')
        self.assertEqual(frame['source_id'], '42')
        self.assertEqual(bytes(frame['data']).hex().upper(), '034BFF0FFFFFFFFF')
        msg = _decode(frame)
        self.assertEqual(msg['name'], 'CHARGER_CONFIGURATION_STATUS_2')
        self.assertEqual(msg['instance'], 3)
        self.assertEqual(msg['shore_breaker_size'], 15)
        self.assertEqual(msg['maximum_charge_current_as_percent'], 37.5)
        self.assertEqual(e.build_frames()[-1], frame)

    def test_rate_caps_at_100_pct(self):
        e, mock, _ = _sb_entity(charge=True)
        _feed(mock, CL_TOPIC, '500')
        self.assertEqual(e._charger_config_2_frame()['data'][1], 0xC8)

    def test_only_breaker_known(self):
        e, mock, _ = _sb_entity(charge=True)
        _feed(mock, SB_TOPIC, '250')
        self.assertEqual(bytes(e._charger_config_2_frame()['data']).hex().upper(),
                         '01FFFF19FFFFFFFF')

    def test_only_limit_known(self):
        e, mock, _ = _sb_entity(charge=True)
        _feed(mock, CL_TOPIC, '400')
        self.assertEqual(bytes(e._charger_config_2_frame()['data']).hex().upper(),
                         '01C8FFFFFFFFFFFF')

    def test_no_frame_until_a_value_arrives(self):
        e, _, _ = _sb_entity(charge=True)
        self.assertIsNone(e._charger_config_2_frame())
        self.assertNotIn('1FF96', [f['dgn'] for f in e.build_frames()])

    def test_own_echo_claimed_by_source(self):
        e, mock, _ = _sb_entity({'charger_config_2_instance': 3})
        _feed(mock, SB_TOPIC, '150')
        echo = _decode(e._charger_config_2_frame())
        self.assertTrue(e.process_rvc_msg(echo))
        foreign = dict(echo, source_id='9C')
        self.assertFalse(e.process_rvc_msg(foreign))

    def test_echo_not_claimed_when_feature_off(self):
        e, _, _ = _make_entity()
        msg = _decode({'dgn': '1FF96', 'source_id': '42',
                       'data': bytes([1, 0xFF, 0xFF, 15, 0xFF, 0xFF, 0xFF, 0xFF])})
        self.assertFalse(e.process_rvc_msg(msg))


class Test_ShoreBreakerCommand(unittest.TestCase):

    def _at(self, raw='300', **kw):
        e, mock, clock = _sb_entity(**kw)
        if raw is not None:
            _feed(mock, SB_TOPIC, raw)
        mock.client.publish.reset_mock()
        return e, mock, clock

    def test_press_writes_raw_register_value(self):
        e, mock, _ = self._at('300')
        self.assertTrue(e.process_rvc_msg(_cmd2(25)))
        self.assertEqual(_published(mock), [(SB_SET, '250', False)])
        self.assertEqual(e._g12_value, 25)

    def test_no_change_byte_ignored(self):
        e, mock, _ = self._at('300')
        self.assertTrue(e.process_rvc_msg(_cmd2(0xFF, byte1=0x64)))
        self.assertEqual(_sb_writes(mock), [])
        self.assertIsNone(e._g12_value)

    def test_clamped_low_and_high(self):
        e, mock, _ = self._at('150')
        e.process_rvc_msg(_cmd2(2))
        e.process_rvc_msg(_cmd2(200))
        self.assertEqual(_sb_writes(mock), [(SB_SET, '50'), (SB_SET, '300')])

    def test_equal_to_state_not_written(self):
        e, mock, _ = self._at('250')
        self.assertTrue(e.process_rvc_msg(_cmd2(25)))
        self.assertEqual(_sb_writes(mock), [])

    def test_out_of_range_inverter_value_not_overwritten(self):
        e, mock, _ = self._at('320')
        self.assertTrue(e.process_rvc_msg(_cmd2(30)))
        self.assertEqual(_sb_writes(mock), [])

    def test_unknown_state_not_written(self):
        e, mock, _ = self._at(None)
        self.assertTrue(e.process_rvc_msg(_cmd2(25)))
        self.assertEqual(_sb_writes(mock), [])
        self.assertEqual(e._g12_value, 25)

    def test_source_offline_not_written(self):
        e, mock, _ = self._at('300')
        _feed(mock, 'modbus/inverter/connected', 'offline')
        self.assertTrue(e.process_rvc_msg(_cmd2(25)))
        self.assertEqual(_sb_writes(mock), [])

    def test_other_instance_not_claimed(self):
        e, mock, _ = self._at('300')
        self.assertFalse(e.process_rvc_msg(_cmd2(25, instance=2)))
        self.assertEqual(_sb_writes(mock), [])

    def test_not_claimed_when_unmapped(self):
        e, mock, _ = _make_entity()
        self.assertFalse(e.process_rvc_msg(_cmd2(25)))
        self.assertEqual(_sb_writes(mock), [])

    def test_custom_set_topic(self):
        e, mock, _ = self._at('300', extra={'shore_breaker_set_topic': 'set/setting39'})
        e.process_rvc_msg(_cmd2(25))
        self.assertEqual(_sb_writes(mock, 'modbus/inverter/set/setting39'),
                         [('modbus/inverter/set/setting39', '250')])

    def test_inverter_command_still_works(self):
        e, mock, _ = self._at('300')
        self.assertTrue(e.process_rvc_msg(_cmd(enable='01')))
        self.assertEqual(_onoff_publishes(mock), [('modbus/inverter/set/onoff', '1')])


def _g12_report(value, source='9C', selector=0x90):
    """A decoded G12_CONFIGURATION (15FCE) report of a config selector."""
    data = bytes([selector, 0x00, value & 0xFF, value >> 8, 0, 0, 0, 0])
    msg = _decode({'dgn': '15FCE', 'data': data, 'source_id': source})
    assert msg['name'] == 'G12_CONFIGURATION'
    return msg


class Test_G12Sync(unittest.TestCase):
    SET_15 = 'FF96900F0F00D1EA'
    READBACK = 'FF96900FFFFFD3FF'

    def _tick(self, e, clock, now):
        clock['now'] = now
        e.tick(now)

    def _state(self, e, mock, clock, now, raw):
        clock['now'] = now
        _feed(mock, SB_TOPIC, raw)

    def _hex(self, e):
        return [bytes(f['data']).hex().upper() for f in _g12_frames(e)]

    def _report(self, e, clock, now, value):
        clock['now'] = now
        return e.process_rvc_msg(_g12_report(value))

    def _queried(self, raw='150'):
        """Entity whose inverter value is known and which has just asked the
        G12 for its value at t=1002."""
        e, mock, clock = _sb_entity(sync=True)
        self._state(e, mock, clock, 1000.0, raw)
        self._tick(e, clock, 1002.0)
        self.assertEqual(self._hex(e), [self.READBACK])
        mock.client.publish.reset_mock()
        return e, mock, clock

    def _pushed_15(self):
        """G12 reported 30, inverter is 15: 15 pushed at t=1002.1."""
        e, mock, clock = self._queried('150')
        self._report(e, clock, 1002.01, 30)
        self._tick(e, clock, 1002.1)
        self.assertEqual(self._hex(e), [self.SET_15, self.READBACK])
        return e, mock, clock

    def _synced_at_30(self):
        e, mock, clock = self._queried('300')
        self._report(e, clock, 1002.01, 30)
        return e, mock, clock

    def test_sync_off_never_writes_g12(self):
        e, mock, clock = _sb_entity()
        self._state(e, mock, clock, 1000.0, '150')
        for t in (1001.0, 1003.0, 1010.0):
            self._tick(e, clock, t)
        self.assertEqual(_g12_frames(e), [])

    def test_sync_off_does_not_claim_report(self):
        e, _, _ = _sb_entity()
        self.assertFalse(e.process_rvc_msg(_g12_report(15)))

    def test_report_claimed_only_from_g12_and_selector_90(self):
        e, _, _ = _sb_entity(sync=True)
        self.assertTrue(e.process_rvc_msg(_g12_report(15)))
        self.assertFalse(e.process_rvc_msg(_g12_report(15, source='9F')))
        self.assertFalse(e.process_rvc_msg(_g12_report(15, selector=0x92)))

    def test_first_asks_after_settle_without_writing(self):
        e, mock, clock = _sb_entity(sync=True)
        self._state(e, mock, clock, 1000.0, '150')
        self._tick(e, clock, 1001.9)
        self.assertEqual(_g12_frames(e), [])
        self._tick(e, clock, 1002.0)
        frames = _g12_frames(e)
        self.assertEqual([bytes(f['data']).hex().upper() for f in frames], [self.READBACK])
        self.assertNotIn('source_id', frames[0])

    def test_startup_already_in_sync_never_pushes_or_fails(self):
        e, mock, clock = self._queried('150')
        self.assertTrue(self._report(e, clock, 1002.01, 15))
        for t in (1002.1, 1003.5, 1006.0, 1100.0):
            self._tick(e, clock, t)
        self.assertEqual(_g12_frames(e), [])
        self.assertEqual(e._push_failures, 0)
        self.assertFalse(e._sync_latched)
        self.assertEqual(_sb_writes(mock), [])

    def test_push_when_g12_differs_has_no_source_override(self):
        e, mock, clock = self._queried('150')
        self._report(e, clock, 1002.01, 30)
        self._tick(e, clock, 1002.1)
        frames = _g12_frames(e)
        self.assertEqual([bytes(f['data']).hex().upper() for f in frames],
                         [self.SET_15, self.READBACK])
        for f in frames:
            self.assertNotIn('source_id', f)

    def test_report_confirms_push(self):
        e, mock, clock = self._pushed_15()
        self._report(e, clock, 1002.11, 15)
        self.assertEqual(e._g12_value, 15)
        self.assertEqual(e._push_failures, 0)
        for t in (1003.5, 1006.0, 1020.0):
            self._tick(e, clock, t)
        self.assertEqual(_g12_frames(e), [])
        self.assertEqual(_sb_writes(mock), [])

    def test_relay_then_report_confirms_push(self):
        e, mock, clock = self._pushed_15()
        clock['now'] = 1002.106
        self.assertTrue(e.process_rvc_msg(_cmd2(15)))
        self._report(e, clock, 1002.11, 15)
        self.assertEqual(e._push_failures, 0)
        self.assertEqual(_sb_writes(mock), [])
        self._tick(e, clock, 1010.0)
        self.assertEqual(_g12_frames(e), [])

    def test_silent_g12_retried_then_latched(self):
        e, mock, clock = self._queried('150')
        e.Logger = MagicMock()
        attempts = [[self.READBACK]]
        t = 1002.0
        for _ in range(200):
            t += 0.25
            self._tick(e, clock, t)
            sent = self._hex(e)
            if sent:
                attempts.append(sent)
        self.assertEqual(attempts, [[self.READBACK]] * 3)
        self.assertTrue(e._sync_latched)
        e.Logger.error.assert_called_once()
        self.assertEqual(_sb_writes(mock), [])

    def test_unanswered_push_asks_again_before_writing(self):
        e, mock, clock = self._pushed_15()
        self._tick(e, clock, 1003.2)      # no report: failure 1
        self.assertEqual(e._push_failures, 1)
        self.assertIsNone(e._g12_value)
        self._tick(e, clock, 1005.3)
        self.assertEqual(self._hex(e), [self.READBACK])

    def test_mismatched_report_counts_and_never_writes_inverter(self):
        e, mock, clock = self._pushed_15()
        self._report(e, clock, 1002.11, 30)
        self.assertEqual(e._push_failures, 1)
        self.assertEqual(e._g12_value, 30)
        self.assertEqual(_sb_writes(mock), [])
        self._tick(e, clock, 1003.0)      # still settling after the failure
        self.assertEqual(_g12_frames(e), [])
        self._tick(e, clock, 1004.2)
        self.assertEqual(self._hex(e), [self.SET_15, self.READBACK])

    def test_delta_behaviour_latches_without_writing_inverter(self):
        e, mock, clock = self._pushed_15()
        e.Logger = MagicMock()
        t = 1002.1
        for _ in range(3):
            self._report(e, clock, t + 0.01, 30)   # G12 keeps saying 30
            t += 2.1
            self._tick(e, clock, t)
        self.assertTrue(e._sync_latched)
        self.assertEqual(_sb_writes(mock), [])
        _drain(e.send_queue)
        self._tick(e, clock, t + 60)
        self.assertEqual(_g12_frames(e), [])

    def test_mismatched_relay_in_window_not_written(self):
        e, mock, clock = self._pushed_15()
        clock['now'] = 1002.11
        self.assertTrue(e.process_rvc_msg(_cmd2(30)))
        self.assertEqual(_sb_writes(mock), [])
        self.assertEqual(e._push_failures, 1)

    def test_confirmation_resets_failure_count(self):
        e, mock, clock = self._pushed_15()
        self._tick(e, clock, 1003.2)      # timeout -> failure 1
        self._tick(e, clock, 1005.3)      # asks again
        self._report(e, clock, 1005.31, 30)
        self.assertEqual(e._push_failures, 0)
        self.assertFalse(e._sync_latched)

    def test_relay_after_window_is_a_press(self):
        e, mock, clock = self._pushed_15()
        self._tick(e, clock, 1003.2)      # window closed
        clock['now'] = 1003.3
        e.process_rvc_msg(_cmd2(20))
        self.assertEqual(_sb_writes(mock), [(SB_SET, '200')])

    def test_press_while_asking_is_still_a_press(self):
        e, mock, clock = self._queried('300')
        clock['now'] = 1002.2
        e.process_rvc_msg(_cmd2(25))
        self.assertEqual(_sb_writes(mock), [(SB_SET, '250')])

    def test_panel_press_report_before_relay_is_not_undone(self):
        """A press arrives as the G12's 15FCE report first and the 1FF95
        relay a few ms later.  A main-loop pass in between must not push the
        inverter's old value back over the press."""
        e, mock, clock = self._queried('150')
        self._report(e, clock, 1002.01, 15)          # in sync at 15
        _drain(e.send_queue)
        self._report(e, clock, 1050.002, 20)         # unsolicited: press in progress
        self._tick(e, clock, 1050.004)
        self.assertEqual(_g12_frames(e), [])
        clock['now'] = 1050.006
        self.assertTrue(e.process_rvc_msg(_cmd2(20)))
        self.assertEqual(_sb_writes(mock), [(SB_SET, '200')])
        self.assertEqual(e._push_failures, 0)
        self._state(e, mock, clock, 1050.2, '200')
        for t in (1051.0, 1052.3, 1060.0):
            self._tick(e, clock, t)
        self.assertEqual(_g12_frames(e), [])

    def test_unsolicited_report_without_relay_pushed_after_settle(self):
        e, mock, clock = self._queried('150')
        self._report(e, clock, 1002.01, 15)
        _drain(e.send_queue)
        self._report(e, clock, 1050.0, 20)
        self._tick(e, clock, 1051.9)
        self.assertEqual(_g12_frames(e), [])
        self._tick(e, clock, 1052.0)
        self.assertEqual(self._hex(e), [self.SET_15, self.READBACK])
        self.assertEqual(_sb_writes(mock), [])

    def test_report_never_writes_inverter(self):
        e, mock, clock = self._synced_at_30()
        self._report(e, clock, 1050.0, 20)
        self.assertEqual(_sb_writes(mock), [])

    def test_single_press_causes_no_push(self):
        e, mock, clock = self._synced_at_30()
        clock['now'] = 1010.0
        e.process_rvc_msg(_cmd2(25))
        self.assertEqual(_sb_writes(mock), [(SB_SET, '250')])
        self._state(e, mock, clock, 1010.2, '250')
        for t in (1011.0, 1012.5, 1020.0):
            self._tick(e, clock, t)
        self.assertEqual(_g12_frames(e), [])

    def test_two_quick_presses_cause_no_push(self):
        e, mock, clock = self._synced_at_30()
        clock['now'] = 1010.0
        e.process_rvc_msg(_cmd2(25))
        clock['now'] = 1010.3
        e.process_rvc_msg(_cmd2(20))
        self.assertEqual(_sb_writes(mock), [(SB_SET, '250'), (SB_SET, '200')])
        self._state(e, mock, clock, 1010.4, '250')
        self._tick(e, clock, 1010.5)
        self._tick(e, clock, 1011.0)
        self._state(e, mock, clock, 1011.2, '200')
        for t in (1012.0, 1013.3, 1020.0):
            self._tick(e, clock, t)
        self.assertEqual(_g12_frames(e), [])

    def test_refused_write_pushes_old_value_back(self):
        e, mock, clock = self._synced_at_30()
        clock['now'] = 1010.0
        e.process_rvc_msg(_cmd2(25))
        self._tick(e, clock, 1011.9)
        self.assertEqual(_g12_frames(e), [])
        self._tick(e, clock, 1012.0)
        self.assertEqual(self._hex(e)[0], 'FF96900F1E00D1EA')

    def test_change_from_home_assistant_is_pushed(self):
        e, mock, clock = self._synced_at_30()
        self._state(e, mock, clock, 1010.0, '200')
        self._tick(e, clock, 1012.0)
        self.assertEqual(self._hex(e)[0], 'FF96900F1400D1EA')

    def test_nothing_sent_while_source_offline(self):
        e, mock, clock = _sb_entity(sync=True)
        self._state(e, mock, clock, 1000.0, '150')
        _feed(mock, 'modbus/inverter/connected', 'offline')
        self._tick(e, clock, 1005.0)
        self.assertEqual(_g12_frames(e), [])
        _feed(mock, 'modbus/inverter/connected', 'online')
        self._tick(e, clock, 1006.0)
        self.assertEqual(self._hex(e), [self.READBACK])


if __name__ == "__main__":
    unittest.main()
