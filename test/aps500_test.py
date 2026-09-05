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
import json
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


class Test_APS500_DcSourceStatus123(unittest.TestCase):
    """DC_SOURCE_STATUS_1 (actual dc_voltage/dc_current), _2 (source_temperature/
    state_of_charge/time_remaining) and _3 (state_of_health/capacity_remaining)
    were previously decoded but never published -- entries below are real
    Renogy-relayed values (confirmed reverse engineering the 0EF70/0EF80 link,
    2026-09-04): 0x88 bytes0-1 are the BMS's ACTUAL measured current (distinct
    from 0x8F bytes2-3's REQUESTED current)."""

    def _make_aps(self):
        return Aps500(_APS_DATA, _make_mock())

    def _topics(self, entity):
        return [c[0][0] for c in entity.mqtt_support.client.publish.call_args_list]

    def _status_1(self, dc_voltage=53.15, dc_current=0.0, source_id='80'):
        return {'name': 'DC_SOURCE_STATUS_1', 'source_id': source_id,
                'dc_voltage': dc_voltage, 'dc_current': dc_current}

    def _status_2(self, source_temperature=21.0, state_of_charge=100.0, time_remaining=65535):
        return {'name': 'DC_SOURCE_STATUS_2', 'source_id': '80',
                'source_temperature': source_temperature,
                'state_of_charge': state_of_charge, 'time_remaining': time_remaining}

    def _status_3(self, state_of_health=255, capacity_remaining=210):
        return {'name': 'DC_SOURCE_STATUS_3', 'source_id': '80',
                'state_of_health': state_of_health, 'capacity_remaining': capacity_remaining}

    def test_dc_current_published_when_nonzero(self):
        l = self._make_aps()
        l.process_rvc_msg(self._status_1(dc_current=2.55))
        l.mqtt_support.client.publish.assert_any_call(
            'aps500/status/dc_current', 2.55, retain=True)

    def test_dc_voltage_and_current_na_not_published(self):
        l = self._make_aps()
        l.process_rvc_msg(self._status_1(dc_voltage='n/a', dc_current='n/a'))
        topics = self._topics(l)
        self.assertNotIn('aps500/status/dc_voltage', topics)
        self.assertNotIn('aps500/status/dc_current', topics)

    def test_wrong_source_id_not_processed_status_1(self):
        l = self._make_aps()
        self.assertFalse(l.process_rvc_msg(self._status_1(source_id='FF')))

    def test_state_of_charge_published_on_change(self):
        l = self._make_aps()
        l.process_rvc_msg(self._status_2(state_of_charge=42.0))
        l.mqtt_support.client.publish.assert_any_call(
            'aps500/status/state_of_charge', 42.0, retain=True)

    def test_state_of_charge_sentinel_not_published(self):
        """255 is the RV-C 'not available' sentinel for a pct field -- rvc.py
        doesn't auto-convert it to 'n/a' the way it does v/a/deg c."""
        l = self._make_aps()
        l.process_rvc_msg(self._status_2(state_of_charge=255))
        self.assertNotIn('aps500/status/state_of_charge', self._topics(l))

    def test_time_remaining_sentinel_not_published(self):
        l = self._make_aps()
        l.process_rvc_msg(self._status_2(time_remaining=65535))
        self.assertNotIn('aps500/status/time_remaining', self._topics(l))

    def test_time_remaining_published_when_available(self):
        l = self._make_aps()
        l.process_rvc_msg(self._status_2(time_remaining=4941))
        l.mqtt_support.client.publish.assert_any_call(
            'aps500/status/time_remaining', 4941, retain=True)

    def test_source_temperature_na_not_published(self):
        l = self._make_aps()
        l.process_rvc_msg(self._status_2(source_temperature='n/a'))
        self.assertNotIn('aps500/status/source_temperature', self._topics(l))

    def test_capacity_remaining_published_on_change(self):
        l = self._make_aps()
        l.process_rvc_msg(self._status_3(capacity_remaining=105))
        l.mqtt_support.client.publish.assert_any_call(
            'aps500/status/capacity_remaining', 105, retain=True)

    def test_capacity_remaining_sentinel_not_published(self):
        l = self._make_aps()
        l.process_rvc_msg(self._status_3(capacity_remaining=65535))
        self.assertNotIn('aps500/status/capacity_remaining', self._topics(l))

    def test_state_of_health_sentinel_not_published(self):
        l = self._make_aps()
        l.process_rvc_msg(self._status_3(state_of_health=255))
        self.assertNotIn('aps500/status/state_of_health', self._topics(l))

    def test_no_publish_when_unchanged(self):
        l = self._make_aps()
        l.process_rvc_msg(self._status_1(dc_current=2.55))
        count = l.mqtt_support.client.publish.call_count
        l.process_rvc_msg(self._status_1(dc_current=2.55))
        self.assertEqual(l.mqtt_support.client.publish.call_count, count)


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


