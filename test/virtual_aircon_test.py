"""
Unit tests for the virtual air conditioner entity.
"""
import logging
import queue
import unittest
from unittest.mock import MagicMock
import context  # add rvc2mqtt package to the python path using local reference
from rvc2mqtt.rvc_encode import encode_temperature_u16
from rvc2mqtt.entity.virtual_aircon import (
    OptimisticState, VirtualAircon, COMMAND_FIELDS,
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

    def test_redundant_command_not_pending(self):
        """A command equal to the reported value gets no confirming report (HA
        publishes on change only), so it must not hold off later real reports."""
        s, _ = _make_state()
        s.report('mode', 'cool')
        s.command('mode', 'cool')
        self.assertFalse(s.is_pending('mode'))
        s.report('mode', 'off')
        self.assertEqual(s.effective('mode'), 'off')

    def test_command_back_to_reported_while_pending_stays_pending(self):
        s, _ = _make_state()
        s.report('setpoint', 24)
        s.command('setpoint', 25)
        s.command('setpoint', 24)
        self.assertTrue(s.is_pending('setpoint'))
        self.assertEqual(s.effective('setpoint'), 24)

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

    def test_bad_payload_warning_is_bounded(self):
        """A source publishing ever-changing junk warns once per field (until a
        good value arrives) and doesn't grow memory per distinct payload."""
        e, _, _ = _make_entity()
        with self.assertLogs(level='WARNING') as logs:
            for i in range(50):
                _mqtt(e, 'fan', f'junk-{i}' + 'x' * 500)
        self.assertEqual(len(logs.records), 1)
        self.assertLess(len(logs.records[0].getMessage()), 200)
        self.assertLessEqual(len(e._warned), 1)
        _mqtt(e, 'fan', '2')
        with self.assertLogs(level='WARNING') as logs:
            _mqtt(e, 'fan', 'junk-again')
        self.assertEqual(len(logs.records), 1)

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


def _frames(entity) -> dict:
    """dgn -> data hex (upper) from build_frames()."""
    return {f['dgn']: f['data'].hex().upper() for f in entity.build_frames()}


def _drain(entity) -> list:
    out = []
    while not entity.send_queue.empty():
        out.append(entity.send_queue.get_nowait())
    return out


class Test_StatusFrames(unittest.TestCase):

    def test_frames_before_any_report(self):
        e, _, _ = _make_entity()
        frames = e.build_frames()
        self.assertEqual([f['dgn'] for f in frames], ['1FFE2', '1FEFA', '1FF9C', '0FFA1'])
        self.assertTrue(all(f['source_id'] == '58' for f in frames))
        self.assertTrue(all(len(f['data']) == 8 for f in frames))
        self.assertEqual([f['data'].hex().upper() for f in frames],
                         ['070000FFFFFFFFFF', '07FFFFC0FFFFFFFF', '07FFFFFFFFFFFFFF', '07F0FFFFFFFFFFFF'])

    def test_frames_cool_fan3_24c(self):
        e, _, _ = _make_entity()
        for field, payload in (('mode', 'cool'), ('fan', '3'), ('setpoint', '24'), ('temperature', '22.5')):
            _mqtt(e, field, payload)
        f = _frames(e)
        self.assertEqual(f['1FFE2'], '071178FFFF2025FF')
        self.assertEqual(f['1FF9C'], '07F024FFFFFFFFFF')

    def test_instance_in_byte0(self):
        e, _, _ = _make_entity({'instance': 3})
        self.assertTrue(all(h.startswith('03') for h in _frames(e).values()))

    def test_fan_thresholds(self):
        e, _, _ = _make_entity()
        for speed, byte2 in ((1, 0x28), (2, 0x50), (3, 0x78), (4, 0xA0), (5, 0xC8)):
            _mqtt(e, 'fan', str(speed))
            data = bytes.fromhex(_frames(e)['1FFE2'])
            self.assertEqual(data[2], byte2)
            self.assertEqual((data[1] >> 4) & 0b11, 0b01)
        _mqtt(e, 'fan', 'auto')
        data = bytes.fromhex(_frames(e)['1FFE2'])
        self.assertEqual(data[2], 0)
        self.assertEqual((data[1] >> 4) & 0b11, 0b00)

    def test_mode_codes(self):
        e, _, _ = _make_entity()
        for mode, code in (('off', 0), ('cool', 1), ('auto', 3), ('fan_only', 4), ('dry', 6)):
            _mqtt(e, 'mode', mode)
            self.assertEqual(bytes.fromhex(_frames(e)['1FFE2'])[1] & 0x0F, code, mode)

    def test_preset_bits(self):
        e, _, _ = _make_entity()
        for preset, byte3 in (('none', 0xC0), ('sleep', 0xC1), ('eco', 0xC4), ('turbo', 0xD0)):
            _mqtt(e, 'preset', preset)
            self.assertEqual(bytes.fromhex(_frames(e)['1FEFA'])[3], byte3, preset)

    def test_osc_display_bits(self):
        e, _, _ = _make_entity()
        _mqtt(e, 'oscillate', 'on')
        _mqtt(e, 'display', 'off')
        self.assertEqual(_frames(e)['0FFA1'], '07F1FFFFFFFFFFFF')
        _mqtt(e, 'display', 'on')
        self.assertEqual(_frames(e)['0FFA1'], '07F5FFFFFFFFFFFF')

    def test_fahrenheit_encoding(self):
        e, _, _ = _make_entity({'temperature_unit': 'F'})
        _mqtt(e, 'setpoint', '75')
        _mqtt(e, 'temperature', '72.5')
        raw = encode_temperature_u16((75 - 32) * 5 / 9)
        data = bytes.fromhex(_frames(e)['1FFE2'])
        self.assertEqual(data[5] | data[6] << 8, raw)
        data = bytes.fromhex(_frames(e)['1FF9C'])
        self.assertEqual(data[1] | data[2] << 8, encode_temperature_u16((72.5 - 32) * 5 / 9))

    def test_offline_reports_mode_off(self):
        e, _, _ = _make_entity({'availability_topic': 'velit/ac/availability'})
        _mqtt(e, 'mode', 'cool')
        _mqtt(e, 'fan', '2')
        e.process_mqtt_msg('velit/ac/availability', 'offline')
        data = bytes.fromhex(_frames(e)['1FFE2'])
        self.assertEqual(data[1] & 0x0F, 0)
        self.assertEqual(data[2], 0x50)  # rest unchanged


class Test_Tick(unittest.TestCase):

    def test_tick_cadence(self):
        e, _, clock = _make_entity(now=0.0)
        e.initialize()
        e.tick(0.0)
        self.assertEqual(len(_drain(e)), 4)
        e.tick(0.5)
        self.assertEqual(len(_drain(e)), 0)
        e.tick(1.0)
        self.assertEqual(len(_drain(e)), 4)
        clock['now'] = 1.2
        _mqtt(e, 'mode', 'cool')
        e.tick(1.2)
        self.assertEqual(len(_drain(e)), 4)
        e.tick(1.3)
        self.assertEqual(len(_drain(e)), 0)

    def test_tick_expiry_rebroadcasts(self):
        e, _, clock = _make_entity(now=0.0)
        _mqtt(e, 'mode', 'off')
        e.state.command('mode', 'cool')
        e.tick(0.0)
        frames = {f['dgn']: f['data'] for f in _drain(e)}
        self.assertEqual(frames['1FFE2'][1] & 0x0F, 1)
        e.tick(0.5)
        self.assertEqual(_drain(e), [])
        clock['now'] = 35.1
        e.tick(35.1)
        frames = {f['dgn']: f['data'] for f in _drain(e)}
        self.assertEqual(frames['1FFE2'][1] & 0x0F, 0)


_DGN_NAMES = {'1FEF9': 'THERMOSTAT_COMMAND_1', '1FEF8': 'THERMOSTAT_COMMAND_2', '0FFA0': 'UNKNOWN-0FFA0',
              '1FFE2': 'THERMOSTAT_STATUS_1', '1FFBD': 'DC_LOAD_STATUS'}


def _rvc(entity, dgn, data, source_id='9F'):
    msg = {'dgn': dgn, 'data': data, 'source_id': source_id, 'name': _DGN_NAMES.get(dgn, 'X'),
           'instance': int(data[:2], 16) if data else None}
    return entity.process_rvc_msg(msg)


def _sets(entity, mock) -> list:
    """[(field, payload)] published to set topics, in order."""
    by_topic = {t: f for f, t in entity.set_topics.items()}
    out = []
    for topic, payload, retain in _published(mock):
        if topic in by_topic:
            assert retain is False, topic
            out.append((by_topic[topic], payload))
    return out


class Test_PanelCommands(unittest.TestCase):

    def test_power_cool_auto_dry_fan(self):
        for data, want in (('07F1FFFFFFFFFFFF', [('mode', 'cool')]),
                           ('07F0FFFFFFFFFFFF', [('mode', 'off')]),
                           ('07C3FFFFFFFFFFFF', [('mode', 'auto'), ('fan', 'auto')]),
                           ('07F6FFFFFFFFFFFF', [('mode', 'dry')]),
                           ('07F4FFFFFFFFFFFF', [('mode', 'fan_only')])):
            e, mock, _ = _make_entity()
            self.assertTrue(_rvc(e, '1FEF9', data))
            self.assertEqual(_sets(e, mock), want, data)
            self.assertEqual(e.state.effective('mode'), want[0][1])

    def test_fan_speeds(self):
        e, mock, _ = _make_entity()
        for byte2 in ('28', '50', '78', 'A0', 'C8'):
            _rvc(e, '1FEF9', f'07DF{byte2}FFFFFFFFFF')
        self.assertEqual(_sets(e, mock), [('fan', '1'), ('fan', '2'), ('fan', '3'), ('fan', '4'), ('fan', '5')])
        self.assertEqual(e.state.effective('fan'), 5)

    def test_setpoint_steps(self):
        e, mock, _ = _make_entity()
        _mqtt(e, 'setpoint', '24')
        for code in ('FC', 'FB', 'FA', 'F9'):
            _rvc(e, '1FEF9', f'07FFFFFFFF{code}FFFF')
        self.assertEqual(_sets(e, mock), [('setpoint', '25'), ('setpoint', '24'),
                                          ('setpoint', '25'), ('setpoint', '24')])

    def test_held_arrow_no_snapback(self):
        e, mock, _ = _make_entity()
        _mqtt(e, 'setpoint', '24')
        _rvc(e, '1FEF9', '07FFFFFFFFFCFFFF')
        _mqtt(e, 'setpoint', '24')  # stale report arrives mid-hold
        _rvc(e, '1FEF9', '07FFFFFFFFFCFFFF')
        _rvc(e, '1FEF9', '07FFFFFFFFFCFFFF')
        self.assertEqual(_sets(e, mock), [('setpoint', '25'), ('setpoint', '26'), ('setpoint', '27')])
        self.assertEqual(e.state.effective('setpoint'), 27)

    def test_step_at_clamp_publishes_nothing(self):
        """A held arrow at the limit must not flood HA (and the BT link) with
        repeats of the same setpoint."""
        e, mock, _ = _make_entity()
        _mqtt(e, 'setpoint', '30')
        for _ in range(5):
            _rvc(e, '1FEF9', '07FFFFFFFFFCFFFF')
        e2, mock2, _ = _make_entity()
        _mqtt(e2, 'setpoint', '17')
        _rvc(e2, '1FEF9', '07FFFFFFFFFBFFFF')
        self.assertEqual(_sets(e, mock), [])
        self.assertEqual(_sets(e2, mock2), [])
        self.assertEqual(e.state.effective('setpoint'), 30)

    def test_step_clamps_to_limit(self):
        e, mock, _ = _make_entity({'setpoint_max': 25})
        _mqtt(e, 'setpoint', '24')
        for _ in range(3):
            _rvc(e, '1FEF9', '07FFFFFFFFFCFFFF')
        self.assertEqual(_sets(e, mock), [('setpoint', '25')])

    def test_step_never_moves_wrong_way(self):
        """Reported value outside the configured range: down must not raise it."""
        e, mock, _ = _make_entity()
        _mqtt(e, 'setpoint', '16')
        _rvc(e, '1FEF9', '07FFFFFFFFFBFFFF')
        e2, mock2, _ = _make_entity()
        _mqtt(e2, 'setpoint', '31')
        _rvc(e2, '1FEF9', '07FFFFFFFFFCFFFF')
        self.assertEqual(_sets(e, mock), [])
        self.assertEqual(_sets(e2, mock2), [])

    def test_redundant_power_then_remote_off(self):
        """Pressing Cool while already Cool, then turning the AC off from its
        remote, must show Off at once (else the Power toggle sends the wrong command)."""
        e, mock, _ = _make_entity()
        _mqtt(e, 'mode', 'cool')
        _rvc(e, '1FEF9', '07F1FFFFFFFFFFFF')
        self.assertEqual(_sets(e, mock), [('mode', 'cool')])  # still forwarded to HA
        _mqtt(e, 'mode', 'off')
        self.assertEqual(bytes.fromhex(_frames(e)['1FFE2'])[1] & 0x0F, 0)

    def test_step_from_default_when_unknown(self):
        e, mock, _ = _make_entity()
        _rvc(e, '1FEF9', '07FFFFFFFFFCFFFF')
        self.assertEqual(_sets(e, mock), [('setpoint', '25')])

    def test_step_logged_at_info(self):
        e, _, _ = _make_entity()
        with self.assertLogs(level='INFO') as logs:
            _rvc(e, '1FEF9', '07FFFFFFFFFCFFFF')
        self.assertTrue(any('0xfffc' in r.getMessage().lower() for r in logs.records))

    def test_absolute_setpoint(self):
        e, mock, _ = _make_entity()
        _rvc(e, '1FEF9', '07FFFFFFFF2025FF')
        self.assertEqual(_sets(e, mock), [('setpoint', '24')])
        e, mock, _ = _make_entity({'temperature_unit': 'F'})
        _rvc(e, '1FEF9', '07FFFFFFFF2025FF')
        self.assertEqual(_sets(e, mock), [('setpoint', '75')])

    def test_presets(self):
        e, mock, _ = _make_entity()
        _rvc(e, '1FEF8', '07FFDFFFFFFFFFFF')   # turbo on
        _rvc(e, '1FEF8', '07FFCFFFFFFFFFFF')   # turbo off
        _rvc(e, '1FEF8', '07FFF7FFFFFFFFFF')   # eco on
        _rvc(e, '1FEF8', '07FFCFFFFFFFFFFF')   # turbo off while eco: nothing
        _rvc(e, '1FEF8', '07FFFDFFFFFFFFFF')   # sleep on
        _rvc(e, '1FEF8', '07FFFCFFFFFFFFFF')   # sleep off
        self.assertEqual(_sets(e, mock), [('preset', 'turbo'), ('preset', 'none'), ('preset', 'eco'),
                                          ('preset', 'sleep'), ('preset', 'none')])

    def test_preset_exclusive_in_status(self):
        e, _, _ = _make_entity()
        _mqtt(e, 'preset', 'eco')
        _rvc(e, '1FEF8', '07FFDFFFFFFFFFFF')
        self.assertEqual(bytes.fromhex(_frames(e)['1FEFA'])[3], 0xD0)

    def test_oscillate_display(self):
        e, mock, _ = _make_entity()
        for data in ('07FDFFFFFFFFFFFF', '07FCFFFFFFFFFFFF', '07F7FFFFFFFFFFFF', '07F3FFFFFFFFFFFF'):
            self.assertTrue(_rvc(e, '0FFA0', data))
        self.assertEqual(_sets(e, mock), [('oscillate', 'on'), ('oscillate', 'off'),
                                          ('display', 'on'), ('display', 'off')])

    def test_toggle_immediate_echo(self):
        e, _, clock = _make_entity(now=0.0)
        e.tick(0.0)
        _drain(e)
        clock['now'] = 0.1
        _rvc(e, '1FEF8', '07FFDFFFFFFFFFFF')
        e.tick(0.1)
        frames = {f['dgn']: f['data'] for f in _drain(e)}
        self.assertEqual((frames['1FEFA'][3] >> 4) & 0b11, 0b01)

    def test_ignores_instance_0(self):
        e, mock, _ = _make_entity()
        self.assertFalse(_rvc(e, '1FEF9', '000000FFFFFFFFFF'))
        self.assertEqual(_sets(e, mock), [])

    def test_claims_own_echo_only(self):
        e, mock, _ = _make_entity()
        self.assertTrue(_rvc(e, '1FFE2', '070000FFFFFFFFFF', source_id='58'))
        self.assertFalse(_rvc(e, '1FFE2', '000000FFFFFFFFFF', source_id='58'))
        self.assertTrue(_rvc(e, '1FEF9', '07F1FFFFFFFFFFFF', source_id='44'))
        self.assertFalse(_rvc(e, '1FFBD', '07FFFFFFFFFFFFFF'))

    def test_short_and_reserved_payloads(self):
        e, mock, _ = _make_entity()
        self.assertTrue(_rvc(e, '1FEF9', '07F1'))
        self.assertEqual(_sets(e, mock), [('mode', 'cool')])
        e, mock, _ = _make_entity()
        self.assertTrue(_rvc(e, '1FEF9', '07FFFFFFFF10FEFF'))
        self.assertTrue(_rvc(e, '1FEF8', '07'))
        self.assertTrue(_rvc(e, '0FFA0', '07'))
        self.assertEqual(_sets(e, mock), [])
        self.assertFalse(_rvc(e, '1FEF9', ''))  # no instance byte at all

    def test_non_string_data_ignored(self):
        """DATA_PACKET (0EBFF) decodes with its own 'data' field as an int
        (seen on the bench); it must be declined, not raise."""
        e, mock, _ = _make_entity()
        msg = {'arbitration_id': '0x18ebff9c', 'data': 9132979057684563, 'dgn': '0EBFF',
               'source_id': '9C', 'name': 'DATA_PACKET', 'packet_number': 1}
        self.assertFalse(e.process_rvc_msg(msg))
        self.assertFalse(e.process_rvc_msg({'dgn': '1FEF9', 'source_id': '9F'}))  # no data at all
        self.assertEqual(_sets(e, mock), [])

    def test_all_no_change_publishes_nothing(self):
        e, mock, _ = _make_entity()
        e._dirty = False
        for dgn in ('1FEF9', '1FEF8', '0FFA0'):
            self.assertTrue(_rvc(e, dgn, '07FFFFFFFFFFFFFF'))
        self.assertEqual(_sets(e, mock), [])
        self.assertFalse(e._dirty)
        for field in COMMAND_FIELDS:
            self.assertFalse(e.state.is_pending(field))

    def test_unconfirmed_command_reverts(self):
        e, _, clock = _make_entity(now=0.0)
        _rvc(e, '1FEF8', '07FFDFFFFFFFFFFF')
        self.assertEqual(bytes.fromhex(_frames(e)['1FEFA'])[3], 0xD0)
        clock['now'] = 36
        e.tick(36)
        frames = {f['dgn']: f['data'] for f in _drain(e)}
        self.assertEqual(frames['1FEFA'][3], 0xC0)


if __name__ == "__main__":
    unittest.main()
