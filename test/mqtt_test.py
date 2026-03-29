"""
Unit tests for the mqtt support class

Copyright 2022 Sean Brogan
SPDX-License-Identifier: Apache-2.0

Licensed under the Apache License, Version 2.0 (the "License");
you may not use this file except in compliance with the License.
You may obtain a copy of the License at

http://www.apache.org/licenses/LICENSE-2.0

Unless required by applicable law or agreed to in writing, software
distributed under the License is distributed on an "AS IS" BASIS,
WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
See the License for the specific language governing permissions and
limitations under the License.

"""
import os
import unittest
from unittest.mock import MagicMock, patch, call
import context  # add rvc2mqtt package to the python path using local reference
from rvc2mqtt.mqtt import MQTT_Support, _RetainTracker


class Test_RetainTracker(unittest.TestCase):

    def _make_tracker(self):
        real = MagicMock()
        tracker = _RetainTracker(real, ha_discovery_prefix='homeassistant')
        return tracker, real

    def test_retained_publish_tracked(self):
        tracker, real = self._make_tracker()
        tracker.publish('rvc/state/light', 'on', retain=True)
        self.assertIn('rvc/state/light', tracker._retained_topics)

    def test_retained_publish_empty_payload_removes_from_tracked(self):
        tracker, real = self._make_tracker()
        tracker._retained_topics.add('rvc/state/light')
        tracker.publish('rvc/state/light', '', retain=True)
        self.assertNotIn('rvc/state/light', tracker._retained_topics)

    def test_non_retained_not_tracked(self):
        tracker, real = self._make_tracker()
        tracker.publish('rvc/state/light', 'on', retain=False)
        self.assertNotIn('rvc/state/light', tracker._retained_topics)

    def test_discovery_topic_tracked(self):
        tracker, real = self._make_tracker()
        tracker.publish('homeassistant/light/test/config', '{"name":"test"}', retain=False)
        self.assertIn('homeassistant/light/test/config', tracker._discovery_topics)

    def test_discovery_topic_empty_payload_removes(self):
        tracker, real = self._make_tracker()
        tracker._discovery_topics.add('homeassistant/light/test/config')
        tracker.publish('homeassistant/light/test/config', '', retain=False)
        self.assertNotIn('homeassistant/light/test/config', tracker._discovery_topics)

    def test_real_client_publish_called(self):
        tracker, real = self._make_tracker()
        tracker.publish('some/topic', 'value', qos=1, retain=True)
        real.publish.assert_called_once_with('some/topic', 'value', 1, True, None)

    def test_getattr_proxies_to_real_client(self):
        tracker, real = self._make_tracker()
        _ = tracker.subscribe  # should not raise
        real.subscribe  # ensure it's accessible


