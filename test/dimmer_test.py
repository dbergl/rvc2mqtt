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

import json
import unittest
from unittest.mock import MagicMock
import context  # add rvc2mqtt package to the python path using local reference
from rvc2mqtt.entity.dimmer_switch import DimmerSwitch_DC_DIMMER_STATUS_3 as Dimmer


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
    mock.make_ha_auto_discovery_config_topic.return_value = 'homeassistant/light/test/config'
    return mock


class Test_Dimmer(unittest.TestCase):

    def test_basic(self):
        mock = MagicMock()
        mock.mqtt_support.make_device_topic_string.return_value = 'topic_string'

        l = Dimmer({'instance': 1, 'instance_name': "test light"}, mock)
        self.assertTrue(type(l), Dimmer)

    def test_publish_ha_discovery_config(self):
        mock = _make_mock()
        entity = Dimmer({'instance': 1, 'instance_name': "test dimmer"}, mock)
        entity.publish_ha_discovery_config()
        self.assertTrue(mock.client.publish.called)
        for call in mock.client.publish.call_args_list:
            _, kwargs = call
            self.assertFalse(kwargs.get('retain', False),
                             f"Discovery config published with retain=True: {call}")

    def _make_dimmer(self, dimmable=True):
        mock = _make_mock()
        return Dimmer(
            {'instance': 1, 'instance_name': "test dimmer",
             'status_topic': 'rvc/state/dimmer', 'command_topic': 'rvc/set/dimmer',
             'dimmable': dimmable},
            mock
        )

    def _make_status_msg(self, brightness):
        return {
            'name': 'DC_DIMMER_STATUS_3',
            'instance': 1,
            'messagestate': 'on',
            'operating_status_brightness': brightness,
        }

    def test_brightness_published_on_status_msg(self):
        d = self._make_dimmer()
        d.process_rvc_msg(self._make_status_msg(brightness=50.0))
        publish_calls = {c[0][0]: c[0][1]
                         for c in d.mqtt_support.client.publish.call_args_list}
        self.assertEqual(publish_calls.get('rvc/state/dimmer/brightness'), 50)

    def test_dimmable_defaults_true(self):
        """A dimmer_switch entry with no `dimmable` key is dimmable."""
        mock = _make_mock()
        d = Dimmer({'instance': 1, 'instance_name': "test dimmer",
                    'status_topic': 'rvc/state/dimmer',
                    'command_topic': 'rvc/set/dimmer'}, mock)
        self.assertTrue(d.dimmable)
        self.assertEqual(d.id, 'dimmer-1FEDB-i1')
        mock.register.assert_any_call('rvc/set/dimmer/brightness', d.process_mqtt_msg)

    def test_dimmable_false_uses_switch_ha_component(self):
        mock = _make_mock()
        mock.make_ha_auto_discovery_config_topic.return_value = 'homeassistant/switch/test/config'
        d = Dimmer({'instance': 1, 'instance_name': "relay",
                    'status_topic': 'rvc/state/relay', 'command_topic': 'rvc/set/relay',
                    'dimmable': False}, mock)
        d.publish_ha_discovery_config()
        mock.make_ha_auto_discovery_config_topic.assert_any_call(
            d.unique_device_id, 'switch')

    def test_rvc_set_brightness_frame_encoding(self):
        import queue as qmod
        d = self._make_dimmer()
        q = qmod.Queue()
        d.set_rvc_send_queue(q)
        d._rvc_set_brightness(50)
        self.assertFalse(q.empty())
        msg = q.get_nowait()
        self.assertEqual(msg['dgn'], '1FEDB')
        data = msg['data']
        self.assertEqual(data[0], 1)     # instance
        self.assertEqual(data[1], 0xFF)  # group all
        self.assertEqual(data[2], 100)   # 50% × 2 = 100 wire format
        self.assertEqual(data[3], 0)     # command = set brightness

    def test_brightness_command_valid_payload(self):
        import queue as qmod
        d = self._make_dimmer()
        q = qmod.Queue()
        d.set_rvc_send_queue(q)
        d.process_mqtt_msg('rvc/set/dimmer/brightness', '75')
        self.assertFalse(q.empty())
        msg = q.get_nowait()
        self.assertEqual(msg['data'][2], 150)  # 75% × 2

    def test_brightness_command_clamped_above_100(self):
        import queue as qmod
        d = self._make_dimmer()
        q = qmod.Queue()
        d.set_rvc_send_queue(q)
        d.process_mqtt_msg('rvc/set/dimmer/brightness', '150')
        msg = q.get_nowait()
        self.assertEqual(msg['data'][2], 200)  # clamped to 100% × 2

    def test_brightness_command_clamped_below_0(self):
        import queue as qmod
        d = self._make_dimmer()
        d.brightness = 50  # set away from 0 so the clamped value triggers a send
        q = qmod.Queue()
        d.set_rvc_send_queue(q)
        d.process_mqtt_msg('rvc/set/dimmer/brightness', '-10')
        msg = q.get_nowait()
        self.assertEqual(msg['data'][2], 0)  # clamped to 0

    def test_brightness_command_invalid_payload_does_not_crash(self):
        d = self._make_dimmer()
        try:
            d.process_mqtt_msg('rvc/set/dimmer/brightness', 'not_a_number')
        except (ValueError, TypeError) as e:
            self.fail(f"process_mqtt_msg raised {type(e).__name__} on invalid brightness: {e}")

    def test_brightness_na_does_not_crash(self):
        """operating_status_brightness of 'n/a' (raw byte 0xFF) must not raise."""
        d = self._make_dimmer()
        try:
            d.process_rvc_msg(self._make_status_msg(brightness='n/a'))
        except (ValueError, TypeError) as e:
            self.fail(f"process_rvc_msg raised {type(e).__name__} on n/a brightness: {e}")


