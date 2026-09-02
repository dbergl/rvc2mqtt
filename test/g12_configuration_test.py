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

    def _make_g12(self, source_id='9C', engine_relay_instance=None):
        mock = MagicMock()
        mock.mqtt_support.make_device_topic_string.return_value = 'topic_string'
        data = {'instance': 1, 'instance_name': "test g12", 'source_id': source_id,
                'status_topic': 'g12/status', 'command_topic': 'g12/set'}
        if engine_relay_instance is not None:
            data['engine_relay_instance'] = engine_relay_instance
        return G12_Configuration(data, mock)

    def _make_g12_with_engine(self, source_id='9C', engine_relay_instance=18):
        return self._make_g12(source_id, engine_relay_instance)

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

    def test_msg_type_16_discards_implausible_max_engine_run_time(self):
        """Observed on the coach 2026-09-01: a mode switch was followed by bursts of
        65531 and 0 on this topic, both outside any real AES/AGS range."""
        g = self._make_g12()
        msg = {'name': 'G12_CONFIGURATION', 'source_id': '9C', 'message_type': '16', 'minutes': 65531}
        result = g.process_rvc_msg(msg)
        self.assertTrue(result)
        g.mqtt_support.client.publish.assert_not_called()
        self.assertEqual(g._max_engine_run_time, "unknown")

    def test_msg_type_0e_discards_implausible_time_at_stop_volts(self):
        g = self._make_g12()
        # duration is *2 on the wire; 20000 -> 10000s, above the 7200s AGS ceiling
        msg = {'name': 'G12_CONFIGURATION', 'source_id': '9C', 'message_type': 'E', 'duration': 20000}
        result = g.process_rvc_msg(msg)
        self.assertTrue(result)
        g.mqtt_support.client.publish.assert_not_called()
        self.assertEqual(g._time_at_stop_volts, "unknown")

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
            'g12/status/aes/quiet_time_start', '22:30:00', retain=True)

    def test_msg_type_2c_publishes_quiet_time_stop(self):
        g = self._make_g12()
        msg = {'name': 'G12_CONFIGURATION', 'source_id': '9C', 'message_type': '2C',
               'hours': 7, 'minutes': 0}
        result = g.process_rvc_msg(msg)
        self.assertTrue(result)
        g.mqtt_support.client.publish.assert_called_once_with(
            'g12/status/aes/quiet_time_stop', '07:00:00', retain=True)

    def test_msg_type_cc_publishes_threshold(self):
        g = self._make_g12()
        msg = {'name': 'G12_CONFIGURATION', 'source_id': '9C', 'message_type': 'CC', 'value': 1000}
        result = g.process_rvc_msg(msg)
        self.assertTrue(result)
        g.mqtt_support.client.publish.assert_called_once_with(
            'g12/status/tanks/threshold_33_pct', 1000, retain=True)

    def test_aes_messages_return_true_no_publish(self):
        g = self._make_g12()
        for msg_type in ('1', '3', '5'):
            g.mqtt_support.client.publish.reset_mock()
            msg = {'name': 'G12_CONFIGURATION', 'source_id': '9C', 'message_type': msg_type}
            result = g.process_rvc_msg(msg)
            self.assertTrue(result)
            g.mqtt_support.client.publish.assert_not_called()

    def test_aes_enabled_from_15fce_reads_byte_2(self):
        """15FCE carries its value at byte 2, not byte 4.

        Payloads captured off the coach: 9B00010000000000 while AES was enabled on the
        touchscreen, 9B00000000000000 after disabling it. Reading byte 4 made this always
        report 'off' and clobbered the state every ~5s.
        """
        for data, expected in (('9B00010000000000', 'on'), ('9B00000000000000', 'off')):
            g = self._make_g12()
            msg = {'name': 'G12_CONFIGURATION', 'source_id': '9C',
                   'message_type': '9B', 'data': data}
            self.assertTrue(g.process_rvc_msg(msg))
            g.mqtt_support.client.publish.assert_called_once_with(
                'g12/status/aes/enabled', expected, retain=True)

    def test_aes_enabled_15fce_does_not_clobber_snooped_state(self):
        """A snooped touchscreen enable must survive the G12's own broadcast."""
        g = self._make_g12()
        g.process_rvc_msg({'name': 'GENERIC_INDICATOR_COMMAND', 'group': '10010110',
                           'data': 'FF969B0F0100D1FF'})
        g.mqtt_support.client.publish.assert_called_once_with(
            'g12/status/aes/enabled', 'on', retain=True)
        g.mqtt_support.client.publish.reset_mock()
        g.process_rvc_msg({'name': 'G12_CONFIGURATION', 'source_id': '9C',
                           'message_type': '9B', 'data': '9B00010000000000'})
        g.mqtt_support.client.publish.assert_not_called()

    def test_1fed9_discards_implausible_max_engine_run_time(self):
        """Same 65531 garbage as the 15FCE broadcast case, but arriving via a snooped
        1FED9 selector 0x16 frame instead."""
        g = self._make_g12()
        g.process_rvc_msg({'name': 'GENERIC_INDICATOR_COMMAND', 'group': '10010110',
                           'data': 'FF96160FFBFFD1EA'})
        g.mqtt_support.client.publish.assert_not_called()
        self.assertEqual(g._max_engine_run_time, "unknown")

    def test_1fed9_discards_implausible_time_at_stop_volts(self):
        g = self._make_g12()
        g.process_rvc_msg({'name': 'GENERIC_INDICATOR_COMMAND', 'group': '10010110',
                           'data': 'FF960E0F204ED1EA'})
        g.mqtt_support.client.publish.assert_not_called()
        self.assertEqual(g._time_at_stop_volts, "unknown")

    def test_aes_enabled_short_payload_warns(self):
        g = self._make_g12()
        msg = {'name': 'G12_CONFIGURATION', 'source_id': '9C',
               'message_type': '9B', 'data': '9B'}
        self.assertTrue(g.process_rvc_msg(msg))
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

    # --- Engine relay (DC_DIMMER_STATUS_3 on engine_relay_instance) tests ---

    def _make_engine_relay_msg(self, source_id='9C', instance=18, brightness=100.0):
        return {
            'name': 'DC_DIMMER_STATUS_3',
            'source_id': source_id,
            'instance': instance,
            'operating_status_brightness': brightness,
        }

    def test_engine_relay_on_when_brightness_nonzero(self):
        g = self._make_g12_with_engine()
        result = g.process_rvc_msg(self._make_engine_relay_msg(brightness=100.0))
        self.assertTrue(result)
        publish_calls = {c[0][0]: c[0][1]
                         for c in g.mqtt_support.client.publish.call_args_list}
        self.assertEqual(publish_calls.get('g12/status/engine/running'), 'on')

    def test_engine_relay_off_when_brightness_zero(self):
        g = self._make_g12_with_engine()
        result = g.process_rvc_msg(self._make_engine_relay_msg(brightness=0))
        self.assertTrue(result)
        publish_calls = {c[0][0]: c[0][1]
                         for c in g.mqtt_support.client.publish.call_args_list}
        self.assertEqual(publish_calls.get('g12/status/engine/running'), 'off')

    def test_engine_relay_honours_configured_instance(self):
        g = self._make_g12_with_engine(engine_relay_instance=7)
        self.assertTrue(g.process_rvc_msg(self._make_engine_relay_msg(instance=7)))
        # 18 is no longer special once the floorplan names a different channel
        self.assertFalse(g.process_rvc_msg(self._make_engine_relay_msg(instance=18)))

    def test_engine_relay_wrong_instance_ignored(self):
        g = self._make_g12_with_engine()
        # Must return False: the G12 broadcasts DC_DIMMER_STATUS_3 for every dimmer
        # channel and app.py stops at the first entity that claims a message, so
        # claiming these would starve the dimmer entities of their own status.
        result = g.process_rvc_msg(self._make_engine_relay_msg(instance=1, brightness=100.0))
        self.assertFalse(result)
        publish_calls = {c[0][0]: c[0][1]
                         for c in g.mqtt_support.client.publish.call_args_list}
        self.assertNotIn('g12/status/engine/running', publish_calls)

    def test_engine_relay_wrong_source_id_ignored(self):
        g = self._make_g12_with_engine()
        result = g.process_rvc_msg(self._make_engine_relay_msg(source_id='FF', brightness=100.0))
        self.assertFalse(result)

    def test_engine_relay_no_publish_when_state_unchanged(self):
        g = self._make_g12_with_engine()
        g.process_rvc_msg(self._make_engine_relay_msg(brightness=100.0))
        g.mqtt_support.client.publish.reset_mock()
        g.process_rvc_msg(self._make_engine_relay_msg(brightness=50.0))  # still on
        publish_calls = {c[0][0]: c[0][1]
                         for c in g.mqtt_support.client.publish.call_args_list}
        self.assertNotIn('g12/status/engine/running', publish_calls)

    # --- Engine relay not declared in the floorplan: fully opt-in ---

    def test_no_engine_relay_instance_does_not_claim_dimmer_status(self):
        g = self._make_g12()
        for instance in (1, 15, 18, 32):
            self.assertFalse(
                g.process_rvc_msg(self._make_engine_relay_msg(instance=instance)),
                f"instance {instance} must fall through to the dimmer entities")
        g.mqtt_support.client.publish.assert_not_called()

    def test_no_engine_relay_instance_creates_no_engine_topics(self):
        g = self._make_g12()
        self.assertFalse(hasattr(g, 'engine_running_topic'))
        self.assertFalse(hasattr(g, 'engine_start_set_topic'))

    def test_engine_start_command_uses_configured_instance(self):
        g = self._make_g12_with_engine(engine_relay_instance=7)
        g.set_rvc_send_queue(queue.Queue())
        g.process_mqtt_msg('g12/set/engine/start', 'on')
        sent = g.send_queue.get_nowait()
        self.assertEqual(sent['dgn'], '1FEDB')
        self.assertEqual(sent['data'][0], 7)   # instance byte
        self.assertEqual(sent['data'][3], 0x01)  # command = on_duration

    def test_engine_stop_command_uses_configured_instance(self):
        g = self._make_g12_with_engine(engine_relay_instance=7)
        g.set_rvc_send_queue(queue.Queue())
        g.process_mqtt_msg('g12/set/engine/start', 'off')
        sent = g.send_queue.get_nowait()
        self.assertEqual(sent['data'][0], 7)
        self.assertEqual(sent['data'][3], 0x03)  # command = off

    # --- AES disable frame sequence (captured from the touchscreen) ---

    def _drain(self, g):
        out = []
        while not g.send_queue.empty():
            out.append(g.send_queue.get_nowait())
        return out

    def test_aes_disable_sends_engine_relay_off_without_floorplan_key(self):
        """The engine-relay off frame is part of a byte-verified capture, so it is
        sent even when the floorplan never declared engine_relay_instance. AES
        1-wire operation always uses channel 18."""
        g = self._make_g12()
        g.set_rvc_send_queue(queue.Queue())
        g.process_mqtt_msg('g12/set/aes/enabled', 'off')
        sent = self._drain(g)
        self.assertEqual([s['dgn'] for s in sent],
                         ['1FED9'] * 6 + ['1FEDB'] + ['1FED9'] * 3)
        relay = sent[6]
        self.assertEqual(relay['data'][0], 18)
        self.assertEqual(relay['data'][3], 0x03)  # command = off

    def test_aes_disable_engine_relay_frame_uses_configured_instance(self):
        """A 2-wire coach declares its own channel; the AES sequence must follow it."""
        g = self._make_g12_with_engine(engine_relay_instance=7)
        g.set_rvc_send_queue(queue.Queue())
        g.process_mqtt_msg('g12/set/aes/enabled', 'off')
        sent = self._drain(g)
        self.assertEqual([s['dgn'] for s in sent],
                         ['1FED9'] * 6 + ['1FEDB'] + ['1FED9'] * 3)
        self.assertEqual(sent[6]['data'][0], 7)

    def test_aes_enable_sends_no_engine_relay_frame(self):
        g = self._make_g12_with_engine()
        g.set_rvc_send_queue(queue.Queue())
        g.process_mqtt_msg('g12/set/aes/enabled', 'on')
        sent = self._drain(g)
        self.assertTrue(sent)
        self.assertEqual({s['dgn'] for s in sent}, {'1FED9'})

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
            'g12/status/aes/quiet_time_start', '22:30:00', retain=True)

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

    # CC/CD/CE take a SIGNED DELTA, not an absolute value. Confirmed on hardware
    # 2026-08-12: the touchscreen arrows sent 64536 (-1000 as int16) and 1000, and the
    # stored value moved by exactly -1000 then +1000. These tests previously asserted
    # absolute writes, which would have ADDED the payload to the current threshold.

    def test_mqtt_set_threshold_cc_sends_delta(self):
        g, q = self._make_g12_with_queue()
        g._threshold_cc = 54000
        g.process_mqtt_msg('g12/set/tanks/threshold_33_pct', '53000')
        frame = q.get_nowait()['data']
        self.assertEqual(frame[2], 0xCC)
        self.assertEqual(int.from_bytes(frame[4:6], 'little', signed=True), -1000)

    def test_mqtt_set_threshold_cd_sends_delta(self):
        g, q = self._make_g12_with_queue()
        g._threshold_cd = 40000
        g.process_mqtt_msg('g12/set/tanks/threshold_66_pct', '42500')
        frame = q.get_nowait()['data']
        self.assertEqual(frame[2], 0xCD)
        self.assertEqual(int.from_bytes(frame[4:6], 'little', signed=True), 2500)

    def test_mqtt_set_threshold_ce_sends_delta(self):
        g, q = self._make_g12_with_queue()
        g._threshold_ce = 25000
        g.process_mqtt_msg('g12/set/tanks/threshold_100_pct', '24000')
        frame = q.get_nowait()['data']
        self.assertEqual(frame[2], 0xCE)
        self.assertEqual(int.from_bytes(frame[4:6], 'little', signed=True), -1000)

    def test_mqtt_set_threshold_negative_delta_is_twos_complement(self):
        """The wire value must match what the touchscreen sends: -1000 as 64536."""
        g, q = self._make_g12_with_queue()
        g._threshold_cc = 54000
        g.process_mqtt_msg('g12/set/tanks/threshold_33_pct', '53000')
        frame = q.get_nowait()['data']
        self.assertEqual(int.from_bytes(frame[4:6], 'little'), 64536)

    def test_mqtt_set_threshold_refuses_when_current_unknown(self):
        """Without a known current value a delta cannot be computed, and guessing would
        corrupt the coach's tank calibration. Refuse rather than send something wrong."""
        g, q = self._make_g12_with_queue()
        self.assertEqual(g._threshold_cc, "unknown")
        g.process_mqtt_msg('g12/set/tanks/threshold_33_pct', '53000')
        self.assertTrue(q.empty())

    def test_mqtt_set_threshold_no_change_sends_nothing(self):
        g, q = self._make_g12_with_queue()
        g._threshold_cc = 54000
        g.process_mqtt_msg('g12/set/tanks/threshold_33_pct', '54000')
        self.assertTrue(q.empty())

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
            'g12/status/aes/quiet_time_stop', '07:00:00', retain=True)

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


    # --- 0x92 max charge rate tests ---

    def _make_max_charge_rate(self, raw, source_id='9C'):
        return {'name': 'G12_CONFIGURATION', 'source_id': source_id,
                'message_type': '92', 'max_charge_rate_raw': raw}

    def test_max_charge_rate_halves_raw_value(self):
        """Raw is RV-C 0.5%/bit; the panel shows raw/2. 200 -> 100%."""
        g = self._make_g12()
        result = g.process_rvc_msg(self._make_max_charge_rate(200))
        self.assertTrue(result)
        g.mqtt_support.client.publish.assert_called_with(
            g.max_charge_rate_topic, 100.0, retain=True)

    def test_max_charge_rate_step_of_20_raw_is_10_pct(self):
        """The panel's own +/- step is 20 raw, which is 10% on screen."""
        g = self._make_g12()
        g.process_rvc_msg(self._make_max_charge_rate(200))
        g.mqtt_support.client.publish.reset_mock()
        g.process_rvc_msg(self._make_max_charge_rate(180))
        g.mqtt_support.client.publish.assert_called_with(
            g.max_charge_rate_topic, 90.0, retain=True)

    def test_max_charge_rate_unchanged_does_not_republish(self):
        g = self._make_g12()
        g.process_rvc_msg(self._make_max_charge_rate(200))
        g.mqtt_support.client.publish.reset_mock()
        g.process_rvc_msg(self._make_max_charge_rate(200))
        g.mqtt_support.client.publish.assert_not_called()

    def test_max_charge_rate_missing_field_ignored(self):
        g = self._make_g12()
        msg = {'name': 'G12_CONFIGURATION', 'source_id': '9C', 'message_type': '92'}
        result = g.process_rvc_msg(msg)
        self.assertTrue(result)
        g.mqtt_support.client.publish.assert_not_called()

    def test_max_charge_rate_is_read_only(self):
        """0x92 is a confirmed signed-delta selector, so no command topic is exposed."""
        g = self._make_g12()
        self.assertFalse(hasattr(g, 'max_charge_rate_set_topic'))

    # --- G12_INPUT_STATUS (1FBDA) tests ---
    #
    # Rewritten 2026-08-24 against BUS-BASELINE.md PC.24, which refuted the model the
    # previous tests encoded (byte 1 as a global 12V flag, 0xFB as an idle code, a
    # heartbeat needing suppression).  Frame bytes below are taken from that capture.

    def _make_input_status(self, instance, input_state=0, source_id='9C'):
        return {
            'name': 'G12_INPUT_STATUS',
            'source_id': source_id,
            'instance': instance,
            'input_state': input_state,
        }

    def test_input_status_wrong_source_id_not_processed(self):
        g = self._make_g12()
        result = g.process_rvc_msg(self._make_input_status(0xA1, 1, source_id='FF'))
        self.assertFalse(result)
        g.mqtt_support.client.publish.assert_not_called()

    def test_input_status_active_publishes_true(self):
        for instance, n in ((0xA1, 1), (0xA2, 2), (0xA4, 4), (0xA9, 9), (0xAA, 10)):
            with self.subTest(instance=hex(instance)):
                g = self._make_g12()
                result = g.process_rvc_msg(self._make_input_status(instance, 1))
                self.assertTrue(result)
                g.mqtt_support.client.publish.assert_called_with(
                    f'g12/status/inputs/{n}/active', "true", retain=True)

    def test_input_status_inactive_publishes_false(self):
        """A pin deactivates via its OWN instance with byte 1 = 0, not via 0xFB."""
        g = self._make_g12()
        g.process_rvc_msg(self._make_input_status(0xA1, 1))
        g.mqtt_support.client.publish.reset_mock()
        g.process_rvc_msg(self._make_input_status(0xA1, 0))
        g.mqtt_support.client.publish.assert_called_with(
            'g12/status/inputs/1/active', "false", retain=True)

    def test_gnd_input_reports_state_with_ignition_off(self):
        """PC.24: pins 1/2/4 are GND-sense and report 01 held / 00 released with no 12V
        input active at all.  This is what refuted the global-aux-flag reading."""
        g = self._make_g12()
        for instance, n in ((0xA1, 1), (0xA2, 2), (0xA4, 4)):
            g.mqtt_support.client.publish.reset_mock()
            g.process_rvc_msg(self._make_input_status(instance, 1))
            g.mqtt_support.client.publish.assert_called_with(
                f'g12/status/inputs/{n}/active', "true", retain=True)
            g.mqtt_support.client.publish.reset_mock()
            g.process_rvc_msg(self._make_input_status(instance, 0))
            g.mqtt_support.client.publish.assert_called_with(
                f'g12/status/inputs/{n}/active', "false", retain=True)

    def test_fb_is_pin_10_not_an_idle_code(self):
        """0xFB is a second instance for pin 10, so FB01 ACTIVATES pin 10."""
        g = self._make_g12()
        g.process_rvc_msg(self._make_input_status(0xFB, 1))
        g.mqtt_support.client.publish.assert_called_with(
            'g12/status/inputs/10/active', "true", retain=True)

    def test_fb_does_not_clear_other_inputs(self):
        """The old handler read FB/aux=0 as 'all inputs released'.  PC.24 says it is pin 10
        alone, so a held pin 1 must survive an ignition-off."""
        g = self._make_g12()
        g.process_rvc_msg(self._make_input_status(0xA1, 1))     # pin 1 held
        g.process_rvc_msg(self._make_input_status(0xFB, 1))     # ignition on
        g.process_rvc_msg(self._make_input_status(0xAA, 1))
        g.mqtt_support.client.publish.reset_mock()
        g.process_rvc_msg(self._make_input_status(0xFB, 0))     # ignition off
        g.process_rvc_msg(self._make_input_status(0xAA, 0))
        published = [c[0] for c in g.mqtt_support.client.publish.call_args_list]
        self.assertIn(('g12/status/inputs/10/active', "false"), [(a, b) for a, b, *_ in published])
        self.assertNotIn('g12/status/inputs/1/active', [a for a, *_ in published])

    def test_fb_and_aa_pair_publishes_pin_10_once(self):
        """They arrive together ~0.6 ms apart, 14 times in PC.24.  One signal, one publish."""
        g = self._make_g12()
        g.process_rvc_msg(self._make_input_status(0xFB, 1))
        g.mqtt_support.client.publish.reset_mock()
        g.process_rvc_msg(self._make_input_status(0xAA, 1))
        g.mqtt_support.client.publish.assert_not_called()

    def test_one_hz_refresh_does_not_republish(self):
        """A held pin refreshes every 1.000 s.  A refresh means the same thing as the edge,
        so the change check makes it a no-op -- no suppression logic needed."""
        g = self._make_g12()
        g.process_rvc_msg(self._make_input_status(0xA1, 1))
        g.mqtt_support.client.publish.reset_mock()
        for _ in range(3):
            g.process_rvc_msg(self._make_input_status(0xA1, 1))
        g.mqtt_support.client.publish.assert_not_called()

    def test_bf_is_ignored(self):
        """0xBF brackets ignition-off with an all-zero tail.  Undecoded: act on nothing."""
        g = self._make_g12()
        g.process_rvc_msg(self._make_input_status(0xA1, 1))
        g.mqtt_support.client.publish.reset_mock()
        result = g.process_rvc_msg(self._make_input_status(0xBF, 1))
        self.assertTrue(result)
        g.mqtt_support.client.publish.assert_not_called()
        result = g.process_rvc_msg(self._make_input_status(0xBF, 0))
        self.assertTrue(result)
        g.mqtt_support.client.publish.assert_not_called()

    def test_unheard_pin_is_unknown_not_inactive(self):
        """An idle pin is silent, so silence carries no information."""
        g = self._make_g12()
        g.process_rvc_msg(self._make_input_status(0xA1, 1))
        published = [c[0][0] for c in g.mqtt_support.client.publish.call_args_list]
        for n in (2, 3, 4, 5, 6, 7, 8, 9, 10):
            self.assertNotIn(f'g12/status/inputs/{n}/active', published)

    def test_two_inputs_are_independent(self):
        g = self._make_g12()
        g.process_rvc_msg(self._make_input_status(0xA1, 1))
        g.process_rvc_msg(self._make_input_status(0xA2, 1))
        g.mqtt_support.client.publish.reset_mock()
        g.process_rvc_msg(self._make_input_status(0xA1, 0))
        calls = [(c[0][0], c[0][1]) for c in g.mqtt_support.client.publish.call_args_list]
        self.assertEqual(calls, [('g12/status/inputs/1/active', "false")])

    def test_pc24_ignition_then_pump_sequence(self):
        """The PC.24 capture in order: ignition held (with 1 Hz refresh), ignition off,
        then the water pump alone -- which produced NO 0xFB frames at all."""
        g = self._make_g12()
        pub = []
        g.mqtt_support.client.publish.side_effect = lambda t, v, **k: pub.append((t, v))
        for _ in range(13):                                   # 13 x (FB01, AA01) at 1 Hz
            g.process_rvc_msg(self._make_input_status(0xFB, 1))
            g.process_rvc_msg(self._make_input_status(0xAA, 1))
        g.process_rvc_msg(self._make_input_status(0xFB, 0))    # ignition off
        g.process_rvc_msg(self._make_input_status(0xAA, 0))
        g.process_rvc_msg(self._make_input_status(0xBF, 1))    # transition frames
        g.process_rvc_msg(self._make_input_status(0xBF, 0))
        g.process_rvc_msg(self._make_input_status(0xA9, 1))    # pump, no FB anywhere
        g.process_rvc_msg(self._make_input_status(0xA9, 1))
        g.process_rvc_msg(self._make_input_status(0xA9, 0))
        self.assertEqual(pub, [
            ('g12/status/inputs/10/active', "true"),
            ('g12/status/inputs/10/active', "false"),
            ('g12/status/inputs/9/active', "true"),
            ('g12/status/inputs/9/active', "false"),
        ])

    # --- selectors confirmed on hardware 2026-08-12 (Jayco B-Van, floorplan WD) ---

    def test_msg_type_eb_publishes_heat_pump(self):
        g = self._make_g12()
        msg = {'name': 'G12_CONFIGURATION', 'source_id': '9C', 'message_type': 'EB',
               'enabled_definition': 'on'}
        self.assertTrue(g.process_rvc_msg(msg))
        g.mqtt_support.client.publish.assert_called_once_with(
            'g12/status/hvac/heat_pump', 'on', retain=True)

    def test_msg_type_e4_publishes_bath_light(self):
        g = self._make_g12()
        msg = {'name': 'G12_CONFIGURATION', 'source_id': '9C', 'message_type': 'E4',
               'enabled_definition': 'on'}
        self.assertTrue(g.process_rvc_msg(msg))
        g.mqtt_support.client.publish.assert_called_once_with(
            'g12/status/lights/bath_light', 'on', retain=True)

    def test_msg_type_0a_publishes_battery_voltage(self):
        # 0x0A is the measured pack voltage; rvc.py has already applied the x0.05 scale.
        g = self._make_g12()
        msg = {'name': 'G12_CONFIGURATION', 'source_id': '9C', 'message_type': 'A',
               'volts': 52.95}
        self.assertTrue(g.process_rvc_msg(msg))
        g.mqtt_support.client.publish.assert_called_once_with(
            'g12/status/batteries/voltage', 52.95, retain=True)

    def test_mqtt_set_heat_pump(self):
        g, q = self._make_g12_with_queue()
        g.process_mqtt_msg('g12/set/hvac/heat_pump', 'on')
        frame = q.get_nowait()['data']
        self.assertEqual(frame[2], 0xEB)
        self.assertEqual(int.from_bytes(frame[4:6], 'little'), 1)
        self.assertEqual(frame[6], 0xD1)

    def test_mqtt_set_cargo_bath_light_writes_both_selectors(self):
        """E3/E4 are mutually exclusive, so a set must write both in opposite
        directions -- writing E3 alone reaches a state the coach never produces."""
        g, q = self._make_g12_with_queue()
        g.process_mqtt_msg('g12/set/lights/cargo_bath_ch25', 'on')

        sets = []
        while not q.empty():
            frame = q.get_nowait()['data']
            if frame[6] == 0xD1:                      # a set, not a read-back
                sets.append((frame[2], int.from_bytes(frame[4:6], 'little')))

        self.assertEqual(sets, [(0xE3, 1), (0xE4, 0)])

    def test_mqtt_set_cargo_bath_light_off_selects_bath_light(self):
        g, q = self._make_g12_with_queue()
        g.process_mqtt_msg('g12/set/lights/cargo_bath_ch25', 'off')

        sets = []
        while not q.empty():
            frame = q.get_nowait()['data']
            if frame[6] == 0xD1:
                sets.append((frame[2], int.from_bytes(frame[4:6], 'little')))

        self.assertEqual(sets, [(0xE3, 0), (0xE4, 1)])

    def test_floorplan_defaults_table_is_internally_consistent(self):
        """Per-build data, observed on the coach. Guards the transcription."""
        from rvc2mqtt.entity.g12_configuration import FLOORPLAN_OPTION_DEFAULTS as D
        self.assertEqual(sorted(D), list(range(1, 11)))
        selectors = {0xEB, 0xE5, 0xE9, 0xE3, 0xE4, 0xEC, 0xEF, 0xE6, 0xD7, 0xD8}
        for value, row in D.items():
            self.assertEqual(set(row), selectors, f"floorplan {value}")
        # Heat pump and bath light default off on every floorplan.
        self.assertTrue(all(r[0xEB] == 0 and r[0xE4] == 0 for r in D.values()))
        # Progressive inverter and Go Power! count move together in every row.
        self.assertTrue(all(r[0xE6] == r[0xD7] for r in D.values()))
        # SY is the only floorplan defaulting to EF=0 (mode disabled).
        self.assertEqual([v for v, r in D.items() if r[0xEF] == 0], [4])

    def test_setting_floorplan_warns_about_options_it_will_reset(self):
        """Changing floorplan is not a neutral write -- the touchscreen sends the new
        floorplan's defaults alongside F5. The operator must be told what it costs."""
        g, q = self._make_g12_with_queue()
        # Coach state: bunk accent and cargo/bath on, matching WD's defaults.
        g._bunk_accent = 'on'
        g._cargo_bath_light = 'on'
        g._black_tank_setting = 'on'
        with self.assertLogs('G12_Configuration', level='WARNING') as captured:
            g.process_mqtt_msg('g12/set/floorplan', 'tb')   # TB defaults both off
        joined = ' '.join(captured.output)
        self.assertIn('bunk accent on->off', joined)
        self.assertIn('cargo/bath light (ch.25) on->off', joined)
        self.assertNotIn('black tank', joined)   # TB also defaults black tank on

        # The write itself is still F5 alone -- we do not replay inferred defaults.
        frame = q.get_nowait()['data']
        self.assertEqual(frame[2], 0xF5)
        self.assertEqual(int.from_bytes(frame[4:6], 'little'), 5)
        self.assertTrue(q.empty(), "must send F5 alone, not the 12-selector transaction")

    def test_setting_floorplan_with_matching_defaults_does_not_warn(self):
        g, q = self._make_g12_with_queue()
        g._bunk_accent = 'on'
        g._cargo_bath_light = 'on'
        g._black_tank_setting = 'on'
        g._heat_pump = 'off'
        g._bath_fan = 'off'
        g._bath_light = 'off'
        g._progressive_inverter = 'off'
        with self.assertLogs('G12_Configuration', level='INFO') as captured:
            g.process_mqtt_msg('g12/set/floorplan', 'wd')   # WD defaults match exactly
        joined = ' '.join(captured.output)
        self.assertNotIn('WARNING', joined)
        self.assertIn('nothing should change', joined)

    def test_mqtt_set_floorplan_full_enum(self):
        """All ten floorplans were observed on hardware 2026-08-12; the four rvc2mqtt
        already knew (SY/WA/WD/WT) were independently reconfirmed in the same pass."""
        expected = {'rt': 1, 'ra': 2, 'rd': 3, 'sy': 4, 'tb': 5,
                    'cb': 6, 'wa': 7, 'wd': 8, 'wt': 9, 'ry': 10}
        for name, value in expected.items():
            g, q = self._make_g12_with_queue()
            g.process_mqtt_msg('g12/set/floorplan', name)
            frame = q.get_nowait()['data']
            self.assertEqual(frame[2], 0xF5, f'{name}: wrong selector')
            self.assertEqual(int.from_bytes(frame[4:6], 'little'), value, f'{name}: wrong value')


