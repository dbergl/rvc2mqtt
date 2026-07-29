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
    # Distinct topic per field so that publish() change tracking cannot
    # collapse unrelated fields onto a single cache key.
    mock.make_device_topic_string.side_effect = lambda id, field, state: \
        f'test/{id}/{field}/{"state" if state else "set"}'
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
        t.process_rvc_msg(self._make_dm_rv(spn_msb=0x7E, spn_isb=0x00, spn_lsb=0,
                                           fmi_definition="Datum erratic"))
        fault_publishes = [c for c in t.mqtt_support.client.publish.call_args_list
                           if 'fault/code' in c[0][0]]
        self.assertEqual(len(fault_publishes), 1)


class Test_Timberline_WaterheaterStatus(unittest.TestCase):
    """WATERHEATER_STATUS publishes ten topics; they must be change-gated
    individually rather than as one group."""

    def _make_timberline(self):
        return hvac_TIMBERLINE(_TIMBERLINE_DATA, _make_mock())

    def _make_status(self, water_temperature=40.0, operating_modes=1,
                     burner_status=0, ac_element_status=0,
                     failure_to_ignite_status=0):
        return {
            'name': 'WATERHEATER_STATUS',
            'instance': 1,
            'operating_modes': operating_modes,
            'operating_modes_definition': 'combustion',
            'water_temperature': water_temperature,
            'burner_status': burner_status,
            'burner_status_definition': 'off',
            'ac_element_status': ac_element_status,
            'ac_element_status_definition': 'off',
            'failure_to_ignite_status': failure_to_ignite_status,
            'failure_to_ignite_status_definition': 'no failure',
        }

    def _topics(self, entity):
        return [c[0][0] for c in entity.mqtt_support.client.publish.call_args_list]

    def test_first_message_publishes_every_topic(self):
        t = self._make_timberline()
        self.assertTrue(t.process_rvc_msg(self._make_status()))
        self.assertEqual(len(self._topics(t)), 10)

    def test_repeated_identical_message_publishes_nothing(self):
        t = self._make_timberline()
        msg = self._make_status()
        t.process_rvc_msg(msg)
        t.mqtt_support.client.publish.reset_mock()
        t.process_rvc_msg(msg)
        t.process_rvc_msg(msg)
        self.assertEqual(self._topics(t), [])

    def test_only_the_changed_field_republishes(self):
        t = self._make_timberline()
        t.process_rvc_msg(self._make_status(water_temperature=40.0))
        t.mqtt_support.client.publish.reset_mock()
        # 40.0 C -> 104 F, 41.0 C -> 106 F, so both the C and F topics move
        t.process_rvc_msg(self._make_status(water_temperature=41.0))
        self.assertEqual(sorted(self._topics(t)), [
            'timberline/status/heat_exchanger_temperature',
            'timberline/status/heat_exchanger_temperaturef',
        ])

    def test_rounded_fahrenheit_is_gated_independently(self):
        # A C change too small to move the rounded F value must not republish F.
        t = self._make_timberline()
        t.process_rvc_msg(self._make_status(water_temperature=40.0))
        t.mqtt_support.client.publish.reset_mock()
        t.process_rvc_msg(self._make_status(water_temperature=40.1))
        self.assertEqual(self._topics(t),
                         ['timberline/status/heat_exchanger_temperature'])

    def test_definition_topic_publishes_with_its_raw_value(self):
        t = self._make_timberline()
        t.process_rvc_msg(self._make_status(operating_modes=1))
        published = {c[0][0]: c[0][1]
                     for c in t.mqtt_support.client.publish.call_args_list}
        self.assertEqual(published['timberline/status/heatsource'], 1)
        self.assertEqual(published['timberline/status/heatsource_definition'],
                         'Combustion')


if __name__ == '__main__':
    unittest.main()
