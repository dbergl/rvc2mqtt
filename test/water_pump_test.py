"""
Unit tests for the water pump entity class

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
from rvc2mqtt.entity.water_pump import WaterPumpClass as WaterPump


def _make_mock():
    mock = MagicMock()
    mock.make_device_topic_string.return_value = 'test/topic'
    mock.TOPIC_BASE = 'rvc2mqtt'
    mock.client_id = 'bridge'
    mock.get_bridge_ha_name.return_value = 'bridge'
    mock.bridge_state_topic = 'rvc2mqtt/bridge/state'
    mock.make_ha_auto_discovery_config_topic.return_value = 'homeassistant/switch/test/config'
    return mock


def _make_pump():
    mock = _make_mock()
    entity = WaterPump({'instance': 1, 'instance_name': "test WaterPump"}, mock)
    return entity, mock


def _make_status_msg(operating='00', pump='00', hookup='00', pressure=0):
    return {
        'name': 'WATER_PUMP_STATUS',
        'operating_status': operating,
        'pump_status': pump,
        'water_hookup_detected': hookup,
        'current_system_pressure': pressure,
    }


class Test_WaterPump(unittest.TestCase):

    def test_basic(self):
        mock = MagicMock()
        mock.mqtt_support.make_device_topic_string.return_value = 'topic_string'
        l = WaterPump({'instance': 1, 'instance_name': "test WaterPump"}, mock)
        self.assertTrue(type(l), WaterPump)

    def test_publish_ha_discovery_config_retain_false(self):
        """All four HA discovery config publishes must use retain=False."""
        mock = _make_mock()
        entity = WaterPump({'instance': 1, 'instance_name': "test WaterPump"}, mock)
        entity.publish_ha_discovery_config()
        self.assertTrue(mock.client.publish.called)
        # Should publish 4 discovery configs (power, running, external_water, system_pressure)
        self.assertEqual(mock.client.publish.call_count, 4)
        for call in mock.client.publish.call_args_list:
            _, kwargs = call
            self.assertFalse(kwargs.get('retain', False),
                             f"Discovery config published with retain=True: {call}")

    # --- process_rvc_msg: status ---

    def test_process_rvc_msg_pump_on(self):
        entity, mock = _make_pump()
        msg = _make_status_msg(operating='01', pump='01', hookup='01')
        result = entity.process_rvc_msg(msg)
        self.assertTrue(result)
        self.assertEqual(entity.power_state, WaterPump.ON)
        self.assertEqual(entity.running_state, WaterPump.ON)
        self.assertEqual(entity.external_water_hookup, WaterPump.OUTSIDE_WATER_DISCONNECTED)

    def test_process_rvc_msg_pump_off(self):
        entity, mock = _make_pump()
        msg = _make_status_msg(operating='00', pump='00', hookup='00')
        result = entity.process_rvc_msg(msg)
        self.assertTrue(result)
        self.assertEqual(entity.power_state, WaterPump.OFF)
        self.assertEqual(entity.running_state, WaterPump.OFF)
        self.assertEqual(entity.external_water_hookup, WaterPump.OUTSIDE_WATER_CONNECTED)

    def test_process_rvc_msg_unexpected_operating_status(self):
        entity, mock = _make_pump()
        msg = _make_status_msg(operating='FF')
        result = entity.process_rvc_msg(msg)
        self.assertTrue(result)
        self.assertIn('UNEXPECTED', entity.power_state)

    def test_process_rvc_msg_unexpected_pump_status(self):
        entity, mock = _make_pump()
        msg = _make_status_msg(pump='FF')
        result = entity.process_rvc_msg(msg)
        self.assertTrue(result)
        self.assertIn('UNEXPECTED', entity.running_state)

    def test_process_rvc_msg_unexpected_hookup_status(self):
        entity, mock = _make_pump()
        msg = _make_status_msg(hookup='FF')
        result = entity.process_rvc_msg(msg)
        self.assertTrue(result)
        self.assertIn('UNEXPECTED', entity.external_water_hookup)

    def test_process_rvc_msg_system_pressure(self):
        entity, mock = _make_pump()
        msg = _make_status_msg(pressure=42.5)
        entity.process_rvc_msg(msg)
        self.assertEqual(entity.system_pressure, 42.5)

    def test_process_rvc_msg_command_eaten(self):
        entity, mock = _make_pump()
        msg = {'name': 'WATER_PUMP_COMMAND'}
        result = entity.process_rvc_msg(msg)
        self.assertTrue(result)

    def test_process_rvc_msg_no_match(self):
        entity, mock = _make_pump()
        msg = {'name': 'SOME_OTHER_MSG'}
        result = entity.process_rvc_msg(msg)
        self.assertFalse(result)

    # --- process_mqtt_msg ---

    def test_process_mqtt_msg_empty_payload_ignored(self):
        entity, mock = _make_pump()
        q = queue.Queue()
        entity.set_rvc_send_queue(q)
        entity.process_mqtt_msg(entity.command_topic, '')
        self.assertTrue(q.empty())

    def test_process_mqtt_msg_none_payload_ignored(self):
        entity, mock = _make_pump()
        q = queue.Queue()
        entity.set_rvc_send_queue(q)
        entity.process_mqtt_msg(entity.command_topic, None)
        self.assertTrue(q.empty())

    def test_process_mqtt_msg_turn_on(self):
        entity, mock = _make_pump()
        entity.power_state = WaterPump.OFF
        q = queue.Queue()
        entity.set_rvc_send_queue(q)
        entity.process_mqtt_msg(entity.command_topic, 'on')
        self.assertFalse(q.empty())
        msg = q.get_nowait()
        self.assertEqual(msg['dgn'], '1FFB2')

    def test_process_mqtt_msg_turn_off(self):
        entity, mock = _make_pump()
        entity.power_state = WaterPump.ON
        q = queue.Queue()
        entity.set_rvc_send_queue(q)
        entity.process_mqtt_msg(entity.command_topic, 'off')
        self.assertFalse(q.empty())
        msg = q.get_nowait()
        self.assertEqual(msg['dgn'], '1FFB2')

    def test_process_mqtt_msg_no_op_already_on(self):
        entity, mock = _make_pump()
        entity.power_state = WaterPump.ON
        q = queue.Queue()
        entity.set_rvc_send_queue(q)
        entity.process_mqtt_msg(entity.command_topic, 'on')
        self.assertTrue(q.empty())

    def test_process_mqtt_msg_no_op_already_off(self):
        entity, mock = _make_pump()
        entity.power_state = WaterPump.OFF
        q = queue.Queue()
        entity.set_rvc_send_queue(q)
        entity.process_mqtt_msg(entity.command_topic, 'off')
        self.assertTrue(q.empty())

    def test_process_mqtt_msg_invalid_payload(self):
        entity, mock = _make_pump()
        q = queue.Queue()
        entity.set_rvc_send_queue(q)
        entity.process_mqtt_msg(entity.command_topic, 'invalid')
        self.assertTrue(q.empty())

    # --- RVC frame encoding ---

    def test_rvc_pump_off_frame(self):
        entity, mock = _make_pump()
        q = queue.Queue()
        entity.set_rvc_send_queue(q)
        entity._rvc_pump_off()
        msg = q.get_nowait()
        self.assertEqual(msg['dgn'], '1FFB2')
        self.assertEqual(msg['data'][0], 0)  # operating_status = off

    def test_rvc_pump_on_frame(self):
        entity, mock = _make_pump()
        q = queue.Queue()
        entity.set_rvc_send_queue(q)
        entity._rvc_pump_on()
        msg = q.get_nowait()
        self.assertEqual(msg['dgn'], '1FFB2')
        self.assertEqual(msg['data'][0], 1)  # operating_status = on

    # --- initialize ---

    def test_initialize_publishes_all_status_topics(self):
        entity, mock = _make_pump()
        entity.initialize()
        published_topics = [call[0][0] for call in mock.client.publish.call_args_list]
        self.assertIn(entity.status_topic, published_topics)
        self.assertIn(entity.running_status_topic, published_topics)
        self.assertIn(entity.external_water_status_topic, published_topics)
        self.assertIn(entity.system_pressure_status_topic, published_topics)


if __name__ == '__main__':
    unittest.main()
