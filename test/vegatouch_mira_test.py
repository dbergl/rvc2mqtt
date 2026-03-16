"""
Unit tests for the Vegatouch Mira entity class

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
from rvc2mqtt.entity.vegatouch_mira import VegatouchMira


class Test_VegatouchMira(unittest.TestCase):

    def _make_mira(self, source_id='FD'):
        mock = MagicMock()
        mock.mqtt_support.make_device_topic_string.return_value = 'topic_string'
        return VegatouchMira(
            {'instance': 1, 'instance_name': "Vegatouch Mira", 'source_id': source_id,
             'status_topic': 'mira/status'},
            mock
        )

    def _make_data_packets(self, product_str, count, source_id='FD'):
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
        m = self._make_mira()
        self.assertTrue(type(m), VegatouchMira)

    def test_unrelated_message_not_processed(self):
        m = self._make_mira()
        result = m.process_rvc_msg({'name': 'DC_SOURCE_STATUS_1', 'source_id': 'FD'})
        self.assertFalse(result)
        m.mqtt_support.client.publish.assert_not_called()

    def test_initial_packet_wrong_source_id_not_processed(self):
        m = self._make_mira()
        msg = {'name': 'INITIAL_PACKET', 'source_id': '9C', 'packet_count': 2, 'message_length': 10}
        result = m.process_rvc_msg(msg)
        self.assertFalse(result)

    def test_initial_packet(self):
        m = self._make_mira()
        msg = {'name': 'INITIAL_PACKET', 'source_id': 'FD', 'packet_count': 2, 'message_length': 12}
        m._mp_packets = {1: b'stale'}
        result = m.process_rvc_msg(msg)
        self.assertTrue(result)
        self.assertEqual(m._mp_expected_count, 2)
        self.assertEqual(m._mp_message_length, 12)
        self.assertEqual(m._mp_packets, {})

    def test_initial_packet_zero_count(self):
        m = self._make_mira()
        msg = {'name': 'INITIAL_PACKET', 'source_id': 'FD', 'packet_count': 0, 'message_length': 10}
        m._mp_expected_count = 3
        result = m.process_rvc_msg(msg)
        self.assertTrue(result)
        self.assertEqual(m._mp_expected_count, 3)  # not overwritten

    def test_data_packet_assembles_product_id(self):
        m = self._make_mira()
        product_str = "Vegatouch Mira"
        m.process_rvc_msg({
            'name': 'INITIAL_PACKET', 'source_id': 'FD',
            'packet_count': 2, 'message_length': len(product_str),
        })
        for pkt in self._make_data_packets(product_str, 2):
            m.process_rvc_msg(pkt)
        m.mqtt_support.client.publish.assert_called_with(
            'mira/status/product_id', product_str, retain=True)
        self.assertEqual(m._mp_expected_count, 0)
        self.assertEqual(m._mp_packets, {})

    def test_data_packet_before_initial_packet(self):
        m = self._make_mira()
        pkt = {'name': 'DATA_PACKET', 'source_id': 'FD', 'packet_number': 1, 'data': 0}
        result = m.process_rvc_msg(pkt)
        self.assertTrue(result)
        m.mqtt_support.client.publish.assert_not_called()

    def test_data_packet_duplicate_ignored(self):
        m = self._make_mira()
        m.process_rvc_msg({'name': 'INITIAL_PACKET', 'source_id': 'FD',
                            'packet_count': 2, 'message_length': 7})
        pkt = {'name': 'DATA_PACKET', 'source_id': 'FD', 'packet_number': 1, 'data': 0}
        m.process_rvc_msg(pkt)
        m.process_rvc_msg(pkt)  # duplicate
        self.assertEqual(len(m._mp_packets), 1)

    def test_product_id_no_publish_when_unchanged(self):
        m = self._make_mira()
        product_str = "Mira"
        for _ in range(2):
            m.process_rvc_msg({'name': 'INITIAL_PACKET', 'source_id': 'FD',
                                'packet_count': 1, 'message_length': len(product_str)})
            for pkt in self._make_data_packets(product_str, 1):
                m.process_rvc_msg(pkt)
        calls = [c for c in m.mqtt_support.client.publish.call_args_list
                 if c[0][0] == 'mira/status/product_id']
        self.assertEqual(len(calls), 1)

    def test_product_id_publishes_when_changed(self):
        m = self._make_mira()
        for product_str in ("Mira v1", "Mira v2"):
            m.process_rvc_msg({'name': 'INITIAL_PACKET', 'source_id': 'FD',
                                'packet_count': 1, 'message_length': len(product_str)})
            for pkt in self._make_data_packets(product_str, 1):
                m.process_rvc_msg(pkt)
        calls = [c for c in m.mqtt_support.client.publish.call_args_list
                 if c[0][0] == 'mira/status/product_id']
        self.assertEqual(len(calls), 2)


    # --- DM_1 tests ---

    def _make_dm_1(self, source_id='FD', spn_msb=0x7F, spn_isb=0x00, spn_lsb=0,
                   red_lamp=0, fmi_definition="No fault"):
        return {
            'name': 'DM_1',
            'source_id': source_id,
            'spn-msb': spn_msb,
            'spn-isb': spn_isb,
            'spn-lsb': spn_lsb,
            'red_lamp_status': red_lamp,
            'fmi_definition': fmi_definition,
        }

    def test_dm_1_wrong_source_id_not_processed(self):
        m = self._make_mira()
        result = m.process_rvc_msg(self._make_dm_1(source_id='9C'))
        self.assertFalse(result)

    def test_dm_1_publishes_fault_code_and_description(self):
        m = self._make_mira()
        result = m.process_rvc_msg(self._make_dm_1(fmi_definition="Bad intelligent RV-C node"))
        self.assertTrue(result)
        publish_calls = {c[0][0]: c[0][1]
                         for c in m.mqtt_support.client.publish.call_args_list}
        self.assertIn('mira/status/fault/code', publish_calls)
        self.assertIn('mira/status/fault/description', publish_calls)
        self.assertEqual(publish_calls['mira/status/fault/description'],
                         "Bad intelligent RV-C node")

    def test_dm_1_lamp_on_when_red_lamp_set(self):
        m = self._make_mira()
        m.process_rvc_msg(self._make_dm_1(red_lamp=1))
        publish_calls = {c[0][0]: c[0][1]
                         for c in m.mqtt_support.client.publish.call_args_list}
        self.assertEqual(publish_calls.get('mira/status/fault/lamp'), 'on')

    def test_dm_1_lamp_off_when_red_lamp_clear(self):
        m = self._make_mira()
        m.process_rvc_msg(self._make_dm_1(red_lamp=0))
        publish_calls = {c[0][0]: c[0][1]
                         for c in m.mqtt_support.client.publish.call_args_list}
        self.assertEqual(publish_calls.get('mira/status/fault/lamp'), 'off')

    def test_dm_1_no_publish_when_fault_unchanged(self):
        m = self._make_mira()
        msg = self._make_dm_1()
        m.process_rvc_msg(msg)
        m.mqtt_support.client.publish.reset_mock()
        m.process_rvc_msg(msg)
        fault_publishes = [c for c in m.mqtt_support.client.publish.call_args_list
                           if 'fault/code' in c[0][0] or 'fault/description' in c[0][0]]
        self.assertEqual(len(fault_publishes), 0)

    def test_dm_1_publishes_on_fault_change(self):
        m = self._make_mira()
        m.process_rvc_msg(self._make_dm_1(spn_msb=0x7F, spn_isb=0x00, spn_lsb=0))
        m.mqtt_support.client.publish.reset_mock()
        m.process_rvc_msg(self._make_dm_1(spn_msb=0x7F, spn_isb=0x00, spn_lsb=4,
                                          fmi_definition="Datum erratic"))
        fault_publishes = [c for c in m.mqtt_support.client.publish.call_args_list
                           if 'fault/code' in c[0][0]]
        self.assertEqual(len(fault_publishes), 1)


if __name__ == '__main__':
    unittest.main()
