"""
Unit tests for the waterheater entity class

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

import unittest
from unittest.mock import MagicMock
import context  # add rvc2mqtt package to the python path using local reference
from rvc2mqtt.entity.water_heater import WaterHeaterClass


def _make_mock():
    mock = MagicMock()
    mock.make_device_topic_string.return_value = 'test/topic'
    mock.TOPIC_BASE = 'rvc2mqtt'
    mock.client_id = 'bridge'
    mock.get_bridge_ha_name.return_value = 'bridge'
    mock.bridge_state_topic = 'rvc2mqtt/bridge/state'
    mock.make_ha_auto_discovery_config_topic.return_value = 'homeassistant/switch/test/config'
    return mock


class Test_Waterheater(unittest.TestCase):

    def test_basic(self):
        mock = MagicMock()
        mock.mqtt_support.make_device_topic_string.return_value = 'topic_string'

        l = WaterHeaterClass({'instance': 1, 'instance_name': "test water heater"}, mock)
        self.assertTrue(type(l), WaterHeaterClass)

    def test_publish_ha_discovery_config(self):
        mock = _make_mock()
        entity = WaterHeaterClass({'instance': 1, 'instance_name': "test water heater"}, mock)
        entity.publish_ha_discovery_config()
        self.assertTrue(mock.client.publish.called)
        for call in mock.client.publish.call_args_list:
            _, kwargs = call
            self.assertFalse(kwargs.get('retain', False),
                             f"Discovery config published with retain=True: {call}")

    def test_rvc_change_mode_off(self):
        mock = _make_mock()
        entity = WaterHeaterClass({'instance': 1, 'instance_name': "test water heater"}, mock)
        entity.send_queue = MagicMock()
        entity._rvc_change_mode(gas_on=False, ac_on=False)
        self.assertTrue(entity.send_queue.put.called)
        msg = entity.send_queue.put.call_args[0][0]
        self.assertEqual(msg['dgn'], '1FFF6')
        self.assertEqual(msg['data'][1], 0)  # mode=0 (off)

    def test_rvc_change_mode_gas_only(self):
        mock = _make_mock()
        entity = WaterHeaterClass({'instance': 1, 'instance_name': "test water heater"}, mock)
        entity.send_queue = MagicMock()
        entity._rvc_change_mode(gas_on=True, ac_on=False)
        msg = entity.send_queue.put.call_args[0][0]
        self.assertEqual(msg['data'][1], 1)  # mode=1 (gas only)

    def test_rvc_change_mode_ac_only(self):
        mock = _make_mock()
        entity = WaterHeaterClass({'instance': 1, 'instance_name': "test water heater"}, mock)
        entity.send_queue = MagicMock()
        entity._rvc_change_mode(gas_on=False, ac_on=True)
        msg = entity.send_queue.put.call_args[0][0]
        self.assertEqual(msg['data'][1], 2)  # mode=2 (ac only)

    def test_rvc_change_mode_both(self):
        mock = _make_mock()
        entity = WaterHeaterClass({'instance': 1, 'instance_name': "test water heater"}, mock)
        entity.send_queue = MagicMock()
        entity._rvc_change_mode(gas_on=True, ac_on=True)
        msg = entity.send_queue.put.call_args[0][0]
        self.assertEqual(msg['data'][1], 3)  # mode=3 (gas+ac)

    def test_rvc_change_mode_padding_bytes(self):
        """Verify struct packing produces correct 8-byte payload with 0xFF padding."""
        import struct
        mock = _make_mock()
        entity = WaterHeaterClass({'instance': 1, 'instance_name': "test water heater"}, mock)
        entity.send_queue = MagicMock()
        entity._rvc_change_mode(gas_on=False, ac_on=False)
        msg = entity.send_queue.put.call_args[0][0]
        data = msg['data']
        self.assertEqual(len(data), 8)
        self.assertEqual(data[0], 1)     # instance
        self.assertEqual(data[1], 0)     # mode=0
        self.assertEqual(data[2], 0xFF)  # H field low byte
        self.assertEqual(data[3], 0xFF)  # H field high byte
        self.assertEqual(data[4], 0xFF)  # padding
        self.assertEqual(data[5], 0xFF)  # padding
        self.assertEqual(data[6], 0xFF)  # padding
        self.assertEqual(data[7], 0xFF)  # padding


if __name__ == '__main__':
    unittest.main()
