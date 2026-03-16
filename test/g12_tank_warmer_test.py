"""
Unit tests for the G12 Tank Warmer entity class

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
from rvc2mqtt.entity.g12_tank_warmer import TankHeater_DC_DIMMER_STATUS_3 as G12TankWarmer


def _make_mock():
    mock = MagicMock()
    mock.make_device_topic_string.return_value = 'test/topic'
    mock.TOPIC_BASE = 'rvc2mqtt'
    mock.client_id = 'bridge'
    mock.get_bridge_ha_name.return_value = 'bridge'
    mock.bridge_state_topic = 'rvc2mqtt/bridge/state'
    mock.make_ha_auto_discovery_config_topic.return_value = 'homeassistant/switch/test/config'
    return mock


class Test_G12TankWarmer(unittest.TestCase):

    def test_basic(self):
        mock = _make_mock()
        entity = G12TankWarmer({'instance': 1, 'instance_name': "test G12 Tank Warmer"}, mock)
        self.assertTrue(type(entity), G12TankWarmer)

    def test_publish_ha_discovery_config(self):
        mock = _make_mock()
        entity = G12TankWarmer({'instance': 1, 'instance_name': "test G12 Tank Warmer"}, mock)
        entity.publish_ha_discovery_config()
        self.assertTrue(mock.client.publish.called)
        for call in mock.client.publish.call_args_list:
            _, kwargs = call
            self.assertFalse(kwargs.get('retain', False),
                             f"Discovery config published with retain=True: {call}")

    def test_process_rvc_msg_on(self):
        mock = _make_mock()
        entity = G12TankWarmer({'instance': 1, 'instance_name': "test G12 Tank Warmer"}, mock)
        msg = {'name': 'DC_DIMMER_STATUS_3', 'instance': 1, 'operating_status_brightness': 100.0}
        result = entity.process_rvc_msg(msg)
        self.assertTrue(result)
        self.assertEqual(entity.state, G12TankWarmer.HEATER_ON)

    def test_process_rvc_msg_off(self):
        mock = _make_mock()
        entity = G12TankWarmer({'instance': 1, 'instance_name': "test G12 Tank Warmer"}, mock)
        msg = {'name': 'DC_DIMMER_STATUS_3', 'instance': 1, 'operating_status_brightness': 0.0}
        result = entity.process_rvc_msg(msg)
        self.assertTrue(result)
        self.assertEqual(entity.state, G12TankWarmer.HEATER_OFF)

    def test_process_rvc_msg_command_eaten(self):
        mock = _make_mock()
        entity = G12TankWarmer({'instance': 1, 'instance_name': "test G12 Tank Warmer"}, mock)
        msg = {'name': 'DC_DIMMER_COMMAND_2', 'instance': 1}
        result = entity.process_rvc_msg(msg)
        self.assertTrue(result)

    def test_process_rvc_msg_no_match(self):
        mock = _make_mock()
        entity = G12TankWarmer({'instance': 1, 'instance_name': "test G12 Tank Warmer"}, mock)
        msg = {'name': 'SOME_OTHER_MSG', 'instance': 1}
        result = entity.process_rvc_msg(msg)
        self.assertFalse(result)


if __name__ == '__main__':
    unittest.main()
