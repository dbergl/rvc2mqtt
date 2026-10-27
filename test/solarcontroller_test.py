"""
Unit tests for the solar controller entity class

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

class SolarController_SOLAR_CONTROLLER_STATUS(EntityPluginBaseClass):
    FACTORY_MATCH_ATTRIBUTES = {"name": "SOLAR_CONTROLLER_STATUS", "type": "solar"}
"""

import unittest
from unittest.mock import MagicMock
import context  # add rvc2mqtt package to the python path using local reference
from rvc2mqtt.entity.solarcontroller import SolarController_SOLAR_CONTROLLER_STATUS as SolarController


def _make_mock():
    mock = MagicMock()
    mock.make_device_topic_string.return_value = 'test/topic'
    mock.TOPIC_BASE = 'rvc2mqtt'
    mock.client_id = 'bridge'
    mock.get_bridge_ha_name.return_value = 'bridge'
    mock.bridge_state_topic = 'rvc2mqtt/bridge/state'
    mock.make_ha_auto_discovery_config_topic.return_value = 'homeassistant/sensor/test/config'
    return mock


def _make_controller(with_status_topic=True):
    mock = _make_mock()
    data = {'instance': 1, 'instance_name': "test solar controller", 'type': 'solar'}
    if with_status_topic:
        data['status_topic'] = 'rvc/state/solar'
    entity = SolarController(data, mock)
    return entity, mock


