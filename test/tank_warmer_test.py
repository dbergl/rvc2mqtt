"""
Unit tests for the tankwarmer entity class

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
from rvc2mqtt.entity.tank_warmer import TankWarmer_DC_LOAD_STATUS as TankWarmer


def _make_mock():
    mock = MagicMock()
    mock.make_device_topic_string.return_value = 'test/topic'
    mock.TOPIC_BASE = 'rvc2mqtt'
    mock.client_id = 'bridge'
    mock.get_bridge_ha_name.return_value = 'bridge'
    mock.bridge_state_topic = 'rvc2mqtt/bridge/state'
    mock.make_ha_auto_discovery_config_topic.return_value = 'homeassistant/switch/test/config'
    return mock


def _make_warmer():
    mock = _make_mock()
    entity = TankWarmer({'instance': 1, 'instance_name': "test tank_warmer"}, mock)
    return entity, mock


class Test_TankWarmer(unittest.TestCase):

    def test_basic(self):
        mock = MagicMock()
        mock.mqtt_support.make_device_topic_string.return_value = 'topic_string'
        l = TankWarmer({'instance': 1, 'instance_name': "test tank_warmer"}, mock)
        self.assertTrue(type(l), TankWarmer)

    def test_publish_ha_discovery_config(self):
        mock = _make_mock()
        entity = TankWarmer({'instance': 1, 'instance_name': "test tank warmer"}, mock)
        entity.publish_ha_discovery_config()
        self.assertTrue(mock.client.publish.called)
        for call in mock.client.publish.call_args_list:
            _, kwargs = call
            self.assertFalse(kwargs.get('retain', False),
                             f"Discovery config published with retain=True: {call}")

    # --- process_rvc_msg ---

    def test_process_rvc_msg_on(self):
        entity, mock = _make_warmer()
        msg = {'name': 'DC_LOAD_STATUS', 'instance': 1, 'operating_status': 100.0}
        result = entity.process_rvc_msg(msg)
        self.assertTrue(result)
        self.assertEqual(entity.state, TankWarmer.ON)
        mock.client.publish.assert_called_with(entity.status_topic, TankWarmer.ON, retain=True)

    def test_process_rvc_msg_off(self):
        entity, mock = _make_warmer()
        entity.state = TankWarmer.ON  # set initial state so publish fires on change
        msg = {'name': 'DC_LOAD_STATUS', 'instance': 1, 'operating_status': 0.0}
        result = entity.process_rvc_msg(msg)
        self.assertTrue(result)
        self.assertEqual(entity.state, TankWarmer.OFF)

    def test_process_rvc_msg_unexpected_status(self):
        entity, mock = _make_warmer()
        msg = {'name': 'DC_LOAD_STATUS', 'instance': 1, 'operating_status': 50.0}
        result = entity.process_rvc_msg(msg)
        self.assertTrue(result)
        self.assertIn('UNEXPECTED', entity.state)

    def test_process_rvc_msg_command_eaten(self):
        entity, mock = _make_warmer()
        msg = {'name': 'DC_LOAD_COMMAND', 'instance': 1}
        result = entity.process_rvc_msg(msg)
        self.assertTrue(result)

    def test_process_rvc_msg_no_match(self):
        entity, mock = _make_warmer()
        msg = {'name': 'SOME_OTHER_MSG', 'instance': 1, 'operating_status': 100.0}
        result = entity.process_rvc_msg(msg)
        self.assertFalse(result)

    def test_process_rvc_msg_wrong_instance(self):
        entity, mock = _make_warmer()
        msg = {'name': 'DC_LOAD_STATUS', 'instance': 2, 'operating_status': 100.0}
        result = entity.process_rvc_msg(msg)
        self.assertFalse(result)

    # --- process_mqtt_msg ---

    def test_process_mqtt_msg_empty_payload_ignored(self):
        entity, mock = _make_warmer()
        q = queue.Queue()
        entity.set_rvc_send_queue(q)
        entity.process_mqtt_msg(entity.command_topic, '')
        self.assertTrue(q.empty())

    def test_process_mqtt_msg_none_payload_ignored(self):
        entity, mock = _make_warmer()
        q = queue.Queue()
        entity.set_rvc_send_queue(q)
        entity.process_mqtt_msg(entity.command_topic, None)
        self.assertTrue(q.empty())

    def test_process_mqtt_msg_turn_on(self):
        entity, mock = _make_warmer()
        entity.state = TankWarmer.OFF
        q = queue.Queue()
        entity.set_rvc_send_queue(q)
        entity.process_mqtt_msg(entity.command_topic, 'on')
        self.assertFalse(q.empty())
        msg = q.get_nowait()
        self.assertEqual(msg['dgn'], '1FFBC')

    def test_process_mqtt_msg_turn_off(self):
        entity, mock = _make_warmer()
        entity.state = TankWarmer.ON
        q = queue.Queue()
        entity.set_rvc_send_queue(q)
        entity.process_mqtt_msg(entity.command_topic, 'off')
        self.assertFalse(q.empty())
        msg = q.get_nowait()
        self.assertEqual(msg['dgn'], '1FFBC')

    def test_process_mqtt_msg_no_op_already_on(self):
        entity, mock = _make_warmer()
        entity.state = TankWarmer.ON
        q = queue.Queue()
        entity.set_rvc_send_queue(q)
        entity.process_mqtt_msg(entity.command_topic, 'on')
        self.assertTrue(q.empty())

    def test_process_mqtt_msg_no_op_already_off(self):
        entity, mock = _make_warmer()
        entity.state = TankWarmer.OFF
        q = queue.Queue()
        entity.set_rvc_send_queue(q)
        entity.process_mqtt_msg(entity.command_topic, 'off')
        self.assertTrue(q.empty())

    def test_process_mqtt_msg_invalid_payload(self):
        entity, mock = _make_warmer()
        q = queue.Queue()
        entity.set_rvc_send_queue(q)
        entity.process_mqtt_msg(entity.command_topic, 'invalid')
        self.assertTrue(q.empty())

    # --- RVC frame encoding ---

    def test_rvc_off_frame(self):
        entity, mock = _make_warmer()
        q = queue.Queue()
        entity.set_rvc_send_queue(q)
        entity._rvc_off()
        msg = q.get_nowait()
        self.assertEqual(msg['dgn'], '1FFBC')
        self.assertEqual(msg['data'][0], 1)  # instance

    def test_rvc_on_frame(self):
        entity, mock = _make_warmer()
        q = queue.Queue()
        entity.set_rvc_send_queue(q)
        entity._rvc_on()
        msg = q.get_nowait()
        self.assertEqual(msg['dgn'], '1FFBC')
        self.assertEqual(msg['data'][0], 1)  # instance

    # --- initialize ---

    def test_initialize_publishes_ha_config_and_state(self):
        entity, mock = _make_warmer()
        q = queue.Queue()
        entity.set_rvc_send_queue(q)
        entity.initialize()
        publish_calls = mock.client.publish.call_args_list
        self.assertGreaterEqual(len(publish_calls), 2)
        # DGN request queued
        self.assertFalse(q.empty())
        dgn_msg = q.get_nowait()
        self.assertEqual(dgn_msg['dgn'], '0EAFF')


if __name__ == '__main__':
    unittest.main()
