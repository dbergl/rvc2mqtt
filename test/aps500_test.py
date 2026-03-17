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
from rvc2mqtt.entity.aps500 import DcSystemSensor_DC_SOURCE_STATUS_1 as Aps500

def _make_mock():
    mock = MagicMock()
    mock.make_device_topic_string.return_value = 'test/topic'
    mock.TOPIC_BASE = 'rvc2mqtt'
    mock.client_id = 'bridge'
    mock.get_bridge_ha_name.return_value = 'bridge'
    mock.bridge_state_topic = 'rvc2mqtt/bridge/state'
    mock.make_ha_auto_discovery_config_topic.return_value = 'homeassistant/device/test/config'
    return mock


_APS_DATA = {'instance': 1, 'instance_name': "test aps", 'source_id': '80',
             'command_topic': 'aps500/set', 'status_topic': 'aps500/status'}


class Test_Aps500(unittest.TestCase):

    def _make_aps(self):
        mock = MagicMock()
        mock.mqtt_support.make_device_topic_string.return_value = 'topic_string'
        return Aps500(
            {'instance': 1, 'instance_name': "test aps", 'source_id': '80',
             'command_topic': 'aps500/set/', 'status_topic': 'aps500/status/'},
            mock
        )

    def test_basic(self):
        l = self._make_aps()
        self.assertTrue(type(l), Aps500)

    def test_publish_ha_discovery_config(self):
        mock = _make_mock()
        entity = Aps500(_APS_DATA, mock)
        entity.publish_ha_discovery_config()
        self.assertTrue(mock.client.publish.called)
        for call in mock.client.publish.call_args_list:
            _, kwargs = call
            self.assertFalse(kwargs.get('retain', False),
                             f"Discovery config published with retain=True: {call}")

    def _make_data_packets(self, product_str, count):
        """Build DATA_PACKET messages matching the rvc.py integer encoding for a product string."""
        product_bytes = product_str.encode('ascii')
        padded = product_bytes.ljust(count * 7, b'\x00')
        packets = []
        for i in range(count):
            chunk = padded[i*7:(i+1)*7]
            # rvc.py _get_bytes reverses bytes then int() converts big-endian hex string,
            # which is equivalent to int.from_bytes(chunk, 'little')
            data_int = int.from_bytes(chunk, 'little')
            packets.append({
                'name': 'DATA_PACKET',
                'source_id': '80',
                'packet_number': i + 1,
                'data': data_int,
            })
        return packets

    def test_initial_packet(self):
        l = self._make_aps()
        msg = {
            'name': 'INITIAL_PACKET',
            'source_id': '80',
            'packet_count': 3,
            'message_length': 17,
        }
        # Pre-populate to verify it gets cleared
        l._mp_packets = {1: b'stale'}
        result = l.process_rvc_msg(msg)
        self.assertTrue(result)
        self.assertEqual(l._mp_expected_count, 3)
        self.assertEqual(l._mp_message_length, 17)
        self.assertEqual(l._mp_packets, {})

    def test_initial_packet_zero_count(self):
        l = self._make_aps()
        msg = {'name': 'INITIAL_PACKET', 'source_id': '80', 'packet_count': 0, 'message_length': 10}
        l._mp_expected_count = 5  # should remain unchanged
        result = l.process_rvc_msg(msg)
        self.assertTrue(result)
        self.assertEqual(l._mp_expected_count, 5)  # not overwritten

    def test_data_packet_assembles_product_id(self):
        l = self._make_aps()
        product_str = "APS500 Wakespeed"  # 16 chars, 3 packets of 7 bytes

        l.process_rvc_msg({
            'name': 'INITIAL_PACKET', 'source_id': '80',
            'packet_count': 3, 'message_length': len(product_str),
        })
        for pkt in self._make_data_packets(product_str, 3):
            l.process_rvc_msg(pkt)

        l.mqtt_support.client.publish.assert_called_with(
            'aps500/status//product_id', product_str, retain=True)
        # State should be reset after assembly
        self.assertEqual(l._mp_expected_count, 0)
        self.assertEqual(l._mp_packets, {})

    def test_data_packet_before_initial_packet(self):
        l = self._make_aps()
        pkt = {'name': 'DATA_PACKET', 'source_id': '80', 'packet_number': 1, 'data': 0}
        result = l.process_rvc_msg(pkt)
        self.assertTrue(result)
        self.assertEqual(l._mp_packets, {})
        l.mqtt_support.client.publish.assert_not_called()

    def test_data_packet_duplicate_ignored(self):
        l = self._make_aps()
        product_str = "Hello!!"  # exactly 7 bytes, 1 packet

        l.process_rvc_msg({
            'name': 'INITIAL_PACKET', 'source_id': '80',
            'packet_count': 1, 'message_length': 7,
        })
        pkts = self._make_data_packets(product_str, 1)
        l.process_rvc_msg(pkts[0])   # first arrival — triggers assembly
        l.process_rvc_msg(pkts[0])   # duplicate — should be discarded

        # publish called exactly once
        self.assertEqual(l.mqtt_support.client.publish.call_count, 1)

    def test_data_packet_out_of_order(self):
        l = self._make_aps()
        product_str = "APS500 Wakespeed"

        l.process_rvc_msg({
            'name': 'INITIAL_PACKET', 'source_id': '80',
            'packet_count': 3, 'message_length': len(product_str),
        })
        pkts = self._make_data_packets(product_str, 3)
        # Send out of order: 3, 1, 2
        for pkt in [pkts[2], pkts[0], pkts[1]]:
            l.process_rvc_msg(pkt)

        l.mqtt_support.client.publish.assert_called_with(
            'aps500/status//product_id', product_str, retain=True)

    def test_second_sequence_same_value_not_republished(self):
        l = self._make_aps()
        product_str = "APS500 Wakespeed"

        for _ in range(2):
            l.process_rvc_msg({
                'name': 'INITIAL_PACKET', 'source_id': '80',
                'packet_count': 3, 'message_length': len(product_str),
            })
            for pkt in self._make_data_packets(product_str, 3):
                l.process_rvc_msg(pkt)

        # Same value received twice — should only publish once
        self.assertEqual(l.mqtt_support.client.publish.call_count, 1)

    def test_changed_value_republished(self):
        l = self._make_aps()

        for product_str in ["APS500 v1.0", "APS500 v2.0"]:
            l.process_rvc_msg({
                'name': 'INITIAL_PACKET', 'source_id': '80',
                'packet_count': 2, 'message_length': len(product_str),
            })
            for pkt in self._make_data_packets(product_str, 2):
                l.process_rvc_msg(pkt)

        self.assertEqual(l.mqtt_support.client.publish.call_count, 2)
        l.mqtt_support.client.publish.assert_called_with(
            'aps500/status//product_id', 'APS500 v2.0', retain=True)

    def test_data_packet_duplicate_mid_sequence_ignored(self):
        # count=2: packet 1 sent twice before packet 2 arrives — hits duplicate branch
        l = self._make_aps()
        l.process_rvc_msg({
            'name': 'INITIAL_PACKET', 'source_id': '80',
            'packet_count': 2, 'message_length': 7,
        })
        pkt1 = {'name': 'DATA_PACKET', 'source_id': '80', 'packet_number': 1, 'data': 0}
        l.process_rvc_msg(pkt1)
        l.process_rvc_msg(pkt1)  # true duplicate mid-sequence
        self.assertEqual(len(l._mp_packets), 1)  # still only one unique packet
        l.mqtt_support.client.publish.assert_not_called()

    def test_data_packet_invalid_bytes_logs_error(self):
        # non-ASCII bytes trigger the decode exception path
        l = self._make_aps()
        l.process_rvc_msg({
            'name': 'INITIAL_PACKET', 'source_id': '80',
            'packet_count': 1, 'message_length': 7,
        })
        invalid_data = int.from_bytes(b'\xff\xff\xff\xff\xff\xff\xff', 'little')
        l.process_rvc_msg({'name': 'DATA_PACKET', 'source_id': '80',
                           'packet_number': 1, 'data': invalid_data})
        # state reset in finally block
        self.assertEqual(l._mp_expected_count, 0)
        self.assertEqual(l._mp_packets, {})
        l.mqtt_support.client.publish.assert_not_called()


