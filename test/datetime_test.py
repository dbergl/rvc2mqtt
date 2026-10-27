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
from rvc2mqtt.entity.datetime import Datetime_DATE_TIME_STATUS as Datetime

class Test_Datetime(unittest.TestCase):

    def test_basic(self):
        mock = MagicMock()
        mock.mqtt_support.make_device_topic_string.return_value = 'topic_string'

        l = Datetime({'instance': 1, 'instance_name': "test date_time"}, mock)
        self.assertTrue(type(l), Datetime)


def _make_mock():
    mock = MagicMock()
    mock.make_device_topic_string.return_value = 'test/topic'
    mock.TOPIC_BASE = 'rvc2mqtt'
    mock.client_id = 'bridge'
    mock.get_bridge_ha_name.return_value = 'bridge'
    mock.bridge_state_topic = 'rvc2mqtt/bridge/state'
    mock.make_ha_auto_discovery_config_topic.return_value = 'homeassistant/device/test/config'
    return mock


_DT_DATA = {'instance': 1, 'instance_name': "clock",
            'status_topic': 'rvc/state/date', 'command_topic': 'rvc/set/date',
            'timezone': 'America/New_York'}


class Test_Datetime_StatePayload(unittest.TestCase):
    """HA's datetime platform parses the state topic as a date/time expression.
    Anything that isn't one is rejected with:
      "Invalid received date/time expression on topic ... got unknown"
    so the "unknown" sentinel must never reach that topic.
    """

    def _make_dt(self):
        return Datetime(_DT_DATA, _make_mock())

    def _state_calls(self, entity):
        return [c for c in entity.mqtt_support.client.publish.call_args_list
                if c[0][0] == 'rvc/state/date']

    def _make_msg(self, year=26, month=8, date=10, hour=16, minute=11, second=12):
        return {'name': 'DATE_TIME_STATUS', 'source_id': '9C',
                'year': year, 'month': month, 'date': date,
                'day_of_week': 2, 'hour': hour, 'minute': minute,
                'second': second, 'time_zone': 255}

    def test_initialize_does_not_publish_unknown(self):
        l = self._make_dt()
        l.initialize()
        payloads = [c[0][1] for c in self._state_calls(l)]
        self.assertNotIn('unknown', payloads)

    def test_initialize_clears_retained_state(self):
        """An empty retained payload deletes a stale retained value on the
        broker; HA ignores it with only a debug log."""
        l = self._make_dt()
        l.initialize()
        calls = self._state_calls(l)
        self.assertTrue(calls, "initialize() published nothing to the state topic")
        self.assertEqual(calls[-1][0][1], "")
        self.assertTrue(calls[-1][1].get('retain', False),
                        "clearing publish must be retained to delete the stored value")

    def test_publishes_iso_datetime_from_rvc_msg(self):
        l = self._make_dt()
        l.process_rvc_msg(self._make_msg())
        l.mqtt_support.client.publish.assert_any_call(
            'rvc/state/date', '2026-08-10T16:11:12', retain=True)

    def test_invalid_rvc_datetime_not_published(self):
        l = self._make_dt()
        self.assertTrue(l.process_rvc_msg(self._make_msg(month=13)))
        self.assertEqual(self._state_calls(l), [])

    def test_no_republish_when_unchanged(self):
        l = self._make_dt()
        l.process_rvc_msg(self._make_msg())
        count = len(self._state_calls(l))
        l.process_rvc_msg(self._make_msg())
        self.assertEqual(len(self._state_calls(l)), count)


if __name__ == '__main__':
    unittest.main()
