"""
Unit tests for the temperature entity class

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

import json
import unittest
from unittest.mock import MagicMock
import context  # add rvc2mqtt package to the python path using local reference
from rvc2mqtt.entity.temperature import TemperatureSensor_THERMOSTAT_AMBIENT_STATUS as TemperatureSensor


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
    mock.make_ha_auto_discovery_config_topic.return_value = 'homeassistant/sensor/test/config'
    return mock


class Test_TemperatureSensor(unittest.TestCase):

    def test_basic(self):
        mock = MagicMock()
        mock.mqtt_support.make_device_topic_string.return_value = 'topic_string'

        l = TemperatureSensor({'instance': 1, 'instance_name': "test TemperatureSensor"}, mock)
        self.assertTrue(type(l), TemperatureSensor)

    def test_publish_ha_discovery_config(self):
        mock = _make_mock()
        entity = TemperatureSensor({'instance': 1, 'instance_name': "test TemperatureSensor"}, mock)
        entity.publish_ha_discovery_config()
        self.assertTrue(mock.client.publish.called)
        for call in mock.client.publish.call_args_list:
            _, kwargs = call
            self.assertFalse(kwargs.get('retain', False),
                             f"Discovery config published with retain=True: {call}")

class Test_TemperatureSensor_Deadband(unittest.TestCase):
    """Ambient temperature moves constantly, so it is filtered by a 0.25 C
    deadband rather than by equality."""

    def _make_sensor(self):
        mock = _make_mock()
        entity = TemperatureSensor(
            {'instance': 1, 'instance_name': "test temp"}, mock)
        return entity, mock

    def _msg(self, temp_c):
        return {'name': 'THERMOSTAT_AMBIENT_STATUS', 'instance': 1,
                'ambient_temp': temp_c}

    def _payloads(self, mock):
        return [json.loads(c[0][1]) for c in mock.client.publish.call_args_list]

    def test_first_reading_always_publishes(self):
        entity, mock = self._make_sensor()
        self.assertTrue(entity.process_rvc_msg(self._msg(22.0)))
        self.assertEqual(self._payloads(mock), [{'c': 22.0, 'f': 72}])

    def test_small_change_is_suppressed(self):
        entity, mock = self._make_sensor()
        entity.process_rvc_msg(self._msg(22.0))
        mock.client.publish.reset_mock()
        entity.process_rvc_msg(self._msg(22.1))
        self.assertEqual(self._payloads(mock), [])

    def test_exactly_at_the_deadband_publishes(self):
        entity, mock = self._make_sensor()
        entity.process_rvc_msg(self._msg(22.0))
        mock.client.publish.reset_mock()
        entity.process_rvc_msg(self._msg(22.25))
        self.assertEqual(len(self._payloads(mock)), 1)

    def test_deadband_measured_from_last_published_reading(self):
        """A slow drift must eventually publish rather than being suppressed
        forever by comparing against the most recent reading."""
        entity, mock = self._make_sensor()
        entity.process_rvc_msg(self._msg(22.0))
        mock.client.publish.reset_mock()
        for temp in (22.1, 22.15, 22.2):
            entity.process_rvc_msg(self._msg(temp))
        self.assertEqual(self._payloads(mock), [])
        entity.process_rvc_msg(self._msg(22.3))
        self.assertEqual(self._payloads(mock), [{'c': 22.3, 'f': 72}])

    def test_a_first_reading_of_zero_publishes(self):
        entity, mock = self._make_sensor()
        entity.process_rvc_msg(self._msg(0.0))
        self.assertEqual(self._payloads(mock), [{'c': 0.0, 'f': 32}])


if __name__ == '__main__':
    unittest.main()
