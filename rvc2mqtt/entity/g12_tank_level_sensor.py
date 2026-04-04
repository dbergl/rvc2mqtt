"""
Firefly G12 Tank Level Sensor

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
import struct
from rvc2mqtt.mqtt import MQTT_Support
from rvc2mqtt.entity import EntityPluginBaseClass

class TankLevelSensor_TANK_STATUS(EntityPluginBaseClass):
    FACTORY_MATCH_ATTRIBUTES = {"type": "g12_tank_level", "name": "G12_TANK_LEVEL"}

    """ Provide specific tank level values using DGN G12_TANK_LEVEL_SENSOR
        These are broadcast by the g12 unit on 0BFC1

    """

    def __init__(self, data: dict, mqtt_support: MQTT_Support):
        self.id = "g12tanklevel-0BFC1-i" + str(data["instance"])
        super().__init__(data, mqtt_support)
        self.Logger = logging.getLogger(__class__.__name__)

        # RVC message must match the following to be this device
        self.rvc_match_status = {"name": "G12_TANK_LEVEL_SENSOR", "instance": data['instance']}
        tank_status_instance = data.get('tank_status_instance', data['instance'])
        self.rvc_match_tank_status = {"name": "TANK_STATUS", "instance": tank_status_instance}
        self.tank_level = 999999
        self.tank_percent = 0
        self.custom_triggers = False
        self.tank_status_level = -1
        self.waiting_for_first_tank_status_msg = True
        self.Logger.debug(f"Must match: {str(self.rvc_match_status)}")

        self.name = data['instance_name']
        self.instance = data['instance']
        # Default to change of 1 or more if not set in floorplan
        self.diff_min = data.get('minimum_change', 1)

        if 'status_topic' in data:
            topic_base = str(data['status_topic'])
            self.status_topic = str(f"{topic_base}/sensorlvl")
            self.tank_status_level_topic = str(f"{topic_base}/lvl")
        else:
            self.tank_status_level_topic = mqtt_support.make_device_topic_string(self.id, "tank_status_pct", True)

        """ These will be None if they are not set in the floorplan file.
            Only return a tank level % if all 3 are set
        """
        self.thirtythree = data.get('33_custom_threshold')
        self.sixtysix = data.get('66_custom_threshold')
        self.onehundred = data.get('100_custom_threshold')
        if self.thirtythree is not None and self.sixtysix is not None and self.onehundred is not None:
            self.custom_triggers = True
            # Detect if thresholds are descending (lower raw value = more full, e.g. resistive float sensor)
            self.thresholds_descending = (self.thirtythree > self.sixtysix > self.onehundred)

            if 'status_topic' in data:
                topic_base = str(data['status_topic'])
                self.status_tank_percent_topic = str(f"{topic_base}/custlvl")
                self.cust_threshold_33_topic = str(f"{topic_base}/cust_threshold_33")
                self.cust_threshold_66_topic = str(f"{topic_base}/cust_threshold_66")
                self.cust_threshold_100_topic = str(f"{topic_base}/cust_threshold_100")
            else:
                self.status_tank_percent_topic = mqtt_support.make_device_topic_string(self.id, "tank_percent", True)
                self.cust_threshold_33_topic = mqtt_support.make_device_topic_string(self.id, "cust_threshold_33", True)
                self.cust_threshold_66_topic = mqtt_support.make_device_topic_string(self.id, "cust_threshold_66", True)
                self.cust_threshold_100_topic = mqtt_support.make_device_topic_string(self.id, "cust_threshold_100", True)

            if 'command_topic' in data:
                cmd_base = str(data['command_topic'])
            else:
                cmd_base = self.cust_threshold_33_topic.rsplit('/', 1)[0]

            self.cust_threshold_33_set_topic = str(f"{cmd_base}/cust_threshold_33")
            self.cust_threshold_66_set_topic = str(f"{cmd_base}/cust_threshold_66")
            self.cust_threshold_100_set_topic = str(f"{cmd_base}/cust_threshold_100")

        # produce the HA MQTT discovery device config json
        self.device = {"mf": "RV-C",
                       "ids": self.unique_device_id,
                       "name": self.name,
                       "mdl": "RV-C Tank from G12_TANK_LEVEL_SENSOR",
                       }

    def process_rvc_msg(self, new_message: dict) -> bool:
        """ Process an incoming message and determine if it
        is of interest to this object.

        If relevant - Process the message and return True
        else - return False
        """
        # For now only match the status message.

        if self._is_entry_match(self.rvc_match_status, new_message):
            self.Logger.debug(f"Msg Match Status: {str(new_message)}")

            # These events happen a lot.  Lets filter down to when the value changed by more than diff_min
            if abs(new_message["tank_level"] - self.tank_level) >= int(self.diff_min):
                self.tank_level = new_message['tank_level']
                if self.custom_triggers:
                    new_percent = 0
                    if self.thresholds_descending:
                        if self.tank_level <= self.thirtythree:
                            new_percent = 33
                        if self.tank_level <= self.sixtysix:
                            new_percent = 66
                        if self.tank_level <= self.onehundred:
                            new_percent = 100
                    else:
                        if self.tank_level >= self.thirtythree:
                            new_percent = 33
                        if self.tank_level >= self.sixtysix:
                            new_percent = 66
                        if self.tank_level >= self.onehundred:
                            new_percent = 100

                    if new_percent != self.tank_percent:
                        self.tank_percent = new_percent
                        self.mqtt_support.client.publish(
                                self.status_tank_percent_topic, self.tank_percent, retain=True)

                self.mqtt_support.client.publish(
                        self.status_topic, self.tank_level, retain=True)
            return True

        if self._is_entry_match(self.rvc_match_tank_status, new_message):
            self.Logger.debug(f"Msg Match TANK_STATUS: {str(new_message)}")
            if self.waiting_for_first_tank_status_msg:
                self.resolution = new_message['resolution']
                self.waiting_for_first_tank_status_msg = False
            new_level = round((new_message["relative_level"] * 100) / self.resolution)
            if new_level != self.tank_status_level:
                self.tank_status_level = new_level
                self.mqtt_support.client.publish(
                    self.tank_status_level_topic, self.tank_status_level, retain=True)
            return True

        return False

    def process_mqtt_msg(self, topic, payload, properties=None):
        """Handle a threshold set message from MQTT."""
        try:
            value = int(payload)
        except (ValueError, TypeError):
            self.Logger.warning(f"Invalid threshold value on {topic}: {payload!r}")
            return

        if topic == self.cust_threshold_33_set_topic:
            self.thirtythree = value
            self.mqtt_support.client.publish(self.cust_threshold_33_topic, value, retain=True)
            self._persist_override({'33_custom_threshold': value})
        elif topic == self.cust_threshold_66_set_topic:
            self.sixtysix = value
            self.mqtt_support.client.publish(self.cust_threshold_66_topic, value, retain=True)
            self._persist_override({'66_custom_threshold': value})
        elif topic == self.cust_threshold_100_set_topic:
            self.onehundred = value
            self.mqtt_support.client.publish(self.cust_threshold_100_topic, value, retain=True)
            self._persist_override({'100_custom_threshold': value})

    def publish_ha_discovery_config(self):
        # produce the HA MQTT discovery config json
        origin = {'name': self.mqtt_support.get_bridge_ha_name()}

        levelcmp = {'p': 'sensor',
                    'name': 'value',
                    'value_template': '{{value}}',
                    'state_topic': self.status_topic,
                    'unique_id': self.unique_device_id + 'l'}

        tank_status_levelcmp = {'p': 'sensor',
                    'name': 'standard level',
                    'value_template': '{{value}}',
                    'unit_of_measurement': '%',
                    'state_topic': self.tank_status_level_topic,
                    'unique_id': self.unique_device_id + 'tstpct'}

        if self.custom_triggers:
            customlevel = {'p': 'sensor',
                           'name': 'custom level',
                           'value_template': '{{value}}',
                           'unit_of_measurement': '%',
                           'state_topic': self.status_tank_percent_topic,
                           'unique_id': self.unique_device_id + 'pct'}
            cust_threshold_33 = {'p': 'number',
                            'name': 'threshold 33%',
                            'state_topic': self.cust_threshold_33_topic,
                            'command_topic': self.cust_threshold_33_set_topic,
                            'min': 0, 'max': 65535, 'step': 1, 'mode': 'auto',
                            'unique_id': self.unique_device_id + 'thr33'}
            cust_threshold_66 = {'p': 'number',
                            'name': 'threshold 66%',
                            'state_topic': self.cust_threshold_66_topic,
                            'command_topic': self.cust_threshold_66_set_topic,
                            'min': 0, 'max': 65535, 'step': 1, 'mode': 'auto',
                            'unique_id': self.unique_device_id + 'thr66'}
            cust_threshold_100 = {'p': 'number',
                             'name': 'threshold 100%',
                             'state_topic': self.cust_threshold_100_topic,
                             'command_topic': self.cust_threshold_100_set_topic,
                             'min': 0, 'max': 65535, 'step': 1, 'mode': 'auto',
                             'unique_id': self.unique_device_id + 'thr100'}

        components = {'lvl': levelcmp, 'tstpct': tank_status_levelcmp}
        if self.custom_triggers:
            components['custlvl'] = customlevel
            components['thr33'] = cust_threshold_33
            components['thr66'] = cust_threshold_66
            components['thr100'] = cust_threshold_100

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
            ha_config_topic, config_json, retain=False)

    def initialize(self):
        """ Optional function
        Will get called once when the object is loaded.
        RVC canbus tx queue is available
        mqtt client is ready.

        This can be a good place to request data
        """
        # request dgn report - this should trigger the G12 tanks to report
        # dgn = 0BFC1 which is actually  C1 BF 00 <instance> 00 00 00 00
        self.Logger.debug("Sending Request for DGN")
        data = struct.pack("<BBBBBBBB", int("0xC1", 0), int(
            "0xBF", 0), 0, self.instance, 0, 0, 0, 0)
        self.send_queue.put({"dgn": "0EAFF", "data": data})

        # also request standard TANK_STATUS (dgn = 1FFB7)
        data = struct.pack("<BBBBBBBB", int("0xB7", 0), int(
            "0xFF", 0), 1, self.instance, 0, 0, 0, 0)
        self.send_queue.put({"dgn": "0EAFF", "data": data})

        if self.custom_triggers:
            self.mqtt_support.register(self.cust_threshold_33_set_topic, self.process_mqtt_msg)
            self.mqtt_support.register(self.cust_threshold_66_set_topic, self.process_mqtt_msg)
            self.mqtt_support.register(self.cust_threshold_100_set_topic, self.process_mqtt_msg)
            self.mqtt_support.client.publish(self.cust_threshold_33_topic, self.thirtythree, retain=True)
            self.mqtt_support.client.publish(self.cust_threshold_66_topic, self.sixtysix, retain=True)
            self.mqtt_support.client.publish(self.cust_threshold_100_topic, self.onehundred, retain=True)

        self.publish_ha_discovery_config()
