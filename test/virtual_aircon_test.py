"""
Unit tests for the virtual air conditioner entity.
"""
import logging
import unittest
import context  # add rvc2mqtt package to the python path using local reference
from rvc2mqtt.entity.virtual_aircon import OptimisticState


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


if __name__ == "__main__":
    unittest.main()
