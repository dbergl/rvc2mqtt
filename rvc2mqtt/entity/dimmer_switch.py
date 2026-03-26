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


class DimmerSwitch_DC_DIMMER_STATUS_3(EntityPluginBaseClass):
    FACTORY_MATCH_ATTRIBUTES = {"name": "DC_DIMMER_STATUS_3", "type": "dimmer_switch"}
    """
    Dimmer switch that is tied to RVC DGN of DC_DIMMER_STATUS_3 and DC_DIMMER_COMMAND_2
    Supports ON/OFF and brightness (0-100%)
    """
    LIGHT_ON = "on"
    LIGHT_OFF = "off"

    def __init__(self, data: dict, mqtt_support: MQTT_Support):
        self.id = "dimmer-1FEDB-i" + str(data["instance"])
        super().__init__(data, mqtt_support)
        self.Logger = logging.getLogger(__class__.__name__)

        # Allow MQTT to control light
        if 'command_topic' in data:
            self.command_topic = str(data['command_topic'])
        else:
            self.command_topic = mqtt_support.make_device_topic_string(
                self.id, None, False)

        self.mqtt_support.register(self.command_topic, self.process_mqtt_msg)

        if 'status_topic' in data:
            self.status_topic = str(data['status_topic'])

        self.dimmable = data.get('dimmable', True)
        if self.dimmable:
            self.brightness_status_topic = self.status_topic + "/brightness"
            self.brightness_command_topic = self.command_topic + "/brightness"
            self.mqtt_support.register(self.brightness_command_topic, self.process_mqtt_msg)


        # RVC message must match the following to be this device
        self.rvc_match_status = { "name": "DC_DIMMER_STATUS_3", "instance": data['instance']}
        self.rvc_match_command= { "name": "DC_DIMMER_COMMAND_2", "instance": data['instance']}

        self.Logger.debug(f"Must match: {str(self.rvc_match_status)} or {str(self.rvc_match_command)}")

        # save these for later to send rvc msg
        self.rvc_instance = data['instance']
        self.rvc_group = '11111111'
        if 'group' in data:
            self.rvc_group = data['group']
        self.name = data['instance_name']
        self.state = "unknown"
        self.messagestate = "unknown"
        self.brightness = 0

        self.device = {'mf': 'RV-C',
                       'ids': self.unique_device_id,
                       'mdl': 'RV-C Dimmer from DC_DIMMER_STATUS_3',
                       'name': self.name
                       }

    def process_rvc_msg(self, new_message: dict) -> bool:
        """ Process an incoming message and determine if it
        is of interest to this object.

        If relevant - Process the message and return True
        else - return False
        """

        if self._is_entry_match(self.rvc_match_status, new_message):
            self.Logger.debug(f"Msg Match Status: {str(new_message)}")
            if new_message["operating_status_brightness"] != 0.0:
                self.messagestate = DimmerSwitch_DC_DIMMER_STATUS_3.LIGHT_ON
            elif new_message["operating_status_brightness"] == 0.0:
                self.messagestate = DimmerSwitch_DC_DIMMER_STATUS_3.LIGHT_OFF
            else:
                self.messagestate = "UNEXPECTED(" + \
                    str(new_message["operating_status"]) + ")"
                self.Logger.error(
                    f"Unexpected RVC value {str(new_message['operating_status_brightness'])}")

            # Only publish if the state has changed
            if self.messagestate != self.state:
                self.mqtt_support.client.publish(
                    self.status_topic, self.messagestate, retain=True)
                self.state = self.messagestate

            if self.dimmable:
                raw_brightness = new_message["operating_status_brightness"]
                if raw_brightness == "n/a":
                    return True
                new_brightness = int(raw_brightness)
                if new_brightness != self.brightness:
                    self.mqtt_support.client.publish(
                        self.brightness_status_topic, new_brightness, retain=True)
                    self.brightness = new_brightness

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
            if payload.lower() == DimmerSwitch_DC_DIMMER_STATUS_3.LIGHT_OFF:
                if self.state != DimmerSwitch_DC_DIMMER_STATUS_3.LIGHT_OFF:
                    self._rvc_light_toggle()
            elif payload.lower() == DimmerSwitch_DC_DIMMER_STATUS_3.LIGHT_ON:
                if self.state != DimmerSwitch_DC_DIMMER_STATUS_3.LIGHT_ON:
                    self._rvc_light_toggle()
            else:
                self.Logger.warning(
                    f"Invalid payload {payload} for topic {topic}")
        elif self.dimmable and topic == self.brightness_command_topic:
            try:
                level = int(float(payload))
                level = max(0, min(100, level))
                if level != self.brightness:
                    self._rvc_set_brightness(level)
            except ValueError:
                self.Logger.warning(
                    f"Invalid brightness payload {payload} for topic {topic}")

    """
    On:
        2024-09-10 22:00:35 {'arbitration_id': '0x19fedbfd', 'data': '20FFFA05FF00FFFF', 'priority': '6', 'dgn_h': '1FE', 'dgn_l': 'DB', 'dgn': '1FEDB', 'source_id': 'FD', 'name': 'DC_DIMMER_COMMAND_2', 'instance': 32, 'group': '11111111', 'desired_level': 125.0, 'command': 5, 'command_definition': 'toggle', 'delay_duration': 255, 'interlock': '00', 'interlock_definition': 'no interlock active'}

    Off:
    2024-09-10 22:00:39 {'arbitration_id': '0x19fedbfd', 'data': '20FFFA05FF00FFFF', 'priority': '6', 'dgn_h': '1FE', 'dgn_l': 'DB', 'dgn': '1FEDB', 'source_id': 'FD', 'name': 'DC_DIMMER_COMMAND_2', 'instance': 32, 'group': '11111111', 'desired_level': 125.0, 'command': 5, 'command_definition': 'toggle', 'delay_duration': 255, 'interlock': '00', 'interlock_definition': 'no interlock active'}
    """

    def _rvc_set_brightness(self, level: int):
        """Send DC_DIMMER_COMMAND_2 with command=0 (set brightness), level 0-100%"""
        msg_bytes = bytearray(8)
        desired_level = int(level * 2)  # 0-100% → 0-200 wire format
        struct.pack_into("<BBBBBBBB", msg_bytes, 0,
                         self.rvc_instance,
                         int(self.rvc_group, 2),
                         desired_level,
                         0,     # command = set brightness
                         0xFF,  # delay/duration = immediate
                         0,     # interlock = none
                         0xFF,  # ramp_time = immediate
                         0xFF)
        self.send_queue.put({"dgn": "1FEDB", "data": msg_bytes})

    def _rvc_light_off(self):
        # 01 00 FA 00 03 FF 0000
        msg_bytes = bytearray(8)
        struct.pack_into("<BBBBBBB", msg_bytes, 0, self.rvc_instance, int(
            self.rvc_group, 2), 251, 3, 0, 0, 0)
        self.send_queue.put({"dgn": "1FEDB", "data": msg_bytes})

    def _rvc_light_on(self):

        # 01 00 FA 00 01 FF 0000
        msg_bytes = bytearray(8)
        struct.pack_into("<BBBBBBB", msg_bytes, 0, self.rvc_instance, int(
            self.rvc_group, 2), 251, 1, 0xFF, 0, 0)
        self.send_queue.put({"dgn": "1FEDB", "data": msg_bytes})

    def _rvc_light_toggle(self):

        msg_bytes = bytearray(8)
        struct.pack_into("<BBBBBBBB", msg_bytes, 0, self.rvc_instance, int(
            self.rvc_group, 2), 250, 5, 0xFF, 0, 0xFF, 0xFF)
        self.send_queue.put({"dgn": "1FEDB", "data": msg_bytes})

    def publish_ha_discovery_config(self):
        origin = {'name': self.mqtt_support.get_bridge_ha_name()}
        config = {'o': origin,
                  'state_topic': self.status_topic,
                  'command_topic': self.command_topic,
                  'name': None,
                  'qos': 1, 'retain': False,
                  'payload_on': DimmerSwitch_DC_DIMMER_STATUS_3.LIGHT_ON,
                  'payload_off': DimmerSwitch_DC_DIMMER_STATUS_3.LIGHT_OFF,
                  'unique_id': self.unique_device_id,
                  'dev': self.device}
        if self.dimmable:
            config['brightness_state_topic'] = self.brightness_status_topic
            config['brightness_command_topic'] = self.brightness_command_topic
            config['brightness_scale'] = 100
            config['on_command_type'] = 'brightness'
        config.update(self.get_availability_discovery_info_for_ha())
        config_json = json.dumps(config)
        ha_component = "light" if self.dimmable else "switch"
        ha_config_topic = self.mqtt_support.make_ha_auto_discovery_config_topic(
            self.unique_device_id, ha_component)
        self.mqtt_support.client.publish(ha_config_topic, config_json, retain=False)

    def initialize(self):
        """ Optional function
        Will get called once when the object is loaded.
        RVC canbus tx queue is available
        mqtt client is ready.

        This can be a good place to request data

        """
        self.publish_ha_discovery_config()
        self.mqtt_support.client.publish(self.status_topic, self.state, retain=True)
        if self.dimmable:
            self.mqtt_support.client.publish(self.brightness_status_topic, self.brightness, retain=True)

        # request dgn report - this should trigger that dimmer to report
        # dgn = 1FEDA which is actually  DA FE 01 <instance> FF 00 00 00
        self.Logger.debug("Sending Request for DGN")
        msg_bytes = bytearray(8)
        struct.pack_into("<BBBBBBBB", msg_bytes, 0, 0xDA,
            0xFE, 1, self.rvc_instance, 0, 0, 0, 0)
        self.send_queue.put({"dgn": "0EAFF", "data": msg_bytes})
