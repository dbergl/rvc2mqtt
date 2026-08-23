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


if __name__ == "__main__":
    unittest.main()