class Test_APS500_AlternatorInformation(unittest.TestCase):

    def _make_aps(self):
        mock = _make_mock()
        return Aps500(_APS_DATA, mock)

    def _make_msg(self, alternator_speed=1000.0):
        return {'name': 'J1939_ALTERNATOR_INFORMATION_1', 'source_id': '80',
                'alternator_speed': alternator_speed}

    def test_returns_true(self):
        l = self._make_aps()
        self.assertTrue(l.process_rvc_msg(self._make_msg()))

    def test_wrong_source_id_not_processed(self):
        l = self._make_aps()
        result = l.process_rvc_msg({**self._make_msg(), 'source_id': '99'})
        self.assertFalse(result)

    def test_publishes_json_on_change(self):
        l = self._make_aps()
        l.process_rvc_msg(self._make_msg(alternator_speed=2830.0))
        l.mqtt_support.client.publish.assert_any_call(
            'aps500/status/alternator_speed',
            '{"alt": 2830, "engine": 1000}',
            retain=False)

    def test_alternator_speed_not_retained(self):
        """Live RPM must not be retained or HA shows a stale speed forever."""
        l = self._make_aps()
        l.process_rvc_msg(self._make_msg(alternator_speed=2830.0))
        alt_calls = [c for c in l.mqtt_support.client.publish.call_args_list
                     if c[0][0] == 'aps500/status/alternator_speed']
        self.assertTrue(alt_calls, "No publish call to alternator_speed topic")
        for call in alt_calls:
            self.assertFalse(call[1].get('retain', False),
                             f"alternator_speed published with retain=True: {call}")

    def test_engine_rpm_is_alt_divided_by_2_83(self):
        l = self._make_aps()
        l.process_rvc_msg(self._make_msg(alternator_speed=1415.0))
        import json as _json
        alt_speed_calls = [c for c in l.mqtt_support.client.publish.call_args_list
                           if c[0][0] == 'aps500/status/alternator_speed']
        self.assertTrue(alt_speed_calls, "No publish call to alternator_speed topic")
        payload = _json.loads(alt_speed_calls[-1][0][1])
        self.assertEqual(payload['engine'], round(1415.0 / 2.83))
        self.assertIsInstance(payload['alt'], int)
        self.assertIsInstance(payload['engine'], int)

    def test_no_publish_when_unchanged(self):
        l = self._make_aps()
        l.process_rvc_msg(self._make_msg(alternator_speed=1000.0))
        count = l.mqtt_support.client.publish.call_count
        l.process_rvc_msg(self._make_msg(alternator_speed=1000.0))
        self.assertEqual(l.mqtt_support.client.publish.call_count, count)

    def test_republishes_on_change(self):
        l = self._make_aps()
        l.process_rvc_msg(self._make_msg(alternator_speed=1000.0))
        count = l.mqtt_support.client.publish.call_count
        l.process_rvc_msg(self._make_msg(alternator_speed=2000.0))
        self.assertEqual(l.mqtt_support.client.publish.call_count, count + 1)

    def test_na_not_published(self):
        l = self._make_aps()
        l.process_rvc_msg(self._make_msg(alternator_speed="n/a"))
        topics = [c[0][0] for c in l.mqtt_support.client.publish.call_args_list]
        self.assertNotIn('aps500/status/alternator_speed', topics)

    def test_engine_running_true_above_500(self):
        l = self._make_aps()
        l.process_rvc_msg(self._make_msg(alternator_speed=501.0))
        l.mqtt_support.client.publish.assert_any_call(
            'aps500/status/engine_running', 'true', retain=True)

    def test_engine_running_false_at_or_below_500(self):
        l = self._make_aps()
        l.process_rvc_msg(self._make_msg(alternator_speed=500.0))
        l.mqtt_support.client.publish.assert_any_call(
            'aps500/status/engine_running', 'false', retain=True)

    def test_engine_running_false_for_na(self):
        l = self._make_aps()
        l.process_rvc_msg(self._make_msg(alternator_speed="n/a"))
        l.mqtt_support.client.publish.assert_any_call(
            'aps500/status/engine_running', 'false', retain=True)

    def test_engine_running_no_repeat_publish(self):
        l = self._make_aps()
        l.process_rvc_msg(self._make_msg(alternator_speed=1000.0))
        count = l.mqtt_support.client.publish.call_count
        l.process_rvc_msg(self._make_msg(alternator_speed=2000.0))
        # engine_running unchanged (still True), so only alternator_speed republishes
        engine_calls = [c for c in l.mqtt_support.client.publish.call_args_list
                        if c[0][0] == 'aps500/status/engine_running']
        self.assertEqual(sum(1 for c in engine_calls if c[0][1] == 'true'), 1)


