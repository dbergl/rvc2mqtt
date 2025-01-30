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


class Generator_GENERATOR_STATUS_1(EntityPluginBaseClass):
    FACTORY_MATCH_ATTRIBUTES = {"name": "GENERATOR_STATUS_1", "type": "generator"}
    """
    Dimmer switch that is tied to RVC DGN of GENERATOR_STATUS_1 and DC_DIMMER_COMMAND_2

    TODO: support start/stop
    Apparent start message sequence:

        2024-11-08 16:55:22 {'arbitration_id': '0x19ffdc9c', 'data': '008A040000FFFFFF', 'priority': '6', 'dgn_h': '1FF', 'dgn_l': 'DC', 'dgn': '1FFDC', 'source_id': '9C', 'name': 'GENERATOR_STATUS_1', 'status': 0, 'status_definition': 'stopped', 'engine_run_time': 1162, 'engine_load': 255, 'start_battery_voltage': 'n/a'}
        2024-11-08 16:55:23 {'arbitration_id': '0x19fedb9f', 'data': '14FF0003FF00FFFF', 'priority': '6', 'dgn_h': '1FE', 'dgn_l': 'DB', 'dgn': '1FEDB', 'source_id': '9F', 'name': 'DC_DIMMER_COMMAND_2', 'instance': 20, 'group': '11111111', 'desired_level': 0.0, 'command': 3, 'command_definition': 'off', 'delay_duration': 255, 'interlock': '00', 'interlock_definition': 'no interlock active', 'ramp_time': 255}
        2024-11-08 16:55:23 {'arbitration_id': '0x19feda9c', 'data': '14FF00FCFF030000', 'priority': '6', 'dgn_h': '1FE', 'dgn_l': 'DA', 'dgn': '1FEDA', 'source_id': '9C', 'name': 'DC_DIMMER_STATUS_3', 'instance': 20, 'group': '11111111', 'operating_status_brightness': 0.0, 'lock_status': '00', 'lock_status_definition': 'load is unlocked', 'overcurrent_status': '11', 'overcurrent_status_definition': 'overcurrent status is unavailable or not supported', 'override_status': '11', 'override_status_definition': 'override status is unavailable or not supported', 'enable_status': '11', 'enable_status_definition': 'enable status is unavailable or not supported', 'delay_duration': 255, 'last_command': 3, 'last_command_definition': 'off', 'interlock_status': '00', 'interlock_status_definition': 'interlock command is not active', 'load_status': '00', 'load_status_definition': 'operating status is zero', 'master_memory_value': 0.0}
        2024-11-08 16:55:23 {'arbitration_id': '0x19ffdc9c', 'data': '008A040000FFFFFF', 'priority': '6', 'dgn_h': '1FF', 'dgn_l': 'DC', 'dgn': '1FFDC', 'source_id': '9C', 'name': 'GENERATOR_STATUS_1', 'status': 0, 'status_definition': 'stopped', 'engine_run_time': 1162, 'engine_load': 255, 'start_battery_voltage': 'n/a'}
        2024-11-08 16:55:24 {'arbitration_id': '0x19fedb9f', 'data': '13FFC8011E00FFFF', 'priority': '6', 'dgn_h': '1FE', 'dgn_l': 'DB', 'dgn': '1FEDB', 'source_id': '9F', 'name': 'DC_DIMMER_COMMAND_2', 'instance': 19, 'group': '11111111', 'desired_level': 100.0, 'command': 1, 'command_definition': 'on duration', 'delay_duration': 30, 'interlock': '00', 'interlock_definition': 'no interlock active', 'ramp_time': 255}
        2024-11-08 16:55:24 {'arbitration_id': '0x19feda9c', 'data': '13FFC8FC1E010400', 'priority': '6', 'dgn_h': '1FE', 'dgn_l': 'DA', 'dgn': '1FEDA', 'source_id': '9C', 'name': 'DC_DIMMER_STATUS_3', 'instance': 19, 'group': '11111111', 'operating_status_brightness': 100.0, 'lock_status': '00', 'lock_status_definition': 'load is unlocked', 'overcurrent_status': '11', 'overcurrent_status_definition': 'overcurrent status is unavailable or not supported', 'override_status': '11', 'override_status_definition': 'override status is unavailable or not supported', 'enable_status': '11', 'enable_status_definition': 'enable status is unavailable or not supported', 'delay_duration': 30, 'last_command': 1, 'last_command_definition': 'on duration', 'interlock_status': '00', 'interlock_status_definition': 'interlock command is not active', 'load_status': '01', 'load_status_definition': 'operating status is non-zero or flashing', 'master_memory_value': 0.0}
        2024-11-08 16:55:24 {'arbitration_id': '0x19ffdc9c', 'data': '008A040000FFFFFF', 'priority': '6', 'dgn_h': '1FF', 'dgn_l': 'DC', 'dgn': '1FFDC', 'source_id': '9C', 'name': 'GENERATOR_STATUS_1', 'status': 0, 'status_definition': 'stopped', 'engine_run_time': 1162, 'engine_load': 255, 'start_battery_voltage': 'n/a'}
        2024-11-08 16:55:25 {'arbitration_id': '0x19feda9c', 'data': '13FFC8FC1C010400', 'priority': '6', 'dgn_h': '1FE', 'dgn_l': 'DA', 'dgn': '1FEDA', 'source_id': '9C', 'name': 'DC_DIMMER_STATUS_3', 'instance': 19, 'group': '11111111', 'operating_status_brightness': 100.0, 'lock_status': '00', 'lock_status_definition': 'load is unlocked', 'overcurrent_status': '11', 'overcurrent_status_definition': 'overcurrent status is unavailable or not supported', 'override_status': '11', 'override_status_definition': 'override status is unavailable or not supported', 'enable_status': '11', 'enable_status_definition': 'enable status is unavailable or not supported', 'delay_duration': 28, 'last_command': 1, 'last_command_definition': 'on duration', 'interlock_status': '00', 'interlock_status_definition': 'interlock command is not active', 'load_status': '01', 'load_status_definition': 'operating status is non-zero or flashing', 'master_memory_value': 0.0}
        2024-11-08 16:55:25 {'arbitration_id': '0x19ffdc9c', 'data': '008A040000FFFFFF', 'priority': '6', 'dgn_h': '1FF', 'dgn_l': 'DC', 'dgn': '1FFDC', 'source_id': '9C', 'name': 'GENERATOR_STATUS_1', 'status': 0, 'status_definition': 'stopped', 'engine_run_time': 1162, 'engine_load': 255, 'start_battery_voltage': 'n/a'}
        2024-11-08 16:55:26 {'arbitration_id': '0x19ffdc9c', 'data': '038A040000FFFFFF', 'priority': '6', 'dgn_h': '1FF', 'dgn_l': 'DC', 'dgn': '1FFDC', 'source_id': '9C', 'name': 'GENERATOR_STATUS_1', 'status': 3, 'status_definition': 'running', 'engine_run_time': 1162, 'engine_load': 255, 'start_battery_voltage': 'n/a'}
    

    Apparent stop message sequence:
        2024-11-08 16:56:02 {'arbitration_id': '0x19ffdc9c', 'data': '038B040000FFFFFF', 'priority': '6', 'dgn_h': '1FF', 'dgn_l': 'DC', 'dgn': '1FFDC', 'source_id': '9C', 'name': 'GENERATOR_STATUS_1', 'status': 3, 'status_definition': 'running', 'engine_run_time': 1163, 'engine_load': 255, 'start_battery_voltage': 'n/a'}
        2024-11-08 16:56:03 {'arbitration_id': '0x19fedb9f', 'data': '13FF0003FF00FFFF', 'priority': '6', 'dgn_h': '1FE', 'dgn_l': 'DB', 'dgn': '1FEDB', 'source_id': '9F', 'name': 'DC_DIMMER_COMMAND_2', 'instance': 19, 'group': '11111111', 'desired_level': 0.0, 'command': 3, 'command_definition': 'off', 'delay_duration': 255, 'interlock': '00', 'interlock_definition': 'no interlock active', 'ramp_time': 255}
        2024-11-08 16:56:03 {'arbitration_id': '0x19fedb9f', 'data': '14FFC8010200FFFF', 'priority': '6', 'dgn_h': '1FE', 'dgn_l': 'DB', 'dgn': '1FEDB', 'source_id': '9F', 'name': 'DC_DIMMER_COMMAND_2', 'instance': 20, 'group': '11111111', 'desired_level': 100.0, 'command': 1, 'command_definition': 'on duration', 'delay_duration': 2, 'interlock': '00', 'interlock_definition': 'no interlock active', 'ramp_time': 255}
        2024-11-08 16:56:03 {'arbitration_id': '0x19feda9c', 'data': '13FF00FCFF030000', 'priority': '6', 'dgn_h': '1FE', 'dgn_l': 'DA', 'dgn': '1FEDA', 'source_id': '9C', 'name': 'DC_DIMMER_STATUS_3', 'instance': 19, 'group': '11111111', 'operating_status_brightness': 0.0, 'lock_status': '00', 'lock_status_definition': 'load is unlocked', 'overcurrent_status': '11', 'overcurrent_status_definition': 'overcurrent status is unavailable or not supported', 'override_status': '11', 'override_status_definition': 'override status is unavailable or not supported', 'enable_status': '11', 'enable_status_definition': 'enable status is unavailable or not supported', 'delay_duration': 255, 'last_command': 3, 'last_command_definition': 'off', 'interlock_status': '00', 'interlock_status_definition': 'interlock command is not active', 'load_status': '00', 'load_status_definition': 'operating status is zero', 'master_memory_value': 0.0}
        2024-11-08 16:56:03 {'arbitration_id': '0x19feda9c', 'data': '14FFC8FC02010400', 'priority': '6', 'dgn_h': '1FE', 'dgn_l': 'DA', 'dgn': '1FEDA', 'source_id': '9C', 'name': 'DC_DIMMER_STATUS_3', 'instance': 20, 'group': '11111111', 'operating_status_brightness': 100.0, 'lock_status': '00', 'lock_status_definition': 'load is unlocked', 'overcurrent_status': '11', 'overcurrent_status_definition': 'overcurrent status is unavailable or not supported', 'override_status': '11', 'override_status_definition': 'override status is unavailable or not supported', 'enable_status': '11', 'enable_status_definition': 'enable status is unavailable or not supported', 'delay_duration': 2, 'last_command': 1, 'last_command_definition': 'on duration', 'interlock_status': '00', 'interlock_status_definition': 'interlock command is not active', 'load_status': '01', 'load_status_definition': 'operating status is non-zero or flashing', 'master_memory_value': 0.0}
        2024-11-08 16:56:03 {'arbitration_id': '0x19feda9c', 'data': '14FFC8FC01014400', 'priority': '6', 'dgn_h': '1FE', 'dgn_l': 'DA', 'dgn': '1FEDA', 'source_id': '9C', 'name': 'DC_DIMMER_STATUS_3', 'instance': 20, 'group': '11111111', 'operating_status_brightness': 100.0, 'lock_status': '00', 'lock_status_definition': 'load is unlocked', 'overcurrent_status': '11', 'overcurrent_status_definition': 'overcurrent status is unavailable or not supported', 'override_status': '11', 'override_status_definition': 'override status is unavailable or not supported', 'enable_status': '11', 'enable_status_definition': 'enable status is unavailable or not supported', 'delay_duration': 1, 'last_command': 1, 'last_command_definition': 'on duration', 'interlock_status': '00', 'interlock_status_definition': 'interlock command is not active', 'load_status': '01', 'load_status_definition': 'operating status is non-zero or flashing', 'master_memory_value': 0.0}
        2024-11-08 16:56:03 {'arbitration_id': '0x19ffdc9c', 'data': '008B040000FFFFFF', 'priority': '6', 'dgn_h': '1FF', 'dgn_l': 'DC', 'dgn': '1FFDC', 'source_id': '9C', 'name': 'GENERATOR_STATUS_1', 'status': 0, 'status_definition': 'stopped', 'engine_run_time': 1163, 'engine_load': 255, 'start_battery_voltage': 'n/a'}
    """

    def __init__(self, data: dict, mqtt_support: MQTT_Support):
        self.rvc_instance = data.get('instance', 0)
        self.id = "dimmer-1FEDB-i" + str(self.rvc_instance)
        super().__init__(data, mqtt_support)
        self.Logger = logging.getLogger(__class__.__name__)

        ## Allow MQTT to Generator
        #if 'command_topic' in data:
        #    self.command_topic = str(['status_topic'])
        #else:
        #    self.command_topic = mqtt_support.make_device_topic_string(
        #        self.id, None, False)

        #self.mqtt_support.register(self.command_topic, self.process_mqtt_msg)

        if 'status_topic' in data:
            topic_base = f"{data['status_topic']}"

            self.status_topic = str(f"{topic_base}/status")
            self.hours_topic = str(f"{topic_base}/hours")
        else:
            self.status_topic = mqtt_support.make_device_topic_string(self.id, "status", True)
            self.hours_topic = mqtt_support.make_device_topic_string(self.id, "hours", True)


        # RVC message must match the following to be this device
        self.rvc_match_status = { "name": "GENERATOR_STATUS_1"}
        #self.rvc_match_command= { "name": "DC_DIMMER_COMMAND_2", "instance": self.rvc_instance }

        #self.Logger.debug(f"Must match: {str(self.rvc_match_status)} or {str(self.rvc_match_command)}")
        self.Logger.debug(f"Must match: {str(self.rvc_match_status)}")

        # save these for later to send rvc msg
        self.rvc_group = '11111111'
        if 'group' in data:
            self.rvc_group = data['group']
        self.name = data['instance_name']
        self.state = "unknown"
        self.run_time = "unknown"

        self.device = {"manufacturer": "RV-C",
                       "via_device": self.mqtt_support.get_bridge_ha_name(),
                       "identifiers": self.unique_device_id,
                       "name": self.name,
                       "model": "RV-C Dimmer from DC_DIMMER_STATUS_3"
                       }

    def process_rvc_msg(self, new_message: dict) -> bool:
        """ Process an incoming message and determine if it
        is of interest to this object.

        If relevant - Process the message and return True
        else - return False
        """

        if self._is_entry_match(self.rvc_match_status, new_message):
            self.Logger.debug(f"Msg Match Status: {str(new_message)}")
            if new_message["status"] != self.state:
                self.state = new_message["status"]
                self.mqtt_support.client.publish(
                    self.status_topic, new_message["status_definition"].title(), retain=True)

            if new_message["engine_run_time"] != self.run_time:
                self.run_time = new_message["status"]
                self.mqtt_support.client.publish(
                    self.hours_topic, f'{float(new_message["engine_run_time"])/60:.2f}', retain=True)

            return True

        #elif self._is_entry_match(self.rvc_match_command, new_message):
        #    # This is the command.  Just eat the message so it doesn't show up
        #    # as unhandled.
        #    self.Logger.debug(f"Msg Match Command: {str(new_message)}")
        #    return True
        return False

    def process_mqtt_msg(self, topic, payload):
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

    """
    On:
        2024-09-10 22:00:35 {'arbitration_id': '0x19fedbfd', 'data': '20FFFA05FF00FFFF', 'priority': '6', 'dgn_h': '1FE', 'dgn_l': 'DB', 'dgn': '1FEDB', 'source_id': 'FD', 'name': 'DC_DIMMER_COMMAND_2', 'instance': 32, 'group': '11111111', 'desired_level': 125.0, 'command': 5, 'command_definition': 'toggle', 'delay_duration': 255, 'interlock': '00', 'interlock_definition': 'no interlock active'}

    Off:
    2024-09-10 22:00:39 {'arbitration_id': '0x19fedbfd', 'data': '20FFFA05FF00FFFF', 'priority': '6', 'dgn_h': '1FE', 'dgn_l': 'DB', 'dgn': '1FEDB', 'source_id': 'FD', 'name': 'DC_DIMMER_COMMAND_2', 'instance': 32, 'group': '11111111', 'desired_level': 125.0, 'command': 5, 'command_definition': 'toggle', 'delay_duration': 255, 'interlock': '00', 'interlock_definition': 'no interlock active'}
    """

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
                  #"command_topic": self.command_topic,
                  "qos": 1, "retain": False,
                  "payload_on": "Running",
                  "payload_off": "Stopped",
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
        msg_bytes = bytearray(8)
        struct.pack_into("<BBBBBBBB", msg_bytes, 0, 0xDA,
            0xFE, 1, self.rvc_instance, 0, 0, 0, 0)

        self.send_queue.put({"dgn": "0EAFF", "data": msg_bytes})
