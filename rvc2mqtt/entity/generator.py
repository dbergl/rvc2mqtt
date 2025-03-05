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

import queue
import logging
import struct
import json
from rvc2mqtt.mqtt import MQTT_Support
from rvc2mqtt.entity import EntityPluginBaseClass

class Generator_GENERATOR(EntityPluginBaseClass):
    FACTORY_MATCH_ATTRIBUTES = {"name": "GENERATOR", "type": "generator"}
    """
    Dimmer switch that is tied to RVC DGN of GENERATOR_STATUS_1 and DC_DIMMER_COMMAND_2
    Expects an instance_name of either start_trigger or stop_trigger
    """

    def __init__(self, data: dict, mqtt_support: MQTT_Support):
        self.rvc_instance = data.get('instance',0)
        self.rvc_instance_name = data.get('instance_name','')
        self.id = "dimmer-1FEDB-i" + str(self.rvc_instance)
        super().__init__(data, mqtt_support)
        self.Logger = logging.getLogger(__class__.__name__)

        # Allow MQTT to control Generator
        if 'command_topic' in data:
            topic_base = f"{data['command_topic']}"
            self.command_topic = str(f"{topic_base}/{self.rvc_instance_name}")
            self.mqtt_support.register(self.command_topic, self.process_mqtt_msg)

        if 'status_topic' in data:
            topic_base = f"{data['status_topic']}"

            self.status_topic = str(f"{topic_base}/status")
            self.hours_topic = str(f"{topic_base}/hours")
            self.startstop_trigger_topic = str(f"{topic_base}/{self.rvc_instance_name}")

        else:
            self.status_topic = mqtt_support.make_device_topic_string(self.id, "status", True)
            self.hours_topic = mqtt_support.make_device_topic_string(self.id, "hours", True)


        # RVC message must match the following to be this device
        self.rvc_match_status = { "name": "GENERATOR_STATUS_1" }
        self.rvc_match_command = { "name": "DC_DIMMER_COMMAND_2", "instance": self.rvc_instance }
        self.rvc_match_dimmer_status = { "name": "DC_DIMMER_STATUS_3", "instance": self.rvc_instance }

        self.Logger.debug(f"Must match: {str(self.rvc_match_status)} or {str(self.rvc_match_command)}")

        # save these for later to send rvc msg
        self.rvc_group = '11111111'
        if 'group' in data:
            self.rvc_group = data['group']
        self.name = data['instance_name']
        self.status = "unknown"
        self.run_time = "unknown"
        self.state = "unknown"
        self.messagestate = "unknown"

    def process_rvc_msg(self, new_message: dict) -> bool:
        """ Process an incoming message and determine if it
        is of interest to this object.

        If relevant - Process the message and return True
        else - return False
        """

        if self._is_entry_match(self.rvc_match_status, new_message):
            self.Logger.debug(f"Msg Match Status: {str(new_message)}")
            if new_message["status"] != self.status:
                self.status = new_message["status"]
                status_json = json.dumps(
                    {'status': self.status, 'text': new_message.get(
                        "status_definition", "reserved").title()})

                self.mqtt_support.client.publish(
                    self.status_topic, status_json , retain=True)

            if new_message["engine_run_time"] != self.run_time:
                self.run_time = new_message["status"]
                self.mqtt_support.client.publish(
                    self.hours_topic, f'{float(new_message["engine_run_time"])/60:.2f}', retain=True)

            return True

        elif self._is_entry_match(self.rvc_match_dimmer_status, new_message):
            self.Logger.debug(f"Msg Match Status: {str(new_message)}")
            if new_message["operating_status_brightness"] != 0.0:
                self.messagestate = "on"
            elif new_message["operating_status_brightness"] == 0.0:
                self.messagestate = "off"
            else:
                self.messagestate = "UNEXPECTED(" + \
                    str(new_message["operating_status"]) + ")"
                self.Logger.error(
                    f"Unexpected RVC value {str(new_message['operating_status_brightness'])}")

            # Only publish if the state has changed
            if self.messagestate != self.state:
                self.mqtt_support.client.publish(
                    self.startstop_trigger_topic, self.messagestate, retain=True)
                self.state = self.messagestate

            return True

        elif self._is_entry_match(self.rvc_match_command, new_message):
            # This is the command.  Just eat the message so it doesn't show up
            # as unhandled.
            self.Logger.debug(f"Msg Match Command: {str(new_message)}")
            return True

        return False

    def process_mqtt_msg(self, topic, payload, properties = None):
        self.Logger.info(
            f"MQTT Msg Received on topic {topic} with payload {payload}")

        if topic == self.command_topic:
            if payload.lower() == "on":
                if self.rvc_instance_name == "start_trigger":
                    self._rvc_start_trigger_on()
                elif self.rvc_instance_name == "stop_trigger":
                    self._rvc_stop_trigger_on()
            elif payload.lower() == "off":
                if self.rvc_instance_name == "start_trigger":
                    self._rvc_start_trigger_off()
                elif self.rvc_instance_name == "stop_trigger":
                    self._rvc_stop_trigger_off()
            else:
                self.Logger.warning(
                    f"Invalid payload {payload} for topic {topic}")

    def _rvc_start_trigger_on(self):
        # 13 FF C8 01 1E 00 FF FF
        msg_bytes = bytearray(8)
        struct.pack_into("<BBBBBBBB", msg_bytes, 0, self.rvc_instance, int(
            self.rvc_group, 2), 100, 1, 30, 0, 255, 255)
        self.send_queue.put({"dgn": "1FEDB", "data": msg_bytes})

    def _rvc_start_trigger_off(self):
        # 13 FF 00 03 FF 00 FF FF
        msg_bytes = bytearray(8)
        struct.pack_into("<BBBBBBBB", msg_bytes, 0, self.rvc_instance, int(
            self.rvc_group, 2), 0, 3, 255, 0, 255, 255)
        self.send_queue.put({"dgn": "1FEDB", "data": msg_bytes})

    def _rvc_stop_trigger_on(self):
        # 14 FF C8 01 01 00 FF FF
        msg_bytes = bytearray(8)
        struct.pack_into("<BBBBBBBB", msg_bytes, 0, self.rvc_instance, int(
            self.rvc_group, 2), 100, 1, 1, 0, 255, 255)
        self.send_queue.put({"dgn": "1FEDB", "data": msg_bytes})

    def _rvc_stop_trigger_off(self):
        # 14 FF 00 03 FF 00 FF FF
        msg_bytes = bytearray(8)
        struct.pack_into("<BBBBBBBB", msg_bytes, 0, self.rvc_instance, int(
            self.rvc_group, 2), 0, 3, 255, 0, 255, 255)
        self.send_queue.put({"dgn": "1FEDB", "data": msg_bytes})

    def initialize(self):
        """ Optional function
        Will get called once when the object is loaded.
        RVC canbus tx queue is available
        mqtt client is ready.

        This can be a good place to request data

        """

        # publish info to mqtt
        self.mqtt_support.client.publish(
            self.status_topic, self.status, retain=True)
        self.mqtt_support.client.publish(
            self.hours_topic, self.run_time, retain=True)
