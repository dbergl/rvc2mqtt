"""
Tests for SIGHUP-triggered floorplan reload functionality.

Copyright 2022 Sean Brogan
SPDX-License-Identifier: Apache-2.0
"""
import threading
from unittest.mock import MagicMock, patch, call
import pytest
import context  # add rvc2mqtt package to the python path using local reference

from rvc2mqtt.mqtt import _RetainTracker, MQTT_Support


# ---------------------------------------------------------------------------
# _RetainTracker tests
# ---------------------------------------------------------------------------

class TestRetainTracker:
    def _make_tracker(self, ha_prefix=None):
        real = MagicMock()
        real.publish = MagicMock(return_value=MagicMock())
        return _RetainTracker(real, ha_prefix), real

    def test_tracks_retained_publish(self):
        tracker, real = self._make_tracker()
        tracker.publish("topic/a", "val", retain=True)
        assert "topic/a" in tracker._retained_topics

    def test_does_not_track_non_retained_publish(self):
        tracker, real = self._make_tracker()
        tracker.publish("topic/b", "val", retain=False)
        assert "topic/b" not in tracker._retained_topics

    def test_empty_payload_removes_from_tracked(self):
        tracker, real = self._make_tracker()
        tracker.publish("topic/a", "val", retain=True)
        tracker.publish("topic/a", "", retain=True)
        assert "topic/a" not in tracker._retained_topics

    def test_none_payload_removes_from_tracked(self):
        tracker, real = self._make_tracker()
        tracker.publish("topic/a", "val", retain=True)
        tracker.publish("topic/a", None, retain=True)
        assert "topic/a" not in tracker._retained_topics

    def test_zero_int_payload_is_tracked(self):
        """Numeric 0 is a real value and must be tracked, not treated as clearing."""
        tracker, real = self._make_tracker()
        tracker.publish("topic/a", 0, retain=True)
        assert "topic/a" in tracker._retained_topics

    def test_zero_float_payload_is_tracked(self):
        tracker, real = self._make_tracker()
        tracker.publish("topic/a", 0.0, retain=True)
        assert "topic/a" in tracker._retained_topics

    def test_delegates_publish_to_real_client(self):
        tracker, real = self._make_tracker()
        tracker.publish("topic/a", "val", qos=1, retain=True)
        real.publish.assert_called_once_with("topic/a", "val", 1, True, None)

    def test_getattr_delegates_to_real_client(self):
        tracker, real = self._make_tracker()
        real.loop_start = MagicMock()
        tracker.loop_start()
        real.loop_start.assert_called_once()

    def test_multiple_topics_tracked_independently(self):
        tracker, real = self._make_tracker()
        tracker.publish("topic/a", "v1", retain=True)
        tracker.publish("topic/b", "v2", retain=True)
        assert tracker._retained_topics == {"topic/a", "topic/b"}

    def test_removing_one_topic_leaves_others(self):
        tracker, real = self._make_tracker()
        tracker.publish("topic/a", "val", retain=True)
        tracker.publish("topic/b", "val", retain=True)
        tracker.publish("topic/a", "", retain=True)
        assert "topic/a" not in tracker._retained_topics
        assert "topic/b" in tracker._retained_topics

    def test_tracks_ha_discovery_topic_when_prefix_set(self):
        tracker, real = self._make_tracker(ha_prefix="homeassistant")
        tracker.publish("homeassistant/sensor/mydev/config", '{"name":"x"}', retain=False)
        assert "homeassistant/sensor/mydev/config" in tracker._discovery_topics

    def test_does_not_track_ha_discovery_without_prefix(self):
        tracker, real = self._make_tracker(ha_prefix=None)
        tracker.publish("homeassistant/sensor/mydev/config", '{"name":"x"}', retain=False)
        assert "homeassistant/sensor/mydev/config" not in tracker._discovery_topics

    def test_does_not_track_non_ha_topic_in_discovery(self):
        tracker, real = self._make_tracker(ha_prefix="homeassistant")
        tracker.publish("rvc2mqtt/bridge/d/mydev/state", "val", retain=False)
        assert "rvc2mqtt/bridge/d/mydev/state" not in tracker._discovery_topics

    def test_empty_payload_removes_from_discovery(self):
        tracker, real = self._make_tracker(ha_prefix="homeassistant")
        tracker.publish("homeassistant/sensor/mydev/config", '{"name":"x"}', retain=False)
        tracker.publish("homeassistant/sensor/mydev/config", "", retain=False)
        assert "homeassistant/sensor/mydev/config" not in tracker._discovery_topics

    def test_discovery_topic_not_added_to_retained(self):
        """HA discovery topics (retain=False) must not bleed into _retained_topics."""
        tracker, real = self._make_tracker(ha_prefix="homeassistant")
        tracker.publish("homeassistant/sensor/mydev/config", '{"name":"x"}', retain=False)
        assert "homeassistant/sensor/mydev/config" not in tracker._retained_topics


