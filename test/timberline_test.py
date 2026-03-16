"""
Unit tests for the timberline entity class

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
from rvc2mqtt.entity.timberline import hvac_TIMBERLINE


def _make_mock():
    mock = MagicMock()
    mock.make_device_topic_string.return_value = 'test/topic'
    mock.TOPIC_BASE = 'rvc2mqtt'
    mock.client_id = 'bridge'
    mock.get_bridge_ha_name.return_value = 'bridge'
    mock.bridge_state_topic = 'rvc2mqtt/bridge/state'
    mock.make_ha_auto_discovery_config_topic.return_value = 'homeassistant/device/test/config'
    return mock


_TIMBERLINE_DATA = {
    'instance': 1,
    'instance_name': "test timberline",
    'source_id': '65',
    'command_topic': 'timberline/set',
    'status_topic': 'timberline/status',
}


class Test_Timberline(unittest.TestCase):

    def test_basic(self):
        mock = MagicMock()
        mock.make_device_topic_string.return_value = 'topic_string'

        l = hvac_TIMBERLINE(_TIMBERLINE_DATA, mock)
        self.assertTrue(type(l), hvac_TIMBERLINE)

    def test_publish_ha_discovery_config(self):
        mock = _make_mock()
        entity = hvac_TIMBERLINE(_TIMBERLINE_DATA, mock)
        entity.publish_ha_discovery_config()
        self.assertTrue(mock.client.publish.called)
        for call in mock.client.publish.call_args_list:
            _, kwargs = call
            self.assertFalse(kwargs.get('retain', False),
                             f"Discovery config published with retain=True: {call}")


class Test_Timberline_DM_RV(unittest.TestCase):

    def _make_timberline(self, source_id='9D'):
        mock = MagicMock()
        mock.mqtt_support.make_device_topic_string.return_value = 'topic_string'
        return hvac_TIMBERLINE(
            {'instance': 1, 'instance_name': "Timberline", 'source_id': source_id,
             'status_topic': 'timberline/status',
             'command_topic': 'timberline/set'},
            mock
        )

    def _make_dm_rv(self, source_id='9D', spn_msb=0x7F, spn_isb=0x00, spn_lsb=0,
                    red_lamp=0, fmi_definition="No fault"):
        return {
            'name': 'DM_RV',
            'source_id': source_id,
            'spn-msb': spn_msb,
            'spn-isb': spn_isb,
            'spn-lsb': spn_lsb,
            'red_lamp_status': red_lamp,
            'fmi_definition': fmi_definition,
        }

    def test_basic(self):
        t = self._make_timberline()
        self.assertTrue(type(t), hvac_TIMBERLINE)

    def test_dm_rv_wrong_source_id_not_processed(self):
        t = self._make_timberline()
        msg = self._make_dm_rv(source_id='FF')
        result = t.process_rvc_msg(msg)
        self.assertFalse(result)

    def test_dm_rv_publishes_fault_code_and_description(self):
        t = self._make_timberline()
        msg = self._make_dm_rv(spn_msb=0x7F, spn_isb=0x00, spn_lsb=0,
                               fmi_definition="Bad intelligent RV-C node")
        result = t.process_rvc_msg(msg)
        self.assertTrue(result)
        publish_calls = {c[0][0]: c[0][1]
                         for c in t.mqtt_support.client.publish.call_args_list}
        self.assertIn('timberline/status/fault/code', publish_calls)
        self.assertIn('timberline/status/fault/description', publish_calls)
        self.assertEqual(publish_calls['timberline/status/fault/description'],
                         "Bad intelligent RV-C node")

    def test_dm_rv_lamp_on_when_red_lamp_set(self):
        t = self._make_timberline()
        msg = self._make_dm_rv(red_lamp=1)
        t.process_rvc_msg(msg)
        publish_calls = {c[0][0]: c[0][1]
                         for c in t.mqtt_support.client.publish.call_args_list}
        self.assertEqual(publish_calls.get('timberline/status/fault/lamp'), 'on')

    def test_dm_rv_lamp_off_when_red_lamp_clear(self):
        t = self._make_timberline()
        msg = self._make_dm_rv(red_lamp=0)
        t.process_rvc_msg(msg)
        publish_calls = {c[0][0]: c[0][1]
                         for c in t.mqtt_support.client.publish.call_args_list}
        self.assertEqual(publish_calls.get('timberline/status/fault/lamp'), 'off')

    def test_dm_rv_no_publish_when_fault_unchanged(self):
        t = self._make_timberline()
        msg = self._make_dm_rv()
        t.process_rvc_msg(msg)
        t.mqtt_support.client.publish.reset_mock()
        t.process_rvc_msg(msg)
        fault_publishes = [c for c in t.mqtt_support.client.publish.call_args_list
                           if 'fault/code' in c[0][0] or 'fault/description' in c[0][0]]
        self.assertEqual(len(fault_publishes), 0)

    def test_dm_rv_publishes_on_fault_change(self):
        t = self._make_timberline()
        t.process_rvc_msg(self._make_dm_rv(spn_msb=0x7F, spn_isb=0x00, spn_lsb=0))
        t.mqtt_support.client.publish.reset_mock()
        t.process_rvc_msg(self._make_dm_rv(spn_msb=0x7F, spn_isb=0x00, spn_lsb=4,
                                           fmi_definition="Datum erratic"))
        fault_publishes = [c for c in t.mqtt_support.client.publish.call_args_list
                           if 'fault/code' in c[0][0]]
        self.assertEqual(len(fault_publishes), 1)


if __name__ == '__main__':
    unittest.main()
