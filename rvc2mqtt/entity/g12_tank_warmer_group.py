"""
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

import time
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
    TODO: keep track of lastcommand

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
        self.rvc_match_rfd = { "name": "REQUEST_FOR_DGN", "instance": data['instance'], "dgn": "0EA82" }

        self.Logger.debug(f"Must match: {str(self.rvc_match_rfd)}")

        # save these for later to send rvc msg
        self.rvc_instance = data['instance']
        self.rvc_group = '11111111'
        if 'group' in data:
            self.rvc_group = data['group']
        self.name = data['instance_name']
        self.state = "unknown"
        self.tank_entity_links = []
        
    
    def add_entity_link(self, obj):
        self.tank_entity_links.append(obj)

    def process_rvc_msg(self, new_message: dict) -> bool:
        """ Process an incoming message and determine if it
        is of interest to this object.

        If relevant - Process the message and return True
        else - return False
        """
        if self._is_entry_match(self.rvc_match_rfd, new_message):
            self._rvc_heater_group_send_status(self.state)
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

            # HACK wait a bit so the linked entities have time to update their status
            time.sleep(1)

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

    def _rvc_heater_toggle(self, instance_id: int = None):

        if not instance_id:
            instance_id = self.rvc_instance

        msg_bytes = bytearray(8)
        struct.pack_into("<BBBBBBBB", msg_bytes, 0, instance_id, int(
            self.rvc_group, 2), 250, 5, 0xFF, 0, 0xFF, 0xFF)
        self.send_queue.put({"dgn": "1FEDB", "data": msg_bytes})

    def _rvc_heater_group_send_status(self, status: str):

        if status == HEATER_ON:
            brightness = 0xC8
            load_status = 0x04
        elif status == HEATER_OFF:
            brightness = 0
            load_status = 0
        elif status == HEATER_SOME:
            brightness = 0x64
            load_status = 0x04

        msg_bytes = bytearray(8)
        struct.pack_into("<BBBBBBBB", msg_bytes, 0, instance_id, int(
            self.rvc_group, 2), brightness, 0xFC, 0xFF, 5, load_status, 0xFF)
        self.send_queue.put({"dgn": "1FEDA", "data": msg_bytes})

    def initialize(self):
        """ Optional function
        Will get called once when the object is loaded.
        RVC canbus tx queue is available
        mqtt client is ready.

        This can be a good place to request data

        """

        # request dgn report - this should trigger that dimmer to report
        # dgn = 1FEDA which is actually  DA FE 01 <instance> FF 00 00 00
        #self.Logger.debug("Sending Request for DGN")
        #data = struct.pack("<BBBBBBBB", int("0xDA", 0), int(
        #    "0xFE", 0), 1, int(self.rvc_instance), 0xFF, 0xFF, 0xFF, 0xFF)
        #self.send_queue.put({"dgn": "0EAFF", "data": data})

        # publish info to mqtt
        self.mqtt_support.client.publish(
            self.status_topic, self.state, retain=True)

