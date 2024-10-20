"""
N
A dimmer switch

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
import struct
import json
from rvc2mqtt.mqtt import MQTT_Support
from rvc2mqtt.entity import EntityPluginBaseClass


class TankHeater_DC_DIMMER_STATUS_3(EntityPluginBaseClass):
    FACTORY_MATCH_ATTRIBUTES = {"name": "DC_DIMMER_STATUS_3", "type": "tank_heater_group"}
    """
    The Tank heaters are controlled the same way as the lights and use RVC DGN of DC_DIMMER_STATUS_3
    and DC_DIMMER_COMMAND_2

    Supports ON/OFF

    Virtual device Instance in floorplan to turn a group of tanks on/off
        - name: DC_DIMMER_STATUS_3
            instance: 99
            type: tank_heater_group
            instance_name: tank heaters
            status_topic: rvc/tanks/all/heater
            link_id: tank_heater_group
            entity_links:
              - fresh
              - gray
              - black
              - gray2

    """
    HEATER_ON = "on"
    HEATER_OFF = "off"
    HEATER_SOME = "some on"

    def __init__(self, data: dict, mqtt_support: MQTT_Support):
        self.id = "tank_warmer-1FEDA-i" + str(data["instance"])
        super().__init__(data, mqtt_support)
        self.Logger = logging.getLogger(__class__.__name__)

        # Allow MQTT to control warmer
        if 'status_topic' in data:
            self.command_topic = str(f"{data['status_topic']}/set")
        else:
            self.command_topic = mqtt_support.make_device_topic_string(
                self.id, None, False)

        self.mqtt_support.register(self.command_topic, self.process_mqtt_msg)

        if 'status_topic' in data:
            self.status_topic = str(data['status_topic'])

        # RVC message must match the following to be this device
        self.rvc_match_status = { "name": "DC_DIMMER_STATUS_3", "instance": data['instance']}
        self.rvc_match_rfd = { "name": "REQUEST_FOR_DGN", "instance": data['instance'], "dgn": "1FEDA"}
        self.rvc_match_command= { "name": "DC_DIMMER_COMMAND_2", "instance": data['instance']}


        self.Logger.debug(f"Must match: {str(self.rvc_match_status)} or {str(self.rvc_match_command)}")

        self.tank_entity_links = []

        # save these for later to send rvc msg
        self.rvc_instance = data['instance']
        self.rvc_group = '11111111'
        if 'group' in data:
            self.rvc_group = data['group']
        self.name = data['instance_name']
        self.state = "unknown"

        self.device = {"manufacturer": "RV-C",
                       "via_device": self.mqtt_support.get_bridge_ha_name(),
                       "identifiers": self.unique_device_id,
                       "name": self.name,
                       "model": "RV-C Dimmer from DC_DIMMER_STATUS_3"
                       }

    def add_entity_link(self, obj):
        """ optional function
        If the data of the object has an entity_links list this function
        will get called with each entity"""

        self.tank_entity_links.append(obj)

        self.Logger.info(f"{dir(obj)}")

        #self.Logger.info(f"command topic: {obj.command_topic}")
        #self.Logger.info(f"status_topic: {obj.status_topic}")
        #self.Logger.info(f"rvc_match_status: {obj.rvc_match_status}")
        #self.Logger.info(f"rvc_match_command: {obj.rvc_match_command}")


    def process_rvc_msg(self, new_message: dict) -> bool:
        """ Process an incoming message and determine if it
        is of interest to this object.

        If relevant - Process the message and return True
        else - return False
        """

        if self._is_entry_match(self.rvc_match_status, new_message):
            self.Logger.debug(f"Msg Match Status: {str(new_message)}")
            self.Logger.info(f"Msg Match Status: {str(new_message)}")
            if all(link.state == TankHeater_DC_DIMMER_STATUS_3.HEATER_OFF for link in self.tank_entity_links):
                self.state = TankHeater_DC_DIMMER_STATUS_3.HEATER_OFF
            elif all(link.state == TankHeater_DC_DIMMER_STATUS_3.HEATER_ON for link in self.tank_entity_links):
                self.state = TankHeater_DC_DIMMER_STATUS_3.HEATER_ON
            elif any(link.state == TankHeater_DC_DIMMER_STATUS_3.HEATER_ON for link in self.tank_entity_links):
                self.state = TankHeater_DC_DIMMER_STATUS_3.HEATER_SOME
            else:
                self.state = "UNEXPECTED(" + \
                    str(new_message["operating_status"]) + ")"
                self.Logger.error(
                    f"Unexpected RVC value {str(new_message['operating_status_brightness'])}")

            self.mqtt_support.client.publish(self.status_topic, self.state, retain=True)
            return True

        elif self._is_entry_match(self.rvc_match_command, new_message):
            # This is the command.  Just eat the message so it doesn't show up
            # as unhandled.
            self.Logger.debug(f"Msg Match Command: {str(new_message)}")
            self.Logger.info(f"Msg Match Command: {str(new_message)}")
            return True
        return False

    def process_mqtt_msg(self, topic, payload):
        self.Logger.info(
            f"MQTT Msg Received on topic {topic} with payload {payload}")

        if topic == self.command_topic:
            #Send the command for all linked entities
            for link in self.tank_entity_links:
                if payload.lower() == TankHeater_DC_DIMMER_STATUS_3.HEATER_OFF:
                    if link.state != TankHeater_DC_DIMMER_STATUS_3.HEATER_OFF:
                        self._rvc_heater_toggle(link.rvc_instance)
                elif payload.lower() == TankHeater_DC_DIMMER_STATUS_3.HEATER_ON:
                    if link.state != TankHeater_DC_DIMMER_STATUS_3.HEATER_ON:
                        self._rvc_heater_toggle(link.rvc_instance)
                else:
                    self.Logger.warning(
                        f"Invalid payload {payload} for topic {topic}")

            # Set the status of this topic based on the status of the linked entities
            if all(link.state == TankHeater_DC_DIMMER_STATUS_3.HEATER_OFF for link in self.tank_entity_links):
                self.state = TankHeater_DC_DIMMER_STATUS_3.HEATER_OFF
            elif all(link.state == TankHeater_DC_DIMMER_STATUS_3.HEATER_ON for link in self.tank_entity_links):
                self.state = TankHeater_DC_DIMMER_STATUS_3.HEATER_ON
            elif any(link.state == TankHeater_DC_DIMMER_STATUS_3.HEATER_ON for link in self.tank_entity_links):
                self.state = TankHeater_DC_DIMMER_STATUS_3.HEATER_SOME
            else:
                self.state = "UNEXPECTED(" + \
                    str(new_message["operating_status"]) + ")"

            self.mqtt_support.client.publish(
                self.status_topic, self.state, retain=True)

    """
    On:
        2024-09-10 22:00:35 {'arbitration_id': '0x19fedbfd', 'data': '20FFFA05FF00FFFF', 'priority': '6', 'dgn_h': '1FE', 'dgn_l': 'DB', 'dgn': '1FEDB', 'source_id': 'FD', 'name': 'DC_DIMMER_COMMAND_2', 'instance': 32, 'group': '11111111', 'desired_level': 125.0, 'command': 5, 'command_definition': 'toggle', 'delay_duration': 255, 'interlock': '00', 'interlock_definition': 'no interlock active'}

    Off:
    2024-09-10 22:00:39 {'arbitration_id': '0x19fedbfd', 'data': '20FFFA05FF00FFFF', 'priority': '6', 'dgn_h': '1FE', 'dgn_l': 'DB', 'dgn': '1FEDB', 'source_id': 'FD', 'name': 'DC_DIMMER_COMMAND_2', 'instance': 32, 'group': '11111111', 'desired_level': 125.0, 'command': 5, 'command_definition': 'toggle', 'delay_duration': 255, 'interlock': '00', 'interlock_definition': 'no interlock active'}
    """

    def _rvc_heater_toggle(self, instance_id: int = None):

        if not instance_id:
            instance_id = self.rvc_instance

        msg_bytes = bytearray(8)
        struct.pack_into("<BBBBBBBB", msg_bytes, 0, instance_id, int(
            self.rvc_group, 2), 250, 5, 0xFF, 0, 0xFF, 0xFF)
        self.send_queue.put({"dgn": "1FEDB", "data": msg_bytes})

    def initialize(self):
        """ Optional function
        Will get called once when the object is loaded.
        RVC canbus tx queue is available
        mqtt client is ready.

        This can be a good place to request data

        """

        # produce the HA MQTT discovery config json
        config = {"name": self.name,
                  "state_topic": self.status_topic,
                  "command_topic": self.command_topic,
                  "qos": 1, "retain": False,
                  "payload_on": TankHeater_DC_DIMMER_STATUS_3.HEATER_ON,
                  "payload_off": TankHeater_DC_DIMMER_STATUS_3.HEATER_OFF,
                  "unique_id": self.unique_device_id,
                  "device": self.device}

        config.update(self.get_availability_discovery_info_for_ha())

        config_json = json.dumps(config)

        ha_config_topic = self.mqtt_support.make_ha_auto_discovery_config_topic(
            self.unique_device_id, "dimmer_switch")

        # publish info to mqtt
        self.mqtt_support.client.publish(
            ha_config_topic, config_json, retain=True)
        self.mqtt_support.client.publish(
            self.status_topic, self.state, retain=True)

        # request dgn report - this should trigger that dimmer to report
        # dgn = 1FEDA which is actually  DA FE 01 <instance> FF 00 00 00
        self.Logger.debug("Sending Request for DGN")
        data = struct.pack("<BBBBBBBB", int("0xDA", 0), int(
            "0xFE", 0), 1, self.rvc_instance, 0, 0, 0, 0)
        self.send_queue.put({"dgn": "0EAFF", "data": data})