class Test_SolarController(unittest.TestCase):

    def test_basic(self):
        mock = MagicMock()
        mock.mqtt_support.make_device_topic_string.return_value = 'topic_string'
        l = SolarController({'instance': 1, 'instance_name': "test solar controller house battery",
                             'type': 'solar', 'status_topic': 'rvc/state/solar',
                             'command_topic': 'rvc/set/solar'}, mock)
        self.assertTrue(type(l), SolarController)
        l = SolarController({'instance': 2, 'instance_name': "test solar controller chassis battery",
                             'type': 'solar', 'status_topic': 'rvc/state/solar'}, mock)
        self.assertTrue(type(l), SolarController)

    def test_basic_no_status_topic(self):
        entity, mock = _make_controller(with_status_topic=False)
        self.assertTrue(type(entity), SolarController)

    # --- process_rvc_msg: SOLAR_CONTROLLER_STATUS ---

    def test_process_rvc_msg_controller_status(self):
        entity, mock = _make_controller()
        msg = {
            'name': 'SOLAR_CONTROLLER_STATUS', 'instance': 1,
            'operating_state': 'bulk',
            'operating_state_definition': 'bulk charging',
            'power-up_state': 'normal',
            'power-up_state_definition': 'normal operation',
            'force_charge': 'off',
            'force_charge_definition': 'disabled',
        }
        result = entity.process_rvc_msg(msg)
        self.assertTrue(result)
        self.assertEqual(entity.operating_state, 'bulk')

    def test_process_rvc_msg_controller_status_no_publish_if_unchanged(self):
        entity, mock = _make_controller()
        entity.operating_state = 'bulk'
        entity.power_up_state = 'normal'
        entity.force_charge = 'off'
        mock.client.publish.reset_mock()
        msg = {
            'name': 'SOLAR_CONTROLLER_STATUS', 'instance': 1,
            'operating_state': 'bulk',
            'operating_state_definition': 'bulk charging',
            'power-up_state': 'normal',
            'power-up_state_definition': 'normal operation',
            'force_charge': 'off',
            'force_charge_definition': 'disabled',
        }
        entity.process_rvc_msg(msg)
        mock.client.publish.assert_not_called()

    # --- process_rvc_msg: SOLAR_CONTROLLER_STATUS_4 ---

    def test_process_rvc_msg_status4(self):
        entity, mock = _make_controller()
        msg = {
            'name': 'SOLAR_CONTROLLER_STATUS_4', 'instance': 1,
            "today's_amp-hours_to_battery": 10.5,
            "yesterday's_amp-hours_to_battery": 8.2,
            "day_before_yesterday's_amp-hours_to_battery": 9.1,
        }
        result = entity.process_rvc_msg(msg)
        self.assertTrue(result)
        self.assertEqual(entity.today, 10.5)
        self.assertEqual(entity.yesterday, 8.2)
        self.assertEqual(entity.two_days_ago, 9.1)

    def test_process_rvc_msg_status4_publishes_topics(self):
        entity, mock = _make_controller()
        msg = {
            'name': 'SOLAR_CONTROLLER_STATUS_4', 'instance': 1,
            "today's_amp-hours_to_battery": 10.5,
            "yesterday's_amp-hours_to_battery": 8.2,
            "day_before_yesterday's_amp-hours_to_battery": 9.1,
        }
        entity.process_rvc_msg(msg)
        published_topics = [call[0][0] for call in mock.client.publish.call_args_list]
        self.assertIn(entity.today_topic, published_topics)
        self.assertIn(entity.yesterday_topic, published_topics)
        self.assertIn(entity.two_days_ago_topic, published_topics)

    # --- process_rvc_msg: SOLAR_CONTROLLER_STATUS_5 ---

    def test_process_rvc_msg_status5(self):
        entity, mock = _make_controller()
        msg = {
            'name': 'SOLAR_CONTROLLER_STATUS_5', 'instance': 1,
            'last_7_days_amp-hours_to_battery': 70.0,
            'cumulative_power_generation': 1000.0,
        }
        result = entity.process_rvc_msg(msg)
        self.assertTrue(result)
        self.assertEqual(entity.seven_day_total, 70.0)
        self.assertEqual(entity.power_generation, 1000.0)

    def test_process_rvc_msg_status5_power_generation_halved(self):
        entity, mock = _make_controller()
        msg = {
            'name': 'SOLAR_CONTROLLER_STATUS_5', 'instance': 1,
            'last_7_days_amp-hours_to_battery': 70.0,
            'cumulative_power_generation': 1000.0,
        }
        entity.process_rvc_msg(msg)
        calls = {call[0][0]: call[0][1] for call in mock.client.publish.call_args_list}
        self.assertIn(entity.power_generation_topic, calls)
        # should be 1000/2 = 500 rounded
        self.assertEqual(calls[entity.power_generation_topic], '500')

    # --- process_rvc_msg: SOLAR_CONTROLLER_STATUS_6 ---

    def test_process_rvc_msg_status6(self):
        entity, mock = _make_controller()
        msg = {
            'name': 'SOLAR_CONTROLLER_STATUS_6', 'instance': 1,
            'total_number_of_operating_days': 365,
            'solar_charge_controller_measured_temperature': 25.5,
        }
        result = entity.process_rvc_msg(msg)
        self.assertTrue(result)
        self.assertEqual(entity.operating_days, 365)
        self.assertEqual(entity.temperature, 25.5)

    # --- process_rvc_msg: SOLAR_CONTROLLER_SOLAR_ARRAY_STATUS ---

    def test_process_rvc_msg_array_status(self):
        entity, mock = _make_controller()
        msg = {
            'name': 'SOLAR_CONTROLLER_SOLAR_ARRAY_STATUS', 'instance': 1,
            'solar_array_measured_voltage': 24.0,
            'solar_array_measured_current': 5.0,
        }
        result = entity.process_rvc_msg(msg)
        self.assertTrue(result)
        self.assertEqual(entity.array_voltage, 24.0)
        self.assertEqual(entity.array_current, 5.0)
        # power = 24.0 * 5.0 = 120.0
        self.assertAlmostEqual(entity.array_power, 120.0)

    def test_process_rvc_msg_array_status_power_published(self):
        entity, mock = _make_controller()
        msg = {
            'name': 'SOLAR_CONTROLLER_SOLAR_ARRAY_STATUS', 'instance': 1,
            'solar_array_measured_voltage': 24.0,
            'solar_array_measured_current': 5.0,
        }
        entity.process_rvc_msg(msg)
        calls = {call[0][0]: call[0][1] for call in mock.client.publish.call_args_list}
        self.assertIn(entity.array_power_topic, calls)
        self.assertEqual(calls[entity.array_power_topic], '120.0')

    def test_process_rvc_msg_array_status_no_power_publish_if_unchanged(self):
        entity, mock = _make_controller()
        entity.array_voltage = 24.0
        entity.array_current = 5.0
        entity.array_power = 120.0
        mock.client.publish.reset_mock()
        msg = {
            'name': 'SOLAR_CONTROLLER_SOLAR_ARRAY_STATUS', 'instance': 1,
            'solar_array_measured_voltage': 24.0,
            'solar_array_measured_current': 5.0,
        }
        entity.process_rvc_msg(msg)
        calls = {call[0][0] for call in mock.client.publish.call_args_list}
        self.assertNotIn(entity.array_power_topic, calls)

    # --- process_rvc_msg: SOLAR_CONTROLLER_BATTERY_STATUS ---

    def test_process_rvc_msg_battery_status(self):
        entity, mock = _make_controller()
        msg = {
            'name': 'SOLAR_CONTROLLER_BATTERY_STATUS', 'instance': 1,
            'measured_voltage': 13.2,
            'measured_current': 10.0,
            'measured_temperature': 22.0,
        }
        result = entity.process_rvc_msg(msg)
        self.assertTrue(result)
        self.assertEqual(entity.battery_voltage, 13.2)
        self.assertEqual(entity.battery_current, 10.0)
        self.assertEqual(entity.battery_temperature, 22.0)
        self.assertAlmostEqual(entity.battery_power, 132.0)

    def test_process_rvc_msg_battery_status_power_published(self):
        entity, mock = _make_controller()
        msg = {
            'name': 'SOLAR_CONTROLLER_BATTERY_STATUS', 'instance': 1,
            'measured_voltage': 13.2,
            'measured_current': 10.0,
            'measured_temperature': 22.0,
        }
        entity.process_rvc_msg(msg)
        calls = {call[0][0]: call[0][1] for call in mock.client.publish.call_args_list}
        self.assertIn(entity.battery_power_topic, calls)

    def test_process_rvc_msg_no_match(self):
        entity, mock = _make_controller()
        msg = {'name': 'SOME_OTHER_MSG', 'instance': 1}
        result = entity.process_rvc_msg(msg)
        self.assertFalse(result)

    def test_process_rvc_msg_wrong_instance(self):
        entity, mock = _make_controller()
        msg = {
            'name': 'SOLAR_CONTROLLER_STATUS', 'instance': 99,
            'operating_state': 'bulk',
            'operating_state_definition': 'bulk',
            'power-up_state': 'normal',
            'power-up_state_definition': 'normal',
            'force_charge': 'off',
            'force_charge_definition': 'off',
        }
        result = entity.process_rvc_msg(msg)
        self.assertFalse(result)

    # --- initialize ---

    def test_initialize_does_not_crash(self):
        entity, mock = _make_controller()
        entity.initialize()  # should be a no-op

    # --- process_mqtt_msg ---

    def test_process_mqtt_msg_does_not_crash(self):
        entity, mock = _make_controller()
        entity.process_mqtt_msg('some/topic', 'some_payload')


if __name__ == '__main__':
    unittest.main()