# ---------------------------------------------------------------------------
# MQTT_Support.clear_all_retained / unregister_all tests
# ---------------------------------------------------------------------------

class TestMQTTSupportReloadHelpers:
    def _make_support(self):
        support = MQTT_Support("bridge", "rvc2mqtt")
        real_client = MagicMock()
        real_client.publish = MagicMock(return_value=MagicMock())
        real_client.unsubscribe = MagicMock()
        support.set_client(real_client)
        return support, real_client

    def test_set_client_wraps_in_retain_tracker(self):
        support, _ = self._make_support()
        assert isinstance(support.client, _RetainTracker)

    def test_set_client_passes_ha_prefix_to_tracker(self):
        support, _ = self._make_support()
        assert support.client._ha_discovery_prefix == "homeassistant"

    def test_clear_all_retained_publishes_empty_to_all_topics(self):
        support, real_client = self._make_support()
        support.client._retained_topics = {"t/a", "t/b"}
        support.clear_all_retained()
        empty_calls = [c for c in real_client.publish.call_args_list if c[0][1] == ""]
        cleared = {c[0][0] for c in empty_calls}
        assert {"t/a", "t/b"}.issubset(cleared)

    def test_clear_all_retained_clears_tracked_topics(self):
        support, real_client = self._make_support()
        support.client._retained_topics = {"t/a", "t/b"}
        support.clear_all_retained()
        assert support.client._retained_topics == set()

    def test_clear_all_retained_does_not_clear_discovery_topics(self):
        """Discovery topics are NOT cleared by clear_all_retained; use
        clear_stale_discovery_topics() after re-initializing entities instead."""
        support, real_client = self._make_support()
        support.client._discovery_topics = {"homeassistant/sensor/mydev/config"}
        support.clear_all_retained()
        empty_calls = [c for c in real_client.publish.call_args_list if c[0][1] == ""]
        cleared = {c[0][0] for c in empty_calls}
        assert "homeassistant/sensor/mydev/config" not in cleared
        assert support.client._discovery_topics == {"homeassistant/sensor/mydev/config"}

    def test_clear_stale_discovery_topics_removes_only_missing(self):
        support, real_client = self._make_support()
        support.client._discovery_topics = {"ha/new/config"}
        old = {"ha/old/config", "ha/new/config"}
        support.clear_stale_discovery_topics(old)
        empty_calls = [c for c in real_client.publish.call_args_list if c[0][1] == ""]
        cleared = {c[0][0] for c in empty_calls}
        assert "ha/old/config" in cleared
        assert "ha/new/config" not in cleared

    def test_clear_stale_discovery_topics_noop_when_all_republished(self):
        support, real_client = self._make_support()
        support.client._discovery_topics = {"ha/dev/config"}
        support.clear_stale_discovery_topics({"ha/dev/config"})
        real_client.publish.assert_not_called()

    def test_clear_all_retained_noop_when_empty(self):
        support, real_client = self._make_support()
        support.clear_all_retained()  # nothing tracked — should not crash
        real_client.publish.assert_not_called()

    def test_unregister_all_clears_registry(self):
        support, real_client = self._make_support()
        support._connected = True
        support.register("cmd/a", lambda *a: None)
        support.register("cmd/b", lambda *a: None)
        support.unregister_all()
        assert support.registered_mqtt_devices == {}

    def test_unregister_all_calls_unsubscribe_when_connected(self):
        support, real_client = self._make_support()
        support._connected = True
        support.register("cmd/a", lambda *a: None)
        support.unregister_all()
        real_client.unsubscribe.assert_called_once()
        args = real_client.unsubscribe.call_args[0][0]
        assert "cmd/a" in args

    def test_unregister_all_no_unsubscribe_when_disconnected(self):
        support, real_client = self._make_support()
        support._connected = False
        support.register("cmd/a", lambda *a: None)
        support.unregister_all()
        real_client.unsubscribe.assert_not_called()
        assert support.registered_mqtt_devices == {}

    def test_unregister_all_empty_registry_noop(self):
        support, real_client = self._make_support()
        support._connected = True
        support.unregister_all()  # nothing registered — should not crash
        real_client.unsubscribe.assert_not_called()
        assert support.registered_mqtt_devices == {}


