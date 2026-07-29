"""
Unit tests for the inverter/charger entity class

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
from rvc2mqtt.entity.inverter import InverterCharger_INVERTER_STATUS as Inverter


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
    mock.make_ha_auto_discovery_config_topic.return_value = 'homeassistant/device/test/config'
    return mock


def _make_inverter():
    mock = _make_mock()
    entity = Inverter(
        {'instance': 1, 'instance_name': "test inverter",
         'status_topic': 'rvc/state/inverter', 'command_topic': 'rvc/set/inverter'},
        mock)
    return entity, mock


def _ac_status_1(line='1', in_out='output', voltage=120.0, current=5.0,
                 frequency=60.0):
    return {
        'name': 'INVERTER_AC_STATUS_1',
        'instance': 1,
        'line_definition': line,
        'input_output_definition': in_out,
        'rms_voltage': voltage,
        'rms_current': current,
        'frequency': frequency,
        'fault_open_ground': 0,
        'fault_open_neutral': 0,
        'fault_reverse_polarity': 0,
        'fault_ground_current': 0,
    }


def _published(mock):
    return [(c[0][0], c[0][1]) for c in mock.client.publish.call_args_list]


def _topics(mock):
    return [c[0][0] for c in mock.client.publish.call_args_list]


class Test_Inverter(unittest.TestCase):

    def test_basic(self):
        entity, _ = _make_inverter()
        self.assertIsInstance(entity, Inverter)

    def test_wrong_dgn_not_processed(self):
        entity, _ = _make_inverter()
        self.assertFalse(entity.process_rvc_msg({'name': 'SOMETHING_ELSE'}))


class Test_Inverter_AcStatus1(unittest.TestCase):
    """AC status arrives per line and per direction, so the same seven fields
    are published under several topic prefixes."""

    def test_first_message_publishes_every_field(self):
        entity, mock = _make_inverter()
        self.assertTrue(entity.process_rvc_msg(_ac_status_1()))
        self.assertEqual(_topics(mock), [
            'rvc/state/inverter/line1/output/rms_voltage',
            'rvc/state/inverter/line1/output/rms_current',
            'rvc/state/inverter/line1/output/frequency',
            'rvc/state/inverter/line1/output/fault/open_ground',
            'rvc/state/inverter/line1/output/fault/open_neutral',
            'rvc/state/inverter/line1/output/fault/reverse_polarity',
            'rvc/state/inverter/line1/output/fault/ground_current',
        ])

    def test_repeated_identical_message_publishes_nothing(self):
        """The change guard used to store every value under the literal string
        "_volt_key", so it never matched and this republished on every frame."""
        entity, mock = _make_inverter()
        msg = _ac_status_1()
        entity.process_rvc_msg(msg)
        mock.client.publish.reset_mock()
        entity.process_rvc_msg(msg)
        entity.process_rvc_msg(msg)
        self.assertEqual(_topics(mock), [])

    def test_only_the_changed_field_republishes(self):
        entity, mock = _make_inverter()
        entity.process_rvc_msg(_ac_status_1(voltage=120.0))
        mock.client.publish.reset_mock()
        entity.process_rvc_msg(_ac_status_1(voltage=121.5))
        self.assertEqual(_published(mock), [
            ('rvc/state/inverter/line1/output/rms_voltage', 121.5),
        ])

    def test_lines_tracked_independently(self):
        entity, mock = _make_inverter()
        entity.process_rvc_msg(_ac_status_1(line='1', voltage=120.0))
        entity.process_rvc_msg(_ac_status_1(line='2', voltage=120.0))
        mock.client.publish.reset_mock()
        # line 2 moves, line 1 does not
        entity.process_rvc_msg(_ac_status_1(line='1', voltage=120.0))
        entity.process_rvc_msg(_ac_status_1(line='2', voltage=125.0))
        self.assertEqual(_published(mock), [
            ('rvc/state/inverter/line2/output/rms_voltage', 125.0),
        ])

    def test_input_and_output_tracked_independently(self):
        entity, mock = _make_inverter()
        entity.process_rvc_msg(_ac_status_1(in_out='input', voltage=118.0))
        entity.process_rvc_msg(_ac_status_1(in_out='output', voltage=118.0))
        mock.client.publish.reset_mock()
        entity.process_rvc_msg(_ac_status_1(in_out='input', voltage=119.0))
        entity.process_rvc_msg(_ac_status_1(in_out='output', voltage=118.0))
        self.assertEqual(_published(mock), [
            ('rvc/state/inverter/line1/input/rms_voltage', 119.0),
        ])

    def test_zero_is_a_real_first_value(self):
        entity, mock = _make_inverter()
        entity.process_rvc_msg(_ac_status_1(voltage=0.0, current=0.0))
        published = dict(_published(mock))
        self.assertEqual(published['rvc/state/inverter/line1/output/rms_voltage'], 0.0)
        self.assertEqual(published['rvc/state/inverter/line1/output/rms_current'], 0.0)


class Test_Inverter_Status(unittest.TestCase):

    def _status_msg(self, status=1, sensor_present=0):
        return {
            'name': 'INVERTER_STATUS',
            'instance': 1,
            'status': status,
            'status_definition': 'inverting',
            'battery_temperature_sensor_present': sensor_present,
            'battery_temperature_sensor_present_definition': 'not present',
        }

    def test_status_publishes_raw_definition_and_onoff(self):
        entity, mock = _make_inverter()
        self.assertTrue(entity.process_rvc_msg(self._status_msg(status=1)))
        published = dict(_published(mock))
        self.assertEqual(published['rvc/state/inverter/status'], 1)
        self.assertEqual(published['rvc/state/inverter/status_definition'], 'Inverting')
        self.assertEqual(published['rvc/state/inverter/onoff'], 'on')

    def test_status_zero_is_off(self):
        entity, mock = _make_inverter()
        entity.process_rvc_msg(self._status_msg(status=0))
        self.assertEqual(dict(_published(mock))['rvc/state/inverter/onoff'], 'off')

    def test_repeated_status_publishes_nothing(self):
        entity, mock = _make_inverter()
        msg = self._status_msg()
        entity.process_rvc_msg(msg)
        mock.client.publish.reset_mock()
        entity.process_rvc_msg(msg)
        self.assertEqual(_topics(mock), [])

    def test_onoff_republishes_only_when_it_flips(self):
        entity, mock = _make_inverter()
        entity.process_rvc_msg(self._status_msg(status=1))
        mock.client.publish.reset_mock()
        # a different non-zero status is still "on", so onoff must not republish
        entity.process_rvc_msg(self._status_msg(status=2))
        self.assertNotIn('rvc/state/inverter/onoff', _topics(mock))
        entity.process_rvc_msg(self._status_msg(status=0))
        self.assertIn('rvc/state/inverter/onoff', _topics(mock))


class Test_Inverter_DcAndTemperature(unittest.TestCase):

    def test_dc_status_change_gated(self):
        entity, mock = _make_inverter()
        msg = {'name': 'INVERTER_DC_STATUS', 'instance': 1,
               'dc_voltage': 13.2, 'dc_amperage': 40.0}
        self.assertTrue(entity.process_rvc_msg(msg))
        self.assertEqual(len(_topics(mock)), 2)
        mock.client.publish.reset_mock()
        entity.process_rvc_msg(msg)
        self.assertEqual(_topics(mock), [])

    def test_temperature_status_change_gated(self):
        entity, mock = _make_inverter()
        msg = {'name': 'INVERTER_TEMPERATURE_STATUS', 'instance': 1,
               'fet_1_temperature': 40.0, 'transformer_temperature': 45.0,
               'fet_2_temperature': 41.0}
        self.assertTrue(entity.process_rvc_msg(msg))
        self.assertEqual(len(_topics(mock)), 3)
        mock.client.publish.reset_mock()
        entity.process_rvc_msg(msg)
        self.assertEqual(_topics(mock), [])


if __name__ == '__main__':
    unittest.main()
