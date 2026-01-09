"""
Firefly G12 DC system from DC_SOURCE_STATUS_G12


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
import logging
import json
from rvc2mqtt.mqtt import MQTT_Support
from rvc2mqtt.entity import EntityPluginBaseClass


class DcSystemSensor_DC_SOURCE_STATUS_1(EntityPluginBaseClass):
    FACTORY_MATCH_ATTRIBUTES = {"type": "dc_system", "name": "DC_SOURCE_STATUS_G12"}

    """ Provide basic DC system information using DC_SOURCE_STATUS_G12

        This non-standard DGN is broadcast by the firefly g12 in the terrain/launch/swift/ethos and seems to be the same
        as DC_SOURCE_STATUS_1

    """

    def __init__(self, data: dict, mqtt_support: MQTT_Support):
        self.id = "g12_dc_system-i" + str(data["instance"])
        super().__init__(data, mqtt_support)
        self.Logger = logging.getLogger(__class__.__name__)

        # RVC message must match the following to be this device
        self.rvc_match_status = {"name": "DC_SOURCE_STATUS_G12", "instance": data['instance']}
        self.Logger.debug(f"Must match: {str(self.rvc_match_status)}")

        self.name = data['instance_name']

        self.device = {'mf': 'RV-C',
                       'ids': self.unique_device_id,
                       'mdl': 'RV-C DC Source from DC_SOURCE_STATUS_G12',
                       'name': self.name
                       }

        self._voltage_changed = True  # property change tracking
        self._current_changed = True  # property change tracking

        # class specific values that change
        self._dc_voltage = 5  # should never be this low
        self._dc_current = 50  # should not be this high

        if 'status_topic' in data:
            topic_base= str(data['status_topic'])

            self.status_dc_voltage_topic = str(f"{topic_base}/voltage")
            self.status_dc_current_topic = str(f"{topic_base}/current")
        else:
            self.status_dc_voltage_topic = mqtt_support.make_device_topic_string(self.id, "dc_voltage", True)
            self.status_dc_current_topic = mqtt_support.make_device_topic_string(self.id, "dc_current", True)

    @property
    def dc_voltage(self):
        return self._dc_voltage

    @dc_voltage.setter
    def dc_voltage(self, value):
        if value != self._dc_voltage:
            self._dc_voltage = value
            self._voltage_changed = True

    @property
    def dc_current(self):
        return self._dc_current

    @dc_current.setter
    def dc_current(self, value):
        if value != self._dc_current:
            self._dc_current = value
            self._rhanged = True

    def process_rvc_msg(self, new_message: dict) -> bool:
        """ Process an incoming message and determine if it
        is of interest to this object.

        If relevant - Process the message and return True
        else - return False

        {'arbitration_id': '0x19fffd80', 'data': '0114060100000000',
        'priority': '6', 'dgn_h': '1FF', 'dgn_l': 'FD', 'dgn': '1FFFD', 'source_id': '80',
        'name': 'DC_SOURCE_STATUS_1',
        'instance': 1, 'instance_definition': 'main house battery bank',
        'device_priority': 20, 'device_priority_definition': 'voltmeter',
        'dc_voltage': 13.1,
        'dc_current': -2000000.0}
        """
        # For now only match the status message.

        if self._is_entry_match(self.rvc_match_status, new_message):
            self.Logger.debug(f"Msg Match Status: {str(new_message)}")
            self.dc_voltage = new_message["dc_voltage"]
            self.dc_current = new_message["dc_current"]
            self._update_mqtt_topics_with_changed_values()
            return True
        return False

    def _update_mqtt_topics_with_changed_values(self):
        ''' entry data has potentially changed.  Update mqtt'''

        if self._voltage_changed:
            self.mqtt_support.client.publish(
                self.status_dc_voltage_topic, f"{self.dc_voltage:.2f}", retain=True)
            self._voltage_changed = False

        if self._current_changed:
            self.mqtt_support.client.publish(
                self.status_dc_current_topic, self.dc_current, retain=True)
            self._current_changed = False

        return False


    def initialize(self):
        """ Optional function
        Will get called once when the object is loaded.
        RVC canbus tx queue is available
        mqtt client is ready.

        This can be a good place to request data
        """

        # produce the HA MQTT discovery config json
        origin = {'name': self.mqtt_support.get_bridge_ha_name()}
        
        voltscmp = {'p': 'sensor', 'device_class': 'voltage',
                    'unit_of_measurement': 'V', 'value_template': '{{value}}',
                    'state_topic': self.status_dc_voltage_topic,
                    'unique_id': self.unique_device_id + 'v'}
        currentcmp = {'p': 'sensor', 'device_class': 'current',
                      'unit_of_measurement': 'C', 'value_template': '{{value}}',
                      'state_topic': self.status_dc_current_topic,
                      'unique_id': self.unique_device_id + 'c'}

        components = {'volts': voltscmp, 'current': currentcmp} 

        config = {'dev': self.device,
                  'o': origin,
                  'cmps': components,
                  'qos': 1,
                  }

        config.update(self.get_availability_discovery_info_for_ha())

        config_json = json.dumps(config)

        ha_config_topic = self.mqtt_support.make_ha_auto_discovery_config_topic(
            self.unique_device_id, "device")

        # publish info to mqtt
        self.mqtt_support.client.publish(
            ha_config_topic, config_json, retain=True)
