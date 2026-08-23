"""
Unit tests for the virtual inverter entity.
"""
import os
import queue
import unittest
from unittest.mock import MagicMock
import context  # add rvc2mqtt package to the python path using local reference
import rvc2mqtt
from rvc2mqtt.rvc import RVC_Decoder
from rvc2mqtt.entity.virtual_inverter import VirtualInverter, FIELD_DEFAULTS


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
        self.assertEqual(e.stale_timeout, 30.0)
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
        for f in ('ac_out_voltage', 'ac_out_current', 'ac_out_frequency',
                  'dc_voltage', 'dc_current'):
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

    def test_connected_topic(self):
        e, mock, _ = _make_entity()
        self.assertTrue(e.connected)
        self._feed(e, mock, 'modbus/inverter/connected', 'offline')
        self.assertFalse(e.connected)
        self._feed(e, mock, 'modbus/inverter/connected', 'online')
        self.assertTrue(e.connected)


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

    def test_four_frames_with_source_id(self):
        e, _, _ = _make_entity({'source_id': 'A5'})
        frames = e.build_frames()
        self.assertEqual([f['dgn'] for f in frames], ['1FFD4', '1FFD7', '1FFD7', '1FEE8'])
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
        msg = _decode(e.build_frames()[3])
        self.assertEqual(msg['name'], 'INVERTER_DC_STATUS')
        self.assertEqual(msg['instance'], 1)
        self.assertEqual(msg['dc_voltage'], 52.0)
        self.assertEqual(msg['dc_amperage'], -12.5)
        self.assertEqual(msg['data'][10:], 'FFFFFF')

    def test_dc_status_not_available(self):
        e, _, _ = _make_entity()
        msg = _decode(e.build_frames()[3])
        self.assertEqual(msg['dc_voltage'], 'n/a')
        self.assertEqual(msg['dc_amperage'], 'n/a')


def _drain(q: queue.Queue) -> list:
    out = []
    while not q.empty():
        out.append(q.get())
    return out


class Test_Tick(unittest.TestCase):

    def _ready(self, now=100.0):
        e, mock, clock = _make_entity(now=now)
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
        self.assertEqual([f['dgn'] for f in frames], ['1FFD4', '1FFD7', '1FFD7', '1FEE8'])

    def test_respects_interval(self):
        e, _, _ = self._ready(100.0)
        e.tick(100.0)
        _drain(e.send_queue)
        e.tick(100.5)
        self.assertEqual(_drain(e.send_queue), [])
        e.tick(101.0)
        self.assertEqual(len(_drain(e.send_queue)), 4)

    def test_custom_interval(self):
        e, mock, clock = _make_entity({'interval': 5.0}, now=100.0)
        e.initialize()
        _registered(mock)['modbus/inverter/state/status'][0]('modbus/inverter/state/status', '4')
        e.tick(100.0)
        _drain(e.send_queue)
        e.tick(104.9)
        self.assertEqual(_drain(e.send_queue), [])
        e.tick(105.0)
        self.assertEqual(len(_drain(e.send_queue)), 4)

    def test_silent_when_stale(self):
        e, _, clock = self._ready(100.0)
        e.tick(100.0)
        _drain(e.send_queue)
        e.tick(131.0)  # > stale_timeout (30 s) since last status
        self.assertEqual(_drain(e.send_queue), [])

    def test_resumes_after_fresh_status(self):
        e, mock, clock = self._ready(100.0)
        e.tick(131.0)
        self.assertEqual(_drain(e.send_queue), [])
        clock['now'] = 131.5
        _registered(mock)['modbus/inverter/state/onoff'][0]('modbus/inverter/state/onoff', '1')
        e.tick(132.0)
        self.assertEqual(len(_drain(e.send_queue)), 4)

    def test_silent_when_offline(self):
        e, mock, _ = self._ready(100.0)
        _registered(mock)['modbus/inverter/connected'][0]('modbus/inverter/connected', 'offline')
        e.tick(100.0)
        self.assertEqual(_drain(e.send_queue), [])
        _registered(mock)['modbus/inverter/connected'][0]('modbus/inverter/connected', 'online')
        e.tick(101.0)
        self.assertEqual(len(_drain(e.send_queue)), 4)

    def test_silence_transition_logged_once(self):
        e, _, _ = self._ready(100.0)
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


if __name__ == "__main__":
    unittest.main()
