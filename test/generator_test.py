"""
Unit tests for the generator entity class

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

import queue
import json
import unittest
from unittest.mock import MagicMock
import context  # add rvc2mqtt package to the python path using local reference
from rvc2mqtt.entity.generator import Generator_GENERATOR as Generator


def _make_mock():
    mock = MagicMock()
    mock.make_device_topic_string.return_value = 'test/topic'
    mock.TOPIC_BASE = 'rvc2mqtt'
    mock.client_id = 'bridge'
    mock.get_bridge_ha_name.return_value = 'bridge'
    mock.bridge_state_topic = 'rvc2mqtt/bridge/state'
    mock.make_ha_auto_discovery_config_topic.return_value = 'homeassistant/switch/test/config'
    return mock


def _make_generator(instance_name='start_trigger'):
    mock = _make_mock()
    data = {
        'instance': 19,
        'instance_name': instance_name,
        'status_topic': 'rvc/state/generator',
        'command_topic': 'rvc/set/generator',
    }
    entity = Generator(data, mock)
    return entity, mock


class Test_Generator(unittest.TestCase):

    def test_basic_start_trigger(self):
        entity, mock = _make_generator('start_trigger')
        self.assertTrue(type(entity), Generator)

    def test_basic_stop_trigger(self):
        entity, mock = _make_generator('stop_trigger')
        self.assertTrue(type(entity), Generator)

    def test_basic_no_topics(self):
        mock = _make_mock()
        data = {'instance': 19, 'instance_name': 'start_trigger'}
        entity = Generator(data, mock)
        self.assertTrue(type(entity), Generator)

    # --- process_rvc_msg: GENERATOR_STATUS_1 ---

    def test_process_rvc_msg_generator_status(self):
        entity, mock = _make_generator()
        msg = {
            'name': 'GENERATOR_STATUS_1',
            'status': 1,
            'status_definition': 'running',
            'engine_run_time': 120,
        }
        result = entity.process_rvc_msg(msg)
        self.assertTrue(result)
        self.assertEqual(entity.status, 1)

    def test_process_rvc_msg_generator_status_publishes_json(self):
        entity, mock = _make_generator()
        msg = {
            'name': 'GENERATOR_STATUS_1',
            'status': 2,
            'status_definition': 'stopped',
            'engine_run_time': 60,
        }
        entity.process_rvc_msg(msg)
        calls = {call[0][0]: call[0][1] for call in mock.client.publish.call_args_list}
        status_payload = calls.get('rvc/state/generator/status')
        self.assertIsNotNone(status_payload)
        parsed = json.loads(status_payload)
        self.assertIn('status', parsed)

    def test_process_rvc_msg_generator_status_no_publish_if_unchanged(self):
        entity, mock = _make_generator()
        entity.status = 1
        entity.run_time = 60
        mock.client.publish.reset_mock()
        msg = {
            'name': 'GENERATOR_STATUS_1',
            'status': 1,
            'status_definition': 'running',
            'engine_run_time': 60,
        }
        entity.process_rvc_msg(msg)
        # status unchanged, run_time unchanged — no publish
        mock.client.publish.assert_not_called()

    def test_process_rvc_msg_hours_published(self):
        entity, mock = _make_generator()
        msg = {
            'name': 'GENERATOR_STATUS_1',
            'status': 1,
            'status_definition': 'running',
            'engine_run_time': 120,  # 120 minutes = 2.00 hours
        }
        entity.process_rvc_msg(msg)
        calls = {call[0][0]: call[0][1] for call in mock.client.publish.call_args_list}
        hours_payload = calls.get('rvc/state/generator/hours')
        self.assertIsNotNone(hours_payload)
        self.assertAlmostEqual(float(hours_payload), 2.0)

    # --- process_rvc_msg: DC_DIMMER_STATUS_3 ---

    def test_process_rvc_msg_dimmer_status_on(self):
        entity, mock = _make_generator('start_trigger')
        msg = {'name': 'DC_DIMMER_STATUS_3', 'instance': 19, 'operating_status_brightness': 100.0}
        result = entity.process_rvc_msg(msg)
        self.assertTrue(result)
        self.assertEqual(entity.state, 'on')

    def test_process_rvc_msg_dimmer_status_off(self):
        entity, mock = _make_generator('stop_trigger')
        msg = {'name': 'DC_DIMMER_STATUS_3', 'instance': 19, 'operating_status_brightness': 0.0}
        result = entity.process_rvc_msg(msg)
        self.assertTrue(result)
        self.assertEqual(entity.state, 'off')

    def test_process_rvc_msg_dimmer_status_publishes_startstop_topic(self):
        entity, mock = _make_generator('start_trigger')
        mock.client.publish.reset_mock()
        msg = {'name': 'DC_DIMMER_STATUS_3', 'instance': 19, 'operating_status_brightness': 100.0}
        entity.process_rvc_msg(msg)
        calls = {call[0][0]: call[0][1] for call in mock.client.publish.call_args_list}
        self.assertIn(entity.startstop_trigger_topic, calls)

    def test_process_rvc_msg_dimmer_no_publish_if_state_unchanged(self):
        entity, mock = _make_generator()
        entity.state = 'on'
        mock.client.publish.reset_mock()
        msg = {'name': 'DC_DIMMER_STATUS_3', 'instance': 19, 'operating_status_brightness': 100.0}
        entity.process_rvc_msg(msg)
        mock.client.publish.assert_not_called()

    # --- process_rvc_msg: DC_DIMMER_COMMAND_2 ---

    def test_process_rvc_msg_command_eaten(self):
        entity, mock = _make_generator()
        msg = {'name': 'DC_DIMMER_COMMAND_2', 'instance': 19}
        result = entity.process_rvc_msg(msg)
        self.assertTrue(result)

    def test_process_rvc_msg_no_match(self):
        entity, mock = _make_generator()
        msg = {'name': 'SOME_OTHER_MSG', 'instance': 19}
        result = entity.process_rvc_msg(msg)
        self.assertFalse(result)

    # --- process_mqtt_msg ---

    def test_process_mqtt_msg_empty_payload_ignored(self):
        entity, mock = _make_generator()
        q = queue.Queue()
        entity.set_rvc_send_queue(q)
        entity.process_mqtt_msg(entity.command_topic, '')
        self.assertTrue(q.empty())

    def test_process_mqtt_msg_none_payload_ignored(self):
        entity, mock = _make_generator()
        q = queue.Queue()
        entity.set_rvc_send_queue(q)
        entity.process_mqtt_msg(entity.command_topic, None)
        self.assertTrue(q.empty())

    def test_process_mqtt_msg_start_trigger_on(self):
        entity, mock = _make_generator('start_trigger')
        q = queue.Queue()
        entity.set_rvc_send_queue(q)
        entity.process_mqtt_msg(entity.command_topic, 'on')
        self.assertFalse(q.empty())
        msg = q.get_nowait()
        self.assertEqual(msg['dgn'], '1FEDB')
        self.assertEqual(msg['data'][3], 1)  # command = on

    def test_process_mqtt_msg_start_trigger_off(self):
        entity, mock = _make_generator('start_trigger')
        q = queue.Queue()
        entity.set_rvc_send_queue(q)
        entity.process_mqtt_msg(entity.command_topic, 'off')
        self.assertFalse(q.empty())
        msg = q.get_nowait()
        self.assertEqual(msg['dgn'], '1FEDB')
        self.assertEqual(msg['data'][3], 3)  # command = off

    def test_process_mqtt_msg_stop_trigger_on(self):
        entity, mock = _make_generator('stop_trigger')
        q = queue.Queue()
        entity.set_rvc_send_queue(q)
        entity.process_mqtt_msg(entity.command_topic, 'on')
        self.assertFalse(q.empty())
        msg = q.get_nowait()
        self.assertEqual(msg['dgn'], '1FEDB')
        self.assertEqual(msg['data'][3], 1)  # command = on

    def test_process_mqtt_msg_stop_trigger_off(self):
        entity, mock = _make_generator('stop_trigger')
        q = queue.Queue()
        entity.set_rvc_send_queue(q)
        entity.process_mqtt_msg(entity.command_topic, 'off')
        self.assertFalse(q.empty())
        msg = q.get_nowait()
        self.assertEqual(msg['dgn'], '1FEDB')
        self.assertEqual(msg['data'][3], 3)  # command = off

    def test_process_mqtt_msg_invalid_payload(self):
        entity, mock = _make_generator()
        q = queue.Queue()
        entity.set_rvc_send_queue(q)
        entity.process_mqtt_msg(entity.command_topic, 'invalid')
        self.assertTrue(q.empty())

    # --- RVC frame encoding ---

    def test_rvc_start_trigger_on_frame(self):
        entity, mock = _make_generator('start_trigger')
        q = queue.Queue()
        entity.set_rvc_send_queue(q)
        entity._rvc_start_trigger_on()
        msg = q.get_nowait()
        self.assertEqual(msg['dgn'], '1FEDB')
        self.assertEqual(msg['data'][0], 19)  # instance
        self.assertEqual(msg['data'][2], 100) # desired_level

    def test_rvc_start_trigger_off_frame(self):
        entity, mock = _make_generator('start_trigger')
        q = queue.Queue()
        entity.set_rvc_send_queue(q)
        entity._rvc_start_trigger_off()
        msg = q.get_nowait()
        self.assertEqual(msg['dgn'], '1FEDB')
        self.assertEqual(msg['data'][2], 0)   # desired_level = 0 (off)

    def test_rvc_stop_trigger_on_frame(self):
        entity, mock = _make_generator('stop_trigger')
        q = queue.Queue()
        entity.set_rvc_send_queue(q)
        entity._rvc_stop_trigger_on()
        msg = q.get_nowait()
        self.assertEqual(msg['dgn'], '1FEDB')
        self.assertEqual(msg['data'][2], 100)

    def test_rvc_stop_trigger_off_frame(self):
        entity, mock = _make_generator('stop_trigger')
        q = queue.Queue()
        entity.set_rvc_send_queue(q)
        entity._rvc_stop_trigger_off()
        msg = q.get_nowait()
        self.assertEqual(msg['dgn'], '1FEDB')
        self.assertEqual(msg['data'][2], 0)

    # --- initialize ---

    def test_initialize_publishes_status_and_hours(self):
        entity, mock = _make_generator()
        entity.initialize()
        published_topics = [call[0][0] for call in mock.client.publish.call_args_list]
        self.assertIn('rvc/state/generator/status', published_topics)
        self.assertIn('rvc/state/generator/hours', published_topics)


if __name__ == '__main__':
    unittest.main()
