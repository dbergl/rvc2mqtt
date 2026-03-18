"""
DC system sensor from DC_SOURCE_STATUS_1


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
import logging
import json
from rvc2mqtt.mqtt import MQTT_Support
from rvc2mqtt.entity import EntityPluginBaseClass


class DcSystemSensor_DC_SOURCE_STATUS_1(EntityPluginBaseClass):
    FACTORY_MATCH_ATTRIBUTES = {"type": "dc_system", "name": "DC_SOURCE_STATUS_1"}

    """ Provide basic DC system information using DC_SOURCE_STATUS_1

    """

    def __init__(self, data: dict, mqtt_support: MQTT_Support):
        self.id = "dc_system-i" + str(data["instance"])
        super().__init__(data, mqtt_support)
        self.Logger = logging.getLogger(__class__.__name__)

        # RVC message must match the following to be this device
        self.rvc_match_status = {"name": "DC_SOURCE_STATUS_1", "instance": data['instance']}
        self.Logger.debug(f"Must match: {str(self.rvc_match_status)}")

        self.name = data['instance_name']

        self.device = {'mf': 'RV-C',
                       'ids': self.unique_device_id,
                       'mdl': 'RV-C DC System Sensor from DC_SOURCE_STATUS_1',
                       'name': self.name
                       }

        self._changed = False

        # class specific values that change; None until first valid reading received
        self._dc_voltage = None
        self._dc_current = None

        if 'status_topic' in data:
            topic_base = str(data['status_topic'])
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
            self._changed = True

    @property
    def dc_current(self):
        return self._dc_current

    @dc_current.setter
    def dc_current(self, value):
        if value != self._dc_current:
            self._dc_current = value
            self._changed = True

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
            if new_message["dc_voltage"] != "n/a":
                self.dc_voltage = new_message["dc_voltage"]
            if new_message["dc_current"] != "n/a":
                self.dc_current = new_message["dc_current"]
            self._update_mqtt_topics_with_changed_values()
            return True
        return False

    def _update_mqtt_topics_with_changed_values(self):
        ''' entry data has potentially changed.  Update mqtt'''

        if self._changed:
            if self._dc_voltage is not None:
                self.mqtt_support.client.publish(
                    self.status_dc_voltage_topic, self.dc_voltage, retain=True)
            if self._dc_current is not None:
                self.mqtt_support.client.publish(
                    self.status_dc_current_topic, self.dc_current, retain=True)
            self._changed = False
        return False


    def publish_ha_discovery_config(self):
        origin = {'name': self.mqtt_support.get_bridge_ha_name()}
        voltscmp = {'p': 'sensor', 'device_class': 'voltage',
                    'unit_of_measurement': 'V', 'suggested_display_precision': '2',
                    'value_template': '{{value}}',
                    'state_topic': self.status_dc_voltage_topic,
                    'unique_id': self.unique_device_id + 'v',}
        currentcmp = {'p': 'sensor', 'device_class': 'current',
                      'unit_of_measurement': 'A', 'suggested_display_precision': '2',
                      'value_template': '{{value}}',
                      'state_topic': self.status_dc_current_topic,
                      'unique_id': self.unique_device_id + 'c',}
        components = {'volts': voltscmp, 'current': currentcmp}
        config = {'dev': self.device, 'o': origin, 'cmps': components, 'qos': 1}
        config.update(self.get_availability_discovery_info_for_ha())
        config_json = json.dumps(config)
        ha_config_topic = self.mqtt_support.make_ha_auto_discovery_config_topic(
            self.unique_device_id, "device")
        self.mqtt_support.client.publish(ha_config_topic, config_json, retain=False)

    def initialize(self):
        """ Optional function
        Will get called once when the object is loaded.
        RVC canbus tx queue is available
        mqtt client is ready.

        This can be a good place to request data
        """
        self.publish_ha_discovery_config()
