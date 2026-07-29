"""
Unit tests for the G12 Tank Warmer entity class

The tank heater shares its implementation with the dimmer switch and is registered
under `type: tank_heater`.  These tests double as the backwards-compatibility guard
for that alias - the HA identity of an existing tank heater must not change.

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

import json
import queue
import unittest
from unittest.mock import MagicMock
import context  # add rvc2mqtt package to the python path using local reference
from rvc2mqtt.entity.dimmer_switch import TankHeater_DC_DIMMER_STATUS_3 as G12TankWarmer


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
    mock.make_ha_auto_discovery_config_topic.return_value = 'homeassistant/switch/test/config'
    return mock


def _make_warmer(status_topic='rvc/state/tank', command_topic='rvc/set/tank'):
    mock = _make_mock()
    data = {'instance': 1, 'instance_name': "test G12 Tank Warmer",
            'status_topic': status_topic, 'command_topic': command_topic}
    entity = G12TankWarmer(data, mock)
    return entity, mock


class Test_G12TankWarmer(unittest.TestCase):

    def test_basic(self):
        mock = _make_mock()
        entity = G12TankWarmer({'instance': 1, 'instance_name': "test G12 Tank Warmer"}, mock)
        self.assertTrue(type(entity), G12TankWarmer)

    def test_publish_ha_discovery_config(self):
        mock = _make_mock()
        entity = G12TankWarmer({'instance': 1, 'instance_name': "test G12 Tank Warmer"}, mock)
        entity.publish_ha_discovery_config()
        self.assertTrue(mock.client.publish.called)
        for call in mock.client.publish.call_args_list:
            _, kwargs = call
            self.assertFalse(kwargs.get('retain', False),
                             f"Discovery config published with retain=True: {call}")

    # --- backwards compatibility of the tank_heater alias ---
    # The device identity below is baked into existing Home Assistant installs.
    # Changing any of it orphans the entities and loses their statistics history.

    def test_id_prefix_unchanged(self):
        entity, _ = _make_warmer()
        self.assertEqual(entity.id, 'tank_warmer-1FEDB-i1')
        self.assertEqual(entity.unique_device_id,
                         'rvc2mqtt_bridge_tank_warmer-1FEDB-i1')

    def test_not_dimmable_by_default(self):
        entity, _ = _make_warmer()
        self.assertFalse(entity.dimmable)

    def test_dimmable_can_be_opted_into(self):
        mock = _make_mock()
        entity = G12TankWarmer({'instance': 1, 'instance_name': "test G12 Tank Warmer",
                                'status_topic': 'rvc/state/tank',
                                'command_topic': 'rvc/set/tank',
                                'dimmable': True}, mock)
        self.assertTrue(entity.dimmable)

    def test_no_brightness_topics_registered(self):
        entity, mock = _make_warmer()
        registered = [call[0][0] for call in mock.register.call_args_list]
        self.assertIn('rvc/set/tank', registered)
        for topic in registered:
            self.assertFalse(topic.endswith('/brightness'),
                             f"tank heater registered a brightness topic: {topic}")

    def test_ha_component_is_switch(self):
        entity, mock = _make_warmer()
        entity.publish_ha_discovery_config()
        mock.make_ha_auto_discovery_config_topic.assert_any_call(
            entity.unique_device_id, 'switch')

    def test_ha_discovery_config_contents(self):
        entity, mock = _make_warmer()
        entity.publish_ha_discovery_config()
        configs = [json.loads(c[0][1]) for c in mock.client.publish.call_args_list]
        main = next(c for c in configs if c.get('unique_id') == entity.unique_device_id)
        self.assertEqual(main['dev']['mdl'], 'RV-C Tank Warmer from DC_DIMMER_STATUS_3')
        self.assertEqual(main['state_topic'], 'rvc/state/tank')
        self.assertEqual(main['command_topic'], 'rvc/set/tank')
        self.assertEqual(main['payload_on'], G12TankWarmer.LIGHT_ON)
        self.assertEqual(main['payload_off'], G12TankWarmer.LIGHT_OFF)
        self.assertNotIn('brightness_state_topic', main)
        self.assertNotIn('brightness_command_topic', main)

    # --- process_rvc_msg ---

    def test_process_rvc_msg_on(self):
        mock = _make_mock()
        entity = G12TankWarmer({'instance': 1, 'instance_name': "test G12 Tank Warmer"}, mock)
        msg = {'name': 'DC_DIMMER_STATUS_3', 'instance': 1, 'operating_status_brightness': 100.0}
        result = entity.process_rvc_msg(msg)
        self.assertTrue(result)
        self.assertEqual(entity.state, G12TankWarmer.LIGHT_ON)

    def test_process_rvc_msg_off(self):
        mock = _make_mock()
        entity = G12TankWarmer({'instance': 1, 'instance_name': "test G12 Tank Warmer"}, mock)
        msg = {'name': 'DC_DIMMER_STATUS_3', 'instance': 1, 'operating_status_brightness': 0.0}
        result = entity.process_rvc_msg(msg)
        self.assertTrue(result)
        self.assertEqual(entity.state, G12TankWarmer.LIGHT_OFF)

    def test_process_rvc_msg_no_publish_if_state_unchanged(self):
        entity, mock = _make_warmer()
        entity.state = G12TankWarmer.LIGHT_ON
        mock.client.publish.reset_mock()
        msg = {'name': 'DC_DIMMER_STATUS_3', 'instance': 1, 'operating_status_brightness': 100.0}
        entity.process_rvc_msg(msg)
        # state didn't change — no publish
        mock.client.publish.assert_not_called()

    def test_process_rvc_msg_publishes_on_state_change(self):
        entity, mock = _make_warmer()
        entity.state = G12TankWarmer.LIGHT_OFF
        mock.client.publish.reset_mock()
        msg = {'name': 'DC_DIMMER_STATUS_3', 'instance': 1, 'operating_status_brightness': 50.0}
        entity.process_rvc_msg(msg)
        # non-dimmable, so the state publish is the only one
        mock.client.publish.assert_called_once_with(entity.status_topic, G12TankWarmer.LIGHT_ON, retain=True)

    def test_process_rvc_msg_command_eaten(self):
        mock = _make_mock()
        entity = G12TankWarmer({'instance': 1, 'instance_name': "test G12 Tank Warmer"}, mock)
        msg = {'name': 'DC_DIMMER_COMMAND_2', 'instance': 1}
        result = entity.process_rvc_msg(msg)
        self.assertTrue(result)

    def test_process_rvc_msg_no_match(self):
        mock = _make_mock()
        entity = G12TankWarmer({'instance': 1, 'instance_name': "test G12 Tank Warmer"}, mock)
        msg = {'name': 'SOME_OTHER_MSG', 'instance': 1}
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

    def test_process_mqtt_msg_turn_on_sends_toggle(self):
        entity, mock = _make_warmer()
        entity.state = G12TankWarmer.LIGHT_OFF
        q = queue.Queue()
        entity.set_rvc_send_queue(q)
        entity.process_mqtt_msg(entity.command_topic, 'on')
        self.assertFalse(q.empty())
        msg = q.get_nowait()
        self.assertEqual(msg['dgn'], '1FEDB')
        self.assertEqual(msg['data'][3], 5)  # command = toggle

    def test_process_mqtt_msg_turn_off_sends_toggle(self):
        entity, mock = _make_warmer()
        entity.state = G12TankWarmer.LIGHT_ON
        q = queue.Queue()
        entity.set_rvc_send_queue(q)
        entity.process_mqtt_msg(entity.command_topic, 'off')
        self.assertFalse(q.empty())
        msg = q.get_nowait()
        self.assertEqual(msg['dgn'], '1FEDB')

    def test_process_mqtt_msg_no_op_already_on(self):
        entity, mock = _make_warmer()
        entity.state = G12TankWarmer.LIGHT_ON
        q = queue.Queue()
        entity.set_rvc_send_queue(q)
        entity.process_mqtt_msg(entity.command_topic, 'on')
        self.assertTrue(q.empty())

    def test_process_mqtt_msg_no_op_already_off(self):
        entity, mock = _make_warmer()
        entity.state = G12TankWarmer.LIGHT_OFF
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

    def test_brightness_command_topic_ignored_when_not_dimmable(self):
        entity, mock = _make_warmer()
        q = queue.Queue()
        entity.set_rvc_send_queue(q)
        entity.process_mqtt_msg('rvc/set/tank/brightness', '50')
        self.assertTrue(q.empty())

    # --- RVC frame encoding ---

    def test_rvc_toggle_frame(self):
        entity, mock = _make_warmer()
        q = queue.Queue()
        entity.set_rvc_send_queue(q)
        entity._rvc_light_toggle()
        msg = q.get_nowait()
        self.assertEqual(msg['dgn'], '1FEDB')
        self.assertEqual(msg['data'][0], 1)   # instance
        self.assertEqual(msg['data'][2], 250) # desired_level 0xFA
        self.assertEqual(msg['data'][3], 5)   # command = toggle

    # --- initialize ---

    def test_initialize_publishes_ha_config_and_requests_dgn(self):
        entity, mock = _make_warmer()
        q = queue.Queue()
        entity.set_rvc_send_queue(q)
        entity.initialize()
        # HA discovery went out
        published_topics = [call[0][0] for call in mock.client.publish.call_args_list]
        self.assertIn('homeassistant/switch/test/config', published_topics)
        # DGN request queued
        self.assertFalse(q.empty())
        dgn_msg = q.get_nowait()
        self.assertEqual(dgn_msg['dgn'], '0EAFF')

    def test_initialize_preseeds_state_from_retained_value(self):
        """The retained state topic is read back rather than overwritten with
        "unknown", so a bridge restart doesn't clobber a known-good value."""
        entity, mock = _make_warmer()
        entity.set_rvc_send_queue(queue.Queue())
        entity.initialize()
        mock.register.assert_any_call(entity.status_topic, entity._on_state_topic,
                                      retain_ok=True)
        published_topics = [call[0][0] for call in mock.client.publish.call_args_list]
        self.assertNotIn(entity.status_topic, published_topics)

        entity._on_state_topic(entity.status_topic, G12TankWarmer.LIGHT_ON)
        self.assertEqual(entity.state, G12TankWarmer.LIGHT_ON)


