"""
An InverterCharger

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


class InverterCharger_INVERTER_STATUS(EntityPluginBaseClass):
    FACTORY_MATCH_ATTRIBUTES = {"name": "INVERTER_STATUS", "type": "inverter"}
    """
    INVERTER Charger that is tied to at least these RVC DGNs:

    INVERTER_STATUS
    INVERTER_AC_STATUS_1
    INVERTER_AC_STATUS_2
    INVERTER_AC_STATUS_3
    INVERTER_AC_STATUS_4
    INVERTER_DC_STATUS
    INVERTER_TEMPERATURE_STATUS
    GENERIC_ALARM_STATUS

    TODO: Maybe add configuration commands??
    """

    def __init__(self, data: dict, mqtt_support: MQTT_Support):
        self.rvc_instance = data['instance']
        self.id = "solar-charge-controller-1FEB3-i" + str(self.rvc_instance)
        super().__init__(data, mqtt_support)
        self.Logger = logging.getLogger(__class__.__name__)

        ## TODO Allow MQTT to control inverter and config?
        #if 'command_topic' in data:
        #    self.command_topic = str(data['command_topic'])
        #else:
        #    self.command_topic = mqtt_support.make_device_topic_string(
        #        self.id, None, False)

        #self.mqtt_support.register(self.command_topic, self.process_mqtt_msg)

        if 'status_topic' in data:
            topic_base = f"{str(data['status_topic'])}"

            # INVERTER_STATUS
            self.status_definition_topic       = str(f"{topic_base}/status")

            # INVERTER_AC_STATUS_1
            self.rms_voltage_topic             = str(rms_voltage")
            self.rms_current_topic             = str(rms_current")
            self.frequency_topic               = str(frequency")
            self.fault_open_ground_topic       = str(fault/open_ground")
            self.fault_open_neutral_topic      = str(fault/open_neutral")
            self.fault_reverse_polarity_topic  = str(fault/reverse_polarity")
            self.fault_ground_current_topic    = str(fault/ground_current")
            #self.line_definition_topic         = str(f"{topic_base}/line")
            #self.input_output_definition_topic = str(f"{topic_base}/input_output")

            # INVERTER_AC_STATUS_2
            self.peak_voltage_topic            = str(f"{topic_base}/peak_voltage")
            self.peak_current_topic            = str(f"{topic_base}/peak_current")
            self.ground_current_topic          = str(f"{topic_base}/ground_current")
            self.capacity_topic                = str(f"{topic_base}/capacity_current")

            # INVERTER_AC_STATUS_3
            # INVERTER_AC_STATUS_4
            # INVERTER_DC_STATUS
            # INVERTER_TEMPERATURE_STATUS
            # GENERIC_ALARM_STATUS

            self.operating_state_topic  = str(f"{topic_base}/operating-state")
            self.power_up_state_topic   = str(f"{topic_base}/power-up-state")
            self.force_charge_topic     = str(f"{topic_base}/force-charge")
            # SOLAR_CONTROLLER_STATUS_4
            self.today_topic            = str(f"{topic_base}/history/today")
            self.yesterday_topic        = str(f"{topic_base}/history/yesterday")
            self.two_days_ago_topic     = str(f"{topic_base}/history/2-days-ago")
            # SOLAR_CONTROLLER_STATUS_5
            self.seven_day_total_topic  = str(f"{topic_base}/history/7-day-total")
            self.power_generation_topic = str(f"{topic_base}/history/cumulative-power-generation")
            # SOLAR_CONTROLLER_STATUS_6
            self.operating_days_topic   = str(f"{topic_base}/history/operating-days")
            self.temperature_topic      = str(f"{topic_base}/temperature")
            # SOLAR_CONTROLLER_SOLAR_ARRAY_STATUS
            self.array_voltage_topic    = str(f"{topic_base}/solar-array-voltage")
            self.array_current_topic    = str(f"{topic_base}/solar-array-current")
            self.array_power_topic      = str(f"{topic_base}/solar-array-power")
            # SOLAR_CONTROLLER_BATTERY_STATUS
            self.battery_voltage_topic        = str(f"{topic_base}/battery-voltage")
            self.battery_current_topic        = str(f"{topic_base}/battery-current")
            self.battery_power_topic          = str(f"{topic_base}/battery-power")
            self.battery_temperature_topic    = str(f"{topic_base}/battery-temperature")

        else:
            self.operating_state_topic  = mqtt_support.make_device_topic_string(self.id, "operating-state", True)
            self.power_up_state_topic   = mqtt_support.make_device_topic_string(self.id, "power-up-state", True)
            self.force_charge_topic     = mqtt_support.make_device_topic_string(self.id, "force-charge", True)
            self.today_topic            = mqtt_support.make_device_topic_string(self.id, "history/today", True)
            self.yesterday_topic        = mqtt_support.make_device_topic_string(self.id, "history/yesterday", True)
            self.two_days_ago_topic     = mqtt_support.make_device_topic_string(self.id, "history/2-days-ago", True)
            self.seven_day_total_topic  = mqtt_support.make_device_topic_string(self.id, "history/7-day-total", True)
            self.power_generation_topic = mqtt_support.make_device_topic_string(self.id, "history/cumulative-power-generation", True)
            self.operating_days_topic   = mqtt_support.make_device_topic_string(self.id, "operating-days", True)
            self.temperature_topic      = mqtt_support.make_device_topic_string(self.id, "temperature", True)
            self.array_voltage_topic    = mqtt_support.make_device_topic_string(self.id, "solar-array-voltage", True)
            self.array_current_topic    = mqtt_support.make_device_topic_string(self.id, "solar-array-voltage", True)
            self.array_power_topic      = mqtt_support.make_device_topic_string(self.id, "solar-array-voltage", True)
            self.battery_voltage_topic  = mqtt_support.make_device_topic_string(self.id, "battery-voltage", True)
            self.battery_current_topic  = mqtt_support.make_device_topic_string(self.id, "battery-current", True)

        # RVC message must match the following to be this device

        self.rvc_solar_controller_status   = { "name": "SOLAR_CONTROLLER_STATUS", "instance": self.rvc_instance}
        self.rvc_solar_controller_4_status = { "name": "SOLAR_CONTROLLER_STATUS_4", "instance": self.rvc_instance}
        self.rvc_solar_controller_5_status = { "name": "SOLAR_CONTROLLER_STATUS_5", "instance": self.rvc_instance}
        self.rvc_solar_controller_6_status = { "name": "SOLAR_CONTROLLER_STATUS_6", "instance": self.rvc_instance}
        self.rvc_solar_array_status        = { "name": "SOLAR_CONTROLLER_SOLAR_ARRAY_STATUS", "instance": self.rvc_instance}
        self.rvc_solar_battery_status      = { "name": "SOLAR_CONTROLLER_BATTERY_STATUS", "instance": self.rvc_instance}

        #self.rvc_match_command= { "name": "DC_DIMMER_COMMAND_2", "instance": self.rvc_instance }

        #self.Logger.debug(f"Must match: {str(self.rvc_match_status)} or {str(self.rvc_match_command)}")
        self.Logger.debug(f"Must match: {str(self.rvc_solar_controller_status)}")

        # save these for later to send rvc msg
        self.name = data['instance_name']

        self.operating_state      = "unknown"
        self.power_up_state       = "unknown"
        self.force_charge         = "unknown"
        self.today                = "unknown"
        self.yesterday            = "unknown"
        self.two_days_ago         = "unknown"
        self.seven_day_total      = "unknown"
        self.power_generation     = "unknown"
        self.operating_days       = "unknown"
        self.temperature          = "unknown"
        self.array_voltage        = "unknown"
        self.array_current        = "unknown"
        self.array_power          = "unknown"
        self.battery_voltage      = "unknown"
        self.battery_current      = "unknown"
        self.battery_temperature  = "unknown"
        self.battery_power        = "unknown"

    def process_rvc_msg(self, new_message: dict) -> bool:
        """ Process an incoming message and determine if it
        is of interest to this object.

        If relevant - Process the message and return True
        else - return False
        """

        if self._is_entry_match(self.rvc_solar_controller_status, new_message):
            self.Logger.debug(f"Msg Match Status: {str(new_message)}")
            if new_message["operating_state"] != self.operating_state:
                self.operating_state = new_message["operating_state"]
                self.mqtt_support.client.publish(
                    self.operating_state_topic, new_message["operating_state_definition"].title(), retain=True)

            if new_message["power-up_state"] != self.power_up_state:
                self.power_up_state = new_message["power-up_state"]
                self.mqtt_support.client.publish(
                    self.power_up_state_topic, new_message["power-up_state_definition"].title(), retain=True)

            if new_message["force_charge"] != self.force_charge:
                self.force_charge = new_message["force_charge"]
                self.mqtt_support.client.publish(
                    self.force_charge_topic, new_message["force_charge_definition"].title(), retain=True)

            return True

        if self._is_entry_match(self.rvc_solar_controller_4_status, new_message):
            self.Logger.debug(f"Msg Match Status: {str(new_message)}")
            if new_message["today's_amp-hours_to_battery"] != self.today:
                self.today = new_message["today's_amp-hours_to_battery"]
                self.mqtt_support.client.publish(
                    self.today_topic, new_message["today's_amp-hours_to_battery"], retain=True)

            if new_message["yesterday's_amp-hours_to_battery"] != self.yesterday:
                self.yesterday = new_message["yesterday's_amp-hours_to_battery"]
                self.mqtt_support.client.publish(
                    self.yesterday_topic, new_message["yesterday's_amp-hours_to_battery"], retain=True)

            if new_message["day_before_yesterday's_amp-hours_to_battery"] != self.two_days_ago:
                self.two_days_ago = new_message["day_before_yesterday's_amp-hours_to_battery"]
                self.mqtt_support.client.publish(
                    self.two_days_ago_topic, new_message["day_before_yesterday's_amp-hours_to_battery"], retain=True)

            return True

        if self._is_entry_match(self.rvc_solar_controller_5_status, new_message):
            self.Logger.debug(f"Msg Match Status: {str(new_message)}")

            if new_message["last_7_days_amp-hours_to_battery"] != self.seven_day_total:
                self.seven_day_total = new_message["last_7_days_amp-hours_to_battery"]
                self.mqtt_support.client.publish(
                    self.seven_day_total_topic, new_message["last_7_days_amp-hours_to_battery"], retain=True)

            if new_message["cumulative_power_generation"] != self.power_generation:
                self.power_generation = new_message["cumulative_power_generation"]
                # The value needs to be divided by 2, I think, because there are 2 battery banks. This should match firefly screen
                self.mqtt_support.client.publish(
                    self.power_generation_topic, f"{round(float(new_message["cumulative_power_generation"]) / 2 )}", retain=True)

            return True

        if self._is_entry_match(self.rvc_solar_controller_6_status, new_message):
            self.Logger.debug(f"Msg Match Status: {str(new_message)}")

            if new_message["total_number_of_operating_days"] != self.operating_days:
                self.operating_days = new_message["total_number_of_operating_days"]
                self.mqtt_support.client.publish(
                    self.operating_days_topic, new_message["total_number_of_operating_days"], retain=True)

            if new_message["solar_charge_controller_measured_temperature"] != self.temperature:
                self.temperature = new_message["solar_charge_controller_measured_temperature"]
                self.mqtt_support.client.publish(
                    self.temperature_topic, new_message["solar_charge_controller_measured_temperature"], retain=True)

            return True

        if self._is_entry_match(self.rvc_solar_array_status, new_message):
            self.Logger.debug(f"Msg Match Status: {str(new_message)}")

            if new_message["solar_array_measured_voltage"] != self.array_voltage:
                self.array_voltage = new_message["solar_array_measured_voltage"]
                self.mqtt_support.client.publish(
                    self.array_voltage_topic, new_message["solar_array_measured_voltage"], retain=True)

            if new_message["solar_array_measured_current"] != self.array_current:
                self.array_current = new_message["solar_array_measured_current"]
                self.mqtt_support.client.publish(
                    self.array_current_topic, new_message["solar_array_measured_current"], retain=True)

            # power (watts) is calculated v * a
            _calc_power = round(float(self.array_voltage) * float(self.array_current),1)
            if self.array_power != _calc_power:
                self.array_power = _calc_power
                self.mqtt_support.client.publish(
                    self.array_power_topic, f"{self.array_power}", retain=True)

            return True

        if self._is_entry_match(self.rvc_solar_battery_status, new_message):
            self.Logger.debug(f"Msg Match Status: {str(new_message)}")

            if new_message["measured_voltage"] != self.battery_voltage:
                self.battery_voltage = new_message["measured_voltage"]
                self.mqtt_support.client.publish(
                    self.battery_voltage_topic, new_message["measured_voltage"], retain=True)

            if new_message["measured_current"] != self.battery_current:
                self.battery_current = new_message["measured_current"]
                self.mqtt_support.client.publish(
                    self.battery_current_topic, new_message["measured_current"], retain=True)

            if new_message["measured_temperature"] != self.battery_temperature:
                self.battery_temperature = new_message["measured_temperature"]
                self.mqtt_support.client.publish(
                    self.battery_temperature_topic, new_message["measured_temperature"], retain=True)

            # power (watts) is calculated v * a
            _calc_power = round(float(self.battery_voltage) * float(self.battery_current),1)
            if self.battery_power != _calc_power:
                self.battery_power = _calc_power
                self.mqtt_support.client.publish(
                    self.battery_power_topic, f"{self.battery_power}", retain=True)

            return True

        #elif self._is_entry_match(self.rvc_match_command, new_message):
        #    # This is the command.  Just eat the message so it doesn't show up
        #    # as unhandled.
        #    self.Logger.debug(f"Msg Match Command: {str(new_message)}")
        #    return True
        return False

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

