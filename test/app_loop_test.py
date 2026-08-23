"""
Tests for the app main-loop helpers: entity tick dispatch and
instance-collision warnings.
"""
import os
import threading
import unittest
from unittest.mock import MagicMock
import context  # add rvc2mqtt package to the python path using local reference
import rvc2mqtt
from rvc2mqtt.app import app as AppClass
from rvc2mqtt.entity import EntityPluginBaseClass
from rvc2mqtt.entity_factory_support import entity_factory
from rvc2mqtt.plugin_support import PluginSupport


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

    def test_entity_tick_exception_does_not_stop_loop(self):
        a = _make_app()
        e1, e2 = MagicMock(), MagicMock()
        e1.id = "broken-entity"
        e1.tick.side_effect = RuntimeError("boom")
        a.entity_list = [e1, e2]
        a._loop_once(1.0)
        e2.tick.assert_called_once_with(1.0)
        a.message_tx_loop.assert_called_once()
        self.assertEqual(a.Logger.exception.call_count, 1)
        self.assertIn("broken-entity", a.Logger.exception.call_args[0][0])

    def test_entity_tick_exception_logged_once_across_iterations(self):
        a = _make_app()
        e1 = MagicMock()
        e1.id = "broken-entity"
        e1.tick.side_effect = RuntimeError("boom")
        a.entity_list = [e1]
        a._loop_once(1.0)
        a._loop_once(2.0)
        self.assertEqual(a.Logger.exception.call_count, 1)


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


def _mock_support():
    mock = MagicMock()
    mock.make_device_topic_string.return_value = 'test/topic'
    mock.TOPIC_BASE = 'rvc2mqtt'
    mock.client_id = 'bridge'
    mock.get_bridge_ha_name.return_value = 'bridge'
    mock.bridge_state_topic = 'rvc2mqtt/bridge/state'
    return mock


class Test_InstanceCollision(unittest.TestCase):

    def _virtual(self, instance):
        from rvc2mqtt.entity.virtual_inverter import VirtualInverter
        return VirtualInverter({'instance': instance, 'instance_name': 'v'}, _mock_support())

    def _real(self, instance):
        from rvc2mqtt.entity.inverter import InverterCharger_INVERTER_STATUS
        return InverterCharger_INVERTER_STATUS(
            {'instance': instance, 'instance_name': 'r',
             'status_topic': 'rvc/state/inverter', 'command_topic': 'rvc/set/inverter'},
            _mock_support())

    def test_same_instance_logs_error(self):
        a = _make_app()
        a.entity_list = [self._real(1), self._virtual(1)]
        a._warn_instance_collisions()
        a.Logger.error.assert_called_once()
        self.assertIn("instance 1", a.Logger.error.call_args[0][0])

    def test_different_instances_silent(self):
        a = _make_app()
        a.entity_list = [self._real(1), self._virtual(2)]
        a._warn_instance_collisions()
        a.Logger.error.assert_not_called()

    def test_virtual_alone_silent(self):
        a = _make_app()
        a.entity_list = [self._virtual(1)]
        a._warn_instance_collisions()
        a.Logger.error.assert_not_called()

    def test_production_plugin_loaded_classes_still_detected(self):
        """PluginSupport loads entity modules via spec_from_file_location under
        bare module names, so classes it produces are NOT the same objects as
        rvc2mqtt.entity.virtual_inverter.VirtualInverter /
        rvc2mqtt.entity.inverter.InverterCharger_INVERTER_STATUS imported
        directly. isinstance() against those imports is therefore always False
        in production; the guard must match on FACTORY_MATCH_ATTRIBUTES instead."""
        pkg_dir = os.path.dirname(rvc2mqtt.__file__)
        factory_list = []
        PluginSupport(os.path.join(pkg_dir, "entity"), []).register_with_factory_the_entity_plugins(factory_list)
        mock = _mock_support()
        real = entity_factory(
            {'name': 'INVERTER_STATUS', 'type': 'inverter', 'instance': 1,
             'instance_name': 'r', 'status_topic': 'rvc/state/inverter',
             'command_topic': 'rvc/set/inverter'},
            mock, factory_list)
        virtual = entity_factory(
            {'name': 'VIRTUAL_INVERTER', 'type': 'virtual_inverter', 'instance': 1,
             'instance_name': 'v'},
            mock, factory_list)
        self.assertIsNotNone(real)
        self.assertIsNotNone(virtual)

        a = _make_app()
        a.entity_list = [real, virtual]
        a._warn_instance_collisions()
        a.Logger.error.assert_called_once()
        self.assertIn("instance 1", a.Logger.error.call_args[0][0])


if __name__ == "__main__":
    unittest.main()


class Test_ReloadClearsTickFailures(unittest.TestCase):

    def test_do_reload_resets_tick_failure_suppression(self):
        """Entities are rebuilt on reload, so a previously failing entity id
        must be logged again if its fresh instance also fails."""
        a = AppClass.__new__(AppClass)
        a.Logger = MagicMock()
        a._reload_requested = threading.Event()
        a._floorplan_path1 = None
        a._floorplan_path2 = None
        a._entity_factory_list = []
        a.tx_RVC_Buffer = MagicMock()
        a.mqtt_client = None
        a.entity_list = []
        a._tick_failed_ids = {"broken-entity"}
        a._do_reload()
        self.assertEqual(a._tick_failed_ids, set())
