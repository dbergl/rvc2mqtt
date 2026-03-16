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
            '33_trigger': 300, '66_trigger': 200, '100_trigger': 100
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

    def test_process_rvc_msg_custom_triggers(self):
        mock = _make_mock()
        data = {
            'instance': 1, 'instance_name': "test G12 Tank Level",
            '33_trigger': 300, '66_trigger': 200, '100_trigger': 100,
            'status_topic': 'rvc/tank/fresh'
        }
        entity = G12TankLevel(data, mock)
        # level below 100_trigger → 100%
        msg = {'name': 'G12_TANK_LEVEL_SENSOR', 'instance': 1, 'tank_level': 50}
        entity.process_rvc_msg(msg)
        self.assertEqual(entity.tank_percent, 100)
        # level between 66 and 100 triggers → 66%
        msg['tank_level'] = 150
        entity.process_rvc_msg(msg)
        self.assertEqual(entity.tank_percent, 66)
        # level between 33 and 66 triggers → 33%
        msg['tank_level'] = 250
        entity.process_rvc_msg(msg)
        self.assertEqual(entity.tank_percent, 33)
        # level above 33_trigger → 1%
        msg['tank_level'] = 400
        entity.process_rvc_msg(msg)
        self.assertEqual(entity.tank_percent, 1)


if __name__ == '__main__':
    unittest.main()
