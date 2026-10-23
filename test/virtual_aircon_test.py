"""
Unit tests for the virtual air conditioner entity.
"""
import logging
import queue
import unittest
from unittest.mock import MagicMock
import context  # add rvc2mqtt package to the python path using local reference
from rvc2mqtt.entity.virtual_aircon import (
    OptimisticState, VirtualAircon,
    parse_mode, parse_fan, parse_preset, parse_onoff, parse_number)


def _make_state(timeout: float = 35.0, now: float = 0.0):
    clock = {'now': now}
    state = OptimisticState(timeout, lambda: clock['now'], logging.getLogger('test'))
    return state, clock


class Test_OptimisticState(unittest.TestCase):

    def test_effective_falls_back_to_default(self):
        s, _ = _make_state()
        self.assertEqual(s.effective('mode', 'off'), 'off')
        self.assertIsNone(s.effective('mode'))

    def test_report_sets_effective(self):
        s, _ = _make_state()
        self.assertTrue(s.report('mode', 'cool'))
        self.assertEqual(s.effective('mode'), 'cool')
        self.assertFalse(s.report('mode', 'cool'))  # unchanged

    def test_command_is_effective_immediately(self):
        s, _ = _make_state()
        s.report('mode', 'off')
        s.command('mode', 'cool')
        self.assertEqual(s.effective('mode'), 'cool')
        self.assertTrue(s.is_pending('mode'))

    def test_matching_report_confirms(self):
        s, _ = _make_state()
        s.report('mode', 'off')
        s.command('mode', 'cool')
        s.report('mode', 'cool')
        self.assertFalse(s.is_pending('mode'))
        self.assertEqual(s.effective('mode'), 'cool')

    def test_nonmatching_report_held_while_pending(self):
        s, _ = _make_state()
        s.command('setpoint', 25)
        self.assertFalse(s.report('setpoint', 24))
        self.assertEqual(s.effective('setpoint'), 25)
        self.assertEqual(s.reported('setpoint'), 24)

    def test_expire_reverts_after_timeout(self):
        s, clock = _make_state(timeout=35)
        s.report('setpoint', 24)
        s.command('setpoint', 25)
        clock['now'] = 34
        self.assertEqual(s.expire(), [])
        self.assertEqual(s.effective('setpoint'), 25)
        clock['now'] = 35.1
        self.assertEqual(s.expire(), ['setpoint'])
        self.assertEqual(s.effective('setpoint'), 24)
        self.assertFalse(s.is_pending('setpoint'))

    def test_new_command_extends_deadline(self):
        s, clock = _make_state(timeout=35)
        s.command('setpoint', 25)
        clock['now'] = 30
        s.command('setpoint', 26)
        clock['now'] = 40
        self.assertEqual(s.expire(), [])
        self.assertTrue(s.is_pending('setpoint'))

    def test_unrelated_field_report_applies(self):
        s, _ = _make_state()
        s.command('mode', 'cool')
        self.assertTrue(s.report('fan', 3))
        self.assertEqual(s.effective('fan'), 3)
        self.assertTrue(s.is_pending('mode'))


def _make_mock():
    mock = MagicMock()
    mock.make_device_topic_string.return_value = 'test/topic'
    mock.TOPIC_BASE = 'rvc2mqtt'
    mock.client_id = 'bridge'
    mock.get_bridge_ha_name.return_value = 'bridge'
    return mock


def _make_entity(extra: dict = None, now: float = 1000.0):
    mock = _make_mock()
    data = {'name': 'VIRTUAL_AIRCON', 'type': 'virtual_aircon', 'instance': 7}
    if extra:
        data.update(extra)
    entity = VirtualAircon(data, mock)
    clock = {'now': now}
    entity._clock = lambda: clock['now']
    entity.state._clock = entity._clock
    entity.set_rvc_send_queue(queue.Queue())
    return entity, mock, clock


def _registered(mock) -> dict:
    """topic -> (callback, retain_ok) from mock.register calls."""
    out = {}
    for c in mock.register.call_args_list:
        args, kwargs = c
        retain_ok = kwargs.get('retain_ok', args[2] if len(args) > 2 else False)
        out[args[0]] = (args[1], retain_ok)
    return out


def _published(mock) -> list:
    """[(topic, payload, retain)] from mock.client.publish calls."""
    return [(c.args[0], c.args[1], c.kwargs.get('retain', False))
            for c in mock.client.publish.call_args_list]


