"""
DC system sensor from DC_SOURCE_STATUS_1


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
import struct
import json
import time
from rvc2mqtt.mqtt import MQTT_Support
from rvc2mqtt.entity import EntityPluginBaseClass
from paho.mqtt.properties import Properties
from paho.mqtt.packettypes import PacketTypes


class DcSystemSensor_DC_SOURCE_STATUS_1(EntityPluginBaseClass):
    FACTORY_MATCH_ATTRIBUTES = {"type": "dc_system", "name": "APS-500"}

    """ Provide basic DC system information as published by the APS-500
        using DC_SOURCE_STATUS_1 - 5, CHARGER_STATUS, CHARGER_STATUS_2,
        and CHARGER_EQUALIZATION_STATUS
    """
    apcfaults = {
        "0":  "No Fault",
        "12": "Battery Temperature greatly exceeded configured upper limit.",
        "13": "Battery Voltage greatly exceeded upper limit, measured by VBat+",
        "14": "Battery Voltage too low to operate as measured on VBat+. Damaged or missing sensing wire or fuse? (or engine not started!)",
        "15": "Voltage at Vbat+ exceeded Max Bat Volts as defined by $CPB:",
        "16": "Battery Temperature is shorted (Defective)",
        "21": "Alternator Temperature greatly exceeded configured upper limit.",
        "24": "Alternator Temperature greatly exceeded configured upper limit. (2nd temp reached / exceeded while ramping - this can NOT be right, to reach target while ramping means way too risky.)",
        "25": "Alt Temp is rising REALLY fast, damaged?",
        "41": "Internal Field FET temperature exceed limit.",
        "42": "A \'Required\' sensor is missing, and we are configured to FAULT out.",
        "43": "No voltage has been sensed on the VAlt+ line, blown fuse?",
        "44": "There is excessive voltage offset between VAlt+ and VBat+ sense lines - 2.5v. (Not checked in \"Split\" voltage systems)",
        "45": "Voltage at VAlt+ exceeded Max Bat Volts (Plus additional allowance for IR drop) as defined by $CPB:",
        "46": "Voltage greatly exceeded expected upper limit battery limit as measured at VAlt+",
        "51": "Received a generic CAN message that the battery charging bus has been disconnected.",
        "52": "A CAN command has been received asking for the battery bus to be disconnected due to High Voltage. (Note that depending on the BMS, other alarms may trigger this same fault, ala, high charge current)",
        "53": "Battery Instance number is out of range (needs to be from 1..100)",
        "54": "Too many different BMS\'s are asking to be aggregated.",
        "55": "AEBus device (Discovery battery) has send a warning or fault status. As there is no fore-warning of a disconnect, treat all warnings as a pending disconnect and fault. But then do auto-restart to see if it clears.",
        "56": "Too many VEreg (Victron) devices present to track",
        "57": "A CAN command has been received asking for the battery bus to be disconnected due to Low Voltage.",
        "58": "A CAN command has been received asking for the battery bus to be disconnected due to High Current.",
        "59": "A CAN command has been received asking for the battery bus to be disconnected due to High Battery Temperature.",
        "61": "A CAN command has been received asking for the battery bus to be disconnected due to Low Battery Temperature.",
        "62": "A CAN status has been received that the battery has reached its upper limit, but not yet disconnecting. Charging should stop.",
        "82": "Primary Battery (HS) of DC-DC converter Over-voltage trip",
        "83": "Primary Battery (HS) of DC-DC converter Under-voltage trip",
        "84": "Secondary Battery (LS) of DC-DC converter Over-voltage trip",
        "85": "Secondary Battery (LS) of DC-DC converter Under-voltage trip",
        "86": "DCDC Convert too hot.",
        "87": "A configuration value has exceeded the selected DC-DC converter limits.",
        "88": "More than one device seems to be trying to control the DCDC converter.",
        "89": "Attached DCDC Converter is not same as make/model specified",
        "4095": "No Fault"
    }

    def __init__(self, data: dict, mqtt_support: MQTT_Support):
        self.id = "aps-500-i" + str(data["instance"])
        super().__init__(data, mqtt_support)
        self.Logger = logging.getLogger(__class__.__name__)

        self.name = data['instance_name']
        self.device = {'mf': 'Wakespeed',
                       'ids': self.unique_device_id,
                       'mdl': 'APS-500',
                       'name': self.name
                       }

        # RVC message must match the following to be this device
        self.rvc_match_source_status_1 = {'name': 'DC_SOURCE_STATUS_1', 'source_id': str(data['source_id'])}
        self.rvc_match_source_status_2 = {'name': 'DC_SOURCE_STATUS_2', 'source_id': str(data['source_id'])}
        self.rvc_match_source_status_3 = {'name': 'DC_SOURCE_STATUS_3', 'source_id': str(data['source_id'])}
        self.rvc_match_source_status_4 = {'name': 'DC_SOURCE_STATUS_4', 'source_id': str(data['source_id'])}
        self.rvc_match_source_status_5 = {'name': 'DC_SOURCE_STATUS_5', 'source_id': str(data['source_id'])}

        self.rvc_match_battery_status_11 = {'name': 'BATTERY_STATUS_11', 'source_id': str(data['source_id'])}

        self.rvc_match_charger_status = {'name': 'CHARGER_STATUS', 'source_id': str(data['source_id'])}
        self.rvc_match_charger_status_2 = {'name': 'CHARGER_STATUS_2', 'source_id': str(data['source_id'])}

        self.rvc_match_charger_configuration_status = {'name': 'CHARGER_CONFIGURATION_STATUS', 'source_id': str(data['source_id'])}

        self.rvc_match_charger_equalization_status = {'name': 'CHARGER_EQUALIZATION_STATUS', 'source_id': str(data['source_id'])}

        self.rvc_match_dm_rv = {'name': 'DM_RV', 'source_id': str(data['source_id'])}

        self.rvc_match_terminal = {'name': 'TERMINAL', 'source_id': str(data['source_id'])}

        self.rvc_match_initial_packet = {'name': 'INITIAL_PACKET', 'source_id': str(data['source_id'])}
        self.rvc_match_data_packet = {'name': 'DATA_PACKET', 'source_id': str(data['source_id'])}

        # According to Wakespeed these may be J1939 messages. We will just do
        # nothing with them, so they don't show as decoder pending
        # The APS-500 will query the BMS and decode it's response. It will not wait very long so sometimes messages are missed
        # or can come in out of order.
        self.rvc_match_0ef80 = {'name': 'RENOGY_BMS_RESPONSE'} # ignore id since it is the response from the BMS
        self.rvc_match_0ef70 = {'name': 'WAKESPEED_BMS_QUERY', 'source_id': str(data['source_id'])}
        self.rvc_match_0fed5 = {'name': 'J1939_ALTERNATOR_INFORMATION_1', 'source_id': str(data['source_id'])}

        self.Logger.debug(f"Must match: {str(self.rvc_match_source_status_1)}")

        self.name = data['instance_name']

        # class specific values that change
        self._dc_voltage             = 5  # should never be this low
        self._dc_current             = 50  # should not be this high
        #DC_SOURCE_STATUS_4
        self._desired_charge_state   = "unknown"
        self._desired_dc_voltage     = "unknown" # expected is 54.7 volts
        self._desired_dc_current     = "unknown" # expected is 90 A
        #DC_SOURCE_STATUS_5
        self._hp_dc_voltage          = "unknown"
        #CHARGER_CONFIGURATION_STATUS
        self._charging_algorithm     = "unknown"
        self._charging_mode          = "unknown"
        self._battery_sensor_present = "unknown"
        #BATTERY_STATUS_11
        self._charge_detected        = "unknown"
        self._reserve_status         = "unknown"
        #CHARGER_STATUS
        self._charge_voltage         = "unknown"
        self._charge_current         = "unknown"
        self._charge_current_pct     = "unknown"
        self._operating_state        = "unknown"
        self._power_up_default_state = "unknown"
        self._auto_recharge_enable   = "unknown"
        self._force_charge           = "unknown"

        #CHARGER_STATUS_2
        self._charging_voltage       = "unknown"
        self._charging_current       = "unknown"
        self._charger_temperature    = "unknown"

        #CHARGER_EQUALIZATION_STATUS
        self._equalization_time_remaining       = "unknown"
        self._equalization_pre_charging_status  = "unknown"

        #J1939_ALTERNATOR_INFORMATION_1
        self._alternator_speed       = "unknown"

        #DM_RV
        self._fault_code             = "unknown"
        self._fault_description      = "unknown"
        self._lamp                   = "unknown"

        #TERMINAL
        self._terminal_message_call  = {}
        self._terminalmessage        = ""

        # INITIAL_PACKET / DATA_PACKET (multi-packet transport)
        self._mp_expected_count = 0
        self._mp_message_length = 0
        self._mp_packets = {}  # keyed by packet_number for ordered assembly + duplicate detection
        self._product_id = None

        if 'command_topic' in data:
            topic_base                            = str(data['command_topic'])
            self.reset_command_topic              = str(f"{topic_base}/reset")
            self.reboot_command_topic             = str(f"{topic_base}/reboot")
            self.request_last_fault_command_topic = str(f"{topic_base}/request_last_fault")
            self.terminal_command_topic           = str(f"{topic_base}/terminal")

        else:
            self.command_topic = mqtt_support.make_device_topic_string(
                self.id, None, False)

        self.mqtt_support.register(self.reset_command_topic, self.process_mqtt_msg)
        self.mqtt_support.register(self.reboot_command_topic, self.process_mqtt_msg)
        self.mqtt_support.register(self.request_last_fault_command_topic, self.process_mqtt_msg)
        self.mqtt_support.register(self.terminal_command_topic, self.process_mqtt_msg)

        if 'status_topic' in data:
            topic_base= str(data['status_topic'])

            # DC_SOURCE_STATUS_1
            #dc_voltage
            #dc_current - does not seem to actually be reported ??

            # DC_SOURCE_STATUS_4
            self.desired_charge_state_topic = str(f"{topic_base}/desired_charge_state")
            self.desired_dc_voltage_topic = str(f"{topic_base}/desired_dc_voltage")
            self.desired_dc_current_topic = str(f"{topic_base}/desired_dc_current")

            # DC_SOURCE_STATUS_5 (non-standard though)
            self.hp_dc_voltage_topic = str(f"{topic_base}/hp_dc_voltage")

            # CHARGER_STATUS
            self.charge_voltage_topic            = str(f"{topic_base}/charge_voltage")
            self.charge_current_topic            = str(f"{topic_base}/charge_current")
            self.charge_current_pct_topic        = str(f"{topic_base}/charge_current_pct")
            self.operating_state_topic           = str(f"{topic_base}/operating_state")
            self.power_up_default_state_topic    = str(f"{topic_base}/power_up_default_state")
            self.auto_recharge_enable_topic      = str(f"{topic_base}/auto_recharge_enable")
            self.force_charge_topic              = str(f"{topic_base}/force_charge")

            # CHARGER_STATUS_2
            self.charging_voltage_topic          = str(f"{topic_base}/charging_voltage")
            self.charging_current_topic          = str(f"{topic_base}/charging_current")
            self.charger_temperature_topic       = str(f"{topic_base}/charger_temp")

            # CHARGER_CONFIGURATION_STATUS
            self.charging_algorithm_topic        = str(f"{topic_base}/charging_algorithm")
            self.charging_mode_topic             = str(f"{topic_base}/charging_mode")
            self.battery_sensor_present_topic    = str(f"{topic_base}/battery_sensor_present")

            # CHARGER_EQUALIZATION_STATUS
            self.equalization_time_remaining_topic      = str(f"{topic_base}/equalization_time_remaining")
            self.equalization_pre_charging_status_topic = str(f"{topic_base}/equalization_pre_charging_status")

            # BATTERY_STATUS_11
            self.charge_detected_topic           = str(f"{topic_base}/charge_detected")
            self.reserve_status_topic            = str(f"{topic_base}/reserve_status")

            # DM_RV
            self.dm_rv_fault_code_topic          = str(f"{topic_base}/fault/code")
            self.dm_rv_fault_description_topic   = str(f"{topic_base}/fault/description")
            self.dm_rv_lamp_topic                = str(f"{topic_base}/fault/lamp")

            # ???
            self.max_charging_current_topic      = str(f"{topic_base}/max_charging_current")
            self.max_charging_current_pct_topic  = str(f"{topic_base}/max_charging_current_pct")

            self.request_last_fault_status_topic = str(f"{topic_base}/fault/rlf_message")
            self.log_status_topic                = str(f"{topic_base}/log")
            self.terminal_status_topic           = str(f"{topic_base}/danger/terminal_message")
            self.product_id_topic                = str(f"{topic_base}/product_id")

            # J1939_ALTERNATOR_INFORMATION_1
            self.alternator_speed_topic          = str(f"{topic_base}/alternator_speed")


        else:
            self.status_dc_voltage_topic = mqtt_support.make_device_topic_string(self.id, "missing_status_topic", True)
            self.equalization_time_remaining_topic      = mqtt_support.make_device_topic_string(self.id, "missing_status_topic", True)
            self.equalization_pre_charging_status_topic = mqtt_support.make_device_topic_string(self.id, "missing_status_topic", True)

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
                    self.desired_charge_state_topic, new_message.get("desired_charge_state_definition", "unknown").title(), retain=True)
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

            if self._hp_dc_voltage != new_message["hp_dc_voltage"]:
                self._hp_dc_voltage = new_message["hp_dc_voltage"]
                self.mqtt_support.client.publish(
                    self.hp_dc_voltage_topic, f"{self._hp_dc_voltage:.3f}",
                    retain=True)
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
                    self.operating_state_topic, new_message.get("operating_state_definition", "unknown").title(), retain=True)
            if self._power_up_default_state != new_message["default_state_on_power-up"]:
                self._power_up_default_state = new_message["default_state_on_power-up"]
                self.mqtt_support.client.publish(
                    self.power_up_default_state_topic, new_message.get("default_state_on_power-up_definition", "unknown").title(), retain=True)
            if self._auto_recharge_enable != new_message["auto_recharge_enable"]:
                self._auto_recharge_enable = new_message["auto_recharge_enable"]
                self.mqtt_support.client.publish(
                    self.auto_recharge_enable_topic, new_message.get("auto_recharge_enable_definition", "unknown").title(), retain=True)
            if self._force_charge != new_message["force_charge"]:
                self._force_charge = new_message["force_charge"]
                self.mqtt_support.client.publish(
                    self.force_charge_topic, new_message.get("force_charge_definition", "unknown").title(), retain=True)

            return True

        if self._is_entry_match(self.rvc_match_charger_status_2, new_message):
            self.Logger.debug(f"Msg Match Status: {str(new_message)}")

            if self._charging_voltage != new_message["charging_voltage"]:
                self._charging_voltage = new_message["charging_voltage"]
                self.mqtt_support.client.publish(
                    self.charging_voltage_topic, self._charging_voltage, retain=True)
            if self._charging_current != new_message["charging_current"]:
                self._charging_current = new_message["charging_current"]
                self.mqtt_support.client.publish(
                    self.charging_current_topic, self._charging_current, retain=True)
            if self._charger_temperature != new_message["charger_temperature"]:
                self._charger_temperature = new_message["charger_temperature"]
                self.mqtt_support.client.publish(
                    self.charger_temperature_topic, self._charger_temperature, retain=True)

            return True


        if self._is_entry_match(self.rvc_match_charger_configuration_status, new_message):
            self.Logger.debug(f"Msg Match Status: {str(new_message)}")

            if self._charging_algorithm != new_message["charging_algorithm"]:
                self._charging_algorithm = new_message["charging_algorithm"]
                self.mqtt_support.client.publish(
                    self.charging_algorithm_topic, new_message.get("charging_algorithm_definition", "unknown").title(), retain=True)

            if self._charging_mode != new_message["charger_mode"]:
                self._charging_mode = new_message["charger_mode"]
                self.mqtt_support.client.publish(
                    self.charging_mode_topic, new_message.get("charger_mode_definition", "unknown").title(), retain=True)

            if self._battery_sensor_present != new_message["battery_sensor_present"]:
                self._battery_sensor_present = new_message["battery_sensor_present"]
                self.mqtt_support.client.publish(
                    self.battery_sensor_present_topic, new_message.get("battery_sensor_present_definition", "unknown").title(), retain=True)

            return True

        if self._is_entry_match(self.rvc_match_charger_equalization_status, new_message):
            self.Logger.debug(f"Msg Match Status: {str(new_message)}")

            if self._equalization_time_remaining != new_message["time_remaining"]:
                self._equalization_time_remaining = new_message["time_remaining"]
                self.mqtt_support.client.publish(
                    self.equalization_time_remaining_topic,
                    self._equalization_time_remaining, retain=True)

            if self._equalization_pre_charging_status != new_message["pre-charging_status"]:
                self._equalization_pre_charging_status = new_message["pre-charging_status"]
                self.mqtt_support.client.publish(
                    self.equalization_pre_charging_status_topic,
                    new_message.get("pre-charging_status_definition", "unknown").title(),
                    retain=True)

            return True

        if self._is_entry_match(self.rvc_match_battery_status_11, new_message):
            self.Logger.debug(f"Msg Match Status: {str(new_message)}")

            if self._charge_detected != new_message["charge_detected"]:
                self._charge_detected = new_message["charge_detected"]
                self.mqtt_support.client.publish(
                self.charge_detected_topic, new_message.get("charge_detected_definition", "unknown").title(), retain=True)

            if self._reserve_status != new_message["reserve_status"]:
                self._reserve_status = new_message["reserve_status"]
                self.mqtt_support.client.publish(
                self.reserve_status_topic, new_message.get("reserve_status_definition", "unknown").title(), retain=True)

            return True

        if self._is_entry_match(self.rvc_match_dm_rv, new_message):
            self.Logger.debug(f"Msg Match Status: {str(new_message)}")

            message_fault_code = str(
                int(f"{new_message['spn-msb']:08b}"
                    f"{new_message['spn-isb']:08b}"
                    f"{new_message['spn-lsb']:03b}"
                ,2) - 0x7F000)

            fault_description = self.apcfaults.get(str(message_fault_code), "Internal Error")
            lamp_status = "n/a"

            if int(new_message["red_lamp_status"]) > 0:
                lamp_status = "red"
            elif int(new_message["yellow_lamp_status"]) > 0:
                lamp_status = "yellow"
            else:
                lamp_status = "off"

            if self._fault_code != message_fault_code:
                self._fault_code = message_fault_code
                self._fault_description = fault_description
                # Fault_code 4095 actually means "No Fault" so publish "" instead
                self.mqtt_support.client.publish(
                    self.dm_rv_fault_code_topic,
                    "00" if self._fault_code == "4095" else str(self._fault_code),
                    retain=True)

                self.mqtt_support.client.publish(
                    self.dm_rv_fault_description_topic,
                    self._fault_description, retain=True)

            if self._lamp != lamp_status:
                self._lamp = lamp_status
                self.mqtt_support.client.publish(
                self.dm_rv_lamp_topic, self._lamp, retain=True)

            return True

        if self._is_entry_match(self.rvc_match_terminal, new_message):
            self.Logger.debug(f"Msg Match Status: {str(new_message)}")

            messageproperties = Properties(PacketTypes.PUBLISH)
            # Set CorrelationData
            if self._terminal_message_call.get("properties"):
                if hasattr(self._terminal_message_call["properties"],'CorrelationData'):
                    messageproperties.CorrelationData = self._terminal_message_call["properties"].CorrelationData

            self._terminalmessage =  self._terminalmessage + new_message["data"]
            messages = bytearray.fromhex(self._terminalmessage).decode()
            self.Logger.debug(f"terminal_call: {self._terminal_message_call.get('timestamp')}, msg: {messages}")
            publish_msg = False

            if "AOK;" in messages:
                self.Logger.debug(f"Terminal message: {bytearray.fromhex(self._terminalmessage).decode()}")
                publish_msg = True

            elif "NAK;" in messages:
                self.Logger.debug(f"Terminal message: {bytearray.fromhex(self._terminalmessage).decode()}")
                publish_msg = True

            elif "RST;" in messages:
                self.Logger.debug(f"Terminal message: {bytearray.fromhex(self._terminalmessage).decode()}")
                publish_msg = True

            elif self._terminal_message_call.get("tail") == "true":
                if "\r\n" in  messages:
                    self.Logger.debug(f"Terminal message: {bytearray.fromhex(self._terminalmessage).decode()}")
                    publish_msg = True

            if publish_msg:
                # Publish TERMINAL response to responsetopic if it exists
                if self._terminal_message_call.get("responsetopic") is not None:
                    self.mqtt_support.client.publish(topic=self._terminal_message_call.get("responsetopic"),
                        payload=messages, retain=False, properties=messageproperties)
                else:
                    # Pubish TERMINAL response to terminal_status_topic
                    self.mqtt_support.client.publish(topic=self.terminal_status_topic,
                        payload=messages, retain=False, properties=messageproperties)

                self._terminal_message_call = {}
                self._terminalmessage = ""

            return True

        if self._is_entry_match(self.rvc_match_initial_packet, new_message):
            count = new_message["packet_count"]
            if count <= 0:
                self.Logger.warning(f"INITIAL_PACKET: invalid packet_count {count}, ignoring")
                return True
            self._mp_expected_count = count
            self._mp_message_length = new_message["message_length"]
            self._mp_packets = {}
            self.Logger.debug(
                f"INITIAL_PACKET: expecting {self._mp_expected_count} packets, "
                f"{self._mp_message_length} bytes"
            )
            return True

        if self._is_entry_match(self.rvc_match_data_packet, new_message):
            if self._mp_expected_count == 0:
                self.Logger.debug("DATA_PACKET received without INITIAL_PACKET, discarding")
                return True
            packet_num = new_message["packet_number"]
            if packet_num in self._mp_packets:
                self.Logger.warning(f"Duplicate DATA_PACKET #{packet_num}, ignoring")
                return True
            # Recover bytes 1-7 in correct order from the little-endian encoded integer
            data_bytes = int(new_message["data"]).to_bytes(7, 'little')
            self._mp_packets[packet_num] = data_bytes
            self.Logger.debug(
                f"DATA_PACKET #{packet_num}: "
                f"{len(self._mp_packets)}/{self._mp_expected_count}"
            )
            if len(self._mp_packets) >= self._mp_expected_count:
                try:
                    all_bytes = b''.join(
                        self._mp_packets[i] for i in range(1, self._mp_expected_count + 1)
                    )
                    trimmed = all_bytes[:self._mp_message_length]
                    product_id = trimmed.decode('ascii').strip('\x00')
                    if product_id != self._product_id:
                        self._product_id = product_id
                        self.Logger.info(f"PRODUCT_IDENTIFICATION: {product_id}")
                        if hasattr(self, 'product_id_topic'):
                            self.mqtt_support.client.publish(
                                self.product_id_topic, product_id, retain=True)
                except Exception as e:
                    self.Logger.error(f"Failed to decode PRODUCT_IDENTIFICATION: {e}")
                finally:
                    self._mp_packets = {}
                    self._mp_expected_count = 0
            return True

        if self._is_entry_match(self.rvc_match_0ef80, new_message):
            # likely J1939 message so do nothing
            return True
        if self._is_entry_match(self.rvc_match_0ef70, new_message):
            # likely J1939 message so do nothing
            return True
        if self._is_entry_match(self.rvc_match_0fed5, new_message):
            self.Logger.debug(f"Msg Match J1939_ALTERNATOR_INFORMATION_1: {str(new_message)}")
            alt_rpm = new_message["alternator_speed"]
            if alt_rpm != self._alternator_speed:
                self._alternator_speed = alt_rpm
                payload = json.dumps({"alt": alt_rpm, "engine": round(alt_rpm / 2.83, 1)})
                self.mqtt_support.client.publish(self.alternator_speed_topic, payload, retain=True)
            return True

        return False


    def format_terminal_message(self, data: str) -> list[bytearray]:
        """
        Splits a string into 8 byte byte arrays and appends CR/LF
        which is expected by APS-500.
        The RV-C spec calls for padding the message 0xFF if < 8 bytes
        but this causes weird behavior in the APS-500 so don't do it
        """

        try:
            # Append CRLF and encode to ASCII
            data += '\x0d\x0a'
            byte_data = data.encode('ascii')
        except UnicodeEncodeError as e:
            raise ValueError("Input string contains non-ASCII characters.") from e

        # Initialize the result list
        chunks = []

        # Process in chunks of 8 bytes
        for i in range(0, len(byte_data), 8):
            chunk = byte_data[i:i+8]
            #if len(chunk) < 8:
            #    # Pad with 0xFF if less than 8 bytes
            #    chunk += b'\xFF' * (8 - len(chunk))
            chunks.append(bytearray(chunk))

        return chunks


    def send_terminal_message(self, message: list[bytearray]):
        """
        Sends message(s) to the APS-500 using the TERMINAL DGN
        """

        self._terminal_message_call["timestamp"] = time.time()

        for msg_bytes in message:
            self.send_queue.put({"dgn": "17E80", "data": msg_bytes})
            time.sleep(.10)


    def reset_aps(self, properties = None):
        """
        Sends GENERAL_RESET dgn = 17F00 to the APS-500
        Only sends reset message
        """
        self.Logger.debug("Sending GENERAL_RESET message")
        msg_bytes = bytearray(8)
        struct.pack_into("<BBBBBBBB", msg_bytes, 0, 0x05,
            0x00, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF)

        self._terminal_message_call["tail"] = "false"
        self._terminal_message_call["payload"] = ""
        self._terminal_message_call["responsetopic"] = None
        if properties is not None:
            self._terminal_message_call["properties"] = properties
        self._terminal_message_call["timestamp"] = time.time()

        self.send_queue.put({"dgn": "17F80", "data": msg_bytes})


    def request_last_fault(self, properties = None):
        """
        Sends $RLF: to TERMINAL dgn = 17E80 to the APS-500
        $RLF: = 24 52 4C 46 3A
        """
        self.Logger.debug("Sending Request Last Fault ASCII message")

        message = self.format_terminal_message('$RLF:')

        self._terminal_message_call["payload"] = "requested"
        self._terminal_message_call["responsetopic"] = self.request_last_fault_status_topic
        if properties is not None:
            self._terminal_message_call["properties"] = properties

        self.send_terminal_message(message)

    def read_log(self, properties = None):
        """
        Sends an empty message to TERMINAL dgn = 17E80 to the APS-500
        This makes the APS-500 print out the console to TERMINAL
        Messages line are terminated with 0D0A (CR LF) but no AOK; message is sent
        You must send another message or reboot the APS-500 to stop the messages
        """
        self.Logger.debug("Sending Empty ASCII message")

        message = self.format_terminal_message('')

        # Special flag to indicate we should send to MQTT when message ends with 0x0D 0x0A
        # rather than AOK; or NAK; or RBT;
        self._terminal_message_call["tail"] = "true"

        self._terminal_message_call["payload"] = "requested"
        self._terminal_message_call["responsetopic"] = self.log_status_topic
        if properties is not None:
            self._terminal_message_call["properties"] = properties

        self.send_terminal_message(message)


    def reboot_aps(self, properties = None):
        """
        Sends $RBT: to TERMINAL dgn = 17E80 to the APS-500
        $RBT: = 24 52 42 54 3A
        """
        self.Logger.debug("Sending reboot ASCII message")

        message = self.format_terminal_message('$RBT:')

        self._terminal_message_call["payload"] = 0
        self._terminal_message_call["responsetopic"] = None
        if properties is not None:
            self._terminal_message_call["properties"] = properties

        self.send_terminal_message(message)


    def process_mqtt_msg(self, topic, payload, properties = None):
        self.Logger.info(
            f"MQTT Msg Received on topic {topic} with payload {payload}")

        # Clear the tail flag since we have recieved a new request
        self._terminal_message_call["tail"] = "false"

        match topic:
            case self.reset_command_topic:
                try:
                    match payload:
                        case '1':
                            self.reset_aps(properties) if properties is not None else self.reset_aps()
                        case _:
                            self.Logger.warning(
                            f"Invalid payload {payload} for topic {topic}")
                except Exception as e:
                    self.Logger.error(f"Exception trying to respond to topic {topic} + {str(e)}")

            case self.reboot_command_topic:
                try:
                    match payload:
                        case '1':
                            self.reboot_aps(properties) if properties is not None else self.reboot_aps()
                        case _:
                            self.Logger.warning(
                            f"Invalid payload {payload} for topic {topic}")
                except Exception as e:
                    self.Logger.error(f"Exception trying to respond to topic {topic} + {str(e)}")

            case self.request_last_fault_command_topic:
                try:
                    match payload:
                        case '1':
                            self.request_last_fault(properties) if properties is not None else self.request_last_fault()
                        case _:
                            self.Logger.warning(
                            f"Invalid payload {payload} for topic {topic}")
                except Exception as e:
                    self.Logger.error(f"Exception trying to respond to topic {topic} + {str(e)}")

            case self.terminal_command_topic:
                try:
                    match payload:
                        case s if s.startswith('$'):
                            self.Logger.debug("Sending ASCII message")
                            self.Logger.debug(f"payload: {payload}")

                            message = self.format_terminal_message(payload)

                            self._terminal_message_call["payload"] = payload
                            if properties is not None:
                                self._terminal_message_call["properties"] = properties
                                self.Logger.debug(f"{properties}")
                                if hasattr(properties, "ResponseTopic"):
                                    self._terminal_message_call["responsetopic"] = properties.ResponseTopic

                            self.send_terminal_message(message)
                        case s if len(s) == 0:
                            self.Logger.debug("Sending empty payload")
                            self.read_log(properties) if properties is not None else self.read_log()

                        case _:
                            self.Logger.warning(
                            f"Invalid payload {payload} for topic {topic}")
                except Exception as e:
                    self.Logger.error(f"Exception trying to respond to topic {topic} + {str(e)}")


    def publish_ha_discovery_config(self):
        origin = {'name': self.mqtt_support.get_bridge_ha_name()}
        components = {
            # CHARGER_STATUS
            'charge_voltage': {
                'p': 'sensor', 'device_class': 'voltage',
                'name': 'Charge Voltage',
                'unit_of_measurement': 'V', 'suggested_display_precision': '2',
                'value_template': '{{value}}',
                'state_topic': self.charge_voltage_topic,
                'unique_id': self.unique_device_id + '_charge_v'
            },
            'charge_current': {
                'p': 'sensor', 'device_class': 'current',
                'name': 'Charge Current',
                'unit_of_measurement': 'A', 'suggested_display_precision': '2',
                'value_template': '{{value}}',
                'state_topic': self.charge_current_topic,
                'unique_id': self.unique_device_id + '_charge_a'
            },
            'charge_current_pct': {
                'p': 'sensor',
                'name': 'Charge Current %',
                'unit_of_measurement': '%',
                'value_template': '{{value}}',
                'state_topic': self.charge_current_pct_topic,
                'unique_id': self.unique_device_id + '_charge_a_pct'
            },
            'operating_state': {
                'p': 'sensor',
                'name': 'Operating State',
                'value_template': '{{value}}',
                'state_topic': self.operating_state_topic,
                'unique_id': self.unique_device_id + '_op_state'
            },
            'power_up_default_state': {
                'p': 'sensor',
                'name': 'Power-Up Default State',
                'value_template': '{{value}}',
                'state_topic': self.power_up_default_state_topic,
                'unique_id': self.unique_device_id + '_pu_state'
            },
            'auto_recharge_enable': {
                'p': 'sensor',
                'name': 'Auto Recharge Enable',
                'value_template': '{{value}}',
                'state_topic': self.auto_recharge_enable_topic,
                'unique_id': self.unique_device_id + '_auto_rchg'
            },
            'force_charge': {
                'p': 'sensor',
                'name': 'Force Charge',
                'value_template': '{{value}}',
                'state_topic': self.force_charge_topic,
                'unique_id': self.unique_device_id + '_force_chg'
            },
            # CHARGER_STATUS_2
            'charging_voltage': {
                'p': 'sensor', 'device_class': 'voltage',
                'name': 'Charging Voltage',
                'unit_of_measurement': 'V', 'suggested_display_precision': '2',
                'value_template': '{{value}}',
                'state_topic': self.charging_voltage_topic,
                'unique_id': self.unique_device_id + '_chging_v'
            },
            'charging_current': {
                'p': 'sensor', 'device_class': 'current',
                'name': 'Charging Current',
                'unit_of_measurement': 'A', 'suggested_display_precision': '2',
                'value_template': '{{value}}',
                'state_topic': self.charging_current_topic,
                'unique_id': self.unique_device_id + '_chging_a'
            },
            'charger_temperature': {
                'p': 'sensor', 'device_class': 'temperature',
                'name': 'Charger Temperature',
                'unit_of_measurement': '°C', 'suggested_display_precision': '1',
                'value_template': '{{value}}',
                'state_topic': self.charger_temperature_topic,
                'unique_id': self.unique_device_id + '_chg_temp'
            },
            # DC_SOURCE_STATUS_4
            'desired_charge_state': {
                'p': 'sensor',
                'name': 'Desired Charge State',
                'value_template': '{{value}}',
                'state_topic': self.desired_charge_state_topic,
                'unique_id': self.unique_device_id + '_des_chg_st'
            },
            'desired_dc_voltage': {
                'p': 'sensor', 'device_class': 'voltage',
                'name': 'Desired DC Voltage',
                'unit_of_measurement': 'V', 'suggested_display_precision': '2',
                'value_template': '{{value}}',
                'state_topic': self.desired_dc_voltage_topic,
                'unique_id': self.unique_device_id + '_des_dc_v'
            },
            'desired_dc_current': {
                'p': 'sensor', 'device_class': 'current',
                'name': 'Desired DC Current',
                'unit_of_measurement': 'A', 'suggested_display_precision': '2',
                'value_template': '{{value}}',
                'state_topic': self.desired_dc_current_topic,
                'unique_id': self.unique_device_id + '_des_dc_a'
            },
            # DC_SOURCE_STATUS_5
            'hp_dc_voltage': {
                'p': 'sensor', 'device_class': 'voltage',
                'name': 'HP DC Voltage',
                'unit_of_measurement': 'V', 'suggested_display_precision': '3',
                'value_template': '{{value}}',
                'state_topic': self.hp_dc_voltage_topic,
                'unique_id': self.unique_device_id + '_hp_dc_v'
            },
            # CHARGER_CONFIGURATION_STATUS
            'charging_algorithm': {
                'p': 'sensor',
                'name': 'Charging Algorithm',
                'value_template': '{{value}}',
                'state_topic': self.charging_algorithm_topic,
                'unique_id': self.unique_device_id + '_chg_algo'
            },
            'charging_mode': {
                'p': 'sensor',
                'name': 'Charging Mode',
                'value_template': '{{value}}',
                'state_topic': self.charging_mode_topic,
                'unique_id': self.unique_device_id + '_chg_mode'
            },
            'battery_sensor_present': {
                'p': 'sensor',
                'name': 'Battery Sensor Present',
                'value_template': '{{value}}',
                'state_topic': self.battery_sensor_present_topic,
                'unique_id': self.unique_device_id + '_bat_sens'
            },
            # CHARGER_EQUALIZATION_STATUS
            'equalization_time_remaining': {
                'p': 'sensor',
                'name': 'Equalization Time Remaining',
                'unit_of_measurement': 's',
                'value_template': '{{value}}',
                'state_topic': self.equalization_time_remaining_topic,
                'unique_id': self.unique_device_id + '_eq_time'
            },
            'equalization_pre_charging_status': {
                'p': 'sensor',
                'name': 'Equalization Pre-Charging Status',
                'value_template': '{{value}}',
                'state_topic': self.equalization_pre_charging_status_topic,
                'unique_id': self.unique_device_id + '_eq_prchg'
            },
            # BATTERY_STATUS_11
            'charge_detected': {
                'p': 'sensor',
                'name': 'Charge Detected',
                'value_template': '{{value}}',
                'state_topic': self.charge_detected_topic,
                'unique_id': self.unique_device_id + '_chg_det'
            },
            'reserve_status': {
                'p': 'sensor',
                'name': 'Reserve Status',
                'value_template': '{{value}}',
                'state_topic': self.reserve_status_topic,
                'unique_id': self.unique_device_id + '_reserve'
            },
            # DM_RV
            'fault_code': {
                'p': 'sensor',
                'name': 'Fault Code',
                'value_template': '{{value}}',
                'state_topic': self.dm_rv_fault_code_topic,
                'unique_id': self.unique_device_id + '_fault_code'
            },
            'fault_description': {
                'p': 'sensor',
                'name': 'Fault Description',
                'value_template': '{{value}}',
                'state_topic': self.dm_rv_fault_description_topic,
                'unique_id': self.unique_device_id + '_fault_desc'
            },
            'fault_lamp': {
                'p': 'sensor',
                'name': 'Fault Lamp',
                'value_template': '{{value}}',
                'state_topic': self.dm_rv_lamp_topic,
                'unique_id': self.unique_device_id + '_fault_lamp'
            },
            # PRODUCT_ID
            'product_id': {
                'p': 'sensor',
                'name': 'Product ID',
                'value_template': '{{value}}',
                'state_topic': self.product_id_topic,
                'unique_id': self.unique_device_id + '_product_id'
            },
            # Commands
            'reset': {
                'p': 'button',
                'name': 'Reset',
                'command_topic': self.reset_command_topic,
                'payload_press': '1',
                'unique_id': self.unique_device_id + '_reset'
            },
            'request_last_fault': {
                'p': 'button',
                'name': 'Request Last Fault',
                'command_topic': self.request_last_fault_command_topic,
                'payload_press': '1',
                'unique_id': self.unique_device_id + '_rlf_btn'
            },
            'last_fault_response': {
                'p': 'sensor',
                'name': 'Last Fault Response',
                'value_template': '{{value}}',
                'state_topic': self.request_last_fault_status_topic,
                'unique_id': self.unique_device_id + '_rlf_resp'
            },
            'alternator_rpm': {
                'p': 'sensor',
                'name': 'Alternator RPM',
                'unit_of_measurement': 'RPM',
                'value_template': '{{value_json.alt}}',
                'state_topic': self.alternator_speed_topic,
                'unique_id': self.unique_device_id + '_alt_rpm'
            },
            'engine_rpm': {
                'p': 'sensor',
                'name': 'Engine RPM',
                'unit_of_measurement': 'RPM',
                'value_template': '{{value_json.engine}}',
                'state_topic': self.alternator_speed_topic,
                'unique_id': self.unique_device_id + '_eng_rpm'
            },
        }
        config = {'dev': self.device, 'o': origin, 'cmps': components, 'qos': 1}
        config.update(self.get_availability_discovery_info_for_ha())
        config_json = json.dumps(config)
        ha_config_topic = self.mqtt_support.make_ha_auto_discovery_config_topic(
            self.unique_device_id, "device")
        self.mqtt_support.client.publish(ha_config_topic, config_json, retain=False)

    def initialize(self):
        """ Optional function
        Will get called once when the object is loaded.
        RVC canbus tx queue is available
        mqtt client is ready.

        This can be a good place to request data
        """
        self.publish_ha_discovery_config()

        self.mqtt_support.client.publish(
            self.request_last_fault_status_topic, "unknown", retain=True)


        # request dgn report - this should trigger this device to report
        # dgn = 1FFC6 which is actually  C6 FF 01 <instance> 00 00 00 00
        # where instance = FF for all
        self.Logger.debug("Sending Request for DGN")
        msg_bytes = bytearray(8)
        struct.pack_into("<BBBBBBBB", msg_bytes, 0, 0xC6,
            0xFF, 1, 0xFF, 0, 0, 0, 0)

        self.send_queue.put({"dgn": "0EA80", "data": msg_bytes})

