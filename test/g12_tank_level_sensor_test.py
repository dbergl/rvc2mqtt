"""
Unit tests for the G12 Tank Level Sensor entity class

Copyright 2025 Dan Berglund
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

import unittest
import unittest.mock
from unittest.mock import MagicMock
import context  # add rvc2mqtt package to the python path using local reference
from rvc2mqtt.entity.g12_tank_level_sensor import TankLevelSensor_TANK_STATUS as G12TankLevel


def _make_mock():
    mock = MagicMock()
    mock.make_device_topic_string.return_value = 'test/topic'
    mock.TOPIC_BASE = 'rvc2mqtt'
    mock.client_id = 'bridge'
    mock.get_bridge_ha_name.return_value = 'bridge'
    mock.bridge_state_topic = 'rvc2mqtt/bridge/state'
    mock.make_ha_auto_discovery_config_topic.return_value = 'homeassistant/device/test/config'
    return mock


class Test_G12TankLevel(unittest.TestCase):

    def test_basic(self):
        mock = _make_mock()
        entity = G12TankLevel({'instance': 1, 'instance_name': "test G12 Tank Level"}, mock)
        self.assertTrue(type(entity), G12TankLevel)

    def test_publish_ha_discovery_config(self):
        mock = _make_mock()
        entity = G12TankLevel({'instance': 1, 'instance_name': "test G12 Tank Level"}, mock)
        entity.publish_ha_discovery_config()
        self.assertTrue(mock.client.publish.called)
        for call in mock.client.publish.call_args_list:
            _, kwargs = call
            self.assertFalse(kwargs.get('retain', False),
                             f"Discovery config published with retain=True: {call}")

    def test_publish_ha_discovery_config_with_custom_triggers(self):
        mock = _make_mock()
        data = {
            'instance': 1, 'instance_name': "test G12 Tank Level",
            '33_custom_threshold': 300, '66_custom_threshold': 200, '100_custom_threshold': 100
        }
        entity = G12TankLevel(data, mock)
        self.assertTrue(entity.custom_triggers)
        entity.publish_ha_discovery_config()
        self.assertTrue(mock.client.publish.called)
        for call in mock.client.publish.call_args_list:
            _, kwargs = call
            self.assertFalse(kwargs.get('retain', False),
                             f"Discovery config published with retain=True: {call}")

    def test_process_rvc_msg_level_change(self):
        mock = _make_mock()
        entity = G12TankLevel({'instance': 1, 'instance_name': "test G12 Tank Level"}, mock)
        msg = {'name': 'G12_TANK_LEVEL_SENSOR', 'instance': 1, 'tank_level': 500}
        result = entity.process_rvc_msg(msg)
        self.assertTrue(result)
        self.assertEqual(entity.tank_level, 500)

    def test_process_rvc_msg_no_match(self):
        mock = _make_mock()
        entity = G12TankLevel({'instance': 1, 'instance_name': "test G12 Tank Level"}, mock)
        msg = {'name': 'SOME_OTHER_MSG', 'instance': 1, 'tank_level': 500}
        result = entity.process_rvc_msg(msg)
        self.assertFalse(result)

    def test_custlvl_publishes_on_first_reading_even_at_zero_percent(self):
        """Regression: tank_percent initializes to None so first reading always publishes, even 0%."""
        mock = _make_mock()
        data = {
            'instance': 1, 'instance_name': "test G12 Tank Level",
            '33_custom_threshold': 100, '66_custom_threshold': 200, '100_custom_threshold': 300,
            'status_topic': 'rvc/tank/fresh'
        }
        entity = G12TankLevel(data, mock)
        self.assertIsNone(entity.tank_percent)
        msg = {'name': 'G12_TANK_LEVEL_SENSOR', 'instance': 1, 'tank_level': 50}  # below 33% threshold → 0%
        entity.process_rvc_msg(msg)
        self.assertEqual(entity.tank_percent, 0)
        custlvl_publishes = [c for c in mock.client.publish.call_args_list
                             if c[0][0] == 'rvc/tank/fresh/custlvl']
        self.assertEqual(len(custlvl_publishes), 1)
        self.assertEqual(custlvl_publishes[0][0][1], 0)

    def test_process_rvc_msg_custom_triggers(self):
        mock = _make_mock()
        data = {
            'instance': 1, 'instance_name': "test G12 Tank Level",
            '33_custom_threshold': 100, '66_custom_threshold': 200, '100_custom_threshold': 300,
            'status_topic': 'rvc/tank/fresh'
        }
        entity = G12TankLevel(data, mock)
        # level below 33_threshold → 0% (empty)
        msg = {'name': 'G12_TANK_LEVEL_SENSOR', 'instance': 1, 'tank_level': 50}
        entity.process_rvc_msg(msg)
        self.assertEqual(entity.tank_percent, 0)
        # level between 33 and 66 thresholds → 33%
        msg['tank_level'] = 150
        entity.process_rvc_msg(msg)
        self.assertEqual(entity.tank_percent, 33)
        # level between 66 and 100 thresholds → 66%
        msg['tank_level'] = 250
        entity.process_rvc_msg(msg)
        self.assertEqual(entity.tank_percent, 66)
        # level above 100_threshold → 100%
        msg['tank_level'] = 350
        entity.process_rvc_msg(msg)
        self.assertEqual(entity.tank_percent, 100)


    def test_process_rvc_msg_custom_triggers_descending(self):
        """Test custlvl with descending thresholds (lower raw value = more full, e.g. G12 resistive sensor)."""
        mock = _make_mock()
        data = {
            'instance': 1, 'instance_name': "test G12 Tank Level",
            '33_custom_threshold': 57400, '66_custom_threshold': 44400, '100_custom_threshold': 22000,
            'status_topic': 'rvc/tank/fresh'
        }
        entity = G12TankLevel(data, mock)
        self.assertTrue(entity.thresholds_descending)
        # level above 33_threshold → 0% (empty)
        msg = {'name': 'G12_TANK_LEVEL_SENSOR', 'instance': 1, 'tank_level': 60000}
        entity.process_rvc_msg(msg)
        self.assertEqual(entity.tank_percent, 0)
        # level at 33_threshold → 33%
        msg['tank_level'] = 57400
        entity.process_rvc_msg(msg)
        self.assertEqual(entity.tank_percent, 33)
        # level between 33 and 66 thresholds → 33%
        msg['tank_level'] = 50000
        entity.process_rvc_msg(msg)
        self.assertEqual(entity.tank_percent, 33)
        # level between 66 and 100 thresholds → 66%
        msg['tank_level'] = 40000
        entity.process_rvc_msg(msg)
        self.assertEqual(entity.tank_percent, 66)
        # level at 100_threshold → 100% (full)
        msg['tank_level'] = 22000
        entity.process_rvc_msg(msg)
        self.assertEqual(entity.tank_percent, 100)
        # level below 100_threshold → 100% (full)
        msg['tank_level'] = 10000
        entity.process_rvc_msg(msg)
        self.assertEqual(entity.tank_percent, 100)

    def test_initialize_publishes_threshold_values(self):
        mock = _make_mock()
        data = {
            'instance': 1, 'instance_name': "test G12 Tank Level",
            '33_custom_threshold': 57400, '66_custom_threshold': 44400, '100_custom_threshold': 22000,
            'status_topic': 'rvc/tank/fresh'
        }
        entity = G12TankLevel(data, mock)
        entity.send_queue = MagicMock()
        entity.initialize()
        published_topics = [call[0][0] for call in mock.client.publish.call_args_list]
        self.assertIn('rvc/tank/fresh/cust_threshold_33', published_topics)
        self.assertIn('rvc/tank/fresh/cust_threshold_66', published_topics)
        self.assertIn('rvc/tank/fresh/cust_threshold_100', published_topics)
        # values must be retained
        for call in mock.client.publish.call_args_list:
            topic = call[0][0]
            if 'threshold' in topic:
                self.assertTrue(call[1].get('retain', False) or (len(call[0]) > 2 and call[0][2]),
                                f"Threshold topic {topic} not published retained")

    def test_initialize_registers_set_topics_from_command_topic(self):
        mock = _make_mock()
        data = {
            'instance': 1, 'instance_name': "test G12 Tank Level",
            '33_custom_threshold': 57400, '66_custom_threshold': 44400, '100_custom_threshold': 22000,
            'status_topic': 'rvc/state/tanks/fresh',
            'command_topic': 'rvc/set/tanks/fresh',
        }
        entity = G12TankLevel(data, mock)
        entity.send_queue = MagicMock()
        entity.initialize()
        registered = [call[0][0] for call in mock.register.call_args_list]
        self.assertIn('rvc/set/tanks/fresh/cust_threshold_33', registered)
        self.assertIn('rvc/set/tanks/fresh/cust_threshold_66', registered)
        self.assertIn('rvc/set/tanks/fresh/cust_threshold_100', registered)

    def test_initialize_registers_set_topics_fallback_no_command_topic(self):
        mock = _make_mock()
        data = {
            'instance': 1, 'instance_name': "test G12 Tank Level",
            '33_custom_threshold': 57400, '66_custom_threshold': 44400, '100_custom_threshold': 22000,
            'status_topic': 'rvc/state/tanks/fresh',
        }
        entity = G12TankLevel(data, mock)
        entity.send_queue = MagicMock()
        entity.initialize()
        registered = [call[0][0] for call in mock.register.call_args_list]
        self.assertIn('rvc/state/tanks/fresh/cust_threshold_33', registered)
        self.assertIn('rvc/state/tanks/fresh/cust_threshold_66', registered)
        self.assertIn('rvc/state/tanks/fresh/cust_threshold_100', registered)

    def test_process_mqtt_msg_updates_cust_threshold_33(self):
        mock = _make_mock()
        data = {
            'instance': 1, 'instance_name': "test G12 Tank Level",
            '33_custom_threshold': 57400, '66_custom_threshold': 44400, '100_custom_threshold': 22000,
            'status_topic': 'rvc/state/tanks/fresh', 'command_topic': 'rvc/set/tanks/fresh',
        }
        entity = G12TankLevel(data, mock)
        entity.process_mqtt_msg('rvc/set/tanks/fresh/cust_threshold_33', '50000')
        self.assertEqual(entity.thirtythree, 50000)
        mock.client.publish.assert_called_with('rvc/state/tanks/fresh/cust_threshold_33', 50000, retain=True)

    def test_process_mqtt_msg_updates_cust_threshold_66(self):
        mock = _make_mock()
        data = {
            'instance': 1, 'instance_name': "test G12 Tank Level",
            '33_custom_threshold': 57400, '66_custom_threshold': 44400, '100_custom_threshold': 22000,
            'status_topic': 'rvc/state/tanks/fresh', 'command_topic': 'rvc/set/tanks/fresh',
        }
        entity = G12TankLevel(data, mock)
        entity.process_mqtt_msg('rvc/set/tanks/fresh/cust_threshold_66', '40000')
        self.assertEqual(entity.sixtysix, 40000)
        mock.client.publish.assert_called_with('rvc/state/tanks/fresh/cust_threshold_66', 40000, retain=True)

    def test_process_mqtt_msg_updates_cust_threshold_100(self):
        mock = _make_mock()
        data = {
            'instance': 1, 'instance_name': "test G12 Tank Level",
            '33_custom_threshold': 57400, '66_custom_threshold': 44400, '100_custom_threshold': 22000,
            'status_topic': 'rvc/state/tanks/fresh', 'command_topic': 'rvc/set/tanks/fresh',
        }
        entity = G12TankLevel(data, mock)
        entity.process_mqtt_msg('rvc/set/tanks/fresh/cust_threshold_100', '20000')
        self.assertEqual(entity.onehundred, 20000)
        mock.client.publish.assert_called_with('rvc/state/tanks/fresh/cust_threshold_100', 20000, retain=True)

    def test_process_mqtt_msg_persists_threshold_33(self):
        mock = _make_mock()
        data = {
            'instance': 1, 'instance_name': "test G12 Tank Level",
            '33_custom_threshold': 57400, '66_custom_threshold': 44400, '100_custom_threshold': 22000,
            'status_topic': 'rvc/state/tanks/fresh', 'command_topic': 'rvc/set/tanks/fresh',
        }
        entity = G12TankLevel(data, mock)
        with unittest.mock.patch.object(entity, '_persist_override') as mock_persist:
            entity.process_mqtt_msg('rvc/set/tanks/fresh/cust_threshold_33', '50000')
            mock_persist.assert_called_once_with({'33_custom_threshold': 50000})

    def test_process_mqtt_msg_persists_threshold_66(self):
        mock = _make_mock()
        data = {
            'instance': 1, 'instance_name': "test G12 Tank Level",
            '33_custom_threshold': 57400, '66_custom_threshold': 44400, '100_custom_threshold': 22000,
            'status_topic': 'rvc/state/tanks/fresh', 'command_topic': 'rvc/set/tanks/fresh',
        }
        entity = G12TankLevel(data, mock)
        with unittest.mock.patch.object(entity, '_persist_override') as mock_persist:
            entity.process_mqtt_msg('rvc/set/tanks/fresh/cust_threshold_66', '40000')
            mock_persist.assert_called_once_with({'66_custom_threshold': 40000})

    def test_process_mqtt_msg_persists_threshold_100(self):
        mock = _make_mock()
        data = {
            'instance': 1, 'instance_name': "test G12 Tank Level",
            '33_custom_threshold': 57400, '66_custom_threshold': 44400, '100_custom_threshold': 22000,
            'status_topic': 'rvc/state/tanks/fresh', 'command_topic': 'rvc/set/tanks/fresh',
        }
        entity = G12TankLevel(data, mock)
        with unittest.mock.patch.object(entity, '_persist_override') as mock_persist:
            entity.process_mqtt_msg('rvc/set/tanks/fresh/cust_threshold_100', '20000')
            mock_persist.assert_called_once_with({'100_custom_threshold': 20000})

    def test_process_mqtt_msg_invalid_payload_ignored(self):
        mock = _make_mock()
        data = {
            'instance': 1, 'instance_name': "test G12 Tank Level",
            '33_custom_threshold': 57400, '66_custom_threshold': 44400, '100_custom_threshold': 22000,
            'status_topic': 'rvc/state/tanks/fresh', 'command_topic': 'rvc/set/tanks/fresh',
        }
        entity = G12TankLevel(data, mock)
        entity.process_mqtt_msg('rvc/set/tanks/fresh/cust_threshold_33', 'notanumber')
        self.assertEqual(entity.thirtythree, 57400)  # unchanged

    def test_initialize_no_threshold_publish_without_custom_triggers(self):
        mock = _make_mock()
        data = {'instance': 1, 'instance_name': "test G12 Tank Level"}
        entity = G12TankLevel(data, mock)
        entity.send_queue = MagicMock()
        entity.initialize()
        published_topics = [call[0][0] for call in mock.client.publish.call_args_list]
        self.assertFalse(any('threshold' in t for t in published_topics))

    def test_initialize_sends_tank_status_dgn_request(self):
        mock = _make_mock()
        data = {'instance': 2, 'instance_name': "test G12 Tank Level"}
        entity = G12TankLevel(data, mock)
        entity.send_queue = MagicMock()
        entity.initialize()
        dgns = [call[0][0]['dgn'] for call in entity.send_queue.put.call_args_list]
        self.assertIn("0EAFF", dgns)
        # should have at least 2 requests (G12 DGN and TANK_STATUS DGN)
        self.assertGreaterEqual(len(dgns), 2)

    def test_process_rvc_msg_tank_status_match(self):
        mock = _make_mock()
        entity = G12TankLevel({'instance': 1, 'instance_name': "test G12 Tank Level",
                               'status_topic': 'rvc/tank/fresh'}, mock)
        msg = {'name': 'TANK_STATUS', 'instance': 1, 'relative_level': 2, 'resolution': 4}
        result = entity.process_rvc_msg(msg)
        self.assertTrue(result)
        self.assertEqual(entity.tank_status_level, 50)
        mock.client.publish.assert_called_with('rvc/tank/fresh/lvl', 50, retain=True)

    def test_process_rvc_msg_tank_status_no_publish_when_unchanged(self):
        mock = _make_mock()
        entity = G12TankLevel({'instance': 1, 'instance_name': "test G12 Tank Level",
                               'status_topic': 'rvc/tank/fresh'}, mock)
        msg = {'name': 'TANK_STATUS', 'instance': 1, 'relative_level': 2, 'resolution': 4}
        entity.process_rvc_msg(msg)
        publish_count = mock.client.publish.call_count
        entity.process_rvc_msg(msg)
        self.assertEqual(mock.client.publish.call_count, publish_count)

    def test_process_rvc_msg_tank_status_wrong_instance(self):
        mock = _make_mock()
        entity = G12TankLevel({'instance': 1, 'instance_name': "test G12 Tank Level"}, mock)
        msg = {'name': 'TANK_STATUS', 'instance': 2, 'relative_level': 2, 'resolution': 4}
        result = entity.process_rvc_msg(msg)
        self.assertFalse(result)

    def test_process_rvc_msg_tank_status_full(self):
        mock = _make_mock()
        entity = G12TankLevel({'instance': 0, 'instance_name': "test G12 Tank Level",
                               'status_topic': 'rvc/tank/fresh'}, mock)
        msg = {'name': 'TANK_STATUS', 'instance': 0, 'relative_level': 4, 'resolution': 4}
        entity.process_rvc_msg(msg)
        self.assertEqual(entity.tank_status_level, 100)

    def test_tank_status_level_topic_with_status_topic(self):
        mock = _make_mock()
        entity = G12TankLevel({'instance': 1, 'instance_name': "test",
                               'status_topic': 'rvc/tank/fresh'}, mock)
        self.assertEqual(entity.tank_status_level_topic, 'rvc/tank/fresh/lvl')

    def test_tank_status_level_topic_without_status_topic(self):
        mock = _make_mock()
        entity = G12TankLevel({'instance': 1, 'instance_name': "test"}, mock)
        # should use make_device_topic_string fallback
        self.assertTrue(mock.make_device_topic_string.called)

    def test_tank_status_resolution_frozen_after_first_message(self):
        """Resolution captured from first message is used for all subsequent calculations."""
        mock = _make_mock()
        entity = G12TankLevel({'instance': 1, 'instance_name': "test",
                               'status_topic': 'rvc/tank/fresh'}, mock)
        # First message: resolution=4, level=2 → 50%
        msg1 = {'name': 'TANK_STATUS', 'instance': 1, 'relative_level': 2, 'resolution': 4}
        entity.process_rvc_msg(msg1)
        self.assertEqual(entity.tank_status_level, 50)

        # Second message reports a different resolution — should be ignored
        msg2 = {'name': 'TANK_STATUS', 'instance': 1, 'relative_level': 4, 'resolution': 8}
        entity.process_rvc_msg(msg2)
        # Still using resolution=4: round(4*100/4) = 100
        self.assertEqual(entity.tank_status_level, 100)


if __name__ == '__main__':
    unittest.main()