class Test_APS500_UnavailableNumerics(unittest.TestCase):
    """rvc.py decodes an unavailable (0xFF/0xFFFF) v/a/deg c field to the string
    "n/a".  Those topics are announced to HA with a numeric device_class, so the
    string must never be published or HA logs a ValueError and drops the state.
    """

    def _make_aps(self):
        return Aps500(_APS_DATA, _make_mock())

    def _topics(self, entity):
        return [c[0][0] for c in entity.mqtt_support.client.publish.call_args_list]

    def _charger_status_2(self, charging_voltage=13.5, charging_current=20.0,
                          charger_temperature=25):
        return {'name': 'CHARGER_STATUS_2', 'source_id': '80',
                'charger_instance': 1,
                'charging_voltage': charging_voltage,
                'charging_current': charging_current,
                'charger_temperature': charger_temperature}

    def _charger_status(self, charge_voltage=13.5, charge_current=20.0):
        return {'name': 'CHARGER_STATUS', 'source_id': '80', 'instance': 1,
                'charge_voltage': charge_voltage,
                'charge_current': charge_current,
                'charge_current_percent_of_maximum': 50.0,
                'operating_state': 3, 'operating_state_definition': 'float',
                'default_state_on_power-up': 1,
                'default_state_on_power-up_definition': 'enabled',
                'auto_recharge_enable': 1,
                'auto_recharge_enable_definition': 'enabled',
                'force_charge': 0, 'force_charge_definition': 'disabled'}

    def _source_status_4(self, desired_dc_voltage=54.7, desired_dc_current=90.0):
        return {'name': 'DC_SOURCE_STATUS_4', 'source_id': '80', 'instance': 1,
                'desired_charge_state': 3,
                'desired_charge_state_definition': 'float',
                'desired_dc_voltage': desired_dc_voltage,
                'desired_dc_current': desired_dc_current}

    def _source_status_5(self, hp_dc_voltage=13.456):
        return {'name': 'DC_SOURCE_STATUS_5', 'source_id': '80', 'instance': 1,
                'hp_dc_voltage': hp_dc_voltage}

    # --- CHARGER_STATUS_2 -------------------------------------------------

    def test_charging_current_published_when_numeric(self):
        l = self._make_aps()
        l.process_rvc_msg(self._charger_status_2(charging_current=20.0))
        l.mqtt_support.client.publish.assert_any_call(
            'aps500/status/charging_current', 20.0, retain=True)

    def test_charging_current_na_not_published(self):
        l = self._make_aps()
        l.process_rvc_msg(self._charger_status_2(charging_current='n/a'))
        self.assertNotIn('aps500/status/charging_current', self._topics(l))

    def test_charging_voltage_na_not_published(self):
        l = self._make_aps()
        l.process_rvc_msg(self._charger_status_2(charging_voltage='n/a'))
        self.assertNotIn('aps500/status/charging_voltage', self._topics(l))

    def test_charger_temperature_na_not_published(self):
        l = self._make_aps()
        l.process_rvc_msg(self._charger_status_2(charger_temperature='n/a'))
        self.assertNotIn('aps500/status/charger_temp', self._topics(l))

    def test_numeric_siblings_still_published_when_one_is_na(self):
        """An unavailable current must not suppress the fields around it."""
        l = self._make_aps()
        l.process_rvc_msg(self._charger_status_2(charging_current='n/a'))
        topics = self._topics(l)
        self.assertIn('aps500/status/charging_voltage', topics)
        self.assertIn('aps500/status/charger_temp', topics)

    def test_real_value_published_after_na(self):
        """Recovering from n/a must publish the real reading, not stay silent."""
        l = self._make_aps()
        l.process_rvc_msg(self._charger_status_2(charging_current='n/a'))
        l.process_rvc_msg(self._charger_status_2(charging_current=31.5))
        l.mqtt_support.client.publish.assert_any_call(
            'aps500/status/charging_current', 31.5, retain=True)

    # --- CHARGER_STATUS ---------------------------------------------------

    def test_charge_voltage_and_current_na_not_published(self):
        l = self._make_aps()
        l.process_rvc_msg(self._charger_status(charge_voltage='n/a',
                                               charge_current='n/a'))
        topics = self._topics(l)
        self.assertNotIn('aps500/status/charge_voltage', topics)
        self.assertNotIn('aps500/status/charge_current', topics)

    # --- DC_SOURCE_STATUS_4 -----------------------------------------------

    def test_desired_dc_values_na_not_published(self):
        l = self._make_aps()
        l.process_rvc_msg(self._source_status_4(desired_dc_voltage='n/a',
                                                desired_dc_current='n/a'))
        topics = self._topics(l)
        self.assertNotIn('aps500/status/desired_dc_voltage', topics)
        self.assertNotIn('aps500/status/desired_dc_current', topics)

    # --- DC_SOURCE_STATUS_5 -----------------------------------------------

    def test_hp_dc_voltage_na_does_not_raise(self):
        """hp_dc_voltage is formatted with :.3f, which raises on a str."""
        l = self._make_aps()
        self.assertTrue(l.process_rvc_msg(self._source_status_5(hp_dc_voltage='n/a')))
        self.assertNotIn('aps500/status/hp_dc_voltage', self._topics(l))


