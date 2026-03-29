"""
Unit tests for the G12 Configuration entity class

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
import struct
import unittest
from unittest.mock import MagicMock, call
import context  # add rvc2mqtt package to the python path using local reference
from rvc2mqtt.entity.g12_configuration import G12_Configuration


class Test_G12_Configuration(unittest.TestCase):

    def _make_g12(self, source_id='9C'):
        mock = MagicMock()
        mock.mqtt_support.make_device_topic_string.return_value = 'topic_string'
        return G12_Configuration(
            {'instance': 1, 'instance_name': "test g12", 'source_id': source_id,
             'status_topic': 'g12/status', 'command_topic': 'g12/set'},
            mock
        )

    def test_basic(self):
        g = self._make_g12()
        self.assertTrue(type(g), G12_Configuration)

    def test_wrong_name_not_processed(self):
        g = self._make_g12()
        msg = {'name': 'OTHER_DGN', 'source_id': '9C', 'message_type': '16', 'minutes': 120}
        result = g.process_rvc_msg(msg)
        self.assertFalse(result)
        g.mqtt_support.client.publish.assert_not_called()

    def test_wrong_source_id_not_processed(self):
        g = self._make_g12()
        msg = {'name': 'G12_CONFIGURATION', 'source_id': 'FF', 'message_type': '16', 'minutes': 120}
        result = g.process_rvc_msg(msg)
        self.assertFalse(result)
        g.mqtt_support.client.publish.assert_not_called()

    def test_msg_type_16_publishes_max_engine_run_time(self):
        g = self._make_g12()
        msg = {'name': 'G12_CONFIGURATION', 'source_id': '9C', 'message_type': '16', 'minutes': 120}
        result = g.process_rvc_msg(msg)
        self.assertTrue(result)
        g.mqtt_support.client.publish.assert_called_once_with(
            'g12/status/aes/max_engine_run_time', 120, retain=True)

    def test_msg_type_0d_publishes_stop_at_voltage(self):
        g = self._make_g12()
        # 0x0D -> hex(13).upper()[2:] = 'D'
        msg = {'name': 'G12_CONFIGURATION', 'source_id': '9C', 'message_type': 'D', 'volts': 11.6}
        result = g.process_rvc_msg(msg)
        self.assertTrue(result)
        g.mqtt_support.client.publish.assert_called_once_with(
            'g12/status/aes/stop_at_voltage', 11.6, retain=True)

    def test_msg_type_0c_publishes_time_at_start_volts(self):
        g = self._make_g12()
        # rvc.py delivers duration*2; entity divides by 2 to get actual seconds
        # e.g. screen shows 65s → G12 raw=65 → rvc.py gives 130 → entity publishes 65
        msg = {'name': 'G12_CONFIGURATION', 'source_id': '9C', 'message_type': 'C', 'duration': 130}
        result = g.process_rvc_msg(msg)
        self.assertTrue(result)
        g.mqtt_support.client.publish.assert_called_once_with(
            'g12/status/aes/time_at_start_volts', 65, retain=True)

    def test_msg_type_0e_publishes_time_at_stop_volts(self):
        g = self._make_g12()
        msg = {'name': 'G12_CONFIGURATION', 'source_id': '9C', 'message_type': 'E', 'duration': 120}
        result = g.process_rvc_msg(msg)
        self.assertTrue(result)
        g.mqtt_support.client.publish.assert_called_once_with(
            'g12/status/aes/time_at_stop_volts', 60, retain=True)

    def test_msg_type_31_publishes_start_at_voltage(self):
        g = self._make_g12()
        msg = {'name': 'G12_CONFIGURATION', 'source_id': '9C', 'message_type': '31', 'volts': 12.4}
        result = g.process_rvc_msg(msg)
        self.assertTrue(result)
        g.mqtt_support.client.publish.assert_called_once_with(
            'g12/status/aes/start_at_voltage', 12.4, retain=True)

    def test_msg_type_2b_publishes_quiet_time_start(self):
        g = self._make_g12()
        msg = {'name': 'G12_CONFIGURATION', 'source_id': '9C', 'message_type': '2B',
               'hours': 22, 'minutes': 30}
        result = g.process_rvc_msg(msg)
        self.assertTrue(result)
        g.mqtt_support.client.publish.assert_called_once_with(
            'g12/status/aes/quiet_time_start', '22:30', retain=True)

    def test_msg_type_2c_publishes_quiet_time_stop(self):
        g = self._make_g12()
        msg = {'name': 'G12_CONFIGURATION', 'source_id': '9C', 'message_type': '2C',
               'hours': 7, 'minutes': 0}
        result = g.process_rvc_msg(msg)
        self.assertTrue(result)
        g.mqtt_support.client.publish.assert_called_once_with(
            'g12/status/aes/quiet_time_stop', '07:00', retain=True)

    def test_msg_type_cc_publishes_threshold(self):
        g = self._make_g12()
        msg = {'name': 'G12_CONFIGURATION', 'source_id': '9C', 'message_type': 'CC', 'value': 1000}
        result = g.process_rvc_msg(msg)
        self.assertTrue(result)
        g.mqtt_support.client.publish.assert_called_once_with(
            'g12/status/tanks/threshold_33_pct', 1000, retain=True)

    def test_aes_messages_return_true_no_publish(self):
        g = self._make_g12()
        for msg_type in ('1', '3', '5', '9B'):
            g.mqtt_support.client.publish.reset_mock()
            msg = {'name': 'G12_CONFIGURATION', 'source_id': '9C', 'message_type': msg_type}
            result = g.process_rvc_msg(msg)
            self.assertTrue(result)
            g.mqtt_support.client.publish.assert_not_called()

    def test_cd_ce_messages_return_true_no_publish(self):
        g = self._make_g12()
        for msg_type in ('CD', 'CE'):
            g.mqtt_support.client.publish.reset_mock()
            msg = {'name': 'G12_CONFIGURATION', 'source_id': '9C', 'message_type': msg_type}
            result = g.process_rvc_msg(msg)
            self.assertTrue(result)
            g.mqtt_support.client.publish.assert_not_called()

    def test_no_publish_when_value_unchanged(self):
        g = self._make_g12()
        msg = {'name': 'G12_CONFIGURATION', 'source_id': '9C', 'message_type': '16', 'minutes': 120}
        g.process_rvc_msg(msg)
        g.mqtt_support.client.publish.reset_mock()
        # Send same message again - should not publish
        g.process_rvc_msg(msg)
        g.mqtt_support.client.publish.assert_not_called()

    def test_publishes_when_value_changes(self):
        g = self._make_g12()
        msg1 = {'name': 'G12_CONFIGURATION', 'source_id': '9C', 'message_type': '16', 'minutes': 120}
        msg2 = {'name': 'G12_CONFIGURATION', 'source_id': '9C', 'message_type': '16', 'minutes': 180}
        g.process_rvc_msg(msg1)
        g.mqtt_support.client.publish.reset_mock()
        g.process_rvc_msg(msg2)
        g.mqtt_support.client.publish.assert_called_once_with(
            'g12/status/aes/max_engine_run_time', 180, retain=True)


    # --- DM_RV tests ---

    def _make_dm_rv(self, source_id='9C', spn_msb=0x7F, spn_isb=0x00, spn_lsb=0,
                    red_lamp=0, fmi_definition="No fault"):
        return {
            'name': 'DM_RV',
            'source_id': source_id,
            'spn-msb': spn_msb,
            'spn-isb': spn_isb,
            'spn-lsb': spn_lsb,
            'red_lamp_status': red_lamp,
            'fmi_definition': fmi_definition,
        }

    def test_dm_rv_wrong_source_id_not_processed(self):
        g = self._make_g12()
        result = g.process_rvc_msg(self._make_dm_rv(source_id='FF'))
        self.assertFalse(result)

    def test_dm_rv_publishes_fault_code_and_description(self):
        g = self._make_g12()
        result = g.process_rvc_msg(self._make_dm_rv(fmi_definition="Bad intelligent RV-C node"))
        self.assertTrue(result)
        publish_calls = {c[0][0]: c[0][1]
                         for c in g.mqtt_support.client.publish.call_args_list}
        self.assertIn('g12/status/fault/code', publish_calls)
        self.assertIn('g12/status/fault/description', publish_calls)
        self.assertEqual(publish_calls['g12/status/fault/description'],
                         "Bad intelligent RV-C node")

    def test_dm_rv_lamp_on_when_red_lamp_set(self):
        g = self._make_g12()
        g.process_rvc_msg(self._make_dm_rv(red_lamp=1))
        publish_calls = {c[0][0]: c[0][1]
                         for c in g.mqtt_support.client.publish.call_args_list}
        self.assertEqual(publish_calls.get('g12/status/fault/lamp'), 'on')

    def test_dm_rv_lamp_off_when_red_lamp_clear(self):
        g = self._make_g12()
        g.process_rvc_msg(self._make_dm_rv(red_lamp=0))
        publish_calls = {c[0][0]: c[0][1]
                         for c in g.mqtt_support.client.publish.call_args_list}
        self.assertEqual(publish_calls.get('g12/status/fault/lamp'), 'off')

    def test_dm_rv_no_publish_when_fault_unchanged(self):
        g = self._make_g12()
        msg = self._make_dm_rv()
        g.process_rvc_msg(msg)
        g.mqtt_support.client.publish.reset_mock()
        g.process_rvc_msg(msg)
        fault_publishes = [c for c in g.mqtt_support.client.publish.call_args_list
                           if 'fault/code' in c[0][0] or 'fault/description' in c[0][0]]
        self.assertEqual(len(fault_publishes), 0)

    def test_dm_rv_publishes_on_fault_change(self):
        g = self._make_g12()
        g.process_rvc_msg(self._make_dm_rv(spn_msb=0x7F, spn_isb=0x00, spn_lsb=0))
        g.mqtt_support.client.publish.reset_mock()
        g.process_rvc_msg(self._make_dm_rv(spn_msb=0x7F, spn_isb=0x00, spn_lsb=4,
                                           fmi_definition="Datum erratic"))
        fault_publishes = [c for c in g.mqtt_support.client.publish.call_args_list
                           if 'fault/code' in c[0][0]]
        self.assertEqual(len(fault_publishes), 1)

    # --- Engine relay (DC_DIMMER_STATUS_3 instance 18) tests ---

    def _make_engine_relay_msg(self, source_id='9C', instance=18, brightness=100.0):
        return {
            'name': 'DC_DIMMER_STATUS_3',
            'source_id': source_id,
            'instance': instance,
            'operating_status_brightness': brightness,
        }

    def test_engine_relay_on_when_brightness_nonzero(self):
        g = self._make_g12()
        result = g.process_rvc_msg(self._make_engine_relay_msg(brightness=100.0))
        self.assertTrue(result)
        publish_calls = {c[0][0]: c[0][1]
                         for c in g.mqtt_support.client.publish.call_args_list}
        self.assertEqual(publish_calls.get('g12/status/engine/running'), 'on')

    def test_engine_relay_off_when_brightness_zero(self):
        g = self._make_g12()
        result = g.process_rvc_msg(self._make_engine_relay_msg(brightness=0))
        self.assertTrue(result)
        publish_calls = {c[0][0]: c[0][1]
                         for c in g.mqtt_support.client.publish.call_args_list}
        self.assertEqual(publish_calls.get('g12/status/engine/running'), 'off')

    def test_engine_relay_wrong_instance_ignored(self):
        g = self._make_g12()
        g.process_rvc_msg(self._make_engine_relay_msg(instance=1, brightness=100.0))
        publish_calls = {c[0][0]: c[0][1]
                         for c in g.mqtt_support.client.publish.call_args_list}
        self.assertNotIn('g12/status/engine/running', publish_calls)

    def test_engine_relay_wrong_source_id_ignored(self):
        g = self._make_g12()
        result = g.process_rvc_msg(self._make_engine_relay_msg(source_id='FF', brightness=100.0))
        self.assertFalse(result)

    def test_engine_relay_no_publish_when_state_unchanged(self):
        g = self._make_g12()
        g.process_rvc_msg(self._make_engine_relay_msg(brightness=100.0))
        g.mqtt_support.client.publish.reset_mock()
        g.process_rvc_msg(self._make_engine_relay_msg(brightness=50.0))  # still on
        publish_calls = {c[0][0]: c[0][1]
                         for c in g.mqtt_support.client.publish.call_args_list}
        self.assertNotIn('g12/status/engine/running', publish_calls)

    # --- INITIAL_PACKET / DATA_PACKET / product_id tests ---

    def _make_data_packets(self, product_str, count):
        """Build DATA_PACKET messages matching the rvc.py integer encoding for a product string."""
        product_bytes = product_str.encode('ascii')
        padded = product_bytes.ljust(count * 7, b'\x00')
        packets = []
        for i in range(count):
            chunk = padded[i*7:(i+1)*7]
            data_int = int.from_bytes(chunk, 'little')
            packets.append({
                'name': 'DATA_PACKET',
                'source_id': '9C',
                'packet_number': i + 1,
                'data': data_int,
            })
        return packets

    def test_initial_packet(self):
        g = self._make_g12()
        msg = {'name': 'INITIAL_PACKET', 'source_id': '9C', 'packet_count': 2, 'message_length': 10}
        g._mp_packets = {1: b'stale'}
        result = g.process_rvc_msg(msg)
        self.assertTrue(result)
        self.assertEqual(g._mp_expected_count, 2)
        self.assertEqual(g._mp_message_length, 10)
        self.assertEqual(g._mp_packets, {})

    def test_initial_packet_zero_count(self):
        g = self._make_g12()
        msg = {'name': 'INITIAL_PACKET', 'source_id': '9C', 'packet_count': 0, 'message_length': 10}
        g._mp_expected_count = 5
        result = g.process_rvc_msg(msg)
        self.assertTrue(result)
        self.assertEqual(g._mp_expected_count, 5)  # not overwritten

    def test_initial_packet_wrong_source_id_not_processed(self):
        g = self._make_g12()
        msg = {'name': 'INITIAL_PACKET', 'source_id': 'FF', 'packet_count': 2, 'message_length': 10}
        result = g.process_rvc_msg(msg)
        self.assertFalse(result)

    def test_data_packet_assembles_product_id(self):
        g = self._make_g12()
        product_str = "Firefly G12"
        g.process_rvc_msg({
            'name': 'INITIAL_PACKET', 'source_id': '9C',
            'packet_count': 2, 'message_length': len(product_str),
        })
        for pkt in self._make_data_packets(product_str, 2):
            g.process_rvc_msg(pkt)
        g.mqtt_support.client.publish.assert_called_with(
            'g12/status/product_id', product_str, retain=True)
        self.assertEqual(g._mp_expected_count, 0)
        self.assertEqual(g._mp_packets, {})

    def test_data_packet_before_initial_packet(self):
        g = self._make_g12()
        pkt = {'name': 'DATA_PACKET', 'source_id': '9C', 'packet_number': 1, 'data': 0}
        result = g.process_rvc_msg(pkt)
        self.assertTrue(result)
        g.mqtt_support.client.publish.assert_not_called()

    def test_data_packet_duplicate_ignored(self):
        g = self._make_g12()
        g.process_rvc_msg({'name': 'INITIAL_PACKET', 'source_id': '9C',
                            'packet_count': 2, 'message_length': 7})
        pkt = {'name': 'DATA_PACKET', 'source_id': '9C', 'packet_number': 1, 'data': 0}
        g.process_rvc_msg(pkt)
        g.process_rvc_msg(pkt)  # duplicate
        self.assertEqual(len(g._mp_packets), 1)

    def test_product_id_no_publish_when_unchanged(self):
        g = self._make_g12()
        product_str = "G12"
        for _ in range(2):
            g.process_rvc_msg({'name': 'INITIAL_PACKET', 'source_id': '9C',
                                'packet_count': 1, 'message_length': len(product_str)})
            for pkt in self._make_data_packets(product_str, 1):
                g.process_rvc_msg(pkt)
        # publish should only have been called once (second assembly same value)
        calls = [c for c in g.mqtt_support.client.publish.call_args_list
                 if c[0][0] == 'g12/status/product_id']
        self.assertEqual(len(calls), 1)


    # --- 1FED9 (GENERIC_INDICATOR_COMMAND) tests ---

    def _make_1fed9_msg(self, selector, value_le, function, group_byte=0x96):
        """Build a decoded GENERIC_INDICATOR_COMMAND message as process_rvc_msg would receive it."""
        data = bytearray(8)
        data[0] = 0xFF
        data[1] = group_byte
        data[2] = selector
        data[3] = 0x0F
        data[4] = value_le & 0xFF
        data[5] = (value_le >> 8) & 0xFF
        data[6] = function
        data[7] = 0xEA
        return {
            'name': 'GENERIC_INDICATOR_COMMAND',
            'source_id': '9F',
            'group': f"{group_byte:08b}",
            'function': function,
            'data': data.hex().upper(),
        }

    def test_1fed9_set_max_engine_run_time(self):
        g = self._make_g12()
        msg = self._make_1fed9_msg(selector=0x16, value_le=115, function=0xD1)
        result = g.process_rvc_msg(msg)
        self.assertTrue(result)
        g.mqtt_support.client.publish.assert_called_once_with(
            'g12/status/aes/max_engine_run_time', 115, retain=True)
        self.assertEqual(g._max_engine_run_time, 115)

    def test_1fed9_set_updates_state_no_duplicate_publish(self):
        g = self._make_g12()
        msg = self._make_1fed9_msg(selector=0x16, value_le=115, function=0xD1)
        g.process_rvc_msg(msg)
        g.mqtt_support.client.publish.reset_mock()
        g.process_rvc_msg(msg)
        g.mqtt_support.client.publish.assert_not_called()

    def test_1fed9_set_stop_at_voltage(self):
        g = self._make_g12()
        # value_le=232 → round(232 * 0.05, 2) = 11.6
        msg = self._make_1fed9_msg(selector=0x0D, value_le=232, function=0xD1)
        result = g.process_rvc_msg(msg)
        self.assertTrue(result)
        g.mqtt_support.client.publish.assert_called_once_with(
            'g12/status/aes/stop_at_voltage', 11.6, retain=True)

    def test_1fed9_set_quiet_time_start(self):
        g = self._make_g12()
        # For quiet time: data[4]=minutes, data[5]=hours
        data = bytearray(8)
        data[0] = 0xFF
        data[1] = 0x96
        data[2] = 0x2B  # selector = quiet time start
        data[3] = 0x0F
        data[4] = 30    # minutes
        data[5] = 22    # hours
        data[6] = 0xD1
        data[7] = 0xEA
        msg = {
            'name': 'GENERIC_INDICATOR_COMMAND',
            'source_id': '9F',
            'group': '10010110',
            'function': 0xD1,
            'data': data.hex().upper(),
        }
        result = g.process_rvc_msg(msg)
        self.assertTrue(result)
        g.mqtt_support.client.publish.assert_called_once_with(
            'g12/status/aes/quiet_time_start', '22:30', retain=True)

    def test_1fed9_query_ignored(self):
        g = self._make_g12()
        msg = self._make_1fed9_msg(selector=0x16, value_le=0xFFFF, function=0xD3)
        result = g.process_rvc_msg(msg)
        self.assertTrue(result)
        g.mqtt_support.client.publish.assert_not_called()
        self.assertEqual(g._max_engine_run_time, "unknown")

    def test_1fed9_wrong_group_ignored(self):
        g = self._make_g12()
        msg = self._make_1fed9_msg(selector=0x16, value_le=115, function=0xD1, group_byte=0x00)
        result = g.process_rvc_msg(msg)
        self.assertFalse(result)
        g.mqtt_support.client.publish.assert_not_called()

    def test_1fed9_d2_function_also_sets(self):
        g = self._make_g12()
        msg = self._make_1fed9_msg(selector=0x16, value_le=60, function=0xD2)
        result = g.process_rvc_msg(msg)
        self.assertTrue(result)
        g.mqtt_support.client.publish.assert_called_once_with(
            'g12/status/aes/max_engine_run_time', 60, retain=True)

    # --- MQTT set topic tests ---

    def _make_g12_with_queue(self):
        g = self._make_g12()
        q = queue.Queue()
        g.set_rvc_send_queue(q)
        return g, q

    def test_mqtt_set_max_engine_run_time(self):
        g, q = self._make_g12_with_queue()
        g.process_mqtt_msg('g12/set/aes/max_engine_run_time', '115')
        self.assertFalse(q.empty())
        item = q.get_nowait()
        self.assertEqual(item['dgn'], '1FED9')
        frame = item['data']
        self.assertEqual(frame[0], 0xFF)
        self.assertEqual(frame[1], 0x96)
        self.assertEqual(frame[2], 0x16)   # selector
        self.assertEqual(frame[3], 0x0F)
        value = int.from_bytes(frame[4:6], 'little')
        self.assertEqual(value, 115)
        self.assertEqual(frame[6], 0xD1)
        self.assertEqual(frame[7], 0xEA)

    def test_mqtt_set_quiet_time_start(self):
        g, q = self._make_g12_with_queue()
        g.process_mqtt_msg('g12/set/aes/quiet_time_start', '22:30')
        self.assertFalse(q.empty())
        item = q.get_nowait()
        self.assertEqual(item['dgn'], '1FED9')
        frame = item['data']
        self.assertEqual(frame[2], 0x2B)   # selector
        self.assertEqual(frame[4], 30)     # minutes
        self.assertEqual(frame[5], 22)     # hours
        self.assertEqual(frame[6], 0xD1)

    def test_mqtt_set_quiet_time_start_with_seconds(self):
        # HA sends HH:MM:SS — seconds ignored, minutes rounded to nearest 5
        g, q = self._make_g12_with_queue()
        g.process_mqtt_msg('g12/set/aes/quiet_time_start', '16:52:00')
        frame = q.get_nowait()['data']
        self.assertEqual(frame[4], 50)   # 52 rounds to 50
        self.assertEqual(frame[5], 16)   # hours unchanged

    def test_mqtt_set_quiet_time_start_rounds_to_5min(self):
        g, q = self._make_g12_with_queue()
        g.process_mqtt_msg('g12/set/aes/quiet_time_start', '22:33')
        frame = q.get_nowait()['data']
        self.assertEqual(frame[4], 35)   # 33 rounds to 35
        self.assertEqual(frame[5], 22)

    def test_mqtt_set_quiet_time_start_rounds_up_to_next_hour(self):
        g, q = self._make_g12_with_queue()
        g.process_mqtt_msg('g12/set/aes/quiet_time_start', '22:58')
        frame = q.get_nowait()['data']
        self.assertEqual(frame[4], 0)    # 58 rounds to 60 → 0
        self.assertEqual(frame[5], 23)   # hour rolls over

    def test_mqtt_set_quiet_time_start_rounds_up_midnight_rollover(self):
        g, q = self._make_g12_with_queue()
        g.process_mqtt_msg('g12/set/aes/quiet_time_start', '23:58')
        frame = q.get_nowait()['data']
        self.assertEqual(frame[4], 0)    # 58 rounds to 60 → 0
        self.assertEqual(frame[5], 0)    # 23+1 wraps to 0

    def test_mqtt_set_quiet_time_stop(self):
        g, q = self._make_g12_with_queue()
        g.process_mqtt_msg('g12/set/aes/quiet_time_stop', '07:00')
        self.assertFalse(q.empty())
        item = q.get_nowait()
        frame = item['data']
        self.assertEqual(frame[2], 0x2C)
        self.assertEqual(frame[4], 0)   # minutes
        self.assertEqual(frame[5], 7)   # hours

    def test_mqtt_set_quiet_time_stop_with_seconds(self):
        # HA sends HH:MM:SS — seconds ignored, minutes rounded to nearest 5
        g, q = self._make_g12_with_queue()
        g.process_mqtt_msg('g12/set/aes/quiet_time_stop', '07:00:00')
        frame = q.get_nowait()['data']
        self.assertEqual(frame[4], 0)   # minutes unchanged (already on 5-min boundary)
        self.assertEqual(frame[5], 7)   # hours unchanged

    def test_mqtt_set_quiet_time_stop_rounds_to_5min(self):
        g, q = self._make_g12_with_queue()
        g.process_mqtt_msg('g12/set/aes/quiet_time_stop', '07:03')
        frame = q.get_nowait()['data']
        self.assertEqual(frame[4], 5)   # 3 rounds to 5
        self.assertEqual(frame[5], 7)

    def test_mqtt_set_quiet_time_stop_rounds_up_to_next_hour(self):
        g, q = self._make_g12_with_queue()
        g.process_mqtt_msg('g12/set/aes/quiet_time_stop', '06:58')
        frame = q.get_nowait()['data']
        self.assertEqual(frame[4], 0)   # 58 rounds to 60 → 0
        self.assertEqual(frame[5], 7)   # hour rolls over

    def test_mqtt_set_stop_at_voltage(self):
        g, q = self._make_g12_with_queue()
        g.process_mqtt_msg('g12/set/aes/stop_at_voltage', '11.6')
        item = q.get_nowait()
        frame = item['data']
        self.assertEqual(frame[2], 0x0D)
        value = int.from_bytes(frame[4:6], 'little')
        self.assertEqual(value, round(11.6 / 0.05))

    def test_mqtt_set_no_send_queue(self):
        g = self._make_g12()
        # Should not raise even without a send_queue
        g.process_mqtt_msg('g12/set/aes/max_engine_run_time', '115')

    def test_mqtt_set_time_at_start_volts(self):
        # 300 seconds → raw = 300 (G12 stores raw seconds, no conversion)
        g, q = self._make_g12_with_queue()
        g.process_mqtt_msg('g12/set/aes/time_at_start_volts', '300')
        frame = q.get_nowait()['data']
        self.assertEqual(frame[2], 0x0C)
        self.assertEqual(int.from_bytes(frame[4:6], 'little'), 300)

    def test_mqtt_set_time_at_start_volts_float_payload(self):
        # float string like '599.99988' should round to 600 → raw = 600
        g, q = self._make_g12_with_queue()
        g.process_mqtt_msg('g12/set/aes/time_at_start_volts', '599.99988')
        frame = q.get_nowait()['data']
        self.assertEqual(int.from_bytes(frame[4:6], 'little'), 600)

    def test_mqtt_set_time_at_stop_volts(self):
        # 600 seconds → raw = 600 (G12 stores raw seconds, no conversion)
        g, q = self._make_g12_with_queue()
        g.process_mqtt_msg('g12/set/aes/time_at_stop_volts', '600')
        frame = q.get_nowait()['data']
        self.assertEqual(frame[2], 0x0E)
        self.assertEqual(int.from_bytes(frame[4:6], 'little'), 600)

    def test_mqtt_set_start_at_voltage(self):
        # 12.4 V → raw = round(12.4 / 0.05) = 248
        g, q = self._make_g12_with_queue()
        g.process_mqtt_msg('g12/set/aes/start_at_voltage', '12.4')
        frame = q.get_nowait()['data']
        self.assertEqual(frame[2], 0x31)
        self.assertEqual(int.from_bytes(frame[4:6], 'little'), round(12.4 / 0.05))

    def test_mqtt_set_threshold_cc(self):
        g, q = self._make_g12_with_queue()
        g.process_mqtt_msg('g12/set/tanks/threshold_33_pct', '1000')
        frame = q.get_nowait()['data']
        self.assertEqual(frame[2], 0xCC)
        self.assertEqual(int.from_bytes(frame[4:6], 'little'), 1000)

    def test_mqtt_set_threshold_cd(self):
        g, q = self._make_g12_with_queue()
        g.process_mqtt_msg('g12/set/tanks/threshold_66_pct', '2000')
        frame = q.get_nowait()['data']
        self.assertEqual(frame[2], 0xCD)
        self.assertEqual(int.from_bytes(frame[4:6], 'little'), 2000)

    def test_mqtt_set_threshold_ce(self):
        g, q = self._make_g12_with_queue()
        g.process_mqtt_msg('g12/set/tanks/threshold_100_pct', '3000')
        frame = q.get_nowait()['data']
        self.assertEqual(frame[2], 0xCE)
        self.assertEqual(int.from_bytes(frame[4:6], 'little'), 3000)

    def test_mqtt_set_unknown_topic_logs_warning(self):
        g, q = self._make_g12_with_queue()
        g.process_mqtt_msg('g12/set/unknown/topic', '42')
        self.assertTrue(q.empty())

    def test_mqtt_set_bad_payload_logs_error(self):
        g, q = self._make_g12_with_queue()
        g.process_mqtt_msg('g12/set/aes/max_engine_run_time', 'not_a_number')
        self.assertTrue(q.empty())

    def test_1fed9_set_time_at_start_volts(self):
        # value_le=300 → 300 seconds (G12 stores raw seconds, no conversion)
        g = self._make_g12()
        msg = self._make_1fed9_msg(selector=0x0C, value_le=300, function=0xD1)
        result = g.process_rvc_msg(msg)
        self.assertTrue(result)
        g.mqtt_support.client.publish.assert_called_once_with(
            'g12/status/aes/time_at_start_volts', 300, retain=True)

    def test_1fed9_set_time_at_stop_volts(self):
        # value_le=600 → 600 seconds (G12 stores raw seconds, no conversion)
        g = self._make_g12()
        msg = self._make_1fed9_msg(selector=0x0E, value_le=600, function=0xD1)
        result = g.process_rvc_msg(msg)
        self.assertTrue(result)
        g.mqtt_support.client.publish.assert_called_once_with(
            'g12/status/aes/time_at_stop_volts', 600, retain=True)

    def test_1fed9_set_start_at_voltage(self):
        # value_le=248 → round(248 * 0.05, 2) = 12.4
        g = self._make_g12()
        msg = self._make_1fed9_msg(selector=0x31, value_le=248, function=0xD1)
        result = g.process_rvc_msg(msg)
        self.assertTrue(result)
        g.mqtt_support.client.publish.assert_called_once_with(
            'g12/status/aes/start_at_voltage', 12.4, retain=True)

    def test_1fed9_set_threshold_cc(self):
        g = self._make_g12()
        msg = self._make_1fed9_msg(selector=0xCC, value_le=1000, function=0xD1)
        result = g.process_rvc_msg(msg)
        self.assertTrue(result)
        g.mqtt_support.client.publish.assert_called_once_with(
            'g12/status/tanks/threshold_33_pct', 1000, retain=True)

    def test_1fed9_set_threshold_cd(self):
        g = self._make_g12()
        msg = self._make_1fed9_msg(selector=0xCD, value_le=2000, function=0xD1)
        result = g.process_rvc_msg(msg)
        self.assertTrue(result)
        g.mqtt_support.client.publish.assert_called_once_with(
            'g12/status/tanks/threshold_66_pct', 2000, retain=True)

    def test_1fed9_set_threshold_ce(self):
        g = self._make_g12()
        msg = self._make_1fed9_msg(selector=0xCE, value_le=3000, function=0xD1)
        result = g.process_rvc_msg(msg)
        self.assertTrue(result)
        g.mqtt_support.client.publish.assert_called_once_with(
            'g12/status/tanks/threshold_100_pct', 3000, retain=True)

    def test_1fed9_set_quiet_time_stop(self):
        g = self._make_g12()
        data = bytearray(8)
        data[0] = 0xFF
        data[1] = 0x96
        data[2] = 0x2C  # selector = quiet time stop
        data[3] = 0x0F
        data[4] = 0      # minutes
        data[5] = 7      # hours
        data[6] = 0xD1
        data[7] = 0xEA
        msg = {'name': 'GENERIC_INDICATOR_COMMAND', 'source_id': '9F',
               'group': '10010110', 'function': 0xD1, 'data': data.hex().upper()}
        result = g.process_rvc_msg(msg)
        self.assertTrue(result)
        g.mqtt_support.client.publish.assert_called_once_with(
            'g12/status/aes/quiet_time_stop', '07:00', retain=True)

    def test_1fed9_invalid_group_string_returns_false(self):
        # group field that can't be parsed as base-2 → returns False
        msg = {'name': 'GENERIC_INDICATOR_COMMAND', 'source_id': '9F',
               'group': 'not_binary', 'function': 0xD1,
               'data': 'FF96160F7300D1EA'}
        g = self._make_g12()
        result = g.process_rvc_msg(msg)
        self.assertFalse(result)

    def test_1fed9_short_data_returns_false(self):
        # data shorter than 7 bytes
        msg = {'name': 'GENERIC_INDICATOR_COMMAND', 'source_id': '9F',
               'group': '10010110', 'function': 0xD1,
               'data': 'FF9616'}
        g = self._make_g12()
        result = g.process_rvc_msg(msg)
        self.assertFalse(result)

    def test_msg_type_cd_publishes_threshold(self):
        g = self._make_g12()
        msg = {'name': 'G12_CONFIGURATION', 'source_id': '9C',
               'message_type': 'CD', 'value': 2000}
        result = g.process_rvc_msg(msg)
        self.assertTrue(result)
        g.mqtt_support.client.publish.assert_called_once_with(
            'g12/status/tanks/threshold_66_pct', 2000, retain=True)

    def test_msg_type_ce_publishes_threshold(self):
        g = self._make_g12()
        msg = {'name': 'G12_CONFIGURATION', 'source_id': '9C',
               'message_type': 'CE', 'value': 3000}
        result = g.process_rvc_msg(msg)
        self.assertTrue(result)
        g.mqtt_support.client.publish.assert_called_once_with(
            'g12/status/tanks/threshold_100_pct', 3000, retain=True)

    def test_msg_type_unknown_returns_true_no_publish(self):
        g = self._make_g12()
        msg = {'name': 'G12_CONFIGURATION', 'source_id': '9C', 'message_type': 'FF'}
        result = g.process_rvc_msg(msg)
        self.assertTrue(result)
        g.mqtt_support.client.publish.assert_not_called()

    def test_data_packet_decode_error_resets_state(self):
        # Trigger the except block by pre-loading a packet with non-ASCII bytes so
        # trimmed.decode('ascii') raises UnicodeDecodeError.
        g = self._make_g12()
        g.process_rvc_msg({'name': 'INITIAL_PACKET', 'source_id': '9C',
                            'packet_count': 2, 'message_length': 14})
        g._mp_packets[1] = b'\xff' * 7  # inject non-ASCII → decode will fail
        result = g.process_rvc_msg({'name': 'DATA_PACKET', 'source_id': '9C',
                                     'packet_number': 2, 'data': 0})
        self.assertTrue(result)
        # finally block always resets state, even on error
        self.assertEqual(g._mp_expected_count, 0)
        self.assertEqual(g._mp_packets, {})


    # --- G12_INPUT_STATUS (1FBDA) tests ---

    def _make_input_status(self, active_input_code, aux_12v_active=0, source_id='9C'):
        return {
            'name': 'G12_INPUT_STATUS',
            'source_id': source_id,
            'active_input_code': active_input_code,
            'aux_12v_active': aux_12v_active,
        }

    def test_input_status_wrong_source_id_not_processed(self):
        g = self._make_g12()
        result = g.process_rvc_msg(self._make_input_status(0xA1, source_id='FF'))
        self.assertFalse(result)

    def test_input_status_idle_no_publish_on_first_message(self):
        # First message with idle (uninitialized → 0): no previous active input to clear
        g = self._make_g12()
        result = g.process_rvc_msg(self._make_input_status(0xFB))
        self.assertTrue(result)
        g.mqtt_support.client.publish.assert_not_called()

    def test_input_status_input1_active_publishes_true(self):
        g = self._make_g12()
        result = g.process_rvc_msg(self._make_input_status(0xA1))
        self.assertTrue(result)
        calls = {c[0][0]: c[0][1] for c in g.mqtt_support.client.publish.call_args_list}
        self.assertEqual(calls.get('g12/status/inputs/1/active'), 'true')

    def test_input_status_input2_active_publishes_true(self):
        g = self._make_g12()
        result = g.process_rvc_msg(self._make_input_status(0xA2))
        self.assertTrue(result)
        calls = {c[0][0]: c[0][1] for c in g.mqtt_support.client.publish.call_args_list}
        self.assertEqual(calls.get('g12/status/inputs/2/active'), 'true')

    def test_input_status_input4_active_publishes_true(self):
        g = self._make_g12()
        result = g.process_rvc_msg(self._make_input_status(0xA4))
        self.assertTrue(result)
        calls = {c[0][0]: c[0][1] for c in g.mqtt_support.client.publish.call_args_list}
        self.assertEqual(calls.get('g12/status/inputs/4/active'), 'true')

    def test_input_status_input9_active_publishes_true(self):
        g = self._make_g12()
        result = g.process_rvc_msg(self._make_input_status(0xA9, aux_12v_active=1))
        self.assertTrue(result)
        calls = {c[0][0]: c[0][1] for c in g.mqtt_support.client.publish.call_args_list}
        self.assertEqual(calls.get('g12/status/inputs/9/active'), 'true')

    def test_input_status_input10_active_publishes_true(self):
        g = self._make_g12()
        result = g.process_rvc_msg(self._make_input_status(0xAA, aux_12v_active=1))
        self.assertTrue(result)
        calls = {c[0][0]: c[0][1] for c in g.mqtt_support.client.publish.call_args_list}
        self.assertEqual(calls.get('g12/status/inputs/10/active'), 'true')

    def test_input_status_deactivate_publishes_false(self):
        # Input active then goes idle: publish false on the previously active input
        g = self._make_g12()
        g.process_rvc_msg(self._make_input_status(0xA1))
        g.mqtt_support.client.publish.reset_mock()
        g.process_rvc_msg(self._make_input_status(0xFB))
        calls = {c[0][0]: c[0][1] for c in g.mqtt_support.client.publish.call_args_list}
        self.assertEqual(calls.get('g12/status/inputs/1/active'), 'false')
        self.assertNotIn('g12/status/inputs/0/active', calls)

    def test_input_status_two_gnd_inputs_simultaneously_active(self):
        # Two GND inputs seen without an idle frame between them — both are active.
        g = self._make_g12()
        g.process_rvc_msg(self._make_input_status(0xA1))
        g.process_rvc_msg(self._make_input_status(0xA2))
        calls = {c[0][0]: c[0][1] for c in g.mqtt_support.client.publish.call_args_list}
        self.assertEqual(calls.get('g12/status/inputs/1/active'), 'true')
        self.assertEqual(calls.get('g12/status/inputs/2/active'), 'true')
        # Neither is deactivated yet
        self.assertNotEqual(calls.get('g12/status/inputs/1/active'), 'false')

    def test_input_status_gnd_input_deactivates_on_idle(self):
        # GND input deactivates when an idle (FB00) frame appears with aux=0.
        g = self._make_g12()
        g.process_rvc_msg(self._make_input_status(0xA1))
        g.mqtt_support.client.publish.reset_mock()
        g.process_rvc_msg(self._make_input_status(0xFB, aux_12v_active=0))
        calls = {c[0][0]: c[0][1] for c in g.mqtt_support.client.publish.call_args_list}
        self.assertEqual(calls.get('g12/status/inputs/1/active'), 'false')

    def test_input_status_no_publish_when_unchanged(self):
        g = self._make_g12()
        msg = self._make_input_status(0xA1)
        g.process_rvc_msg(msg)
        g.mqtt_support.client.publish.reset_mock()
        g.process_rvc_msg(msg)
        g.mqtt_support.client.publish.assert_not_called()

    def test_input_status_unexpected_code_treated_as_idle_no_publish(self):
        # Unrecognised code with no prior active input → treated as idle, nothing to clear
        g = self._make_g12()
        result = g.process_rvc_msg(self._make_input_status(0x42))
        self.assertTrue(result)
        g.mqtt_support.client.publish.assert_not_called()

    def test_input_status_fb_with_aux_12v_suppressed(self):
        # While a 12V input is held the G12 alternates the active code with 0xFB (aux=1
        # throughout).  The FB heartbeat must NOT toggle the topic to false.
        g = self._make_g12()
        g.process_rvc_msg(self._make_input_status(0xAA, aux_12v_active=1))  # input 10 active
        g.mqtt_support.client.publish.reset_mock()
        g.process_rvc_msg(self._make_input_status(0xFB, aux_12v_active=1))  # heartbeat
        g.mqtt_support.client.publish.assert_not_called()

    def test_input_status_aa00_deactivates_12v_input(self):
        # AA00 = active code with aux_12v_active dropped: the G12 signals 12V deactivation.
        # The known-12V-input check must publish false without waiting for a BF/FB code.
        g = self._make_g12()
        g.process_rvc_msg(self._make_input_status(0xAA, aux_12v_active=1))  # input 10 active
        g.process_rvc_msg(self._make_input_status(0xFB, aux_12v_active=1))  # heartbeat, skipped
        g.mqtt_support.client.publish.reset_mock()
        g.process_rvc_msg(self._make_input_status(0xAA, aux_12v_active=0))  # 12V dropped
        calls = {c[0][0]: c[0][1] for c in g.mqtt_support.client.publish.call_args_list}
        self.assertEqual(calls.get('g12/status/inputs/10/active'), 'false')
        self.assertNotIn('g12/status/inputs/0/active', calls)

    def test_input_status_deactivation_sequence_fb00_then_aa00(self):
        # Observed sequence: FB00 publishes false, subsequent AA00 must be a no-op.
        # _known_12v_codes persists after FB00 so the trailing AA00 is still recognised
        # as a 12V deactivation frame (was_active=False → no publish).
        g = self._make_g12()
        g.process_rvc_msg(self._make_input_status(0xAA, aux_12v_active=1))  # input 10 active
        g.process_rvc_msg(self._make_input_status(0xFB, aux_12v_active=1))  # heartbeat, skipped
        g.process_rvc_msg(self._make_input_status(0xFB, aux_12v_active=0))  # true deactivation
        g.mqtt_support.client.publish.reset_mock()
        g.process_rvc_msg(self._make_input_status(0xAA, aux_12v_active=0))  # trailing AA00, no-op
        g.mqtt_support.client.publish.assert_not_called()

    def test_input_status_simultaneous_inputs_12v_and_gnd(self):
        # Observed real-world scenario: ignition (input 10, 12V-type) held while a GND
        # light switch (input 4) is briefly pressed.
        # Sequence: AA01 → A401 → FB01 → AA01 → A400
        # Expected: input 10 stays active throughout; input 4 activates then deactivates.
        g = self._make_g12()
        g.process_rvc_msg(self._make_input_status(0xAA, aux_12v_active=1))   # input 10 active
        g.process_rvc_msg(self._make_input_status(0xFB, aux_12v_active=1))   # heartbeat, skipped
        g.mqtt_support.client.publish.reset_mock()

        g.process_rvc_msg(self._make_input_status(0xA4, aux_12v_active=1))   # input 4 pressed
        calls_after_press = {c[0][0]: c[0][1] for c in g.mqtt_support.client.publish.call_args_list}
        self.assertEqual(calls_after_press.get('g12/status/inputs/4/active'), 'true')
        # Input 10 must NOT be deactivated when input 4 appears
        self.assertNotIn('g12/status/inputs/10/active', calls_after_press)

        g.mqtt_support.client.publish.reset_mock()
        g.process_rvc_msg(self._make_input_status(0xFB, aux_12v_active=1))   # heartbeat (both held)
        g.process_rvc_msg(self._make_input_status(0xAA, aux_12v_active=1))   # input 10 still active

        g.mqtt_support.client.publish.reset_mock()
        g.process_rvc_msg(self._make_input_status(0xA4, aux_12v_active=0))   # input 4 released
        calls_after_release = {c[0][0]: c[0][1] for c in g.mqtt_support.client.publish.call_args_list}
        self.assertEqual(calls_after_release.get('g12/status/inputs/4/active'), 'false')
        # Input 10 must still NOT be affected
        self.assertNotIn('g12/status/inputs/10/active', calls_after_release)

        # Input 10 is still active
        self.assertIn(10, g._active_inputs)

    def test_input_status_12v_input_stays_active_across_gnd_cycle(self):
        # After the GND input releases, the 12V input's heartbeat continues unaffected.
        g = self._make_g12()
        g.process_rvc_msg(self._make_input_status(0xAA, aux_12v_active=1))   # input 10 active
        g.process_rvc_msg(self._make_input_status(0xA4, aux_12v_active=1))   # input 4 pressed
        g.process_rvc_msg(self._make_input_status(0xA4, aux_12v_active=0))   # input 4 released
        g.mqtt_support.client.publish.reset_mock()
        # Continued heartbeat for input 10 must be suppressed (no publish)
        g.process_rvc_msg(self._make_input_status(0xFB, aux_12v_active=1))
        g.mqtt_support.client.publish.assert_not_called()
        # And input 10 remains active
        self.assertIn(10, g._active_inputs)


class Test_G12_ConfigurationHADiscovery(unittest.TestCase):

    def _make_g12_for_discovery(self):
        mock = MagicMock()
        mock.make_device_topic_string.return_value = 'topic_string'
        mock.make_ha_auto_discovery_config_topic.return_value = 'ha/config/topic'
        mock.get_bridge_ha_name.return_value = 'rvc2mqtt_bridge'
        mock.bridge_state_topic = 'rvc2mqtt/bridge/state'
        mock.TOPIC_BASE = 'rvc2mqtt'
        mock.client_id = 'bridge'
        return G12_Configuration(
            {'instance': 1, 'instance_name': 'Generator Controller',
             'source_id': '9C',
             'status_topic': 'g12/status', 'command_topic': 'g12/set'},
            mock
        )

    def _make_g12_no_status_topic(self):
        mock = MagicMock()
        mock.make_device_topic_string.return_value = 'topic_string'
        mock.make_ha_auto_discovery_config_topic.return_value = 'ha/config/topic'
        mock.TOPIC_BASE = 'rvc2mqtt'
        mock.client_id = 'bridge'
        return G12_Configuration(
            {'instance': 1, 'instance_name': 'Generator Controller', 'source_id': '9C'},
            mock
        )

    def test_publish_ha_discovery_config_no_status_topic_skips(self):
        g = self._make_g12_no_status_topic()
        g.publish_ha_discovery_config()
        g.mqtt_support.client.publish.assert_not_called()

    def test_publish_ha_discovery_config_all_retain_false(self):
        g = self._make_g12_for_discovery()
        g.publish_ha_discovery_config()
        for c in g.mqtt_support.client.publish.call_args_list:
            self.assertFalse(c[1].get('retain', c[0][2] if len(c[0]) > 2 else False),
                             f"Unexpected retain=True in call: {c}")

    def _get_published_configs(self, g):
        """Return list of component dicts from the single device config publish call."""
        import json as _json
        for c in g.mqtt_support.client.publish.call_args_list:
            try:
                payload = _json.loads(c[0][1])
                if 'cmps' in payload:
                    return list(payload['cmps'].values())
            except Exception:
                pass
        return []

    def test_publish_ha_discovery_config_publishes_number_for_max_engine_run_time(self):
        import json as _json
        g = self._make_g12_for_discovery()
        g.publish_ha_discovery_config()
        configs = self._get_published_configs(g)
        matches = [c for c in configs
                   if c.get('unit_of_measurement') == 'min'
                   and 'state_topic' in c and 'command_topic' in c]
        self.assertEqual(len(matches), 1)
        self.assertIn('max_engine_run_time', matches[0]['unique_id'])

    def test_publish_ha_discovery_config_publishes_number_for_stop_at_voltage(self):
        g = self._make_g12_for_discovery()
        g.publish_ha_discovery_config()
        configs = self._get_published_configs(g)
        matches = [c for c in configs
                   if c.get('device_class') == 'voltage'
                   and 'stop_at_voltage' in c.get('unique_id', '')]
        self.assertEqual(len(matches), 1)

    def test_publish_ha_discovery_config_publishes_text_for_quiet_time_start(self):
        g = self._make_g12_for_discovery()
        g.publish_ha_discovery_config()
        configs = self._get_published_configs(g)
        matches = [c for c in configs
                   if 'pattern' in c
                   and 'quiet_time_start' in c.get('unique_id', '')]
        self.assertEqual(len(matches), 1)

    def test_publish_ha_discovery_config_publishes_text_for_quiet_time_stop(self):
        g = self._make_g12_for_discovery()
        g.publish_ha_discovery_config()
        configs = self._get_published_configs(g)
        matches = [c for c in configs
                   if 'pattern' in c
                   and 'quiet_time_stop' in c.get('unique_id', '')]
        self.assertEqual(len(matches), 1)

    def test_publish_ha_discovery_config_publishes_binary_sensor_for_fault_lamp(self):
        g = self._make_g12_for_discovery()
        g.publish_ha_discovery_config()
        configs = self._get_published_configs(g)
        matches = [c for c in configs
                   if c.get('device_class') == 'problem'
                   and 'fault_lamp' in c.get('unique_id', '')]
        self.assertEqual(len(matches), 1)

    def test_publish_ha_discovery_config_publishes_sensor_for_fault_code(self):
        g = self._make_g12_for_discovery()
        g.publish_ha_discovery_config()
        configs = self._get_published_configs(g)
        matches = [c for c in configs if 'fault_code' in c.get('unique_id', '')]
        self.assertEqual(len(matches), 1)

    def test_publish_ha_discovery_config_publishes_sensor_for_product_id_disabled_by_default(self):
        g = self._make_g12_for_discovery()
        g.publish_ha_discovery_config()
        configs = self._get_published_configs(g)
        matches = [c for c in configs
                   if 'product_id' in c.get('unique_id', '')
                   and c.get('enabled_by_default') is False]
        self.assertEqual(len(matches), 1)

    def test_publish_ha_discovery_config_publishes_15_input_binary_sensors(self):
        g = self._make_g12_for_discovery()
        g.publish_ha_discovery_config()
        configs = self._get_published_configs(g)
        matches = [c for c in configs if '_input_' in c.get('unique_id', '')]
        self.assertEqual(len(matches), 15)

    def test_initialize_calls_publish_ha_discovery_config(self):
        from unittest.mock import patch
        g = self._make_g12_for_discovery()
        with patch.object(g, 'publish_ha_discovery_config') as mock_pub:
            g.initialize()
            mock_pub.assert_called_once()


if __name__ == '__main__':
    unittest.main()
