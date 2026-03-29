"""
Unit tests for the hvac entity class

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

import queue
import unittest
from unittest.mock import MagicMock
import context  # add rvc2mqtt package to the python path using local reference
from rvc2mqtt.entity.hvac import HvacClass, FanMode, HvacMode


class Test_FanMode(unittest.TestCase):

    def test_fan_mode(self):
        self.assertEqual(FanMode.AUTO.rvc_fan_mode_str, 'auto')
        self.assertEqual(FanMode.AUTO.rvc_fan_mode_int, 0)
        self.assertEqual(FanMode.AUTO.rvc_fan_speed_percent, 50)
        self.assertEqual(FanMode.AUTO.rvc_fan_speed_for_rvc_msg, 100)

        self.assertEqual(FanMode.LOW.rvc_fan_mode_str, 'on')
        self.assertEqual(FanMode.LOW.rvc_fan_mode_int, 1)
        self.assertEqual(FanMode.LOW.rvc_fan_speed_percent, 25)
        self.assertEqual(FanMode.LOW.rvc_fan_speed_for_rvc_msg, 50)

        self.assertEqual(FanMode.MEDIUM.rvc_fan_mode_str, 'on')
        self.assertEqual(FanMode.MEDIUM.rvc_fan_mode_int, 1)
        self.assertEqual(FanMode.MEDIUM.rvc_fan_speed_percent, 50)
        self.assertEqual(FanMode.MEDIUM.rvc_fan_speed_for_rvc_msg, 100)

        self.assertEqual(FanMode.HIGH.rvc_fan_mode_str, 'on')
        self.assertEqual(FanMode.HIGH.rvc_fan_mode_int, 1)
        self.assertEqual(FanMode.HIGH.rvc_fan_speed_percent, 100)
        self.assertEqual(FanMode.HIGH.rvc_fan_speed_for_rvc_msg, 200)

        self.assertEqual(FanMode.OFF.rvc_fan_mode_str, 'on')
        self.assertEqual(FanMode.OFF.rvc_fan_mode_int, 1)
        self.assertEqual(FanMode.OFF.rvc_fan_speed_percent, 0)
        self.assertEqual(FanMode.OFF.rvc_fan_speed_for_rvc_msg, 0)

    def test_fan_mode_from_rvc(self):
        self.assertEqual(FanMode.get_fan_mode_from_rvc(0, "on"), FanMode.OFF)
        self.assertEqual(FanMode.get_fan_mode_from_rvc(25, "on"), FanMode.LOW)
        self.assertEqual(FanMode.get_fan_mode_from_rvc(50, "on"), FanMode.MEDIUM)
        self.assertEqual(FanMode.get_fan_mode_from_rvc(100, "on"), FanMode.HIGH)
        self.assertEqual(FanMode.get_fan_mode_from_rvc(50, "auto"), FanMode.AUTO)
        self.assertEqual(FanMode.get_fan_mode_from_rvc(75, "auto"), FanMode.AUTO)


class Test_HvacMode(unittest.TestCase):
    def test_hvac_mode(self):
        self.assertEqual(HvacMode.OFF, HvacMode("off"))
        self.assertEqual(HvacMode.COOL, HvacMode("cool"))
        self.assertEqual(HvacMode.HEAT, HvacMode("heat"))
        self.assertEqual(HvacMode.FAN_ONLY, HvacMode("fan_only"))

    def test_hvac_to_rvc(self):
        self.assertEqual(HvacMode.OFF.rvc_mode_for_rvc_msg, 0)
        self.assertEqual(HvacMode.COOL.rvc_mode_for_rvc_msg, 1)
        self.assertEqual(HvacMode.HEAT.rvc_mode_for_rvc_msg, 5)
        self.assertEqual(HvacMode.FAN_ONLY.rvc_mode_for_rvc_msg, 4)

    def test_hvac_from_rvc(self):
        self.assertEqual(HvacMode.get_hvac_mode_from_rvc('off'), HvacMode.OFF)
        self.assertEqual(HvacMode.get_hvac_mode_from_rvc('fan only'), HvacMode.FAN_ONLY)
        self.assertEqual(HvacMode.get_hvac_mode_from_rvc('aux heat'), HvacMode.HEAT)
        self.assertEqual(HvacMode.get_hvac_mode_from_rvc('cool'), HvacMode.COOL)


def _make_mock():
    mock = MagicMock()
    mock.make_device_topic_string.return_value = 'test/topic'
    mock.TOPIC_BASE = 'rvc2mqtt'
    mock.client_id = 'bridge'
    mock.get_bridge_ha_name.return_value = 'bridge'
    mock.bridge_state_topic = 'rvc2mqtt/bridge/state'
    mock.make_ha_auto_discovery_config_topic.return_value = 'homeassistant/climate/test/config'
    return mock


def _make_hvac():
    mock = _make_mock()
    entity = HvacClass(
        {'instance': 1, 'instance_name': "test hvac",
         'status_topic': 'rvc/state/hvac', 'command_topic': 'rvc/set/hvac'},
        mock
    )
    return entity, mock


def _make_status_msg(mode_def='off', fan_def='auto', fan_speed=0.0,
                     set_point_c=18.0, set_point_h=18.0):
    return {
        'name': 'THERMOSTAT_STATUS_1',
        'instance': 1,
        'operating_mode_definition': mode_def,
        'fan_mode_definition': fan_def,
        'fan_speed': fan_speed,
        'setpoint_temp_cool': set_point_c,
        'setpoint_temp_heat': set_point_h,
    }


class Test_HvacClimate(unittest.TestCase):

    def test_basic(self):
        mock = MagicMock()
        mock.mqtt_support.make_device_topic_string.return_value = 'topic_string'
        l = HvacClass({'instance': 1, 'instance_name': "test hvac"}, mock)
        self.assertTrue(type(l), HvacClass)

    def test_publish_ha_discovery_config(self):
        mock = _make_mock()
        entity = HvacClass({'instance': 1, 'instance_name': "test hvac"}, mock)
        entity.publish_ha_discovery_config()
        self.assertTrue(mock.client.publish.called)
        for call in mock.client.publish.call_args_list:
            _, kwargs = call
            self.assertFalse(kwargs.get('retain', False),
                             f"Discovery config published with retain=True: {call}")

    def test_convert_c_to_uint16(self):
        mock = MagicMock()
        mock.mqtt_support.make_device_topic_string.return_value = 'topic_string'
        l = HvacClass({'instance': 1, 'instance_name': "test hvac"}, mock)
        self.assertEqual(l._convert_temp_c_to_rvc_uint16(17.75), 0x2458)
        self.assertEqual(l._convert_temp_c_to_rvc_uint16(18.00), 0x2460)
        self.assertEqual(l._convert_temp_c_to_rvc_uint16(17.22), 0x2447)
        self.assertEqual(l._convert_temp_c_to_rvc_uint16(15.53), 0x2411)
        self.assertEqual(l._convert_temp_c_to_rvc_uint16(25.53), 0x2551)

    def test_make_data_buffer(self):
        mock = MagicMock()
        mock.mqtt_support.make_device_topic_string.return_value = 'topic_string'
        l = HvacClass({'instance': 1, 'instance_name': "test hvac"}, mock)
        self.assertEqual(l._make_rvc_payload(2, HvacMode.OFF, FanMode.AUTO, 'disabled', 17.75),
                         bytearray.fromhex("0200645824582400"))

    def test_hvac_modes_override(self):
        mock = _make_mock()
        entity = HvacClass(
            {'instance': 1, 'instance_name': "test hvac", 'hvac_modes': ['cool', 'off']},
            mock)
        self.assertEqual(entity._hvac_modes, ['cool', 'off'])

    def test_fan_modes_override(self):
        mock = _make_mock()
        entity = HvacClass(
            {'instance': 1, 'instance_name': "test hvac", 'fan_modes': ['auto', 'high', 'low']},
            mock)
        self.assertEqual(entity._fan_modes, ['auto', 'high', 'low'])

    def test_hvac_modes_default_when_not_specified(self):
        mock = _make_mock()
        entity = HvacClass({'instance': 1, 'instance_name': "test hvac"}, mock)
        self.assertEqual(entity._hvac_modes, HvacClass.MQTT_SUPPORTED_MODES)

    def test_fan_modes_default_when_not_specified(self):
        mock = _make_mock()
        entity = HvacClass({'instance': 1, 'instance_name': "test hvac"}, mock)
        self.assertEqual(entity._fan_modes, HvacClass.MQTT_SUPPORTED_FAN_MODE)

    def test_hvac_modes_invalid_values_ignored(self):
        mock = _make_mock()
        entity = HvacClass(
            {'instance': 1, 'instance_name': "test hvac",
             'hvac_modes': ['cool', 'off', 'invalid_mode']},
            mock)
        self.assertEqual(entity._hvac_modes, ['cool', 'off'])

    def test_fan_modes_invalid_values_ignored(self):
        mock = _make_mock()
        entity = HvacClass(
            {'instance': 1, 'instance_name': "test hvac",
             'fan_modes': ['auto', 'high', 'low', 'turbo']},
            mock)
        self.assertEqual(entity._fan_modes, ['auto', 'high', 'low'])

    def test_hvac_modes_used_in_discovery_config(self):
        import json
        mock = _make_mock()
        entity = HvacClass(
            {'instance': 1, 'instance_name': "test hvac", 'hvac_modes': ['cool', 'off']},
            mock)
        entity.publish_ha_discovery_config()
        payload = json.loads(mock.client.publish.call_args[0][1])
        self.assertEqual(payload['modes'], ['cool', 'off'])

    def test_fan_modes_used_in_discovery_config(self):
        import json
        mock = _make_mock()
        entity = HvacClass(
            {'instance': 1, 'instance_name': "test hvac", 'fan_modes': ['auto', 'high', 'low']},
            mock)
        entity.publish_ha_discovery_config()
        payload = json.loads(mock.client.publish.call_args[0][1])
        self.assertEqual(payload['fan_modes'], ['auto', 'high', 'low'])

    # --- property setters ---

    def test_mode_setter_sets_changed(self):
        entity, mock = _make_hvac()
        entity._changed = False
        entity.mode = HvacMode.COOL  # different from default OFF
        self.assertTrue(entity._changed)

    def test_mode_setter_no_change_if_same(self):
        entity, mock = _make_hvac()
        entity._mode = HvacMode.OFF
        entity._changed = False
        entity.mode = HvacMode.OFF
        self.assertFalse(entity._changed)

    def test_fan_mode_setter_sets_changed(self):
        entity, mock = _make_hvac()
        entity._changed = False
        entity.fan_mode = FanMode.HIGH  # different from default AUTO
        self.assertTrue(entity._changed)

    def test_set_point_temperature_setter_sets_changed(self):
        entity, mock = _make_hvac()
        entity._changed = False
        entity.set_point_temperature = 25.0  # different from default 16.09
        self.assertTrue(entity._changed)

    def test_set_point_temperaturef_setter_sets_changed(self):
        entity, mock = _make_hvac()
        entity._changed = False
        entity.set_point_temperaturef = 80.0  # different from default 61.0
        self.assertTrue(entity._changed)

    # --- process_rvc_msg ---

    def test_process_rvc_msg_status_off(self):
        entity, mock = _make_hvac()
        msg = _make_status_msg(mode_def='off', fan_def='auto', fan_speed=50.0)
        result = entity.process_rvc_msg(msg)
        self.assertTrue(result)
        self.assertEqual(entity.mode, HvacMode.OFF)
        self.assertEqual(entity.fan_mode, FanMode.AUTO)

    def test_process_rvc_msg_status_cool_high_fan(self):
        entity, mock = _make_hvac()
        msg = _make_status_msg(mode_def='cool', fan_def='on', fan_speed=100.0, set_point_c=22.0, set_point_h=22.0)
        result = entity.process_rvc_msg(msg)
        self.assertTrue(result)
        self.assertEqual(entity.mode, HvacMode.COOL)
        self.assertEqual(entity.fan_mode, FanMode.HIGH)

    def test_process_rvc_msg_publishes_when_changed(self):
        entity, mock = _make_hvac()
        mock.client.publish.reset_mock()
        msg = _make_status_msg(mode_def='cool', fan_def='on', fan_speed=100.0, set_point_c=22.0, set_point_h=22.0)
        entity.process_rvc_msg(msg)
        # should have published mode, fan_mode, set_point_temp, set_point_tempf
        published_topics = [call[0][0] for call in mock.client.publish.call_args_list]
        self.assertIn(entity.status_mode_topic, published_topics)
        self.assertIn(entity.status_fan_mode_topic, published_topics)
        self.assertIn(entity.status_set_point_temp_topic, published_topics)
        self.assertIn(entity.status_set_point_tempf_topic, published_topics)

    def test_process_rvc_msg_setpoint_mismatch_logged(self):
        entity, mock = _make_hvac()
        # cool != heat should log error but not crash
        msg = _make_status_msg(set_point_c=20.0, set_point_h=18.0)
        result = entity.process_rvc_msg(msg)
        self.assertTrue(result)

    def test_process_rvc_msg_command_returns_false(self):
        entity, mock = _make_hvac()
        msg = {'name': 'THERMOSTAT_COMMAND_1', 'instance': 1}
        result = entity.process_rvc_msg(msg)
        self.assertFalse(result)

    def test_process_rvc_msg_no_match(self):
        entity, mock = _make_hvac()
        msg = {'name': 'SOME_OTHER_MSG', 'instance': 1}
        result = entity.process_rvc_msg(msg)
        self.assertFalse(result)

    # --- process_mqtt_msg ---

    def test_process_mqtt_msg_empty_payload_ignored(self):
        entity, mock = _make_hvac()
        q = queue.Queue()
        entity.set_rvc_send_queue(q)
        entity.process_mqtt_msg(entity.command_mode_topic, '')
        self.assertTrue(q.empty())

    def test_process_mqtt_msg_mode_cool(self):
        entity, mock = _make_hvac()
        q = queue.Queue()
        entity.set_rvc_send_queue(q)
        entity.process_mqtt_msg(entity.command_mode_topic, 'cool')
        self.assertFalse(q.empty())
        msg = q.get_nowait()
        self.assertEqual(msg['dgn'], '1FEF9')

    def test_process_mqtt_msg_mode_invalid_logs_error(self):
        entity, mock = _make_hvac()
        q = queue.Queue()
        entity.set_rvc_send_queue(q)
        entity.process_mqtt_msg(entity.command_mode_topic, 'invalid_mode')
        # should log error but not crash; no RVC frame sent
        self.assertTrue(q.empty())

    def test_process_mqtt_msg_fan_mode_high(self):
        entity, mock = _make_hvac()
        q = queue.Queue()
        entity.set_rvc_send_queue(q)
        entity.process_mqtt_msg(entity.command_fan_mode_topic, 'high')
        self.assertFalse(q.empty())
        msg = q.get_nowait()
        self.assertEqual(msg['dgn'], '1FEF9')

    def test_process_mqtt_msg_fan_mode_invalid(self):
        entity, mock = _make_hvac()
        q = queue.Queue()
        entity.set_rvc_send_queue(q)
        entity.process_mqtt_msg(entity.command_fan_mode_topic, 'invalid_fan')
        self.assertTrue(q.empty())

    def test_process_mqtt_msg_set_point_temp(self):
        entity, mock = _make_hvac()
        q = queue.Queue()
        entity.set_rvc_send_queue(q)
        entity.process_mqtt_msg(entity.command_set_point_temp_topic, '22.5')
        self.assertFalse(q.empty())
        msg = q.get_nowait()
        self.assertEqual(msg['dgn'], '1FEF9')

    def test_process_mqtt_msg_set_point_temp_invalid(self):
        entity, mock = _make_hvac()
        q = queue.Queue()
        entity.set_rvc_send_queue(q)
        entity.process_mqtt_msg(entity.command_set_point_temp_topic, 'not_a_number')
        self.assertTrue(q.empty())

    def test_process_mqtt_msg_set_point_tempf(self):
        entity, mock = _make_hvac()
        q = queue.Queue()
        entity.set_rvc_send_queue(q)
        entity.process_mqtt_msg(entity.command_set_point_tempf_topic, '72.5')
        self.assertFalse(q.empty())
        msg = q.get_nowait()
        self.assertEqual(msg['dgn'], '1FEF9')

    def test_process_mqtt_msg_set_point_tempf_invalid(self):
        entity, mock = _make_hvac()
        q = queue.Queue()
        entity.set_rvc_send_queue(q)
        entity.process_mqtt_msg(entity.command_set_point_tempf_topic, 'not_a_number')
        self.assertTrue(q.empty())

    def test_process_mqtt_msg_unknown_topic_logs_error(self):
        entity, mock = _make_hvac()
        q = queue.Queue()
        entity.set_rvc_send_queue(q)
        entity.process_mqtt_msg('some/unknown/topic', 'value')
        self.assertTrue(q.empty())

    # --- add_entity_link ---

    def test_add_entity_link(self):
        entity, mock = _make_hvac()
        temp_sensor = MagicMock()
        temp_sensor.status_topic = 'rvc/state/temp'
        entity.add_entity_link(temp_sensor)
        self.assertEqual(entity.temperature_entity_link, temp_sensor)

    def test_publish_ha_discovery_config_with_temperature_link(self):
        import json
        entity, mock = _make_hvac()
        temp_sensor = MagicMock()
        temp_sensor.status_topic = 'rvc/state/temp'
        entity.add_entity_link(temp_sensor)
        mock.client.publish.reset_mock()
        entity.publish_ha_discovery_config()
        payload = json.loads(mock.client.publish.call_args[0][1])
        self.assertIn('current_temperature_topic', payload)
        self.assertEqual(payload['current_temperature_topic'], 'rvc/state/temp')

    # --- initialize ---

    def test_initialize_publishes_ha_config(self):
        entity, mock = _make_hvac()
        entity.initialize()
        self.assertTrue(mock.client.publish.called)


if __name__ == '__main__':
    unittest.main()