class Test_Dimmer_ComponentDriverStatus(unittest.TestCase):
    """DC_COMPONENT_DRIVER_STATUS_1 / _4 report instance as 0xFF and identify the
    channel with driver_index, which tracks the dimmer instance."""

    def _make_dimmer(self, **extra):
        data = {'instance': 1, 'instance_name': "test dimmer",
                'status_topic': 'rvc/state/dimmer', 'command_topic': 'rvc/set/dimmer'}
        data.update(extra)
        return Dimmer(data, _make_mock())

    def _make_driver_1_msg(self, driver_index=1, current=12.5):
        return {'name': 'DC_COMPONENT_DRIVER_STATUS_1', 'instance': 255,
                'driver_index': driver_index, 'voltage': 13.2, 'current': current,
                'output_status': 1, 'output_status_definition': 'on'}

    def _make_driver_4_msg(self, driver_index=1, cycle_count=42, on_time=3600):
        return {'name': 'DC_COMPONENT_DRIVER_STATUS_4', 'instance': 255,
                'driver_index': driver_index, 'on_cycle_count': cycle_count,
                'channel_on_time': on_time}

    def _published(self, d):
        return {c[0][0]: c[0][1]
                for c in d.mqtt_support.client.publish.call_args_list}

    def test_status_1_publishes_current(self):
        d = self._make_dimmer()
        self.assertTrue(d.process_rvc_msg(self._make_driver_1_msg(current=12.5)))
        self.assertEqual(self._published(d).get('rvc/state/dimmer/current'), 12.5)

    def test_status_4_publishes_cycle_count_and_on_time(self):
        d = self._make_dimmer()
        self.assertTrue(d.process_rvc_msg(
            self._make_driver_4_msg(cycle_count=42, on_time=3600)))
        published = self._published(d)
        self.assertEqual(published.get('rvc/state/dimmer/cycle_count'), 42)
        self.assertEqual(published.get('rvc/state/dimmer/on_time'), 3600)

    def test_non_matching_driver_index_ignored(self):
        d = self._make_dimmer()
        self.assertFalse(d.process_rvc_msg(self._make_driver_1_msg(driver_index=7)))
        self.assertFalse(d.process_rvc_msg(self._make_driver_4_msg(driver_index=7)))
        self.assertFalse(d.mqtt_support.client.publish.called)

    def test_instance_alone_does_not_match(self):
        """instance is 0xFF on these DGNs - it must not be what identifies the channel."""
        d = self._make_dimmer(instance=255)
        self.assertFalse(d.process_rvc_msg(self._make_driver_1_msg(driver_index=1)))

    def test_driver_index_override(self):
        """A floorplan driver_index takes precedence over instance."""
        d = self._make_dimmer(driver_index=9)
        self.assertFalse(d.process_rvc_msg(self._make_driver_1_msg(driver_index=1)))
        self.assertTrue(d.process_rvc_msg(self._make_driver_1_msg(driver_index=9)))

    def test_unchanged_values_publish_once(self):
        d = self._make_dimmer()
        for _ in range(3):
            d.process_rvc_msg(self._make_driver_1_msg(current=12.5))
            d.process_rvc_msg(self._make_driver_4_msg(cycle_count=42, on_time=3600))
        topics = [c[0][0] for c in d.mqtt_support.client.publish.call_args_list]
        self.assertEqual(topics.count('rvc/state/dimmer/current'), 1)
        self.assertEqual(topics.count('rvc/state/dimmer/cycle_count'), 1)
        self.assertEqual(topics.count('rvc/state/dimmer/on_time'), 1)

    def test_changed_values_republish(self):
        d = self._make_dimmer()
        d.process_rvc_msg(self._make_driver_1_msg(current=12.5))
        d.process_rvc_msg(self._make_driver_1_msg(current=13.0))
        currents = [c[0][1] for c in d.mqtt_support.client.publish.call_args_list
                    if c[0][0] == 'rvc/state/dimmer/current']
        self.assertEqual(currents, [12.5, 13.0])

    def test_unavailable_values_not_published_but_consumed(self):
        """0xFFFF current decodes to 'n/a'; the _4 counters arrive raw."""
        d = self._make_dimmer()
        self.assertTrue(d.process_rvc_msg(self._make_driver_1_msg(current='n/a')))
        self.assertTrue(d.process_rvc_msg(
            self._make_driver_4_msg(cycle_count=0xFFFF, on_time=0xFFFFFFFF)))
        self.assertFalse(d.mqtt_support.client.publish.called)

    def test_sensor_discovery_configs_published(self):
        d = self._make_dimmer()
        d.publish_ha_discovery_config()
        for sub_type in ('current', 'cycle_count', 'on_time'):
            d.mqtt_support.make_ha_auto_discovery_config_topic.assert_any_call(
                d.unique_device_id, 'sensor', sub_type)
        for call in d.mqtt_support.client.publish.call_args_list:
            _, kwargs = call
            self.assertFalse(kwargs.get('retain', False),
                             f"Discovery config published with retain=True: {call}")

    def test_sensor_discovery_config_contents(self):
        d = self._make_dimmer()
        d.publish_ha_discovery_config()
        configs = [json.loads(c[0][1])
                   for c in d.mqtt_support.client.publish.call_args_list]
        by_uid = {c['unique_id']: c for c in configs if 'unique_id' in c}
        current = by_uid[d.unique_device_id + '_current']
        self.assertEqual(current['state_topic'], 'rvc/state/dimmer/current')
        self.assertEqual(current['device_class'], 'current')
        self.assertEqual(current['unit_of_measurement'], 'A')
        on_time = by_uid[d.unique_device_id + '_on_time']
        self.assertEqual(on_time['state_topic'], 'rvc/state/dimmer/on_time')
        self.assertEqual(on_time['entity_category'], 'diagnostic')
        self.assertEqual(on_time['unit_of_measurement'], 'min')
        # every sensor is grouped under the same HA device as the light
        self.assertEqual(on_time['dev'], d.device)


if __name__ == '__main__':
    unittest.main()
