"""
Tests for the app main-loop helpers: entity tick dispatch and
instance-collision warnings.
"""
import threading
import unittest
from unittest.mock import MagicMock
import context  # add rvc2mqtt package to the python path using local reference
from rvc2mqtt.app import app as AppClass
from rvc2mqtt.entity import EntityPluginBaseClass


def _make_app():
    a = AppClass.__new__(AppClass)
    a.Logger = MagicMock()
    a._reload_requested = threading.Event()
    a.message_rx_loop = MagicMock()
    a.message_tx_loop = MagicMock()
    a._do_reload = MagicMock()
    a.entity_list = []
    return a


class Test_LoopOnce(unittest.TestCase):

    def test_ticks_every_entity_with_now(self):
        a = _make_app()
        e1, e2 = MagicMock(), MagicMock()
        a.entity_list = [e1, e2]
        a._loop_once(123.5)
        e1.tick.assert_called_once_with(123.5)
        e2.tick.assert_called_once_with(123.5)

    def test_rx_then_tick_then_tx_order(self):
        a = _make_app()
        order = []
        a.message_rx_loop.side_effect = lambda: order.append("rx")
        a.message_tx_loop.side_effect = lambda: order.append("tx")
        e = MagicMock()
        e.tick.side_effect = lambda now: order.append("tick")
        a.entity_list = [e]
        a._loop_once(1.0)
        self.assertEqual(order, ["rx", "tick", "tx"])

    def test_reload_runs_when_requested(self):
        a = _make_app()
        a._reload_requested.set()
        a._loop_once(1.0)
        a._do_reload.assert_called_once()

    def test_reload_not_run_when_not_requested(self):
        a = _make_app()
        a._loop_once(1.0)
        a._do_reload.assert_not_called()


class Test_BaseTick(unittest.TestCase):

    def test_base_tick_is_noop(self):
        class Dummy(EntityPluginBaseClass):
            def __init__(self):
                self.id = "dummy"
                mock = MagicMock()
                mock.make_device_topic_string.return_value = "t"
                mock.TOPIC_BASE = "rvc2mqtt"
                mock.client_id = "bridge"
                super().__init__({}, mock)
        Dummy().tick(0.0)  # must not raise


if __name__ == "__main__":
    unittest.main()
