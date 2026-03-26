"""
Unit tests for the dimmer entity class

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
from rvc2mqtt.entity.dimmer_switch import DimmerSwitch_DC_DIMMER_STATUS_3 as Dimmer


def _make_mock():
    mock = MagicMock()
    mock.make_device_topic_string.return_value = 'test/topic'
    mock.TOPIC_BASE = 'rvc2mqtt'
    mock.client_id = 'bridge'
    mock.get_bridge_ha_name.return_value = 'bridge'
    mock.bridge_state_topic = 'rvc2mqtt/bridge/state'
    mock.make_ha_auto_discovery_config_topic.return_value = 'homeassistant/light/test/config'
    return mock


class Test_Dimmer(unittest.TestCase):

    def test_basic(self):
        mock = MagicMock()
        mock.mqtt_support.make_device_topic_string.return_value = 'topic_string'

        l = Dimmer({'instance': 1, 'instance_name': "test light"}, mock)
        self.assertTrue(type(l), Dimmer)

    def test_publish_ha_discovery_config(self):
        mock = _make_mock()
        entity = Dimmer({'instance': 1, 'instance_name': "test dimmer"}, mock)
        entity.publish_ha_discovery_config()
        self.assertTrue(mock.client.publish.called)
        for call in mock.client.publish.call_args_list:
            _, kwargs = call
            self.assertFalse(kwargs.get('retain', False),
                             f"Discovery config published with retain=True: {call}")

    def _make_dimmer(self, dimmable=True):
        mock = _make_mock()
        return Dimmer(
            {'instance': 1, 'instance_name': "test dimmer",
             'status_topic': 'rvc/state/dimmer', 'command_topic': 'rvc/set/dimmer',
             'dimmable': dimmable},
            mock
        )

    def _make_status_msg(self, brightness):
        return {
            'name': 'DC_DIMMER_STATUS_3',
            'instance': 1,
            'messagestate': 'on',
            'operating_status_brightness': brightness,
        }

    def test_brightness_published_on_status_msg(self):
        d = self._make_dimmer()
        d.process_rvc_msg(self._make_status_msg(brightness=50.0))
        publish_calls = {c[0][0]: c[0][1]
                         for c in d.mqtt_support.client.publish.call_args_list}
        self.assertEqual(publish_calls.get('rvc/state/dimmer/brightness'), 50)

    def test_dimmable_false_uses_switch_ha_component(self):
        mock = _make_mock()
        mock.make_ha_auto_discovery_config_topic.return_value = 'homeassistant/switch/test/config'
        d = Dimmer({'instance': 1, 'instance_name': "relay",
                    'status_topic': 'rvc/state/relay', 'command_topic': 'rvc/set/relay',
                    'dimmable': False}, mock)
        d.publish_ha_discovery_config()
        mock.make_ha_auto_discovery_config_topic.assert_called_with(
            d.unique_device_id, 'switch')

    def test_rvc_set_brightness_frame_encoding(self):
        import queue as qmod
        d = self._make_dimmer()
        q = qmod.Queue()
        d.set_rvc_send_queue(q)
        d._rvc_set_brightness(50)
        self.assertFalse(q.empty())
        msg = q.get_nowait()
        self.assertEqual(msg['dgn'], '1FEDB')
        data = msg['data']
        self.assertEqual(data[0], 1)     # instance
        self.assertEqual(data[1], 0xFF)  # group all
        self.assertEqual(data[2], 100)   # 50% × 2 = 100 wire format
        self.assertEqual(data[3], 0)     # command = set brightness

    def test_brightness_command_valid_payload(self):
        import queue as qmod
        d = self._make_dimmer()
        q = qmod.Queue()
        d.set_rvc_send_queue(q)
        d.process_mqtt_msg('rvc/set/dimmer/brightness', '75')
        self.assertFalse(q.empty())
        msg = q.get_nowait()
        self.assertEqual(msg['data'][2], 150)  # 75% × 2

    def test_brightness_command_clamped_above_100(self):
        import queue as qmod
        d = self._make_dimmer()
        q = qmod.Queue()
        d.set_rvc_send_queue(q)
        d.process_mqtt_msg('rvc/set/dimmer/brightness', '150')
        msg = q.get_nowait()
        self.assertEqual(msg['data'][2], 200)  # clamped to 100% × 2

    def test_brightness_command_clamped_below_0(self):
        import queue as qmod
        d = self._make_dimmer()
        d.brightness = 50  # set away from 0 so the clamped value triggers a send
        q = qmod.Queue()
        d.set_rvc_send_queue(q)
        d.process_mqtt_msg('rvc/set/dimmer/brightness', '-10')
        msg = q.get_nowait()
        self.assertEqual(msg['data'][2], 0)  # clamped to 0

    def test_brightness_command_invalid_payload_does_not_crash(self):
        d = self._make_dimmer()
        try:
            d.process_mqtt_msg('rvc/set/dimmer/brightness', 'not_a_number')
        except (ValueError, TypeError) as e:
            self.fail(f"process_mqtt_msg raised {type(e).__name__} on invalid brightness: {e}")

    def test_brightness_na_does_not_crash(self):
        """operating_status_brightness of 'n/a' (raw byte 0xFF) must not raise."""
        d = self._make_dimmer()
        try:
            d.process_rvc_msg(self._make_status_msg(brightness='n/a'))
        except (ValueError, TypeError) as e:
            self.fail(f"process_rvc_msg raised {type(e).__name__} on n/a brightness: {e}")


if __name__ == '__main__':
    unittest.main()
