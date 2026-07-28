"""
Unit tests for entity_factory / FACTORY_MATCH_ATTRIBUTES matching

These load the real entity plugins from rvc2mqtt/entity and resolve floorplan
entries through the factory, so they guard the floorplan `type` strings that
existing configuration files depend on.

Copyright 2026 Dan Berglund
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

import os
import unittest
from unittest.mock import MagicMock
import context  # add rvc2mqtt package to the python path using local reference
from rvc2mqtt.plugin_support import PluginSupport
from rvc2mqtt.entity_factory_support import entity_factory

ENTITY_PATH = os.path.abspath(os.path.join(
    os.path.dirname(__file__), '..', 'rvc2mqtt', 'entity'))


def _make_mock():
    mock = MagicMock()
    mock.make_device_topic_string.return_value = 'test/topic'
    mock.TOPIC_BASE = 'rvc2mqtt'
    mock.client_id = 'bridge'
    mock.get_bridge_ha_name.return_value = 'bridge'
    mock.bridge_state_topic = 'rvc2mqtt/bridge/state'
    return mock


def _factory_list():
    fm = []
    PluginSupport(ENTITY_PATH, []).register_with_factory_the_entity_plugins(fm)
    return fm


class Test_EntityFactory(unittest.TestCase):

    @classmethod
    def setUpClass(cls):
        cls.factory_list = _factory_list()

    def _make(self, data):
        return entity_factory(data, _make_mock(), self.factory_list)

    # --- DC_DIMMER_STATUS_3 shares one implementation across two types ---

    def test_dimmer_switch_type_resolves(self):
        """Floorplan entry copied from the coach floorplan (main lights)."""
        entity = self._make({'name': 'DC_DIMMER_STATUS_3', 'instance': 32,
                             'type': 'dimmer_switch', 'instance_name': 'main lights',
                             'status_topic': 'rvc/state/lights/int/main',
                             'command_topic': 'rvc/set/lights/int/main'})
        self.assertIsNotNone(entity)
        self.assertEqual(type(entity).__name__, 'DimmerSwitch_DC_DIMMER_STATUS_3')
        self.assertEqual(entity.id, 'dimmer-1FEDB-i32')
        self.assertTrue(entity.dimmable)

    def test_tank_heater_type_resolves(self):
        """Floorplan entry copied from the coach floorplan (fresh tank heater)."""
        entity = self._make({'name': 'DC_DIMMER_STATUS_3', 'instance': 5,
                             'type': 'tank_heater', 'instance_name': 'tank heater fresh',
                             'status_topic': 'rvc/state/tanks/fresh/heater',
                             'command_topic': 'rvc/set/tanks/fresh/heater'})
        self.assertIsNotNone(entity)
        self.assertEqual(type(entity).__name__, 'TankHeater_DC_DIMMER_STATUS_3')
        self.assertEqual(entity.id, 'tank_warmer-1FEDB-i5')
        self.assertFalse(entity.dimmable)

    def test_dimmer_and_tank_heater_share_implementation(self):
        dimmer = self._make({'name': 'DC_DIMMER_STATUS_3', 'instance': 1,
                             'type': 'dimmer_switch', 'instance_name': 'a light'})
        heater = self._make({'name': 'DC_DIMMER_STATUS_3', 'instance': 1,
                             'type': 'tank_heater', 'instance_name': 'a heater'})
        self.assertIsInstance(heater, type(dimmer))
        self.assertNotEqual(type(heater), type(dimmer))

    def test_each_dimmer_status_3_type_registered_exactly_once(self):
        """A duplicate FACTORY_MATCH_ATTRIBUTES would silently shadow one of these -
        entity_factory takes the first match with no ambiguity warning."""
        matches = [fma for fma, _ in self.factory_list
                   if fma.get('name') == 'DC_DIMMER_STATUS_3']
        types = sorted(fma['type'] for fma in matches)
        self.assertEqual(types, ['dimmer_switch', 'tank_heater'])

    # --- general matching behavior ---

    def test_unknown_type_returns_none(self):
        self.assertIsNone(self._make({'name': 'DC_DIMMER_STATUS_3', 'instance': 1,
                                      'type': 'not_a_real_type',
                                      'instance_name': 'nope'}))

    def test_unknown_name_returns_none(self):
        self.assertIsNone(self._make({'name': 'NOT_A_REAL_DGN', 'instance': 1,
                                      'type': 'dimmer_switch',
                                      'instance_name': 'nope'}))

    def test_type_match_is_case_sensitive(self):
        self.assertIsNone(self._make({'name': 'DC_DIMMER_STATUS_3', 'instance': 1,
                                      'type': 'Dimmer_Switch',
                                      'instance_name': 'nope'}))

    def test_extra_floorplan_keys_are_ignored_by_matching(self):
        entity = self._make({'name': 'DC_DIMMER_STATUS_3', 'instance': 1,
                             'type': 'dimmer_switch', 'instance_name': 'a light',
                             'dimmable': False, 'driver_index': 9,
                             'group': '00000001', 'link_id': 'whatever'})
        self.assertIsNotNone(entity)
        self.assertFalse(entity.dimmable)
        self.assertEqual(entity.driver_index, 9)


if __name__ == '__main__':
    unittest.main()
