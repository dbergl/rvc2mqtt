"""
Unit tests for the Touchscreen entity class

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
from rvc2mqtt.entity.touchscreen import Touchscreen


class Test_Touchscreen(unittest.TestCase):

    def _make_ts(self, source_id='9F'):
        mock = MagicMock()
        mock.mqtt_support.make_device_topic_string.return_value = 'topic_string'
        return Touchscreen(
            {'instance': 1, 'instance_name': "Touchscreen", 'source_id': source_id,
             'status_topic': 'touchscreen/status'},
            mock
        )

    def _make_data_packets(self, product_str, count, source_id='9F'):
        product_bytes = product_str.encode('ascii')
        padded = product_bytes.ljust(count * 7, b'\x00')
        packets = []
        for i in range(count):
            chunk = padded[i*7:(i+1)*7]
            data_int = int.from_bytes(chunk, 'little')
            packets.append({
                'name': 'DATA_PACKET',
                'source_id': source_id,
                'packet_number': i + 1,
                'data': data_int,
            })
        return packets

    def test_basic(self):
        t = self._make_ts()
        self.assertTrue(type(t), Touchscreen)

    def test_unrelated_message_not_processed(self):
        t = self._make_ts()
        result = t.process_rvc_msg({'name': 'DC_SOURCE_STATUS_1', 'source_id': '9F'})
        self.assertFalse(result)
        t.mqtt_support.client.publish.assert_not_called()

    def test_initial_packet_wrong_source_id_not_processed(self):
        t = self._make_ts()
        msg = {'name': 'INITIAL_PACKET', 'source_id': 'FD', 'packet_count': 2, 'message_length': 10}
        result = t.process_rvc_msg(msg)
        self.assertFalse(result)

    def test_initial_packet(self):
        t = self._make_ts()
        msg = {'name': 'INITIAL_PACKET', 'source_id': '9F', 'packet_count': 2, 'message_length': 12}
        t._mp_packets = {1: b'stale'}
        result = t.process_rvc_msg(msg)
        self.assertTrue(result)
        self.assertEqual(t._mp_expected_count, 2)
        self.assertEqual(t._mp_message_length, 12)
        self.assertEqual(t._mp_packets, {})

    def test_initial_packet_zero_count(self):
        t = self._make_ts()
        msg = {'name': 'INITIAL_PACKET', 'source_id': '9F', 'packet_count': 0, 'message_length': 10}
        t._mp_expected_count = 3
        result = t.process_rvc_msg(msg)
        self.assertTrue(result)
        self.assertEqual(t._mp_expected_count, 3)  # not overwritten

    def test_data_packet_assembles_product_id(self):
        t = self._make_ts()
        product_str = "Touchscreen v1"
        t.process_rvc_msg({
            'name': 'INITIAL_PACKET', 'source_id': '9F',
            'packet_count': 2, 'message_length': len(product_str),
        })
        for pkt in self._make_data_packets(product_str, 2):
            t.process_rvc_msg(pkt)
        t.mqtt_support.client.publish.assert_called_with(
            'touchscreen/status/product_id', product_str, retain=True)
        self.assertEqual(t._mp_expected_count, 0)
        self.assertEqual(t._mp_packets, {})

    def test_data_packet_before_initial_packet(self):
        t = self._make_ts()
        pkt = {'name': 'DATA_PACKET', 'source_id': '9F', 'packet_number': 1, 'data': 0}
        result = t.process_rvc_msg(pkt)
        self.assertTrue(result)
        t.mqtt_support.client.publish.assert_not_called()

    def test_data_packet_duplicate_ignored(self):
        t = self._make_ts()
        t.process_rvc_msg({'name': 'INITIAL_PACKET', 'source_id': '9F',
                            'packet_count': 2, 'message_length': 7})
        pkt = {'name': 'DATA_PACKET', 'source_id': '9F', 'packet_number': 1, 'data': 0}
        t.process_rvc_msg(pkt)
        t.process_rvc_msg(pkt)  # duplicate
        self.assertEqual(len(t._mp_packets), 1)

    def test_product_id_no_publish_when_unchanged(self):
        t = self._make_ts()
        product_str = "Touchscreen"
        for _ in range(2):
            t.process_rvc_msg({'name': 'INITIAL_PACKET', 'source_id': '9F',
                                'packet_count': 1, 'message_length': len(product_str)})
            for pkt in self._make_data_packets(product_str, 1):
                t.process_rvc_msg(pkt)
        calls = [c for c in t.mqtt_support.client.publish.call_args_list
                 if c[0][0] == 'touchscreen/status/product_id']
        self.assertEqual(len(calls), 1)

    def test_product_id_publishes_when_changed(self):
        t = self._make_ts()
        for product_str in ("TS v1.0", "TS v2.0"):
            t.process_rvc_msg({'name': 'INITIAL_PACKET', 'source_id': '9F',
                                'packet_count': 1, 'message_length': len(product_str)})
            for pkt in self._make_data_packets(product_str, 1):
                t.process_rvc_msg(pkt)
        calls = [c for c in t.mqtt_support.client.publish.call_args_list
                 if c[0][0] == 'touchscreen/status/product_id']
        self.assertEqual(len(calls), 2)

    def test_data_packet_overflow_does_not_crash(self):
        """data value too large for 7 bytes must not raise OverflowError."""
        t = self._make_ts()
        t.process_rvc_msg({'name': 'INITIAL_PACKET', 'source_id': '9F',
                           'packet_count': 1, 'message_length': 7})
        overflow_data = 2 ** 56  # one bit too many for 7 bytes
        try:
            t.process_rvc_msg({'name': 'DATA_PACKET', 'source_id': '9F',
                               'packet_number': 1, 'data': overflow_data})
        except OverflowError as e:
            self.fail(f"process_rvc_msg raised OverflowError on oversized data: {e}")

    def test_data_packet_invalid_bytes_logs_error(self):
        t = self._make_ts()
        t.process_rvc_msg({'name': 'INITIAL_PACKET', 'source_id': '9F',
                           'packet_count': 1, 'message_length': 7})
        invalid_data = int.from_bytes(b'\xff\xff\xff\xff\xff\xff\xff', 'little')
        t.process_rvc_msg({'name': 'DATA_PACKET', 'source_id': '9F',
                           'packet_number': 1, 'data': invalid_data})
        self.assertEqual(t._mp_expected_count, 0)
        self.assertEqual(t._mp_packets, {})
        t.mqtt_support.client.publish.assert_not_called()


    # --- DM_RV tests ---

    def _make_dm_rv(self, source_id='9F', spn_msb=0x7F, spn_isb=0x00, spn_lsb=0,
                    red_lamp=0, yellow_lamp=0, fmi_definition="No fault"):
        return {
            'name': 'DM_RV',
            'source_id': source_id,
            'spn-msb': spn_msb,
            'spn-isb': spn_isb,
            'spn-lsb': spn_lsb,
            'red_lamp_status': red_lamp,
            'yellow_lamp_status': yellow_lamp,
            'fmi_definition': fmi_definition,
        }

    def test_dm_rv_wrong_source_id_not_processed(self):
        t = self._make_ts()
        result = t.process_rvc_msg(self._make_dm_rv(source_id='FD'))
        self.assertFalse(result)

    def test_dm_rv_publishes_fault_code_and_description(self):
        t = self._make_ts()
        result = t.process_rvc_msg(self._make_dm_rv(fmi_definition="Bad node"))
        self.assertTrue(result)
        publish_calls = {c[0][0]: c[0][1]
                         for c in t.mqtt_support.client.publish.call_args_list}
        self.assertIn('touchscreen/status/fault/code', publish_calls)
        self.assertIn('touchscreen/status/fault/description', publish_calls)
        self.assertEqual(publish_calls['touchscreen/status/fault/description'], "Bad node")

    def test_dm_rv_lamp_red_when_red_lamp_set(self):
        t = self._make_ts()
        t.process_rvc_msg(self._make_dm_rv(red_lamp=1, yellow_lamp=0))
        publish_calls = {c[0][0]: c[0][1]
                         for c in t.mqtt_support.client.publish.call_args_list}
        self.assertEqual(publish_calls.get('touchscreen/status/fault/lamp'), 'red')

    def test_dm_rv_lamp_yellow_when_only_yellow_lamp_set(self):
        t = self._make_ts()
        t.process_rvc_msg(self._make_dm_rv(red_lamp=0, yellow_lamp=1))
        publish_calls = {c[0][0]: c[0][1]
                         for c in t.mqtt_support.client.publish.call_args_list}
        self.assertEqual(publish_calls.get('touchscreen/status/fault/lamp'), 'yellow')

    def test_dm_rv_lamp_off_when_no_lamps_set(self):
        t = self._make_ts()
        t.process_rvc_msg(self._make_dm_rv(red_lamp=0, yellow_lamp=0))
        publish_calls = {c[0][0]: c[0][1]
                         for c in t.mqtt_support.client.publish.call_args_list}
        self.assertEqual(publish_calls.get('touchscreen/status/fault/lamp'), 'off')

    def test_dm_rv_red_takes_priority_over_yellow(self):
        t = self._make_ts()
        t.process_rvc_msg(self._make_dm_rv(red_lamp=1, yellow_lamp=1))
        publish_calls = {c[0][0]: c[0][1]
                         for c in t.mqtt_support.client.publish.call_args_list}
        self.assertEqual(publish_calls.get('touchscreen/status/fault/lamp'), 'red')

    def test_dm_rv_no_publish_when_fault_unchanged(self):
        t = self._make_ts()
        msg = self._make_dm_rv()
        t.process_rvc_msg(msg)
        t.mqtt_support.client.publish.reset_mock()
        t.process_rvc_msg(msg)
        fault_publishes = [c for c in t.mqtt_support.client.publish.call_args_list
                           if 'fault/code' in c[0][0] or 'fault/description' in c[0][0]]
        self.assertEqual(len(fault_publishes), 0)

    def test_dm_rv_publishes_on_fault_change(self):
        t = self._make_ts()
        t.process_rvc_msg(self._make_dm_rv(spn_msb=0x7F, spn_isb=0x00, spn_lsb=0))
        t.mqtt_support.client.publish.reset_mock()
        t.process_rvc_msg(self._make_dm_rv(spn_msb=0x7F, spn_isb=0x00, spn_lsb=4,
                                           fmi_definition="Datum erratic"))
        fault_publishes = [c for c in t.mqtt_support.client.publish.call_args_list
                           if 'fault/code' in c[0][0]]
        self.assertEqual(len(fault_publishes), 1)


if __name__ == '__main__':
    unittest.main()