class Test_MQTT_Support(unittest.TestCase):

    def _make_support(self):
        """Return (support, mock_real_client).

        support.client is a _RetainTracker wrapping mock_real_client.
        All paho-level assertions (publish, subscribe, unsubscribe) must be
        made against mock_real_client, not support.client.
        """
        support = MQTT_Support('bridge', 'rvc2mqtt')
        mock_real_client = MagicMock()
        support.set_client(mock_real_client)
        return support, mock_real_client

    def test_topic_string_construction(self):
        support, _ = self._make_support()
        topic = support.make_device_topic_string('light-1', 'brightness', True)
        self.assertIn('state', topic)
        self.assertIn('brightness', topic)

    def test_topic_string_set(self):
        support, _ = self._make_support()
        topic = support.make_device_topic_string('light-1', 'brightness', False)
        self.assertIn('set', topic)

    def test_topic_string_no_field(self):
        support, _ = self._make_support()
        topic = support.make_device_topic_string('light-1', None, True)
        self.assertIn('state', topic)
        self.assertNotIn('None', topic)

    def test_ha_auto_discovery_topic(self):
        support, _ = self._make_support()
        topic = support.make_ha_auto_discovery_config_topic('mydev', 'light')
        self.assertTrue(topic.startswith('homeassistant/light/'))
        self.assertTrue(topic.endswith('/config'))

    def test_ha_auto_discovery_topic_with_subtype(self):
        support, _ = self._make_support()
        topic = support.make_ha_auto_discovery_config_topic('mydev', 'switch', 'power')
        self.assertIn('power', topic)

    def test_get_bridge_ha_name(self):
        support, _ = self._make_support()
        name = support.get_bridge_ha_name()
        self.assertIsInstance(name, str)
        self.assertGreater(len(name), 0)

    # --- register ---

    def test_register_stores_func_and_retain_ok(self):
        support, mock_client = self._make_support()
        func = MagicMock()
        support.register('some/topic', func, retain_ok=False)
        self.assertIn('some/topic', support.registered_mqtt_devices)
        stored_func, stored_retain_ok = support.registered_mqtt_devices['some/topic']
        self.assertEqual(stored_func, func)
        self.assertFalse(stored_retain_ok)

    def test_register_when_connected_clears_then_subscribes(self):
        support, mock_client = self._make_support()
        support._connected = True
        func = MagicMock()
        support.register('cmd/topic', func, retain_ok=False)
        # Should clear before subscribe (via _RetainTracker → mock_client)
        mock_client.publish.assert_called_with('cmd/topic', '', 0, True, None)
        mock_client.subscribe.assert_called()

    def test_register_retain_ok_does_not_clear(self):
        support, mock_client = self._make_support()
        support._connected = True
        func = MagicMock()
        support.register('state/topic', func, retain_ok=True)
        # Should NOT clear retained message for retain_ok topics
        for c in mock_client.publish.call_args_list:
            self.assertFalse(
                c[0][0] == 'state/topic' and c[0][1] == '' and c[0][3],
                "Should not clear retained message for retain_ok=True topic"
            )

    # --- on_connect ---

    def test_on_connect_success_publishes_online(self):
        support, mock_client = self._make_support()
        func = MagicMock()
        support.register('cmd/topic', func)
        support.on_connect(mock_client, None, None, 0, None)
        # _RetainTracker.publish → mock_client.publish(topic, payload, qos, retain, properties)
        mock_client.publish.assert_any_call(support.bridge_state_topic, 'online', 0, True, None)
        self.assertTrue(support._connected)

    def test_on_connect_clears_command_topics_before_subscribe(self):
        support, mock_client = self._make_support()
        func = MagicMock()
        support.register('cmd/topic', func, retain_ok=False)
        mock_client.publish.reset_mock()
        support.on_connect(mock_client, None, None, 0, None)
        # clearing call: publish('cmd/topic', '', 0, True, None)
        mock_client.publish.assert_any_call('cmd/topic', '', 0, True, None)

    def test_on_connect_does_not_clear_retain_ok_topics(self):
        support, mock_client = self._make_support()
        func = MagicMock()
        support.register('state/topic', func, retain_ok=True)
        mock_client.publish.reset_mock()
        support.on_connect(mock_client, None, None, 0, None)
        # state/topic clearing should NOT appear
        clearing_calls = [c for c in mock_client.publish.call_args_list
                          if c[0][0] == 'state/topic' and c[0][1] == '']
        self.assertEqual(len(clearing_calls), 0)

    def test_on_connect_subscribes_all_topics(self):
        support, mock_client = self._make_support()
        support.register('topic/a', MagicMock())
        support.register('topic/b', MagicMock())
        support.on_connect(mock_client, None, None, 0, None)
        mock_client.subscribe.assert_called()

    def test_on_connect_failure_logs_critical(self):
        support, mock_client = self._make_support()
        support.on_connect(mock_client, None, None, 1, None)
        self.assertFalse(support._connected)

    # --- on_message ---

    def test_on_message_dispatches_to_handler(self):
        support, mock_client = self._make_support()
        func = MagicMock()
        support.register('some/topic', func)
        msg = MagicMock()
        msg.topic = 'some/topic'
        msg.payload = b'hello'
        msg.retain = False
        msg.properties = None
        support.on_message(mock_client, None, msg)
        func.assert_called_once_with('some/topic', 'hello', None)

    def test_on_message_drops_retained_if_retain_ok_false(self):
        support, mock_client = self._make_support()
        func = MagicMock()
        support.register('cmd/topic', func, retain_ok=False)
        msg = MagicMock()
        msg.topic = 'cmd/topic'
        msg.payload = b'on'
        msg.retain = True
        msg.properties = None
        support.on_message(mock_client, None, msg)
        func.assert_not_called()

    def test_on_message_passes_retained_if_retain_ok_true(self):
        support, mock_client = self._make_support()
        func = MagicMock()
        support.register('state/topic', func, retain_ok=True)
        msg = MagicMock()
        msg.topic = 'state/topic'
        msg.payload = b'on'
        msg.retain = True
        msg.properties = None
        support.on_message(mock_client, None, msg)
        func.assert_called_once_with('state/topic', 'on', None)

    def test_on_message_unknown_topic_logs_warning(self):
        support, mock_client = self._make_support()
        msg = MagicMock()
        msg.topic = 'unknown/topic'
        msg.payload = b'data'
        msg.retain = False
        msg.qos = 0
        # should not crash
        support.on_message(mock_client, None, msg)

    # --- on_disconnect ---

    def test_on_disconnect_clears_connected_flag(self):
        support, mock_client = self._make_support()
        support._connected = True
        support.on_disconnect(mock_client, None, None, 0, None)
        self.assertFalse(support._connected)

    # --- clear_all_retained ---

    def test_clear_all_retained(self):
        support, mock_client = self._make_support()
        support.client._retained_topics = {'rvc/state/a', 'rvc/state/b'}
        support.clear_all_retained()
        # each topic should have been cleared via mock_client.publish
        cleared = {c[0][0] for c in mock_client.publish.call_args_list
                   if c[0][1] == '' and c[0][3]}  # args: (topic, payload, qos, retain, ...)
        self.assertIn('rvc/state/a', cleared)
        self.assertIn('rvc/state/b', cleared)
        self.assertEqual(len(support.client._retained_topics), 0)

    # --- clear_stale_discovery_topics ---

    def test_clear_stale_discovery_topics(self):
        support, mock_client = self._make_support()
        support.client._discovery_topics = {'ha/light/new/config'}
        old_topics = {'ha/light/old/config', 'ha/light/new/config'}
        support.clear_stale_discovery_topics(old_topics)
        cleared = {c[0][0] for c in mock_client.publish.call_args_list}
        self.assertIn('ha/light/old/config', cleared)
        self.assertNotIn('ha/light/new/config', cleared)

    # --- unregister_all ---

    def test_unregister_all_clears_registry(self):
        support, mock_client = self._make_support()
        support._connected = True
        support.register('topic/a', MagicMock())
        support.register('topic/b', MagicMock())
        support.unregister_all()
        self.assertEqual(len(support.registered_mqtt_devices), 0)
        mock_client.unsubscribe.assert_called()

    def test_unregister_all_not_connected_no_unsubscribe(self):
        support, mock_client = self._make_support()
        support._connected = False
        support.register('topic/a', MagicMock())
        support.unregister_all()
        self.assertEqual(len(support.registered_mqtt_devices), 0)
        mock_client.unsubscribe.assert_not_called()

    # --- shutdown ---

    def test_shutdown_publishes_offline(self):
        support, mock_client = self._make_support()
        support.shutdown()
        mock_client.publish.assert_any_call(support.bridge_state_topic, 'offline', 0, True, None)

    # --- get_discovery_topics ---

    def test_get_discovery_topics_returns_snapshot(self):
        support, mock_client = self._make_support()
        support.client._discovery_topics = {'ha/light/test/config'}
        topics = support.get_discovery_topics()
        self.assertEqual(topics, {'ha/light/test/config'})
        # modifying the snapshot doesn't affect the original
        topics.add('extra')
        self.assertNotIn('extra', support.client._discovery_topics)


if __name__ == '__main__':
    unittest.main()