def _mqtt(entity, field, payload):
    entity.process_mqtt_msg(entity.state_topics[field], payload)


class Test_Parsers(unittest.TestCase):

    def test_parse_mode(self):
        for p, want in (('cool', 'cool'), ('OFF', 'off'), ('fan', 'fan_only'), ('fan_only', 'fan_only'),
                        ('heat_cool', 'auto'), ('Dry', 'dry'), ('auto', 'auto'),
                        ('heat', None), ('unavailable', None), ('', None)):
            self.assertEqual(parse_mode(p), want, p)

    def test_parse_fan(self):
        for p, want in (('3', 3), ('3.0', 3), (' 3 ', 3), ('auto', 'auto'), ('AUTO', 'auto'),
                        ('0', None), ('6', None), ('unknown', None), ('x', None)):
            self.assertEqual(parse_fan(p), want, p)

    def test_parse_preset(self):
        for p, want in (('none', 'none'), ('Cooling', 'none'), ('Eco', 'eco'), ('energy_saving', 'eco'),
                        ('Sleep', 'sleep'), ('Turbo', 'turbo'), ('boost', 'turbo'),
                        ('unavailable', None), ('', None)):
            self.assertEqual(parse_preset(p), want, p)

    def test_parse_onoff(self):
        for p, want in (('on', True), ('ON', True), ('1', True), ('true', True),
                        ('off', False), ('0', False), ('False', False), ('unknown', None), ('x', None)):
            self.assertEqual(parse_onoff(p), want, p)

    def test_parse_number(self):
        for p, want in (('24', 24.0), ('22.4', 22.4), (' 23.6 ', 23.6), ('nan', None), ('inf', None),
                        ('unavailable', None), ('', None)):
            self.assertEqual(parse_number(p), want, p)


class Test_Construction(unittest.TestCase):

    def test_defaults(self):
        e, _, _ = _make_entity()
        self.assertEqual(e.rvc_instance, 7)
        self.assertEqual(e.id, 'virtual-aircon-1FFE2-i7')
        self.assertEqual(e.source_id, '58')
        self.assertEqual(e.topic_base, 'rvc2mqtt/aircon')
        self.assertEqual(e.set_topics['mode'], 'rvc2mqtt/aircon/set/mode')
        self.assertEqual(e.state_topics['temperature'], 'rvc2mqtt/aircon/state/temperature')
        self.assertNotIn('temperature', e.set_topics)
        self.assertEqual(set(e.set_topics), {'mode', 'fan', 'setpoint', 'preset', 'oscillate', 'display'})
        self.assertEqual(e.confirm_timeout, 35.0)
        self.assertEqual(e.interval, 1.0)
        self.assertEqual(e.temperature_unit, 'C')
        self.assertEqual((e.setpoint_min, e.setpoint_max, e.setpoint_default), (17, 30, 24))
        self.assertIsNone(e.availability_topic)
        self.assertTrue(e.available)

    def test_fahrenheit_defaults(self):
        e, _, _ = _make_entity({'temperature_unit': 'f'})
        self.assertEqual(e.temperature_unit, 'F')
        self.assertEqual((e.setpoint_min, e.setpoint_max, e.setpoint_default), (62, 86, 75))

    def test_bad_config_raises(self):
        for bad in ({'interval': 0}, {'temperature_unit': 'K'}, {'confirm_timeout': -1},
                    {'fields': {'bogus': {'state': 'x'}}}, {'step_codes': {0xFFFC: 'sideways'}}):
            with self.assertRaises(ValueError, msg=str(bad)):
                _make_entity(bad)

    def test_field_override(self):
        e, _, _ = _make_entity({'fields': {'setpoint': {'set': 'velit/sp/set'},
                                           'mode': {'state': 'rvc2mqtt/aircon/custom/mode'}}})
        self.assertEqual(e.set_topics['setpoint'], 'rvc2mqtt/aircon/velit/sp/set')
        self.assertEqual(e.state_topics['setpoint'], 'rvc2mqtt/aircon/state/setpoint')
        self.assertEqual(e.state_topics['mode'], 'rvc2mqtt/aircon/custom/mode')

    def test_step_codes_from_floorplan(self):
        e, _, _ = _make_entity({'step_codes': {'0xFFFC': 'down', 0xFFFB: 'up'}})
        self.assertEqual(e.step_codes, {0xFFFC: -1, 0xFFFB: +1, 0xFFFA: +1, 0xFFF9: -1})

    def test_state_topics_registered_retain_ok(self):
        e, mock, _ = _make_entity({'availability_topic': 'velit/ac/availability'})
        reg = _registered(mock)
        for topic in list(e.state_topics.values()) + ['velit/ac/availability']:
            self.assertIn(topic, reg)
            self.assertTrue(reg[topic][1], topic)
        for topic in e.set_topics.values():
            self.assertNotIn(topic, reg)  # set topics are outbound only

    def test_no_ha_discovery(self):
        e, mock, _ = _make_entity()
        e.initialize()
        for topic, _payload, _retain in _published(mock):
            self.assertFalse(topic.startswith('homeassistant/'), topic)


