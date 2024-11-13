"""
A solar charge controller

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
    Solar Charge Controller that is tied to at least these RVC DGNs:
    SOLAR_EQUALIZATION_STATUS
    SOLAR_EQUALIZATION_CONFIGURATION_STATUS
    SOLAR_CONTROLLER_SOLAR_ARRAY_STATUS
    SOLAR_CONTROLLER_BATTERY_STATUS
    SOLAR_CONTROLLER_CONFIGURATION_STATUS
    SOLAR_CONTROLLER_CONFIGURATION_STATUS_2
    SOLAR_CONTROLLER_CONFIGURATION_STATUS_3
    SOLAR_CONTROLLER_CONFIGURATION_STATUS_4
    SOLAR_CONTROLLER_STATUS
    SOLAR_CONTROLLER_STATUS_2
    SOLAR_CONTROLLER_STATUS_3
    SOLAR_CONTROLLER_STATUS_4
    SOLAR_CONTROLLER_STATUS_5
    SOLAR_CONTROLLER_STATUS_6
    GENERIC_ALARM_STATUS

    TODO: Maybe add configuration commands??
    """

    def __init__(self, data: dict, mqtt_support: MQTT_Support):
        self.rvc_instance = data['instance']
        self.id = "solar-charge-controller-1FEB3-i" + str(self.rvc_instance)
        super().__init__(data, mqtt_support)
        self.Logger = logging.getLogger(__class__.__name__)

        ## TODO Allow MQTT to control solar charge controller and config?
        #if 'status_topic' in data:
        #    self.command_topic = str(f"{data['status_topic']}/set")
        #else:
        #    self.command_topic = mqtt_support.make_device_topic_string(
        #        self.id, None, False)

        #self.mqtt_support.register(self.command_topic, self.process_mqtt_msg)

        if 'status_topic' in data:
            topic_base = f"{str(data['status_topic'])}/{str(self.rvc_instance)}"

            # SOLAR_CONTROLLER_STATUS
            self.operating_state_topic = str(f"{topic_base}/operating-state")
            self.power_up_state_topic = str(f"{topic_base}/power-up-state")
            self.force_charge_topic = str(f"{topic_base}/force-charge")
            # SOLAR_CONTROLLER_STATUS_4
            self.today_topic = str(f"{topic_base}/history/today")
            self.yesterday_topic = str(f"{topic_base}/history/yesterday")
            self.two_days_ago_topic = str(f"{topic_base}/history/2-days-ago")
            # SOLAR_CONTROLLER_STATUS_5
            self.seven_day_total_topic = str(f"{topic_base}/history/7-day-total")
            self.cumulative_power_generation_topic = str(f"{topic_base}/history/cumulative-power-generation")
            # SOLAR_CONTROLLER_STATUS_6
            self.operating_days__topic = str(f"{topic_base}/history/operating-days")
            self.temperature_topic = str(f"{topic_base}/temp")
            # SOLAR_CONTROLLER_SOLAR_ARRAY_STATUS
            self.array_voltage_topic = str(f"{topic_base}/solar_array_voltage")
            self.array_current_topic = str(f"{topic_base}/solar_array_current")
            # SOLAR_CONTROLLER_BATTERY_STATUS
            self.battery_voltage_topic = str(f"{topic_base}/battery_voltage")
            self.battery_current_topic = str(f"{topic_base}/battery_current")
                    

            self.hours_topic = str(f"{topic_base}/")
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