class Test_APS500_ChargerEqualizationStatus(unittest.TestCase):

    def _make_aps(self):
        mock = MagicMock()
        mock.mqtt_support.make_device_topic_string.return_value = 'topic_string'
        return Aps500(
            {'instance': 1, 'instance_name': "test aps", 'source_id': '80',
             'command_topic': 'aps500/set/', 'status_topic': 'aps500/status/'},
            mock
        )

    def _make_msg(self, time_remaining=10, pre_charging_status=0,
                  pre_charging_status_definition="pre-charging not in process",
                  source_id='80'):
        return {
            'name': 'CHARGER_EQUALIZATION_STATUS',
            'source_id': source_id,
            'instance': 1,
            'time_remaining': time_remaining,
            'pre-charging_status': pre_charging_status,
            'pre-charging_status_definition': pre_charging_status_definition,
        }

    def test_returns_true(self):
        l = self._make_aps()
        result = l.process_rvc_msg(self._make_msg())
        self.assertTrue(result)

    def test_wrong_source_id_not_processed(self):
        l = self._make_aps()
        result = l.process_rvc_msg(self._make_msg(source_id='FF'))
        self.assertFalse(result)

    def test_publishes_time_remaining_on_change(self):
        l = self._make_aps()
        l.process_rvc_msg(self._make_msg(time_remaining=42))
        l.mqtt_support.client.publish.assert_any_call(
            'aps500/status//equalization_time_remaining', 42, retain=True)

    def test_publishes_pre_charging_status_definition_on_change(self):
        l = self._make_aps()
        l.process_rvc_msg(self._make_msg(
            pre_charging_status=1,
            pre_charging_status_definition="charging batteries to prepare for equalization"))
        l.mqtt_support.client.publish.assert_any_call(
            'aps500/status//equalization_pre_charging_status',
            "Charging Batteries To Prepare For Equalization",
            retain=True)

    def test_no_publish_when_unchanged(self):
        l = self._make_aps()
        msg = self._make_msg(time_remaining=10, pre_charging_status=0)
        l.process_rvc_msg(msg)
        first_call_count = l.mqtt_support.client.publish.call_count
        l.process_rvc_msg(msg)
        self.assertEqual(l.mqtt_support.client.publish.call_count, first_call_count)

    def test_fields_tracked_independently(self):
        l = self._make_aps()
        # Establish baseline for both fields
        l.process_rvc_msg(self._make_msg(time_remaining=10, pre_charging_status=0))
        call_count_after_first = l.mqtt_support.client.publish.call_count

        # Only time_remaining changes — only that topic should be published
        l.process_rvc_msg(self._make_msg(time_remaining=99, pre_charging_status=0))
        self.assertEqual(l.mqtt_support.client.publish.call_count, call_count_after_first + 1)
        l.mqtt_support.client.publish.assert_called_with(
            'aps500/status//equalization_time_remaining', 99, retain=True)

        # Only pre-charging_status changes — only that topic should be published
        l.process_rvc_msg(self._make_msg(
            time_remaining=99, pre_charging_status=1,
            pre_charging_status_definition="charging batteries to prepare for equalization"))
        self.assertEqual(l.mqtt_support.client.publish.call_count, call_count_after_first + 2)
        l.mqtt_support.client.publish.assert_called_with(
            'aps500/status//equalization_pre_charging_status',
            "Charging Batteries To Prepare For Equalization",
            retain=True)


if __name__ == '__main__':
    unittest.main()