class Test_G12_ConfigurationHADiscovery(unittest.TestCase):

    def _make_g12_for_discovery(self, engine_relay_instance=None):
        mock = MagicMock()
        mock.make_device_topic_string.return_value = 'topic_string'
        mock.make_ha_auto_discovery_config_topic.return_value = 'ha/config/topic'
        mock.get_bridge_ha_name.return_value = 'rvc2mqtt_bridge'
        mock.bridge_state_topic = 'rvc2mqtt/bridge/state'
        mock.TOPIC_BASE = 'rvc2mqtt'
        mock.client_id = 'bridge'
        data = {'instance': 1, 'instance_name': 'Generator Controller',
                'source_id': '9C',
                'status_topic': 'g12/status', 'command_topic': 'g12/set'}
        if engine_relay_instance is not None:
            data['engine_relay_instance'] = engine_relay_instance
        return G12_Configuration(data, mock)

    def test_discovery_omits_engine_components_without_relay_instance(self):
        g = self._make_g12_for_discovery()
        g.publish_ha_discovery_config()
        uids = [c.get('unique_id', '') for c in self._get_published_configs(g)]
        self.assertEqual([u for u in uids if 'engine_st' in u], [])

    def test_discovery_includes_engine_components_with_relay_instance(self):
        g = self._make_g12_for_discovery(engine_relay_instance=18)
        g.publish_ha_discovery_config()
        uids = [c.get('unique_id', '') for c in self._get_published_configs(g)]
        for suffix in ('_engine_status', '_engine_start', '_engine_stop'):
            self.assertTrue(any(u.endswith(suffix) for u in uids),
                            f"missing {suffix} in {uids}")

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

    def test_publish_ha_discovery_config_publishes_time_for_quiet_time_start(self):
        g = self._make_g12_for_discovery()
        g.publish_ha_discovery_config()
        configs = self._get_published_configs(g)
        matches = [c for c in configs
                   if c.get('p') == 'time'
                   and 'quiet_time_start' in c.get('unique_id', '')]
        self.assertEqual(len(matches), 1)

    def test_publish_ha_discovery_config_publishes_time_for_quiet_time_stop(self):
        g = self._make_g12_for_discovery()
        g.publish_ha_discovery_config()
        configs = self._get_published_configs(g)
        matches = [c for c in configs
                   if c.get('p') == 'time'
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

    # --- mode-dependent parameter ranges ---

    def _range_for(self, g, sub_id):
        for c in self._get_published_configs(g):
            if c.get('unique_id', '').endswith('_' + sub_id):
                return c['min'], c['max']
        self.fail(f'no discovery config for {sub_id}')

    def test_ha_voltage_ranges_are_48v_under_aes(self):
        g = self._make_g12_for_discovery()
        g._gen_aes_mode = 'AES'
        g.publish_ha_discovery_config()
        self.assertEqual(self._range_for(g, 'stop_at_voltage'), (50.0, 58.8))
        self.assertEqual(self._range_for(g, 'max_engine_run_time'), (60, 115))
        self.assertEqual(self._range_for(g, 'time_at_stop_volts'), (600, 3600))

    def test_ha_voltage_ranges_are_12v_under_ags(self):
        """Under AGS the same selectors describe a 12V generator system; the coach was
        observed reporting 13.50V stop and 720 min, far outside the AES bounds."""
        g = self._make_g12_for_discovery()
        g._gen_aes_mode = 'AGS'
        g.publish_ha_discovery_config()
        lo, hi = self._range_for(g, 'stop_at_voltage')
        self.assertLessEqual(lo, 13.50)
        self.assertGreaterEqual(hi, 13.50)
        self.assertGreaterEqual(self._range_for(g, 'max_engine_run_time')[1], 720)

    def test_ha_time_at_stop_volts_range_is_wider_under_ags(self):
        """Confirmed 2026-09-02 by a live candump capture across an AES->AGS switch: the
        G12's own AGS profile broadcasts 7200 (2 h), which the previously-fixed 600-3600
        range rejected regardless of mode."""
        g = self._make_g12_for_discovery()
        g._gen_aes_mode = 'AGS'
        g.publish_ha_discovery_config()
        lo, hi = self._range_for(g, 'time_at_stop_volts')
        self.assertLessEqual(lo, 7200)
        self.assertGreaterEqual(hi, 7200)

    def test_mode_change_republishes_discovery(self):
        from unittest.mock import patch
        g = self._make_g12_for_discovery()
        msg = {'name': 'G12_CONFIGURATION', 'source_id': '9C', 'message_type': 'EF',
               'mode_definition': 'AGS'}
        with patch.object(g, 'publish_ha_discovery_config') as mock_pub:
            g.process_rvc_msg(msg)
            mock_pub.assert_called_once()


if __name__ == '__main__':
    unittest.main()