class Test_StateIngest(unittest.TestCase):

    def test_ingest_each_field(self):
        e, _, _ = _make_entity()
        e._dirty = False
        for field, payload in (('mode', 'cool'), ('fan', '3'), ('setpoint', '24'), ('preset', 'eco'),
                               ('oscillate', 'on'), ('display', 'off'), ('temperature', '22.5')):
            _mqtt(e, field, payload)
        self.assertEqual(e.state.effective('mode'), 'cool')
        self.assertEqual(e.state.effective('fan'), 3)
        self.assertEqual(e.state.effective('setpoint'), 24)
        self.assertEqual(e.state.effective('preset'), 'eco')
        self.assertIs(e.state.effective('oscillate'), True)
        self.assertIs(e.state.effective('display'), False)
        self.assertEqual(e.state.effective('temperature'), 22.5)
        self.assertTrue(e._dirty)

    def test_unchanged_report_not_dirty(self):
        e, _, _ = _make_entity()
        _mqtt(e, 'mode', 'cool')
        e._dirty = False
        _mqtt(e, 'mode', 'cool')
        self.assertFalse(e._dirty)

    def test_ha_unavailable_strings_ignored(self):
        e, _, _ = _make_entity()
        _mqtt(e, 'mode', 'cool')
        with self.assertLogs(level='DEBUG') as logs:
            _mqtt(e, 'mode', 'unavailable')
            _mqtt(e, 'mode', 'unknown')
            _mqtt(e, 'setpoint', 'unavailable')
        self.assertEqual(e.state.effective('mode'), 'cool')
        self.assertTrue(all(r.levelno <= logging.DEBUG for r in logs.records))

    def test_bad_payload_warns_and_keeps_value(self):
        e, _, _ = _make_entity()
        _mqtt(e, 'fan', '3')
        with self.assertLogs(level='WARNING'):
            _mqtt(e, 'fan', 'banana')
        self.assertEqual(e.state.effective('fan'), 3)

    def test_float_formatted_payloads(self):
        e, _, _ = _make_entity()
        _mqtt(e, 'setpoint', '24.0')
        self.assertEqual(e.state.effective('setpoint'), 24)
        self.assertIsInstance(e.state.effective('setpoint'), int)
        _mqtt(e, 'setpoint', '23.6')
        self.assertEqual(e.state.effective('setpoint'), 24)
        _mqtt(e, 'fan', '3.0')
        self.assertEqual(e.state.effective('fan'), 3)
        _mqtt(e, 'temperature', '22.4')
        self.assertEqual(e.state.effective('temperature'), 22.4)

    def test_velit_preset_names(self):
        e, _, _ = _make_entity()
        _mqtt(e, 'preset', 'Cooling')
        self.assertEqual(e.state.effective('preset'), 'none')
        _mqtt(e, 'preset', 'Turbo')
        self.assertEqual(e.state.effective('preset'), 'turbo')

    def test_availability(self):
        e, _, _ = _make_entity({'availability_topic': 'velit/ac/availability'})
        e._dirty = False
        e.process_mqtt_msg('velit/ac/availability', 'offline')
        self.assertFalse(e.available)
        self.assertTrue(e._dirty)
        e.process_mqtt_msg('velit/ac/availability', 'online')
        self.assertTrue(e.available)

    def test_callback_never_raises(self):
        e, _, _ = _make_entity()
        e.process_mqtt_msg('some/other/topic', 'x')
        e.process_mqtt_msg(e.state_topics['mode'], None)


if __name__ == "__main__":
    unittest.main()