class Test_APS500_BmsProprietaryLink(unittest.TestCase):
    """WAKESPEED_BMS_QUERY (0EF70) / RENOGY_BMS_RESPONSE (0EF80): the
    response doesn't self-identify its register, so decode is stateful --
    it depends on the query that immediately preceded it."""

    def _make_aps(self):
        return Aps500(_APS_DATA, _make_mock())

    def _topics(self, entity):
        return [c[0][0] for c in entity.mqtt_support.client.publish.call_args_list]

    def _query(self, data_hex, source_id='80'):
        return {'name': 'WAKESPEED_BMS_QUERY', 'source_id': source_id, 'data': data_hex}

    def _response(self, data_hex, source_id='70'):
        return {'name': 'RENOGY_BMS_RESPONSE', 'source_id': source_id, 'data': data_hex}

    def test_query_returns_true_and_remembers_register(self):
        l = self._make_aps()
        self.assertTrue(l.process_rvc_msg(self._query('13950004FFFFFFFF')))
        self.assertEqual(l._bms_query_register, 0x95)

    def test_non_read_opcode_does_not_set_register(self):
        l = self._make_aps()
        l.process_rvc_msg(self._query('0043432A007D7900'))
        self.assertIsNone(l._bms_query_register)

    def test_response_without_preceding_query_is_ignored(self):
        l = self._make_aps()
        self.assertTrue(l.process_rvc_msg(self._response('00CF00CD00DB00DA')))
        self.assertEqual(l._bms_temps, [None, None, None, None])
        l.mqtt_support.client.publish.assert_not_called()

    def test_temps_decoded_and_published(self):
        l = self._make_aps()
        l.process_rvc_msg(self._query('13950004FFFFFFFF'))
        l.process_rvc_msg(self._response('00CF00CD00DB00DA'))
        self.assertEqual(l._bms_temps, [20.7, 20.5, 21.9, 21.8])
        l.mqtt_support.client.publish.assert_called_with(
            'aps500/status/bms_temps', json.dumps([20.7, 20.5, 21.9, 21.8]), retain=False)

    def test_temps_unavailable_sentinel(self):
        l = self._make_aps()
        l.process_rvc_msg(self._query('13950004FFFFFFFF'))
        l.process_rvc_msg(self._response('FFFF00CD00DB00DA'))
        self.assertEqual(l._bms_temps[0], 'n/a')

    def test_temps_not_republished_when_unchanged(self):
        l = self._make_aps()
        for _ in range(2):
            l.process_rvc_msg(self._query('13950004FFFFFFFF'))
            l.process_rvc_msg(self._response('00CF00CD00DB00DA'))
        temp_calls = [c for c in l.mqtt_support.client.publish.call_args_list
                      if c[0][0] == 'aps500/status/bms_temps']
        self.assertEqual(len(temp_calls), 1)

    def test_register_consumed_after_one_response(self):
        """A stray response with no fresh query must not be decoded as temps."""
        l = self._make_aps()
        l.process_rvc_msg(self._query('13950004FFFFFFFF'))
        l.process_rvc_msg(self._response('00CF00CD00DB00DA'))
        l.process_rvc_msg(self._response('FFFFFFFFFFFFFFFF'))
        self.assertEqual(l._bms_temps, [20.7, 20.5, 21.9, 21.8])

    def test_alarm_bit_decoded_and_published_retained(self):
        l = self._make_aps()
        l.process_rvc_msg(self._query('13920004FFFFFFFF'))
        # byte2 = 0x02 -> code 52, High Voltage
        l.process_rvc_msg(self._response('0000020000000000'))
        expected = {"2": {"code": "52", "description": Aps500.apcfaults["52"]}}
        self.assertEqual(l._bms_active_alarms, expected)
        l.mqtt_support.client.publish.assert_called_with(
            'aps500/status/bms_alarm', json.dumps(expected), retain=True)

    def test_alarm_multi_bit_value_is_not_a_fault(self):
        """Only an exact single-bit value is a recognized alarm."""
        l = self._make_aps()
        l.process_rvc_msg(self._query('13920004FFFFFFFF'))
        l.process_rvc_msg(self._response('00FF000000000000'))
        self.assertEqual(l._bms_active_alarms, {})

    def test_alarm_clears_when_byte_returns_to_zero(self):
        l = self._make_aps()
        l.process_rvc_msg(self._query('13920004FFFFFFFF'))
        l.process_rvc_msg(self._response('0000020000000000'))
        l.process_rvc_msg(self._query('13920004FFFFFFFF'))
        l.process_rvc_msg(self._response('0000000000000000'))
        self.assertEqual(l._bms_active_alarms, {})
        l.mqtt_support.client.publish.assert_called_with(
            'aps500/status/bms_alarm', json.dumps({}), retain=True)


if __name__ == '__main__':
    unittest.main()