class Test_G12TankWarmer_ComponentDriverStatus(unittest.TestCase):
    """DC_COMPONENT_DRIVER_STATUS_1 / _4 report instance as 0xFF and identify the
    channel with driver_index, which tracks the dimmer instance.  Inherited from
    the dimmer implementation - these cases guard the alias."""

    def _make_heater(self, **extra):
        mock = _make_mock()
        data = {'instance': 1, 'instance_name': "test G12 Tank Warmer",
                'status_topic': 'rvc/state/tank', 'command_topic': 'rvc/set/tank'}
        data.update(extra)
        return G12TankWarmer(data, mock), mock

    def _make_driver_1_msg(self, driver_index=1, current=8.25):
        return {'name': 'DC_COMPONENT_DRIVER_STATUS_1', 'instance': 255,
                'driver_index': driver_index, 'voltage': 13.2, 'current': current,
                'output_status': 1, 'output_status_definition': 'on'}

    def _make_driver_4_msg(self, driver_index=1, cycle_count=17, on_time=240):
        return {'name': 'DC_COMPONENT_DRIVER_STATUS_4', 'instance': 255,
                'driver_index': driver_index, 'on_cycle_count': cycle_count,
                'channel_on_time': on_time}

    def test_status_1_publishes_current(self):
        entity, mock = self._make_heater()
        self.assertTrue(entity.process_rvc_msg(self._make_driver_1_msg(current=8.25)))
        published = {c[0][0]: c[0][1] for c in mock.client.publish.call_args_list}
        self.assertEqual(published.get('rvc/state/tank/current'), 8.25)

    def test_status_4_publishes_cycle_count_and_on_time(self):
        entity, mock = self._make_heater()
        self.assertTrue(entity.process_rvc_msg(
            self._make_driver_4_msg(cycle_count=17, on_time=240)))
        published = {c[0][0]: c[0][1] for c in mock.client.publish.call_args_list}
        self.assertEqual(published.get('rvc/state/tank/cycle_count'), 17)
        self.assertEqual(published.get('rvc/state/tank/on_time'), 240)

    def test_non_matching_driver_index_ignored(self):
        entity, mock = self._make_heater()
        self.assertFalse(entity.process_rvc_msg(self._make_driver_1_msg(driver_index=7)))
        self.assertFalse(entity.process_rvc_msg(self._make_driver_4_msg(driver_index=7)))
        self.assertFalse(mock.client.publish.called)

    def test_driver_index_override(self):
        """A floorplan driver_index takes precedence over instance."""
        entity, _ = self._make_heater(driver_index=9)
        self.assertFalse(entity.process_rvc_msg(self._make_driver_1_msg(driver_index=1)))
        self.assertTrue(entity.process_rvc_msg(self._make_driver_1_msg(driver_index=9)))

    def test_unchanged_values_publish_once(self):
        entity, mock = self._make_heater()
        for _ in range(3):
            entity.process_rvc_msg(self._make_driver_1_msg(current=8.25))
            entity.process_rvc_msg(self._make_driver_4_msg(cycle_count=17, on_time=240))
        topics = [c[0][0] for c in mock.client.publish.call_args_list]
        self.assertEqual(topics.count('rvc/state/tank/current'), 1)
        self.assertEqual(topics.count('rvc/state/tank/cycle_count'), 1)
        self.assertEqual(topics.count('rvc/state/tank/on_time'), 1)

    def test_unavailable_values_not_published_but_consumed(self):
        """0xFFFF current decodes to 'n/a'; the _4 counters arrive raw."""
        entity, mock = self._make_heater()
        self.assertTrue(entity.process_rvc_msg(self._make_driver_1_msg(current='n/a')))
        self.assertTrue(entity.process_rvc_msg(
            self._make_driver_4_msg(cycle_count=0xFFFF, on_time=0xFFFFFFFF)))
        self.assertFalse(mock.client.publish.called)

    def test_sensor_discovery_configs_published(self):
        entity, mock = self._make_heater()
        entity.publish_ha_discovery_config()
        for sub_type in ('current', 'cycle_count', 'on_time'):
            mock.make_ha_auto_discovery_config_topic.assert_any_call(
                entity.unique_device_id, 'sensor', sub_type)
        for call in mock.client.publish.call_args_list:
            _, kwargs = call
            self.assertFalse(kwargs.get('retain', False),
                             f"Discovery config published with retain=True: {call}")

    def test_sensor_discovery_config_contents(self):
        entity, mock = self._make_heater()
        entity.publish_ha_discovery_config()
        configs = [json.loads(c[0][1]) for c in mock.client.publish.call_args_list]
        by_uid = {c['unique_id']: c for c in configs if 'unique_id' in c}
        current = by_uid[entity.unique_device_id + '_current']
        self.assertEqual(current['state_topic'], 'rvc/state/tank/current')
        self.assertEqual(current['device_class'], 'current')
        self.assertEqual(current['unit_of_measurement'], 'A')
        on_time = by_uid[entity.unique_device_id + '_on_time']
        self.assertEqual(on_time['state_topic'], 'rvc/state/tank/on_time')
        self.assertEqual(on_time['unit_of_measurement'], 'min')
        self.assertEqual(on_time['entity_category'], 'diagnostic')
        # every sensor is grouped under the same HA device as the switch
        self.assertEqual(on_time['dev'], entity.device)


if __name__ == '__main__':
    unittest.main()
