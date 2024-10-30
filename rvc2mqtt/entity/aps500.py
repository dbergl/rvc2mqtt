"""
DC system sensor from DC_SOURCE_STATUS_G12


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


class DcSystemSensor_DC_SOURCE_STATUS_1(EntityPluginBaseClass):
    FACTORY_MATCH_ATTRIBUTES = {"type": "dc_system", "name": "APS-500"}

    """ Provide basic DC system information as published by the APS-500 using DC_SOURCE_STATUS_1 - 5,
        CHARGER_STATUS, CHARGER_STATUS_2, and CHARGER_EQUALIZATION_STATUS

        2024-10-25 23:55:02 {'arbitration_id': '0x19ffc780', 'data': '3146040884000101', 'priority': '6', 'dgn_h': '1FF', 'dgn_l': 'C7', 'dgn': '1FFC7', 'source_id': '80', 'name': 'CHARGER_STATUS', 'instance': 49, 'charge_voltage': 54.7, 'charge_current': 90.0, 'charge_current_percent_of_maximum': 0.0, 'operating_state': 1, 'operating_state_definition': 'do not charge', 'default_state_on_power-up': '01', 'default_state_on_power-up_definition': 'enabled', 'auto_recharge_enable': '00', 'auto_recharge_enable_definition': 'disabled', 'force_charge': 0, 'force_charge_definition': 'charging not forced'}
        2024-10-25 23:55:02 {'arbitration_id': '0x19fea380', 'data': '3101782E04007D35', 'priority': '6', 'dgn_h': '1FE', 'dgn_l': 'A3', 'dgn': '1FEA3', 'source_id': '80', 'name': 'CHARGER_STATUS_2', 'charger_instance': 49, 'dc_source_instance': 1, 'charger_priority': 120, 'charging_voltage': 1070, 'charging_current': 32000, 'charger_temperature': 53}
        
        2024-10-29 19:29:54 {'arbitration_id': '0x19ffc680', 'data': '3102000DD200FFFF', 'priority': '6', 'dgn_h': '1FF', 'dgn_l': 'C6', 'dgn': '1FFC6', 'source_id': '80', 'name': 'CHARGER_CONFIGURATION_STATUS', 'instance': 49, 'charging_algorithm': 2, 'charging_algorithm_definition': '3-stage', 'charger_mode': 0, 'charger_mode_definition': 'stand-alone', 'battery_sensor_present': 1, 'battery_sensor_present_definition': 'sensor present and active', 'charger_installation_line': 3, 'battery_type': 0, 'battery_type_definition': 'flooded', 'battery_bank_size': 210, 'maximum_charging_current': 'n/a'}
        2024-10-29 19:29:54 {'arbitration_id': '0x19ff9680', 'data': '3100FFFF410000FF', 'priority': '6', 'dgn_h': '1FF', 'dgn_l': '96', 'dgn': '1FF96', 'source_id': '80', 'name': 'CHARGER_CONFIGURATION_STATUS_2', 'instance': 49, 'maximum_charge_current_as_percent': 0.0, 'charge_rate_limit_as_percent_of_bank_size': 255, 'shore_breaker_size': 255, 'default_battery_temperature': 25, 'recharge_voltage': 0.0}
        2024-10-29 19:29:54 {'arbitration_id': '0x19fecc80', 'data': '311F041F041F0400', 'priority': '6', 'dgn_h': '1FE', 'dgn_l': 'CC', 'dgn': '1FECC', 'source_id': '80', 'name': 'CHARGER_CONFIGURATION_STATUS_3', 'instance': 49, 'bulk_voltage': 52.75, 'absorption_voltage': 52.75, 'float_voltage': 52.75, 'temperature_compensation_constant': 0}
        2024-10-29 19:29:54 {'arbitration_id': '0x19febf80', 'data': '31FAFF00000000FF', 'priority': '6', 'dgn_h': '1FE', 'dgn_l': 'BF', 'dgn': '1FEBF', 'source_id': '80', 'name': 'CHARGER_CONFIGURATION_STATUS_4', 'instance': 49, 'bulk_time': 65530, 'absorption_time': 0, 'float_time': 0}
        
        2024-10-25 23:55:02 {'arbitration_id': '0x19ff9980', 'data': '31FFFFFCFFFFFFFF', 'priority': '6', 'dgn_h': '1FF', 'dgn_l': '99', 'dgn': '1FF99', 'source_id': '80', 'name': 'CHARGER_EQUALIZATION_STATUS', 'instance': 49, 'time_remaining': 65535, 'pre-charging_status': 0, 'pre-charging_status_definition': 'pre-charging not in process'}
        
        2024-10-25 23:55:02 {'arbitration_id': '0x19feca80', 'data': '054CFFFFFFFF00FF', 'priority': '6', 'dgn_h': '1FE', 'dgn_l': 'CA', 'dgn': '1FECA', 'source_id': '80', 'name': 'DM_RV', 'operating_status': '0101', 'operating_status_definition': 'on normal', 'yellow_lamp_status': '00', 'red_lamp_status': '00', 'dsa': 76, 'spn-msb': 255, 'spn-isb': 255, 'fmi': 31, 'fmi_definition': 'failure mode not available', 'spn-lsb': 7, 'occurrence_count': 127, 'dsa_extension': 0, 'bank_select': 15}
        
        2024-10-25 23:55:02 {'arbitration_id': '0x19fffd80', 'data': '01782E0478803577', 'priority': '6', 'dgn_h': '1FF', 'dgn_l': 'FD', 'dgn': '1FFFD', 'source_id': '80', 'name': 'DC_SOURCE_STATUS_1', 'instance': 1, 'instance_definition': 'main house battery bank', 'device_priority': 120, 'device_priority_definition': 'battery soc device', 'dc_voltage': 53.5, 'dc_current': -5.0}
        2024-10-25 23:55:02 {'arbitration_id': '0x19fffc80', 'data': '01782024C80100FD', 'priority': '6', 'dgn_h': '1FF', 'dgn_l': 'FC', 'dgn': '1FFFC', 'source_id': '80', 'name': 'DC_SOURCE_STATUS_2', 'instance': 1, 'instance_definition': 'main house battery bank', 'device_priority': 120, 'device_priority_definition': 'battery soc device', 'source_temperature': 16.0, 'state_of_charge': 100.0, 'time_remaining': 1}
        2024-10-25 23:55:02 {'arbitration_id': '0x19fffb80', 'data': '0178FFD200FFFFFF', 'priority': '6', 'dgn_h': '1FF', 'dgn_l': 'FB', 'dgn': '1FFFB', 'source_id': '80', 'name': 'DC_SOURCE_STATUS_3', 'instance': 1, 'instance_definition': 'main house battery bank', 'device_priority': 120, 'device_priority_definition': 'battery soc device', 'state_of_health': 255, 'capacity_remaining': 210, 'relative_capacity': 255, 'ac_rms_ripple': 65535}
        2024-10-25 23:55:02 {'arbitration_id': '0x19fec980', 'data': '01780746040884F3', 'priority': '6', 'dgn_h': '1FE', 'dgn_l': 'C9', 'dgn': '1FEC9', 'source_id': '80', 'name': 'DC_SOURCE_STATUS_4', 'instance': 1, 'instance_definition': 'main house battery bank', 'device_priority': 120, 'device_priority_definition': 'battery soc device', 'desired_charge_state': 7, 'desired_charge_state_definition': 'constant voltage current', 'desired_dc_voltage': 54.7, 'desired_dc_current': 90.0, 'battery_type': 3, 'battery_type_definition': 'lithium iron phosphate'}
        2024-10-25 23:55:02 {'arbitration_id': '0x19fec880', 'data': '01782CD10000FFFF', 'priority': '6', 'dgn_h': '1FE', 'dgn_l': 'C8', 'dgn': '1FEC8', 'source_id': '80', 'name': 'DC_SOURCE_STATUS_5', 'dc_instance': 1, 'dc_instance_definition': 'main house battery bank', 'device_priority': 120, 'device_priority_definition': 'battery soc device', 'hp_dc_voltage': 'n/a', 'deprecated': 65535}
        
        2024-10-29 23:13:35 {'arbitration_id': '0x19fea580', 'data': '017815D2000C01FF', 'priority': '6', 'dgn_h': '1FE', 'dgn_l': 'A5', 'dgn': '1FEA5', 'source_id': '80', 'name': 'BATTERY_STATUS_11', 'instance': 1, 'dc_instance': 120, 'discharge_on_off_status': '01', 'discharge_on_off_status_definition': 'battery discharge bus connected', 'charge_on_off_status': '01', 'charge_on_off_status_definition': 'charge bus connected', 'charge_detected': '01', 'charge_detected_definition': 'charge detected', 'reserve_status': '00', 'reserve_status_definition': 'battery charge is above reserve level', 'full_capacity': 210, 'dc_power': 268}
    """

    def __init__(self, data: dict, mqtt_support: MQTT_Support):
        self.id = "aps-500-i" + str(data["instance"])
        super().__init__(data, mqtt_support)
        self.Logger = logging.getLogger(__class__.__name__)

        # RVC message must match the following to be this device
        self.rvc_match_source_status_1 = {'name': 'DC_SOURCE_STATUS_1', 'source_id': str(data['source_id'])}
        self.rvc_match_source_status_2 = {'name': 'DC_SOURCE_STATUS_2', 'source_id': str(data['source_id'])}
        self.rvc_match_source_status_3 = {'name': 'DC_SOURCE_STATUS_3', 'source_id': str(data['source_id'])}
        self.rvc_match_source_status_4 = {'name': 'DC_SOURCE_STATUS_4', 'source_id': str(data['source_id'])}
        self.rvc_match_source_status_5 = {'name': 'DC_SOURCE_STATUS_5', 'source_id': str(data['source_id'])}

        self.rvc_match_battery_status_11 = {'name': 'BATTERY_STATUS_11', 'source_id': str(data['source_id'])}
        
        self.rvc_match_charger_status = {'name': 'CHARGER_STATUS', 'source_id': str(data['source_id'])}
        self.rvc_match_charger_status_2 = {'name': 'CHARGER_STATUS_2', 'source_id': str(data['source_id'])}
        self.rvc_match_charging_configuration_status = {'name': 'CHARGER_CONFIGURATION_STATUS', 'source_id': str(data['source_id'])}
        self.rvc_match_charger_equalization_status = {'name': 'CHARGER_EQUALIZATION_STATUS', 'source_id': str(data['source_id'])}

        self.Logger.debug(f"Must match: {str(self.rvc_match_source_status_1)}")

        self.name = data['instance_name']

        # class specific values that change
        self._dc_voltage = 5  # should never be this low
        self._dc_current = 50  # should not be this high
        #DC_SOURCE_STATUS_4
        self._desired_charge_state = "unknown"
        self._desired_dc_voltage = "unknown" # expected is 54.7 volts
        self._desired_dc_current = "unknown" # expected is 90 A
        self._charge_voltage = "unknown"
        self._charge_current = "unknown"
        self._charge_current_pct = "unknown"
        self._operating_state = "unknown"
        self._power_up_default_state = "unknown"
        self._auto_recharge_enable = "unknown"
        self._force_charge = "unknown"
        #CHARGER_CONFIGURATION_STATUS
        self._charging_algorithm = "unknown"
        self._charging_mode = "unknown"
        self._battery_sensor_present = "unknown"
        #BATTERY_STATUS_11
        self._charge_detected = "unknown"
        self._reserve_status = "unknown"


        if 'status_topic' in data:
            topic_base= str(data['status_topic'])

            # DC_SOURCE_STATUS_1
            #dc_voltage
            #dc_current - does not seem to actually be reported ??

            # DC_SOURCE_STATUS_4
            self.desired_charge_state_topic = str(f"{topic_base}/desired_charge_state")
            self.desired_dc_voltage_topic = str(f"{topic_base}/desired_dc_voltage")
            self.desired_dc_current_topic = str(f"{topic_base}/desired_dc_current")
            
            # CHARGER_STATUS
            self.charge_voltage_topic = str(f"{topic_base}/charge_voltage")
            self.charge_current_topic = str(f"{topic_base}/charge_current")
            self.charge_current_pct_topic = str(f"{topic_base}/charge_current_pct")
            self.operating_state_topic = str(f"{topic_base}/operating_state")
            self.power_up_default_state_topic = str(f"{topic_base}/power_up_default_state")
            self.auto_recharge_enable_topic = str(f"{topic_base}/auto_recharge_enable")
            self.force_charge_topic = str(f"{topic_base}/force_charge")

            # CHARGER_STATUS_2
            self.charging_voltage_topic = str(f"{topic_base}/charging_voltage")
            self.charging_temp_topic = str(f"{topic_base}/charging_temp")
            
            # CHARGER_CONFIGURATION_STATUS            
            self.charging_algorithm_topic = str(f"{topic_base}/charging_algorithm")
            self.charging_mode_topic = str(f"{topic_base}/charging_mode")
            self.battery_sensor_present_topic = str(f"{topic_base}/battery_sensor_present")
        
            # BATTERY_STATUS_11
            self.charge_detected_topic = str(f"{topic_base}/charge_detected")
            self.reserve_status_topic = str(f"{topic_base}/reserve_status")

            # ???
            self.hp_dc_voltage_topic = str(f"{topic_base}/hp_dc_voltage") 
            self.max_charging_current_topic = str(f"{topic_base}/max_charging_current")
            self.max_charging_current_pct_topic = str(f"{topic_base}/max_charging_current_pct")

            self.faults_topic = str(f"{topic_base}/faults")
        else:
            self.status_dc_voltage_topic = mqtt_support.make_device_topic_string(self.id, "dc_voltage", True)
            self.status_dc_current_topic = mqtt_support.make_device_topic_string(self.id, "dc_current", True)

    def process_rvc_msg(self, new_message: dict) -> bool:
        """ Process an incoming message and determine if it
        is of interest to this object.

        If relevant - Process the message and return True
        else - return False

        """

        if self._is_entry_match(self.rvc_match_source_status_1, new_message):
            self.Logger.debug(f"Msg Match Status: {str(new_message)}")
            return True

        if self._is_entry_match(self.rvc_match_source_status_2, new_message):
            self.Logger.debug(f"Msg Match Status: {str(new_message)}")
            return True

        if self._is_entry_match(self.rvc_match_source_status_3, new_message):
            self.Logger.debug(f"Msg Match Status: {str(new_message)}")
            return True

        if self._is_entry_match(self.rvc_match_source_status_4, new_message):
            self.Logger.debug(f"Msg Match Status: {str(new_message)}")

            if new_message["desired_charge_state"] != self._desired_charge_state:
                self._desired_charge_state = new_message["desired_charge_state"]
                self.mqtt_support.client.publish(
                    self.desired_charge_state_topic, new_message["desired_charge_state_definition"].title(), retain=True)
            if new_message["desired_dc_voltage"] != self._desired_dc_voltage:
                self._desired_dc_voltage = new_message["desired_dc_voltage"]
                self.mqtt_support.client.publish(
                    self.desired_dc_voltage_topic, self._desired_dc_voltage, retain=True)
            if new_message["desired_dc_current"] != self._desired_dc_current:
                self._desired_dc_current = new_message["desired_dc_current"]
                self.mqtt_support.client.publish(
                    self.desired_dc_current_topic, self._desired_dc_current, retain=True)
                
            return True

        if self._is_entry_match(self.rvc_match_source_status_5, new_message):
            self.Logger.debug(f"Msg Match Status: {str(new_message)}")
            return True

        if self._is_entry_match(self.rvc_match_charger_status, new_message):
            self.Logger.debug(f"Msg Match Status: {str(new_message)}")

            if self._charge_voltage != new_message["charge_voltage"]:
                self._charge_voltage = new_message["charge_voltage"]
                self.mqtt_support.client.publish(
                    self.charge_voltage_topic, self._charge_voltage, retain=True)
            if self._charge_current != new_message["charge_current"]:
                self._charge_current = new_message["charge_current"]
                self.mqtt_support.client.publish(
                    self.charge_current_topic, self._charge_current, retain=True)
            if self._charge_current_pct != new_message["charge_current_percent_of_maximum"]:
                self._charge_current_pct = new_message["charge_current_percent_of_maximum"]
                self.mqtt_support.client.publish(
                    self.charge_current_pct_topic, self._charge_current_pct, retain=True)
            if self._operating_state != new_message["operating_state"]:
                self._operating_state = new_message["operating_state"]
                self.mqtt_support.client.publish(
                    self.operating_state_topic, new_message["operating_state_definition"].title(), retain=True)
            if self._power_up_default_state != new_message["default_state_on_power-up"]:
                self._power_up_default_state = new_message["default_state_on_power-up"]
                self.mqtt_support.client.publish(
                    self.power_up_default_state_topic, new_message["default_state_on_power-up_definition"].title(), retain=True)
            if self._auto_recharge_enable != new_message["auto_recharge_enable"]:
                self._auto_recharge_enable = new_message["auto_recharge_enable"]
                self.mqtt_support.client.publish(
                    self.auto_recharge_enable_topic, new_message["auto_recharge_enable_definition"].title(), retain=True)
            if self._force_charge != new_message["force_charge"]:
                self._force_charge = new_message["force_charge"]
                self.mqtt_support.client.publish(
                    self.force_charge_topic, new_message["force_charge_definition"].title(), retain=True)

            return True
            
        if self._is_entry_match(self.rvc_match_charging_configuration_status, new_message):
            self.Logger.debug(f"Msg Match Status: {str(new_message)}")

            if self._charging_algorithm != new_message["charging_algorithm"]:
                self._charging_algorithm = new_message["charging_algorithm"]
                self.mqtt_support.client.publish(
                    self.charging_algorithm_topic, new_message["charging_algorithm_definition"].title(), retain=True)

            if self._charging_mode != new_message["charger_mode"]:
                self._charging_mode = new_message["charger_mode"]
                self.mqtt_support.client.publish(
                    self.charging_mode_topic, new_message["charger_mode_definition"].title(), retain=True)

            if self._battery_sensor_present != new_message["battery_sensor_present"]:
                self._battery_sensor_present = new_message["battery_sensor_present"]
                self.mqtt_support.client.publish(
                    self.battery_sensor_present_topic, new_message["battery_sensor_present_definition"].title(), retain=True)

            return True

        if self._is_entry_match(self.rvc_match_battery_status_11, new_message):
            self.Logger.debug(f"Msg Match Status: {str(new_message)}")

            if self._charge_detected != new_message["charge_detected"]:
                self._charge_detected = new_message["charge_detected"]
                self.mqtt_support.client.publish(
                self.charge_detected_topic, new_message["charge_detected_definition"].title(), retain=True)

            if self._reserve_status != new_message["reserve_status"]: 
                self._reserve_status = new_message["reserve_status"]
                self.mqtt_support.client.publish(
                self.reserve_status_topic, new_message["reserve_status_definition"].title(), retain=True)

            return True

        return False


    def initialize(self):
        """ Optional function
        Will get called once when the object is loaded.
        RVC canbus tx queue is available
        mqtt client is ready.

        This can be a good place to request data
        """

        # request dgn report - this should trigger that dimmer to report
        # dgn = 1FFC6 which is actually  C6 FF 01 <instance> 00 00 00 00
        # where instance = FF for all
        self.Logger.debug("Sending Request for DGN")
        msg_bytes = bytearray(8)
        struct.pack_into("<BBBBBBBB", msg_bytes, 0, 0xC6,
            0xFF, 1, 0xFF, 0, 0, 0, 0)

        self.send_queue.put({"dgn": "0EAFF", "data": msg_bytes})
