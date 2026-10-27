"""
Unit tests for the waterheater entity class

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
import struct
import unittest
from unittest.mock import MagicMock
import context  # add rvc2mqtt package to the python path using local reference
from rvc2mqtt.entity.water_heater import WaterHeaterClass


def _make_mock():
    mock = MagicMock()
    mock.make_device_topic_string.return_value = 'test/topic'
    mock.TOPIC_BASE = 'rvc2mqtt'
    mock.client_id = 'bridge'
    mock.get_bridge_ha_name.return_value = 'bridge'
    mock.bridge_state_topic = 'rvc2mqtt/bridge/state'
    mock.make_ha_auto_discovery_config_topic.return_value = 'homeassistant/switch/test/config'
    return mock


def _make_heater():
    mock = _make_mock()
    # Return distinct topics per field so topic comparisons in process_mqtt_msg work correctly
    mock.make_device_topic_string.side_effect = lambda id, field, state: \
        f'test/{id}/{field}/{"state" if state else "set"}'
    entity = WaterHeaterClass({'instance': 1, 'instance_name': "test water heater"}, mock)
    return entity, mock


def _make_status_msg(mode=0, set_point=-273.0, water_temp=-273.0,
                     thermostat='00', burner='00', ac_element='00',
                     high_temp='00', ignite='00', ac_power='00',
                     dc_power='00', dc_warning='00'):
    return {
        'name': 'WATERHEATER_STATUS',
        'instance': 1,
        'operating_modes': mode,
        'set_point_temperature': set_point,
        'water_temperature': water_temp,
        'thermostat_status': thermostat,
        'burner_status': burner,
        'ac_element_status': ac_element,
        'high_temperature_limit_switch_status': high_temp,
        'failure_to_ignite_status': ignite,
        'ac_power_failure_status': ac_power,
        'dc_power_failure_status': dc_power,
        'dc_power_warning_status': dc_warning,
    }


class Test_Waterheater(unittest.TestCase):

    def test_basic(self):
        mock = MagicMock()
        mock.mqtt_support.make_device_topic_string.return_value = 'topic_string'
        l = WaterHeaterClass({'instance': 1, 'instance_name': "test water heater"}, mock)
        self.assertTrue(type(l), WaterHeaterClass)

    def test_publish_ha_discovery_config(self):
        mock = _make_mock()
        entity = WaterHeaterClass({'instance': 1, 'instance_name': "test water heater"}, mock)
        entity.publish_ha_discovery_config()
        self.assertTrue(mock.client.publish.called)
        for call in mock.client.publish.call_args_list:
            _, kwargs = call
            self.assertFalse(kwargs.get('retain', False),
                             f"Discovery config published with retain=True: {call}")

    # --- process_rvc_msg ---

    def test_process_rvc_msg_mode_off(self):
        entity, mock = _make_heater()
        result = entity.process_rvc_msg(_make_status_msg(mode=0))
        self.assertTrue(result)
        self.assertEqual(entity.gas_mode, WaterHeaterClass.OFF)
        self.assertEqual(entity.ac_mode, WaterHeaterClass.OFF)

    def test_process_rvc_msg_mode_gas_only(self):
        entity, mock = _make_heater()
        entity.process_rvc_msg(_make_status_msg(mode=1))
        self.assertEqual(entity.gas_mode, WaterHeaterClass.ON)
        self.assertEqual(entity.ac_mode, WaterHeaterClass.OFF)

    def test_process_rvc_msg_mode_ac_only(self):
        entity, mock = _make_heater()
        entity.process_rvc_msg(_make_status_msg(mode=2))
        self.assertEqual(entity.gas_mode, WaterHeaterClass.OFF)
        self.assertEqual(entity.ac_mode, WaterHeaterClass.ON)

    def test_process_rvc_msg_mode_gas_and_ac(self):
        entity, mock = _make_heater()
        entity.process_rvc_msg(_make_status_msg(mode=3))
        self.assertEqual(entity.gas_mode, WaterHeaterClass.ON)
        self.assertEqual(entity.ac_mode, WaterHeaterClass.ON)

    def test_process_rvc_msg_mode_auto_gas_and_ac(self):
        entity, mock = _make_heater()
        entity.process_rvc_msg(_make_status_msg(mode=4))
        self.assertEqual(entity.gas_mode, WaterHeaterClass.ON)
        self.assertEqual(entity.ac_mode, WaterHeaterClass.ON)

    def test_process_rvc_msg_mode_5_gas_only(self):
        entity, mock = _make_heater()
        entity.process_rvc_msg(_make_status_msg(mode=5))
        self.assertEqual(entity.gas_mode, WaterHeaterClass.ON)
        self.assertEqual(entity.ac_mode, WaterHeaterClass.OFF)

    def test_process_rvc_msg_mode_6_ac_only(self):
        entity, mock = _make_heater()
        entity.process_rvc_msg(_make_status_msg(mode=6))
        self.assertEqual(entity.gas_mode, WaterHeaterClass.OFF)
        self.assertEqual(entity.ac_mode, WaterHeaterClass.ON)

    def test_process_rvc_msg_unexpected_mode(self):
        entity, mock = _make_heater()
        # mode > 7 triggers error log but should not crash
        result = entity.process_rvc_msg(_make_status_msg(mode=8))
        self.assertTrue(result)

    def test_process_rvc_msg_thermostat_on(self):
        entity, mock = _make_heater()
        entity.process_rvc_msg(_make_status_msg(thermostat='01'))
        self.assertEqual(entity.thermostat_status, WaterHeaterClass.ON)

    def test_process_rvc_msg_thermostat_off(self):
        entity, mock = _make_heater()
        entity.process_rvc_msg(_make_status_msg(thermostat='00'))
        self.assertEqual(entity.thermostat_status, WaterHeaterClass.OFF)

    def test_process_rvc_msg_thermostat_unexpected(self):
        entity, mock = _make_heater()
        entity.process_rvc_msg(_make_status_msg(thermostat='FF'))
        # should log error but not crash
        self.assertTrue(True)

    def test_process_rvc_msg_burner_on(self):
        entity, mock = _make_heater()
        entity.process_rvc_msg(_make_status_msg(burner='01'))
        self.assertEqual(entity.burner_status, WaterHeaterClass.ON)

    def test_process_rvc_msg_ac_element_on(self):
        entity, mock = _make_heater()
        entity.process_rvc_msg(_make_status_msg(ac_element='01'))
        self.assertEqual(entity.ac_element_status, WaterHeaterClass.ON)

    def test_process_rvc_msg_high_temp_on(self):
        entity, mock = _make_heater()
        entity.process_rvc_msg(_make_status_msg(high_temp='01'))
        self.assertEqual(entity.high_temp_switch_status, WaterHeaterClass.ON)

    def test_process_rvc_msg_failure_gas_on(self):
        entity, mock = _make_heater()
        entity.process_rvc_msg(_make_status_msg(ignite='01'))
        self.assertEqual(entity.failure_to_ignite, WaterHeaterClass.ON)

    def test_process_rvc_msg_failure_ac_on(self):
        entity, mock = _make_heater()
        entity.process_rvc_msg(_make_status_msg(ac_power='01'))
        self.assertEqual(entity.failure_ac_power, WaterHeaterClass.ON)

    def test_process_rvc_msg_failure_dc_on(self):
        entity, mock = _make_heater()
        entity.process_rvc_msg(_make_status_msg(dc_power='01'))
        self.assertEqual(entity.failure_dc_power, WaterHeaterClass.ON)

    def test_process_rvc_msg_failure_dc_warning_on(self):
        entity, mock = _make_heater()
        entity.process_rvc_msg(_make_status_msg(dc_warning='01'))
        self.assertEqual(entity.failure_dc_warning, WaterHeaterClass.ON)

    def test_process_rvc_msg_unexpected_burner_status(self):
        entity, mock = _make_heater()
        entity.process_rvc_msg(_make_status_msg(burner='FF'))
        self.assertTrue(True)  # should not crash

    def test_process_rvc_msg_unexpected_ac_element(self):
        entity, mock = _make_heater()
        entity.process_rvc_msg(_make_status_msg(ac_element='FF'))
        self.assertTrue(True)

    def test_process_rvc_msg_unexpected_high_temp(self):
        entity, mock = _make_heater()
        entity.process_rvc_msg(_make_status_msg(high_temp='FF'))
        self.assertTrue(True)

    def test_process_rvc_msg_unexpected_ignite(self):
        entity, mock = _make_heater()
        entity.process_rvc_msg(_make_status_msg(ignite='FF'))
        self.assertTrue(True)

    def test_process_rvc_msg_unexpected_ac_power(self):
        entity, mock = _make_heater()
        entity.process_rvc_msg(_make_status_msg(ac_power='FF'))
        self.assertTrue(True)

    def test_process_rvc_msg_unexpected_dc_power(self):
        entity, mock = _make_heater()
        entity.process_rvc_msg(_make_status_msg(dc_power='FF'))
        self.assertTrue(True)

    def test_process_rvc_msg_unexpected_dc_warning(self):
        entity, mock = _make_heater()
        entity.process_rvc_msg(_make_status_msg(dc_warning='FF'))
        self.assertTrue(True)

    def test_process_rvc_msg_command_eaten(self):
        entity, mock = _make_heater()
        msg = {'name': 'WATERHEATER_COMMAND', 'instance': 1}
        result = entity.process_rvc_msg(msg)
        self.assertTrue(result)

    def test_process_rvc_msg_command2_eaten(self):
        entity, mock = _make_heater()
        msg = {'name': 'WATERHEATER_COMMAND2', 'instance': 1}
        result = entity.process_rvc_msg(msg)
        self.assertTrue(result)

    def test_process_rvc_msg_no_match(self):
        entity, mock = _make_heater()
        msg = {'name': 'SOME_OTHER_MSG', 'instance': 1}
        result = entity.process_rvc_msg(msg)
        self.assertFalse(result)

    # --- process_mqtt_msg ---

    def test_process_mqtt_msg_empty_payload_ignored(self):
        entity, mock = _make_heater()
        q = queue.Queue()
        entity.set_rvc_send_queue(q)
        entity.process_mqtt_msg(entity.command_ac_topic, '')
        self.assertTrue(q.empty())

    def test_process_mqtt_msg_ac_on(self):
        entity, mock = _make_heater()
        entity.ac_mode = WaterHeaterClass.OFF
        entity.gas_mode = WaterHeaterClass.OFF
        q = queue.Queue()
        entity.set_rvc_send_queue(q)
        entity.process_mqtt_msg(entity.command_ac_topic, 'on')
        self.assertFalse(q.empty())
        msg = q.get_nowait()
        self.assertEqual(msg['dgn'], '1FFF6')
        self.assertEqual(msg['data'][1], 2)  # ac only mode

    def test_process_mqtt_msg_ac_off(self):
        entity, mock = _make_heater()
        entity.ac_mode = WaterHeaterClass.ON
        entity.gas_mode = WaterHeaterClass.OFF
        q = queue.Queue()
        entity.set_rvc_send_queue(q)
        entity.process_mqtt_msg(entity.command_ac_topic, 'off')
        self.assertFalse(q.empty())
        msg = q.get_nowait()
        self.assertEqual(msg['data'][1], 0)  # all off

    def test_process_mqtt_msg_ac_no_op_already_on(self):
        entity, mock = _make_heater()
        entity.ac_mode = WaterHeaterClass.ON
        q = queue.Queue()
        entity.set_rvc_send_queue(q)
        entity.process_mqtt_msg(entity.command_ac_topic, 'on')
        self.assertTrue(q.empty())

    def test_process_mqtt_msg_ac_invalid_payload(self):
        entity, mock = _make_heater()
        q = queue.Queue()
        entity.set_rvc_send_queue(q)
        entity.process_mqtt_msg(entity.command_ac_topic, 'invalid')
        self.assertTrue(q.empty())

    def test_process_mqtt_msg_gas_on(self):
        entity, mock = _make_heater()
        entity.gas_mode = WaterHeaterClass.OFF
        entity.ac_mode = WaterHeaterClass.OFF
        q = queue.Queue()
        entity.set_rvc_send_queue(q)
        entity.process_mqtt_msg(entity.command_gas_topic, 'on')
        self.assertFalse(q.empty())
        msg = q.get_nowait()
        self.assertEqual(msg['data'][1], 1)  # gas only

    def test_process_mqtt_msg_gas_off(self):
        entity, mock = _make_heater()
        entity.gas_mode = WaterHeaterClass.ON
        entity.ac_mode = WaterHeaterClass.OFF
        q = queue.Queue()
        entity.set_rvc_send_queue(q)
        entity.process_mqtt_msg(entity.command_gas_topic, 'off')
        self.assertFalse(q.empty())
        msg = q.get_nowait()
        self.assertEqual(msg['data'][1], 0)  # all off

    def test_process_mqtt_msg_gas_no_op_already_on(self):
        entity, mock = _make_heater()
        entity.gas_mode = WaterHeaterClass.ON
        q = queue.Queue()
        entity.set_rvc_send_queue(q)
        entity.process_mqtt_msg(entity.command_gas_topic, 'on')
        self.assertTrue(q.empty())

    def test_process_mqtt_msg_gas_invalid_payload(self):
        entity, mock = _make_heater()
        q = queue.Queue()
        entity.set_rvc_send_queue(q)
        entity.process_mqtt_msg(entity.command_gas_topic, 'invalid')
        self.assertTrue(q.empty())

    def test_process_mqtt_msg_set_point_valid(self):
        entity, mock = _make_heater()
        q = queue.Queue()
        entity.set_rvc_send_queue(q)
        # _rvc_change_set_point logs a warning but does not crash
        entity.process_mqtt_msg(entity.command_set_point_temp_topic, '55.0')
        # no RVC frame is queued — set point is not implemented
        self.assertTrue(q.empty())

    def test_process_mqtt_msg_set_point_invalid(self):
        entity, mock = _make_heater()
        q = queue.Queue()
        entity.set_rvc_send_queue(q)
        entity.process_mqtt_msg(entity.command_set_point_temp_topic, 'notanumber')
        self.assertTrue(q.empty())

    # --- _rvc_change_mode ---

    def test_rvc_change_mode_off(self):
        mock = _make_mock()
        entity = WaterHeaterClass({'instance': 1, 'instance_name': "test water heater"}, mock)
        entity.send_queue = MagicMock()
        entity._rvc_change_mode(gas_on=False, ac_on=False)
        self.assertTrue(entity.send_queue.put.called)
        msg = entity.send_queue.put.call_args[0][0]
        self.assertEqual(msg['dgn'], '1FFF6')
        self.assertEqual(msg['data'][1], 0)  # mode=0 (off)

    def test_rvc_change_mode_gas_only(self):
        mock = _make_mock()
        entity = WaterHeaterClass({'instance': 1, 'instance_name': "test water heater"}, mock)
        entity.send_queue = MagicMock()
        entity._rvc_change_mode(gas_on=True, ac_on=False)
        msg = entity.send_queue.put.call_args[0][0]
        self.assertEqual(msg['data'][1], 1)  # mode=1 (gas only)

    def test_rvc_change_mode_ac_only(self):
        mock = _make_mock()
        entity = WaterHeaterClass({'instance': 1, 'instance_name': "test water heater"}, mock)
        entity.send_queue = MagicMock()
        entity._rvc_change_mode(gas_on=False, ac_on=True)
        msg = entity.send_queue.put.call_args[0][0]
        self.assertEqual(msg['data'][1], 2)  # mode=2 (ac only)

    def test_rvc_change_mode_both(self):
        mock = _make_mock()
        entity = WaterHeaterClass({'instance': 1, 'instance_name': "test water heater"}, mock)
        entity.send_queue = MagicMock()
        entity._rvc_change_mode(gas_on=True, ac_on=True)
        msg = entity.send_queue.put.call_args[0][0]
        self.assertEqual(msg['data'][1], 3)  # mode=3 (gas+ac)

    def test_rvc_change_mode_padding_bytes(self):
        """Verify struct packing produces correct 8-byte payload with 0xFF padding."""
        mock = _make_mock()
        entity = WaterHeaterClass({'instance': 1, 'instance_name': "test water heater"}, mock)
        entity.send_queue = MagicMock()
        entity._rvc_change_mode(gas_on=False, ac_on=False)
        msg = entity.send_queue.put.call_args[0][0]
        data = msg['data']
        self.assertEqual(len(data), 8)
        self.assertEqual(data[0], 1)     # instance
        self.assertEqual(data[1], 0)     # mode=0
        self.assertEqual(data[2], 0xFF)  # H field low byte
        self.assertEqual(data[3], 0xFF)  # H field high byte
        self.assertEqual(data[4], 0xFF)  # padding
        self.assertEqual(data[5], 0xFF)  # padding
        self.assertEqual(data[6], 0xFF)  # padding
        self.assertEqual(data[7], 0xFF)  # padding

    # --- _rvc_change_set_point ---

    def test_rvc_change_set_point_logs_warning_not_raises(self):
        entity, mock = _make_heater()
        q = queue.Queue()
        entity.set_rvc_send_queue(q)
        try:
            entity._rvc_change_set_point(60.0)
        except Exception as e:
            self.fail(f"_rvc_change_set_point raised {type(e).__name__}: {e}")
        self.assertTrue(q.empty())  # no RVC frame sent

    # --- initialize ---

    def test_initialize_publishes_all_status_topics(self):
        entity, mock = _make_heater()
        entity.initialize()
        published_topics = [call[0][0] for call in mock.client.publish.call_args_list]
        self.assertIn(entity.status_gas_topic, published_topics)
        self.assertIn(entity.status_ac_topic, published_topics)
        self.assertIn(entity.status_set_point_temp_topic, published_topics)
        self.assertIn(entity.status_water_temp_topic, published_topics)
        self.assertIn(entity.status_thermostat_topic, published_topics)
        self.assertIn(entity.status_gas_burner_topic, published_topics)
        self.assertIn(entity.status_ac_element_topic, published_topics)
        self.assertIn(entity.status_high_temp_topic, published_topics)
        self.assertIn(entity.status_failure_gas_topic, published_topics)
        self.assertIn(entity.status_failure_ac_topic, published_topics)
        self.assertIn(entity.status_failure_dc_topic, published_topics)
        self.assertIn(entity.status_failure_low_dc_topic, published_topics)


if __name__ == '__main__':
    unittest.main()