# ---------------------------------------------------------------------------
# app._do_reload integration tests
# ---------------------------------------------------------------------------

class TestAppDoReload:
    def _make_app(self, tmp_path=None):
        """Create an app instance wired with mocks."""
        from rvc2mqtt.app import app as AppClass

        a = AppClass.__new__(AppClass)
        a.Logger = MagicMock()
        a._reload_requested = threading.Event()
        a._reload_requested.set()
        a._floorplan_path1 = None
        a._floorplan_path2 = None
        a._entity_factory_list = []
        a.tx_RVC_Buffer = MagicMock()

        mqtt = MagicMock(spec=MQTT_Support)
        mqtt.HA_AUTO_BASE = "homeassistant"
        a.mqtt_client = mqtt

        e1 = MagicMock()
        e2 = MagicMock()
        a.entity_list = [e1, e2]

        return a, mqtt, e1, e2

    def test_do_reload_tears_down_old_entities(self):
        a, mqtt, e1, e2 = self._make_app()
        a._do_reload()
        e1.teardown.assert_called_once()
        e2.teardown.assert_called_once()

    def test_do_reload_clears_entity_list(self):
        a, mqtt, e1, e2 = self._make_app()
        a._do_reload()
        assert a.entity_list == []

    def test_do_reload_calls_unregister_all(self):
        a, mqtt, e1, e2 = self._make_app()
        a._do_reload()
        mqtt.unregister_all.assert_called_once()

    def test_do_reload_does_not_clear_retained_state_topics(self):
        """Retained state topics must NOT be cleared during reload to avoid
        publishing empty payloads that race with the offline signal and cause
        HA pattern-validation errors on text/climate entities."""
        a, mqtt, e1, e2 = self._make_app()
        a._do_reload()
        mqtt.clear_all_retained.assert_not_called()

    def test_do_reload_publishes_offline_before_entity_teardown(self):
        """Bridge must go offline before entities are torn down."""
        call_order = []
        a, mqtt, e1, e2 = self._make_app()
        mqtt.publish_bridge_offline.side_effect = lambda: call_order.append("offline")
        e1.teardown.side_effect = lambda: call_order.append("teardown")
        a._do_reload()
        assert call_order.index("offline") < call_order.index("teardown")

    def test_do_reload_publishes_online_after_entities_initialize(self):
        """Bridge must come back online after entities are re-initialized."""
        call_order = []
        a, mqtt, e1, e2 = self._make_app()
        a.entity_list = []
        mock_entity = MagicMock()
        mock_entity.entity_links = []
        mock_entity.initialize.side_effect = lambda: call_order.append("initialize")
        mqtt.publish_bridge_online.side_effect = lambda: call_order.append("online")

        import tempfile, os
        fp = tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False)
        fp.write("floorplan:\n  - name: X\n    instance: 1\n    type: x\n")
        fp.flush()
        a._floorplan_path1 = fp.name
        try:
            with patch("rvc2mqtt.app.entity_factory", return_value=mock_entity):
                a._do_reload()
        finally:
            os.unlink(fp.name)

        assert "initialize" in call_order
        assert "online" in call_order
        assert call_order.index("initialize") < call_order.index("online")

    def test_do_reload_re_registers_ha_birth_handler(self):
        a, mqtt, e1, e2 = self._make_app()
        a._do_reload()
        mqtt.register.assert_called()
        register_topics = [c[0][0] for c in mqtt.register.call_args_list]
        assert any("status" in t for t in register_topics)

    def test_do_reload_ha_birth_registered_before_clear_retained(self):
        """HA birth handler must be re-registered before going offline so no
        birth message is missed during the reload window."""
        call_order = []
        a, mqtt, e1, e2 = self._make_app()
        mqtt.unregister_all.side_effect = lambda: call_order.append("unregister")
        mqtt.register.side_effect = lambda *a, **kw: call_order.append("register")
        mqtt.publish_bridge_offline.side_effect = lambda: call_order.append("offline")
        a._do_reload()
        assert call_order.index("register") < call_order.index("offline")

    def test_do_reload_clears_event_flag(self):
        a, mqtt, e1, e2 = self._make_app()
        a._do_reload()
        assert not a._reload_requested.is_set()

    def test_do_reload_with_no_mqtt_client(self):
        """Reload must complete cleanly when MQTT is disabled."""
        a, mqtt, e1, e2 = self._make_app()
        a.mqtt_client = None
        a._do_reload()
        assert a.entity_list == []
        e1.teardown.assert_called_once()
        e2.teardown.assert_called_once()

    def test_do_reload_loads_new_entities_from_floorplan(self, tmp_path):
        fp_file = tmp_path / "floorplan.yaml"
        fp_file.write_text(
            "floorplan:\n"
            "  - name: DC_LOAD_STATUS\n"
            "    instance: 1\n"
            "    type: light_switch\n"
            "    instance_name: Test Light\n"
        )

        a, mqtt, e1, e2 = self._make_app()
        a._floorplan_path1 = str(fp_file)
        a.entity_list = []

        mock_entity = MagicMock()
        mock_entity.entity_links = []

        with patch("rvc2mqtt.app.entity_factory", return_value=mock_entity) as mock_factory:
            a._do_reload()

        mock_factory.assert_called_once()
        mock_entity.initialize.assert_called_once()
        assert mock_entity in a.entity_list

    def test_do_reload_loads_both_floorplan_files(self, tmp_path):
        fp1 = tmp_path / "fp1.yaml"
        fp2 = tmp_path / "fp2.yaml"
        fp1.write_text("floorplan:\n  - name: A\n    instance: 1\n    type: x\n")
        fp2.write_text("floorplan:\n  - name: B\n    instance: 2\n    type: y\n")

        a, mqtt, e1, e2 = self._make_app()
        a._floorplan_path1 = str(fp1)
        a._floorplan_path2 = str(fp2)
        a.entity_list = []

        mock_entity = MagicMock()
        mock_entity.entity_links = []

        with patch("rvc2mqtt.app.entity_factory", return_value=mock_entity) as mock_factory:
            a._do_reload()

        assert mock_factory.call_count == 2

    def test_do_reload_skips_missing_floorplan_file(self):
        a, mqtt, e1, e2 = self._make_app()
        a._floorplan_path1 = "/nonexistent/path.yaml"
        a.entity_list = []

        with patch("rvc2mqtt.app.entity_factory") as mock_factory:
            a._do_reload()

        mock_factory.assert_not_called()
        assert a.entity_list == []

    def test_do_reload_handles_entity_factory_returns_none(self, tmp_path):
        fp_file = tmp_path / "floorplan.yaml"
        fp_file.write_text("floorplan:\n  - name: X\n    instance: 1\n    type: unknown\n")

        a, mqtt, e1, e2 = self._make_app()
        a._floorplan_path1 = str(fp_file)
        a.entity_list = []

        with patch("rvc2mqtt.app.entity_factory", return_value=None):
            a._do_reload()

        assert a.entity_list == []

    def test_do_reload_handles_entity_factory_exception(self, tmp_path):
        fp_file = tmp_path / "floorplan.yaml"
        fp_file.write_text("floorplan:\n  - name: X\n    instance: 1\n    type: bad\n")

        a, mqtt, e1, e2 = self._make_app()
        a._floorplan_path1 = str(fp_file)
        a.entity_list = []

        with patch("rvc2mqtt.app.entity_factory", side_effect=ValueError("bad entry")):
            a._do_reload()  # should not raise

        a.Logger.error.assert_called()
        assert a.entity_list == []

    def test_do_reload_handles_floorplan_parse_error(self, tmp_path):
        fp_file = tmp_path / "floorplan.yaml"
        fp_file.write_text(": invalid: yaml: {{\n")

        a, mqtt, e1, e2 = self._make_app()
        a._floorplan_path1 = str(fp_file)
        a.entity_list = []

        with patch("rvc2mqtt.app.entity_factory") as mock_factory:
            a._do_reload()  # should not raise

        # Either parse error logged or no entities created — either way no crash
        assert a.entity_list == []

    def test_do_reload_entity_factory_exception_does_not_stop_remaining(self, tmp_path):
        """A bad entity entry should be skipped; subsequent entries still load."""
        fp_file = tmp_path / "floorplan.yaml"
        fp_file.write_text(
            "floorplan:\n"
            "  - name: BAD\n    instance: 1\n    type: bad\n"
            "  - name: GOOD\n    instance: 2\n    type: good\n"
        )

        a, mqtt, e1, e2 = self._make_app()
        a._floorplan_path1 = str(fp_file)
        a.entity_list = []

        good_entity = MagicMock()
        good_entity.entity_links = []

        call_count = 0
        def factory_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                raise ValueError("bad entry")
            return good_entity

        with patch("rvc2mqtt.app.entity_factory", side_effect=factory_side_effect):
            a._do_reload()

        assert good_entity in a.entity_list
