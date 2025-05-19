"""
An Elwell Timberline 1.5 controller

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
from rvc2mqtt.rvc import RVC_Decoder


class hvac_TIMBERLINE(EntityPluginBaseClass):
    FACTORY_MATCH_ATTRIBUTES = {"name": "TIMBERLINE_CONTROLLER", "type": "hvac"}
    """
    Some of this could probably be handled by another entity
    but the timberline doesn't quite fit because it is a combo device

    Timberline 1.5 Controller that is tied to at least these RVC DGNs:
    WATERHEATER_STATUS
    WATERHEATER_STATUS_4
    CIRCULATION_PUMP_STATUS
    FURNACE_STATUS
    THERMOSTAT_STATUS_1
    THERMOSTAT_STATUS_2
    THERMOSTAT_SCHEDULE_STATUS_1
    THERMOSTAT_AMBIENT_STATUS (handled by temperature entity, timberline is always instance 1)
    DM_RV
    WATERHEATER_COMMAND
    CIRCULATION_PUMP_COMMAND
    FURNACE_COMMAND
    THERMOSTAT_COMMAND_1
    THERMOSTAT_SCHEDULE_COMMAND_1
    TIMBERLINE_PROPRIETARY aka 1EF65
    """

    # Using RVC_Decoder for virtual/fake DGNs for proprietary
    # timberline message on 1EF65 so we can have them in the spec
    # Fake DGNs are 1EF65<1st byte of message> i.e. 1EF6581

    rvc = RVC_Decoder()

    current_schedule_instance_definition = {"0":"sleep","1":"wake"}

    def __init__(self, data: dict, mqtt_support: MQTT_Support):
        self.rvc_instance = data['instance']
        self.source_id = str(data['source_id'])
        self.id = "timberline-controller-1EF65-i" + str(self.rvc_instance)
        super().__init__(data, mqtt_support)
        self.Logger = logging.getLogger(__class__.__name__)

        if 'command_topic' in data:
            command_base = f"{str(data['command_topic'])}"
            #WATERHEATER_COMMAND
            self.command_source = str(f"{command_base}/heatsource")
            self.mqtt_support.register(self.command_source, self.process_mqtt_msg)
            #CIRCULATION_PUMP_COMMAND
            self.command_pumptest = str(f"{command_base}/pumptest")
            self.mqtt_support.register(self.command_pumptest, self.process_mqtt_msg)
            #FURNACE_COMMAND
            self.command_fan_mode = str(f"{command_base}/fan_mode")
            self.mqtt_support.register(self.command_fan_mode, self.process_mqtt_msg)
            self.command_fan_speed = str(f"{command_base}/fan_speed")
            self.mqtt_support.register(self.command_fan_speed, self.process_mqtt_msg)
            #THERMOSTAT_COMMAND_1
            self.command_operating_mode = str(f"{command_base}/mode")
            self.mqtt_support.register(self.command_operating_mode, self.process_mqtt_msg)
            self.command_setpointtemp = str(f"{command_base}/set_point_temperature")
            self.mqtt_support.register(self.command_setpointtemp, self.process_mqtt_msg)
            self.command_setpointtempf = str(f"{command_base}/set_point_temperaturef")
            self.mqtt_support.register(self.command_setpointtempf, self.process_mqtt_msg)
            #THERMOSTAT_SCHEDULE_COMMAND_1
            self.command_sleep_start_hour = str(f"{command_base}/sleep/start_hour")
            self.mqtt_support.register(self.command_sleep_start_hour, self.process_mqtt_msg)
            self.command_sleep_start_minute = str(f"{command_base}/sleep/start_minute")
            self.mqtt_support.register(self.command_sleep_start_minute, self.process_mqtt_msg)
            self.command_sleep_schedule_temp = str(f"{command_base}/sleep/schedule_temperature")
            self.mqtt_support.register(self.command_sleep_schedule_temp, self.process_mqtt_msg)
            self.command_sleep_schedule_tempf = str(f"{command_base}/sleep/schedule_temperaturef")
            self.mqtt_support.register(self.command_sleep_schedule_tempf, self.process_mqtt_msg)
            self.command_wake_start_hour = str(f"{command_base}/wake/start_hour")
            self.mqtt_support.register(self.command_wake_start_hour, self.process_mqtt_msg)
            self.command_wake_start_minute = str(f"{command_base}/wake/start_minute")
            self.mqtt_support.register(self.command_wake_start_minute, self.process_mqtt_msg)
            self.command_wake_schedule_temp = str(f"{command_base}/wake/schedule_temperature")
            self.mqtt_support.register(self.command_wake_schedule_temp, self.process_mqtt_msg)
            self.command_wake_schedule_tempf = str(f"{command_base}/wake/schedule_temperaturef")
            self.mqtt_support.register(self.command_wake_schedule_tempf, self.process_mqtt_msg)
            #TIMBERLINE_PROPRIETARY
            #0x81
            self.command_clear_errors = str(f"{command_base}/clear_errors")
            self.mqtt_support.register(self.command_clear_errors, self.process_mqtt_msg)
            #0x83
            self.command_hot_water_priority = str(f"{command_base}/hot_water_priority")
            self.mqtt_support.register(self.command_hot_water_priority, self.process_mqtt_msg)
            self.command_temperature_sensor = str(f"{command_base}/temperature_sensor")
            self.mqtt_support.register(self.command_temperature_sensor, self.process_mqtt_msg)
            #0x89
            self.command_timers_system_limit = str(f"{command_base}/timers/system_limit")
            self.mqtt_support.register(self.command_timers_system_limit, self.process_mqtt_msg)
            self.command_timers_water_limit = str(f"{command_base}/timers/water_limit")
            self.mqtt_support.register(self.command_timers_water_limit, self.process_mqtt_msg)

        if 'status_topic' in data:
            topic_base = f"{str(data['status_topic'])}"

            # WATERHEATER_STATUS
            self.source_topic                       = str(f"{topic_base}/heatsource")
            self.source_def_topic                   = str(f"{topic_base}/heatsource_definition")
            self.waterheater_temp_topic             = str(f"{topic_base}/water_temperature")
            self.burner_status_topic                = str(f"{topic_base}/burner_status")
            self.burner_status_def_topic            = str(f"{topic_base}/burner_status_definition")
            self.ac_element_status_topic            = str(f"{topic_base}/ac_element_status")
            self.ac_element_status_def_topic        = str(f"{topic_base}/ac_element_status_definition")
            self.failure_to_ignite_status_topic     = str(f"{topic_base}/failure_to_ignite_status")
            self.failure_to_ignite_status_def_topic = str(f"{topic_base}/failure_to_ignite_status_definition")
            # WATERHEATER_STATUS_2
            self.hot_water_priority_topic           = str(f"{topic_base}/hot_water_priority")
            self.hot_water_priority_def_topic       = str(f"{topic_base}/hot_water_priority_definition")
            # CIRCULATION_PUMP_STATUS
            self.output_status_topic                = str(f"{topic_base}/pump_status")
            self.output_status_def_topic            = str(f"{topic_base}/pump_status_definition")
            # FURNACE_STATUS
            self.operating_mode_topic               = str(f"{topic_base}/fan_mode")
            self.operating_mode_def_topic           = str(f"{topic_base}/fan_mode_definition")
            self.circulation_fan_speed_topic        = str(f"{topic_base}/fan_speed")
            # THERMOSTAT_STATUS_1
            self.thermostat_operating_mode_topic    = str(f"{topic_base}/mode")
            self.thermostat_operating_mode_def_topic= str(f"{topic_base}/mode_definition")
            self.thermostat_schedule_mode_topic     = str(f"{topic_base}/schedule_mode")
            self.thermostat_schedule_mode_def_topic = str(f"{topic_base}/schedule_mode_definition")
            self.set_point_temp_topic               = str(f"{topic_base}/set_point_temperature")
            self.set_point_tempf_topic              = str(f"{topic_base}/set_point_temperaturef")
            # THERMOSTAT_STATUS_2
            self.current_schedule_instance_topic    = str(f"{topic_base}/current_schedule_instance")
            self.current_schedule_instance_def_topic= str(f"{topic_base}/current_schedule_instance_definition")
            # THERMOSTAT_SCHEDULE_STATUS_1
            self.sleep_start_hour_topic             = str(f"{topic_base}/sleep/start_hour")
            self.sleep_start_minute_topic           = str(f"{topic_base}/sleep/start_minute")
            self.sleep_schedule_temp_topic          = str(f"{topic_base}/sleep/schedule_temperature")
            self.sleep_schedule_tempf_topic         = str(f"{topic_base}/sleep/schedule_temperaturef")
            self.wake_start_hour_topic              = str(f"{topic_base}/wake/start_hour")
            self.wake_start_minute_topic            = str(f"{topic_base}/wake/start_minute")
            self.wake_schedule_temp_topic           = str(f"{topic_base}/wake/schedule_temperature")
            self.wake_schedule_tempf_topic          = str(f"{topic_base}/wake/schedule_temperaturef")
            # TIMBERLINE_PROPRIETARY
            # 0x84
            self.solenoid_topic                     = str(f"{topic_base}/solenoid")
            self.solenoid_def_topic                 = str(f"{topic_base}/solenoid_definition")
            self.temperature_sensor_topic           = str(f"{topic_base}/temperature_sensor")
            self.temperature_sensor_def_topic       = str(f"{topic_base}/temperature_sensor_definition")
            self.tank_temperature_topic             = str(f"{topic_base}/tank_temperature")
            self.tank_temperaturef_topic            = str(f"{topic_base}/tank_temperaturef")
            self.heater_temperature_topic           = str(f"{topic_base}/heater_temperature")
            self.heater_temperaturef_topic          = str(f"{topic_base}/heater_temperaturef")
            self.fan_manual_speed_topic             = str(f"{topic_base}/fan_manual_speed")
            # 0x85
            self.system_timer_topic                 = str(f"{topic_base}/timers/system")
            self.domestic_water_timer_topic         = str(f"{topic_base}/timers/water_priority")
            self.pump_override_timer_topic          = str(f"{topic_base}/timers/pump_override")
            # 0x86
            self.heater_minutes_topic               = str(f"{topic_base}/info/heater/minutes")
            self.heater_version_topic               = str(f"{topic_base}/info/heater/version")
            # 0x87
            self.panel_minutes_topic                = str(f"{topic_base}/info/panel/minutes")
            self.panel_version_topic                = str(f"{topic_base}/info/panel/version")
            # 0x88
            self.hcu_version_topic                  = str(f"{topic_base}/info/hcu/version")
            # 0x8A
            self.system_limitation_topic            = str(f"{topic_base}/info/system_limit")
            self.water_limitation_topic             = str(f"{topic_base}/info/water_limit")


        # RVC message must match the following to be this device

        self.rvc_waterheater_status           = { "name": "WATERHEATER_STATUS", "instance": self.rvc_instance}
        self.rvc_waterheater_status_2         = { "name": "WATERHEATER_STATUS_2", "instance": self.rvc_instance}
        self.rvc_circulation_pump_status      = { "name": "CIRCULATION_PUMP_STATUS", "instance": self.rvc_instance}
        self.rvc_furnace_status               = { "name": "FURNACE_STATUS", "instance": self.rvc_instance}
        self.rvc_thermostat_status_1          = { "name": "THERMOSTAT_STATUS_1", "instance": self.rvc_instance}
        self.rvc_thermostat_status_2          = { "name": "THERMOSTAT_STATUS_2", "instance": self.rvc_instance}
        self.rvc_thermostat_schedule_status_1 = { "name": "THERMOSTAT_SCHEDULE_STATUS_1", "instance": self.rvc_instance}
        self.rvc_dm_rv                        = { "name": "DM_RV", "source_id": self.source_id}
        self.rvc_timberline_proprietary       = { "name": "TIMBERLINE_PROPRIETARY", "source_id": self.source_id}
        self.rvc_waterheater_command          = { "name": "WATERHEATER_COMMAND", "instance": self.rvc_instance}
        self.rvc_circulation_pump_command     = { "name": "CIRCULATION_PUMP_COMMAND", "instance": self.rvc_instance}
        self.rvc_furnace_command              = { "name": "FURNACE_COMMAND", "instance": self.rvc_instance}
        self.rvc_thermostat_command_1         = { "name": "THERMOSTAT_COMMAND_1", "instance": self.rvc_instance}
        self.rvc_thermostat_schedule_command_1= { "name": "THERMOSTAT_SCHEDULE_COMMAND_1", "instance": self.rvc_instance}

        # save these for later to send rvc msg

        # WATERHEATER_STATUS
        self._source = "unknown"
        self._water_temperature = "unknown"
        self._burner_status = "unknown"
        self._ac_element_status = "unknown"
        self._failure_to_ignite_status = "unknown"
        # WATERHEATER_STATUS_2
        self._hot_water_priority = "unknown"
        # CIRCULATION_PUMP_STATUS
        self._output_status = "unknown"
        # FURNACE_STATUS
        self._operating_mode = "unknown"
        self._circulation_fan_speed = "unknown"
        # THERMOSTAT_STATUS_1
        self._thermostat_operating_mode = "unknown"
        self._thermostat_schedule_mode = "unknown"
        self._set_point_temp = "unknown"
        # THERMOSTAT_STATUS_2
        self._current_schedule_instance = "unknown"
        # THERMOSTAT_SCHEDULE_STATUS_1
        self._sleep_start_hour = "unknown"
        self._sleep_start_minute = "unknown"
        self._sleep_schedule_temp = "unknown"
        self._wake_start_hour = "unknown"
        self._wake_start_minute = "unknown"
        self._wake_schedule_temp = "unknown"
        # TIMBERLINE_PROPRIETARY
        # 0x84
        self._solenoid = "unknown"
        self._temperature_sensor = "unknown"
        self._tank_temperature = "unknown"
        self._heater_temperature = "unknown"
        self._fan_manual_speed = "unknown"
        # 0x85
        self._system_timer = "unknown"
        self._domestic_water_timer = "unknown"
        self._pump_override_timer = "unknown"
        # 0x86
        self._heater_minutes = "unknown"
        self._heater_version = "unknown"
        # 0x87
        self._panel_minutes = "unknown"
        self._panel_version = "unknown"
        # 0x88
        self._hcu_version = "unknown"
        # 0x8A
        self._system_limitation = "unknown"
        self._water_limitation = "unknown"

    def _convert_c_to_f(self, temp_c: float):
        """ Convert Celsius to Fahrenheit"""
        return f"{(temp_c * 9/5) + 32:.2f}"

    def _convert_f_to_c(self, temp_f: float):
        """ Convert Celsius to Fahrenheit"""
        return f"{(temp_f - 32) * 5/9:.2f}"

    def _convert_temp_c_to_rvc_uint16(self, temp_c: float):
        """ convert a temperature stored in C to a UINT16 value for RVC"""
        return round((temp_c + 273 ) * 32)

    def process_rvc_msg(self, new_message: dict) -> bool:
        """ Process an incoming message and determine if it
        is of interest to this object.

        If relevant - Process the message and return True
        else - return False
        """

        processed = False

        if self._is_entry_match(self.rvc_waterheater_status, new_message):
            self.Logger.debug(f"Msg Match Status: {str(new_message)}")
            if new_message["operating_modes"] != self._source:
                self._source = new_message["operating_modes"]
                self.mqtt_support.client.publish(
                    self.source_topic, new_message["operating_modes"], retain=True)
                self.mqtt_support.client.publish(
                    self.source_def_topic, new_message["operating_modes_definition"].title(), retain=True)
            if new_message["water_temperature"] != self._water_temperature:
                self._water_temperature = new_message["water_temperature"]
                self.mqtt_support.client.publish(
                    self.waterheater_temp_topic, new_message["water_temperature"], retain=True)
            if new_message["burner_status"] != self._burner_status:
                self._burner_status = new_message["burner_status"]
                self.mqtt_support.client.publish(
                    self.burner_status_topic, new_message["burner_status"], retain=True)
                self.mqtt_support.client.publish(
                    self.burner_status_def_topic, new_message["burner_status_definition"].title(), retain=True)
            if new_message["ac_element_status"] != self._ac_element_status:
                self._ac_element_status = new_message["ac_element_status"]
                self.mqtt_support.client.publish(
                    self.ac_element_status_topic, new_message["ac_element_status"], retain=True)
                self.mqtt_support.client.publish(
                    self.ac_element_status_def_topic, new_message["ac_element_status_definition"].title(), retain=True)
            if new_message["failure_to_ignite_status"] != self._failure_to_ignite_status:
                self._failure_to_ignite_status = new_message["failure_to_ignite_status"]
                self.mqtt_support.client.publish(
                    self.failure_to_ignite_status_topic, new_message["failure_to_ignite_status"], retain=True)
                self.mqtt_support.client.publish(
                    self.failure_to_ignite_status_def_topic, new_message["failure_to_ignite_status_definition"].title(), retain=True)
            processed = True
        elif self._is_entry_match(self.rvc_waterheater_status_2, new_message):
            self.Logger.debug(f"Msg Match Status: {str(new_message)}")
            if new_message["hot_water_priority"] != self._hot_water_priority:
                self._hot_water_priority = new_message["hot_water_priority"]
                self.mqtt_support.client.publish(
                    self.hot_water_priority_topic, new_message["hot_water_priority"], retain=True)
                self.mqtt_support.client.publish(
                    self.hot_water_priority_def_topic, new_message["hot_water_priority_definition"].title(), retain=True)
            processed = True
        elif self._is_entry_match(self.rvc_circulation_pump_status, new_message):
            self.Logger.debug(f"Msg Match Status: {str(new_message)}")
            if new_message["output_status"] != self._output_status:
                self._output_status = new_message["output_status"]
                self.mqtt_support.client.publish(
                    self.output_status_topic, new_message["output_status"], retain=True)
                self.mqtt_support.client.publish(
                    self.output_status_def_topic, new_message["output_status_definition"].title(), retain=True)
            processed = True
        elif self._is_entry_match(self.rvc_furnace_status, new_message):
            self.Logger.debug(f"Msg Match Status: {str(new_message)}")
            if new_message["operating_mode"] != self._operating_mode:
                self._operating_mode = new_message["operating_mode"]
                self.mqtt_support.client.publish(
                    self.operating_mode_topic, new_message["operating_mode"], retain=True)
                self.mqtt_support.client.publish(
                    self.operating_mode_def_topic, new_message["operating_mode_definition"].title(), retain=True)
            if new_message["circulation_fan_speed"] != self._circulation_fan_speed:
                self._circulation_fan_speed = new_message["circulation_fan_speed"]
                self.mqtt_support.client.publish(
                    self.circulation_fan_speed_topic, new_message["circulation_fan_speed"], retain=True)
            processed = True
        elif self._is_entry_match(self.rvc_thermostat_status_1, new_message):
            self.Logger.debug(f"Msg Match Status: {str(new_message)}")
            if new_message["operating_mode"] != self._thermostat_operating_mode:
                self._thermostat_operating_mode = new_message["operating_mode"]
                self.mqtt_support.client.publish(
                    self.thermostat_operating_mode_topic, new_message["operating_mode"], retain=True)
                self.mqtt_support.client.publish(
                    self.thermostat_operating_mode_def_topic, new_message["operating_mode_definition"].title(), retain=True)
            if new_message["schedule_mode"] != self._thermostat_schedule_mode:
                self._thermostat_schedule_mode = new_message["schedule_mode"]
                self.mqtt_support.client.publish(
                    self.thermostat_schedule_mode_topic, new_message["schedule_mode"], retain=True)
                self.mqtt_support.client.publish(
                    self.thermostat_schedule_mode_def_topic, new_message["schedule_mode_definition"].title(), retain=True)
            if new_message["setpoint_temp_heat"] != self._set_point_temp:
                self._set_point_temp = new_message["setpoint_temp_heat"]
                self.mqtt_support.client.publish(
                    self.set_point_temp_topic, new_message["setpoint_temp_heat"], retain=True)
                self.mqtt_support.client.publish(
                    self.set_point_tempf_topic, round(float(
                        self._convert_c_to_f(new_message["setpoint_temp_heat"]))), retain=True)
            processed = True
        elif self._is_entry_match(self.rvc_thermostat_status_2, new_message):
            self.Logger.debug(f"Msg Match Status: {str(new_message)}")
            if new_message["current_schedule_instance"] != self._current_schedule_instance:
                self._current_schedule_instance = new_message["current_schedule_instance"]
                self.mqtt_support.client.publish(
                    self.current_schedule_instance_topic, new_message["current_schedule_instance"], retain=True)
                self.mqtt_support.client.publish(
                    self.current_schedule_instance_def_topic, self.current_schedule_instance_definition.get(
                        str(new_message["current_schedule_instance"]),"unknown").title(), retain=True)
            processed = True
        elif self._is_entry_match(self.rvc_thermostat_schedule_status_1, new_message):
            self.Logger.debug(f"Msg Match Status: {str(new_message)}")
            if new_message["schedule_mode_instance"] == "0":
                if new_message["start_hour"] != self._sleep_start_hour:
                    self._sleep_start_hour = new_message["start_hour"]
                    self.mqtt_support.client.publish(
                        self.sleep_start_hour_topic, new_message["start_hour"], retain=True)
                if new_message["start_minute"] != self._sleep_start_minute:
                    self._sleep_start_minute = new_message["start_minute"]
                    self.mqtt_support.client.publish(
                        self.sleep_start_minute_topic, new_message["start_minute"], retain=True)
                if new_message["setpoint_temp_heat"] != self._sleep_schedule_temp:
                    self._sleep_schedule_temp = new_message["setpoint_temp_heat"]
                    self.mqtt_support.client.publish(
                        self.sleep_schedule_temp_topic, new_message["setpoint_temp_heat"], retain=True)
                    self.mqtt_support.client.publish(
                        self.sleep_schedule_tempf_topic, round(float(
                            self._convert_c_to_f(new_message["setpoint_temp_heat"]))), retain=True)
            elif new_message["schedule_mode_instance"] == "1": 
                if new_message["start_hour"] != self._wake_start_hour:
                    self._wake_start_hour = new_message["start_hour"]
                    self.mqtt_support.client.publish(
                        self.wake_start_hour_topic, new_message["start_hour"], retain=True)
                if new_message["start_minute"] != self._wake_start_minute:
                    self._wake_start_minute = new_message["start_minute"]
                    self.mqtt_support.client.publish(
                        self.wake_start_minute_topic, new_message["start_minute"], retain=True)
                if new_message["setpoint_temp_heat"] != self._wake_schedule_temp:
                    self._wake_schedule_temp = new_message["setpoint_temp_heat"]
                    self.mqtt_support.client.publish(
                        self.wake_schedule_temp_topic, new_message["setpoint_temp_heat"], retain=True)
                    self.mqtt_support.client.publish(
                        self.wake_schedule_tempf_topic, round(float(
                            self._convert_c_to_f(new_message["setpoint_temp_heat"]))), retain=True)
            processed = True
        elif self._is_entry_match(self.rvc_timberline_proprietary, new_message):
            self.Logger.debug(f"Msg Match Status: {str(new_message)}")
            if new_message["message_type"] == "81": #0x81 Timberline 1.5 Extension Error codes clear command
                # This is the command. Eat message so it doesn't show up as unhandled.
                self.Logger.debug(f"Msg Match Command: {str(new_message)}")
            elif new_message["message_type"] == "83": #0x81 Timberline 1.5 Extension command
                # This is the command. Eat message so it doesn't show up as unhandled.
                self.Logger.debug(f"Msg Match Command: {str(new_message)}")
            elif new_message["message_type"] == "84": #0x84 Timberline 1.5 Extension status message
                if new_message["solenoid"] != self._solenoid:
                    self._solenoid = new_message["solenoid"]
                    self.mqtt_support.client.publish(
                        self.solenoid_topic, new_message["solenoid"], retain=True)
                    self.mqtt_support.client.publish(
                        self.solenoid_def_topic, new_message["solenoid_definition"].title(), retain=True)
                if new_message["used_temperature_sensor"] != self._temperature_sensor:
                    self._temperature_sensor = new_message["used_temperature_sensor"]
                    self.mqtt_support.client.publish(
                        self.temperature_sensor_topic, new_message["used_temperature_sensor"], retain=True)
                    self.mqtt_support.client.publish(
                        self.temperature_sensor_def_topic, new_message["used_temperature_sensor_definition"].title(), retain=True)
                if new_message["tank_temperature"] != self._tank_temperature:
                    self._tank_temperature = new_message["tank_temperature"]
                    self.mqtt_support.client.publish(
                        self.tank_temperature_topic, new_message["tank_temperature"], retain=True)
                    self.mqtt_support.client.publish(
                        self.tank_temperaturef_topic,round(float(
                            self._convert_c_to_f(new_message["tank_temperature"]))), retain=True)
                if new_message["heater_temperature"] != self._heater_temperature:
                    self._heater_temperature = new_message["heater_temperature"]
                    self.mqtt_support.client.publish(
                        self.heater_temperature_topic, new_message["heater_temperature"], retain=True)
                    self.mqtt_support.client.publish(
                        self.heater_temperaturef_topic,round(float(
                            self._convert_c_to_f(new_message["heater_temperature"]))), retain=True)
                if new_message["fan_manual_percents"] != self._fan_manual_speed:
                    self._fan_manual_speed = new_message["fan_manual_percents"]
                    self.mqtt_support.client.publish(
                        self.fan_manual_speed_topic, new_message["fan_manual_percents"], retain=True)
            elif new_message["message_type"] == "85": #0x85 Timberline 1.5 Timers
                if new_message["system_timer"] != self._system_timer:
                    self._system_timer = new_message["system_timer"]
                    self.mqtt_support.client.publish(
                        self.system_timer_topic, new_message["system_timer"], retain=True)
                if new_message["domestic_water_timer"] != self._domestic_water_timer:
                    self._domestic_water_timer = new_message["domestic_water_timer"]
                    self.mqtt_support.client.publish(
                        self.domestic_water_timer_topic, new_message["domestic_water_timer"], retain=True)
                if new_message["pump_override_timer"] != self._pump_override_timer:
                    self._pump_override_timer = new_message["pump_override_timer"]
                    self.mqtt_support.client.publish(
                        self.pump_override_timer_topic, new_message["pump_override_timer"], retain=True)
            elif new_message["message_type"] == "86": #0x86 Timberline 1.5 Heater info
                _ver = '.'.join([new_message["heater_version_1st_byte"],
                        new_message["heater_version_2nd_byte"],
                        new_message["heater_version_3rd_byte"],
                        new_message["heater_version_4th_byte"]])
                if new_message["heater_minutes"] != self._heater_minutes:
                    self._heater_minutes = new_message["heater_minutes"]
                    self.mqtt_support.client.publish(
                        self.heater_minutes_topic, new_message["heater_minutes"], retain=True)
                if _ver != self._heater_version:
                    self._heater_version = _ver
                    self.mqtt_support.client.publish(
                        self.heater_version_topic, _ver, retain=True)
            elif new_message["message_type"] == "87": #0x87 Timberline 1.5 Panel info
                _ver = '.'.join([new_message["panel_version_1st_byte"],
                        new_message["panel_version_2nd_byte"],
                        new_message["panel_version_3rd_byte"],
                        new_message["panel_version_4th_byte"]])
                if new_message["minutes_since_start"] != self._minutes_since_start:
                    self._minutes_since_start = new_message["minutes_since_start"]
                    self.mqtt_support.client.publish(
                        self.minutes_since_start_topic, new_message["minutes_since_start"], retain=True)
                if _ver != self._panel_version:
                    self._panel_version = _ver
                    self.mqtt_support.client.publish(
                        self.panel_version_topic, _ver, retain=True)
            elif new_message["message_type"] == "88": #0x88 Timberline 1.5 HCU info
                _ver = '.'.join([new_message["hcu_version_1st_byte"],
                        new_message["hcu_version_2nd_byte"],
                        new_message["hcu_version_3rd_byte"],
                        new_message["hcu_version_4th_byte"]])
                if _ver != self._hcu_version:
                    self._hcu_version = _ver
                    self.mqtt_support.client.publish(
                        self.hcu_version_topic, _ver, retain=True)
            elif new_message["message_type"] == "89": #0x81 Timberline 1.5 Extension command
                # This is the command. Eat message so it doesn't show up as unhandled.
                self.Logger.debug(f"Msg Match Command: {str(new_message)}")
            elif new_message["message_type"] == "8A": #0x8A Timberline 1.5 Timers Setup status
                if new_message["system_limitation"] != self._system_limitation:
                    self._system_limitation = new_message["system_limitation"]
                    self.mqtt_support.client.publish(
                        self.system_limitation_topic, new_message["system_limitation"], retain=True)
                if new_message["water_limitation"] != self._water_limitation:
                    self._water_limitation = new_message["water_limitation"]
                    self.mqtt_support.client.publish(
                        self.water_limitation_topic, new_message["water_limitation"], retain=True)
            processed = True
        elif self._is_entry_match(self.rvc_waterheater_command, new_message):
            # This is the command. Eat message so it doesn't show up as unhandled.
            self.Logger.debug(f"Msg Match Command: {str(new_message)}")
            processed = True
        elif self._is_entry_match(self.rvc_circulation_pump_command, new_message):
            # This is the command. Eat message so it doesn't show up as unhandled.
            self.Logger.debug(f"Msg Match Command: {str(new_message)}")
            processed = True
        elif self._is_entry_match(self.rvc_furnace_command, new_message):
            # This is the command. Eat message so it doesn't show up as unhandled.
            self.Logger.debug(f"Msg Match Command: {str(new_message)}")
            processed = True
        elif self._is_entry_match(self.rvc_thermostat_command_1, new_message):
            # This is the command. Eat message so it doesn't show up as unhandled.
            self.Logger.debug(f"Msg Match Command: {str(new_message)}")
            processed = True
        elif self._is_entry_match(self.rvc_thermostat_schedule_command_1, new_message):
            # This is the command. Eat message so it doesn't show up as unhandled.
            self.Logger.debug(f"Msg Match Command: {str(new_message)}")
            processed = True

        return processed

    def process_mqtt_msg(self, topic, payload, properties = None):
        self.Logger.info(
            f"MQTT Msg Received on topic {topic} with payload {payload}")

        #if topic == self.command_topic:
        #    else:
        #        self.Logger.warning(
        #            f"Invalid payload {payload} for topic {topic}")

    def initialize(self):
        """ Optional function
        Will get called once when the object is loaded.
        RVC canbus tx queue is available
        mqtt client is ready.

        This can be a good place to request data

        """

