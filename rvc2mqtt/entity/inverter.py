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
    TODO: GENERIC_ALARM_STATUS

    TODO: Maybe add configuration commands??
    """

    def __init__(self, data: dict, mqtt_support: MQTT_Support):
        self.rvc_instance = data['instance']
        self.id = "solar-charge-controller-1FFD4-i" + str(self.rvc_instance)
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
            self.topic_base = f"{str(data['status_topic'])}"

            # some of these messages can be broadcast with multiple lines and input or output
            # This is stored in the Instance byte 0
            # we will need to piece together the topic after we get the message
            # i.e {self.topic_base} + "/" + {line} + "/" + {input/output} + "/" + {self.rms_voltage_topic}

            # INVERTER_STATUS
            self.status_topic                  = str(f"{self.topic_base}/status")
            self.status_def_topic              = str(f"{self.topic_base}/status_definition")
            self.batt_sensor_pres_topic        = str(f"{self.topic_base}/batt_sensor_present")
            self.batt_sensor_pres_def_topic    = str(f"{self.topic_base}/batt_sensor_present_definition")

            # INVERTER_AC_STATUS_1
            self.rms_voltage_topic             = str(f"rms_voltage")
            self.rms_current_topic             = str(f"rms_current")
            self.frequency_topic               = str(f"frequency")
            self.fault_open_ground_topic       = str(f"fault/open_ground")
            self.fault_open_neutral_topic      = str(f"fault/open_neutral")
            self.fault_reverse_polarity_topic  = str(f"fault/reverse_polarity")
            self.fault_ground_current_topic    = str(f"fault/ground_current")

            # INVERTER_AC_STATUS_2
            self.peak_voltage_topic            = str(f"peak_voltage")
            self.peak_current_topic            = str(f"peak_current")
            self.ground_current_topic          = str(f"ground_current")
            self.capacity_topic                = str(f"capacity")

            # INVERTER_AC_STATUS_3
            self.waveform_topic                = str(f"waveform")
            self.waveform_def_topic            = str(f"waveform_definition")
            self.phase_status_topic            = str(f"phase_status")
            self.phase_status_def_topic        = str(f"phase_status_definition")
            self.real_power_topic              = str(f"real_power")
            self.reactive_power_topic          = str(f"reactive_power")
            self.harmonic_distortion_topic     = str(f"harmonic_distortion")
            self.complementary_leg_topic       = str(f"complementary_leg")

            # INVERTER_AC_STATUS_4
            self.voltage_fault_topic            = str(f"fault/voltage")
            self.voltage_fault_def_topic        = str(f"fault/voltage_definition")
            self.fault_surge_prot_topic         = str(f"fault/surge_protection")
            self.fault_surge_prot_def_topic     = str(f"fault/surge_protection_definition")
            self.fault_high_frequency_topic     = str(f"fault/high_frequency")
            self.fault_high_frequency_def_topic = str(f"fault/high_frequency_definition")
            self.fault_low_frequency_topic      = str(f"fault/low_frequency")
            self.fault_low_frequency_def_topic  = str(f"fault/low_frequency_definition")
            self.bypass_mode_active_topic       = str(f"bypass_mode_active")
            self.bypass_mode_active_def_topic   = str(f"bypass_mode_active_definition")
            self.qualification_status_topic     = str(f"qualification_status")
            self.qualification_status_def_topic = str(f"qualification_status_definition")

            # INVERTER_DC_STATUS
            self.dc_voltage_topic              = str(f"{self.topic_base}/dc_voltage")
            self.dc_amperage_topic             = str(f"{self.topic_base}/dc_amperage")

            # INVERTER_TEMPERATURE_STATUS
            self.fet_1_temperature_topic        = str(f"{self.topic_base}/temps/fet1")
            self.transformer_temperature_topic = str(f"{self.topic_base}/temps/transformer")
            self.fet_2_temperature_topic        = str(f"{self.topic_base}/temps/fet2")

            # GENERIC_ALARM_STATUS
            # TODO ???

        # RVC message must match the following to be this device

        self.rvc_match_inverter_status             = { "name": "INVERTER_STATUS", "instance": self.rvc_instance}
        self.rvc_match_inverter_ac_status_1        = { "name": "INVERTER_AC_STATUS_1", "instance": self.rvc_instance}
        self.rvc_match_inverter_ac_status_2        = { "name": "INVERTER_AC_STATUS_2", "instance": self.rvc_instance}
        self.rvc_match_inverter_ac_status_3        = { "name": "INVERTER_AC_STATUS_3", "instance": self.rvc_instance}
        self.rvc_match_inverter_ac_status_4        = { "name": "INVERTER_AC_STATUS_4", "instance": self.rvc_instance}
        self.rvc_match_inverter_dc_status          = { "name": "INVERTER_DC_STATUS", "instance": self.rvc_instance}
        self.rvc_match_inverter_temperature_status = { "name": "INVERTER_DC_STATUS", "instance": self.rvc_instance}

        #self.rvc_match_command= { "name": "DC_DIMMER_COMMAND_2", "instance": self.rvc_instance }

        #self.Logger.debug(f"Must match: {str(self.rvc_match_status)} or {str(self.rvc_match_command)}")
        self.Logger.debug(f"Must match: {str(self.rvc_match_inverter_status)}")

        # save these for later to send rvc msg
        self.name = data['instance_name']

        # INVERTER_STATUS
        self.status = "unknown"
        self.batt_sensor_present = "unknown"

        # INVERTER_AC_STATUS_1
        self.rms_voltage = {}
        self.rms_current = {}
        self.frequency = {}
        self.open_ground = {}
        self.open_neutral = {}
        self.reverse_polarity = {}
        self.ground_current = {}

        # INVERTER_AC_STATUS_2
        self.peak_voltage = {}
        self.peak_current = {}
        self.ground_current = {}
        self.capacity = {}

        # INVERTER_AC_STATUS_3
        self.waveform = {}
        self.phase_status = {}
        self.real_power = {}
        self.reactive_power = {}
        self.harmonic_distortion = {}
        self.complementary_leg = {}

        # INVERTER_AC_STATUS_4
        self.voltage_fault = {}
        self.fault_surge_prot = {}
        self.high_frequency = {}
        self.low_frequency = {}
        self.bypass_mode_active = {}
        self.qualification_status = {}

        # INVERTER_DC_STATUS
        self.dc_voltage = "unknown"
        self.dc_amperage = "unknown"

        # INVERTER_TEMPERATURE_STATUS
        self.fet_1_temperature = "unknown"
        self.transformer_temperature = "unknown"
        self.fet_2_temperature = "unknown"


    def process_rvc_msg(self, new_message: dict) -> bool:
        """ Process an incoming message and determine if it
        is of interest to this object.

        If relevant - Process the message and return True
        else - return False
        """

        _line = new_message.get("line_definition", "unknown")
        _in_out = new_message.get("input_output_definition", "unknown")
        _prefix = f"{self.topic_base}/line{_line}/{_in_out}"

        if self._is_entry_match(self.rvc_match_inverter_status, new_message):
            self.Logger.debug(f"Msg Match Status: {str(new_message)}")

            if new_message["status"] != self.status:
                self.status = new_message["status"]
                self.mqtt_support.client.publish(
                    self.status_topic, self.status, retain=True)
                self.mqtt_support.client.publish(
                    self.status_def_topic, new_message.get("status_definition", "unknown").title(), retain=True)

            if new_message["battery_temperature_sensor_present"] != self.batt_sensor_present:
                self.batt_sensor_present = new_message["battery_temperature_sensor_present"]
                self.mqtt_support.client.publish(
                    self.batt_sensor_pres_topic, self.batt_sensor_present, retain=True)
                self.mqtt_support.client.publish(
                    self.batt_sensor_pres_def_topic, new_message.get("battery_temperature_sensor_present_definition", "unknown").title(), retain=True)

            return True

        elif self._is_entry_match(self.rvc_match_inverter_ac_status_1, new_message):
            self.Logger.debug(f"Msg Match Status: {str(new_message)}")
            _volt = new_message["rms_voltage"]
            _volt_key = f"{_line}-{_in_out}-rms_voltage"
            _volt_topic = f"{prefix}/{self.rms_voltage_topic}"
            _curr = new_message["rms_current"]
            _curr_key = f"{_line}-{_in_out}-rms_current"
            _curr_topic = f"{_prefix}/{self.rms_current_topic}"
            _freq = new_message["frequency"]
            _freq_key = f"{_line}-{_in_out}-frequency"
            _freq_topic = f"{_prefix}/{self.frequency_topic}"
            _f_o_g = new_message["fault_open_ground"]
            _f_o_g_key = f"{_line}-{_in_out}-fault_open_ground"
            _f_o_g_topic = f"{_prefix}/{self.fault_open_ground_topic}"
            _f_o_n = new_message["fault_open_neutral"]
            _f_o_n_key = f"{_line}-{_in_out}-fault_open_neutral"
            _f_o_n_topic = f"{_prefix}/{self.fault_open_neutral_topic}"
            _f_r_p = new_message["fault_reverse_polarity"]
            _f_r_p_key = f"{_line}-{_in_out}-fault_reverse_polarity"
            _f_r_p_topic = f"{_prefix}/{self.fault_reverse_polarity_topic}"
            _f_g_c = new_message["fault_ground_current"]
            _f_g_c_key = f"{_line}-{_in_out}-fault_ground_current"
            _f_g_c_topic = f"{_prefix}/{self.fault_ground_current_topic}"

            if _volt != self.rms_voltage.get(_volt_key, "unknown"):
                self.rms_voltage.update(_volt_key=_volt)
                self.mqtt_support.client.publish(
                    _volt_topic, _volt, retain=True)

            if _curr != self.rms_current.get(_curr_key, "unknown"):
                self.rms_current.update(_curr_key=_curr)
                self.mqtt_support.client.publish(
                    _curr_topic, _curr, retain=True)

            if _freq != self.frequency.get(_freq_key, "unknown"):
                self.frequency.update(_freq_key=_freq)
                self.mqtt_support.client.publish(
                    _freq_topic, _freq, retain=True)

            if _f_o_g != self.open_ground.get(_f_o_g_key, "unknown"):
                self.open_ground.update(_f_o_g_key=_f_o_g)
                self.mqtt_support.client.publish(
                    _f_o_g_topic, _f_o_g, retain=True)

            if _f_o_n != self.open_neutral.get(_f_o_n_key, "unknown"):
                self.open_neutral.update(_f_o_n_key=_f_o_n)
                self.mqtt_support.client.publish(
                    _f_o_n_topic, _f_o_n, retain=True)

            if _f_r_p != self.reverse_polarity.get(_f_r_p_key, "unknown"):
                self.reverse_polarity.update(_f_r_p_key=_f_r_p)
                self.mqtt_support.client.publish(
                    _f_r_p_topic, _f_r_p, retain=True)

            if _f_g_c != self.ground_current.get(_f_g_c_key, "unknown"):
                self.ground_current.update(_f_g_c_key=_f_g_c)
                self.mqtt_support.client.publish(
                    _f_g_c_topic, _f_g_c, retain=True)

            return True

        elif self._is_entry_match(self.rvc_match_inverter_ac_status_2, new_message):
            self.Logger.debug(f"Msg Match Status: {str(new_message)}")
            _volt = new_message["peak_voltage"]
            _volt_key = f"{_line}-{_in_out}-peak_voltage"
            _volt_topic = f"{_prefix}/{self.peak_voltage_topic}"
            _curr = new_message["peak_current"]
            _curr_key = f"{_line}-{_in_out}-peak_current"
            _curr_topic = f"{_prefix}/{self.peak_current_topic}"
            _gcur = new_message["ground_current"]
            _gcur_key = f"{_line}-{_in_out}-ground_current"
            _gcur_topic = f"{_prefix}/{self.ground_current_topic}"
            _cap = new_message["capacity"]
            _cap_key = f"{_line}-{_in_out}-capacity"
            _cap_topic = f"{_prefix}/{self.capacity_topic}"

            if _volt != self.rms_voltage.get(_volt_key, "unknown"):
                self.rms_voltage.update(_volt_key=_volt)
                self.mqtt_support.client.publish(
                    _volt_topic, _volt, retain=True)

            if _curr != self.rms_current.get(_curr_key, "unknown"):
                self.rms_current.update(_curr_key=_curr)
                self.mqtt_support.client.publish(
                    _curr_topic, _curr, retain=True)

            if _gcur != self.ground_current.get(_gcur_key, "unknown"):
                self.ground_current.update(_gcur_key=_gcur)
                self.mqtt_support.client.publish(
                    _gcur_topic, _gcur, retain=True)

            if _cap != self.capacity.get(_cap_key, "unknown"):
                self.capacity.update(_cap_key=_cap)
                self.mqtt_support.client.publish(
                    _cap_topic, _cap, retain=True)

            return True

        elif self._is_entry_match(self.rvc_match_inverter_ac_status_3, new_message):
            self.Logger.debug(f"Msg Match Status: {str(new_message)}")
            _wave = new_message["waveform"]
            _wave_key = f"{_line}-{_in_out}-waveform"
            _wave_topic = f"{_prefix}/{self.waveform_topic}"
            _wave_def = new_message.get("waveform_definition", "unknown")
            _wave_def_topic = f"{_prefix}/{self.waveform_def_topic}"
            _phase = new_message["phase_status"]
            _phase_key = f"{_line}-{_in_out}-phase_status"
            _phase_topic = f"{_prefix}/{self.phase_status_topic}"
            _phase_def = new_message.get("phase_status_definition", "unknown")
            _phase_def_topic = f"{_prefix}/{self.phase_status_def_topic}"
            _realp = new_message["real_power"]
            _realp_key = f"{_line}-{_in_out}-real_power"
            _realp_topic = f"{_prefix}/{self.real_power_topic}"
            _reactp = new_message["reactive_power"]
            _reactp_key = f"{_line}-{_in_out}-reactive_power"
            _reactp_topic = f"{_prefix}/{self.reactive_power_topic}"
            _harmd = new_message["harmonic_distortion"]
            _harmd_key = f"{_line}-{_in_out}-harmonic_distortion"
            _harmd_topic = f"{_prefix}/{self.harmonic_distortion_topic}"
            _compleg = new_message["complementary_leg"]
            _compleg_key = f"{_line}-{_in_out}-complementary_leg"
            _compleg_topic = f"{_prefix}/{self.complementary_leg_topic}"

            if _wave != self.waveform.get(_wave_key, "unknown"):
                self.waveform.update(_wave_key=_wave)
                self.mqtt_support.client.publish(
                    _wave_topic, _wave, retain=True)
                self.mqtt_support.client.publish(
                    _wave_def_topic, _wave_def, retain=True)

            if _phase != self.phase_status.get(_phase_key, "unknown"):
                self.phase_status.update(_phase_key=_phase)
                self.mqtt_support.client.publish(
                    _phase_topic, _phase, retain=True)
                self.mqtt_support.client.publish(
                    _phase_def_topic, _phase_def, retain=True)

            if _realp != self.real_power.get(_realp_key, "unknown"):
                self.real_power.update(_realp_key=_realp)
                self.mqtt_support.client.publish(
                    _realp_topic, _realp, retain=True)

            if _reactp != self.reactive_power.get(_reactp_key, "unknown"):
                self.reactive_power.update(_reactp_key=_reactp)
                self.mqtt_support.client.publish(
                    _reactp_topic, _reactp, retain=True)

            if _harmd != self.harmonic_distortion.get(_harmd_key, "unknown"):
                self.harmonic_distortion.update(_harmd_key=_harmd)
                self.mqtt_support.client.publish(
                    _harmd_topic, _harmd, retain=True)

            if _compleg != self.complementary_leg.get(_compleg_key, "unknown"):
                self.complementary_leg.update(_compleg_key=_compleg)
                self.mqtt_support.client.publish(
                    _compleg_topic, _compleg, retain=True)

            return True

        elif self._is_entry_match(self.rvc_match_inverter_ac_status_4, new_message):
            self.Logger.debug(f"Msg Match Status: {str(new_message)}")
            _f_volt            = new_message["voltage_fault"]
            _f_volt_key        = f"{_line}-{_in_out}-voltage_fault"
            _f_volt_topic      = f"{_prefix}/{self.voltage_fault_topic}"
            _f_volt_def        = new_message.get("voltage_fault_definition", "unknown")
            _f_volt_def_topic  = f"{_prefix}/{self.voltage_fault_def_topic}"
            _f_surge           = new_message["fault_surge_protection"]
            _f_surge_key       = f"{_line}-{_in_out}-fault_surge_protection"
            _f_surge_topic     = f"{_prefix}/{self.fault_surge_prot_topic}"
            _f_surge_def       = new_message.get("fault_surge_protection_definition", "unknown")
            _f_surge_def_topic = f"{_prefix}/{self.fault_surge_prot_def_topic}"
            _f_hfreq           = new_message["fault_high_frequency"]
            _f_hfreq_key       = f"{_line}-{_in_out}-fault_high_frequency"
            _f_hfreq_topic     = f"{_prefix}/{self.fault_high_frequency_topic}"
            _f_hfreq_def       = new_message.get("fault_surge_protection_definition", "unknown")
            _f_hfreq_def_topic = f"{_prefix}/{self.fault_high_frequency_def_topic}"
            _f_lfreq           = new_message["fault_low_frequency"]
            _f_lfreq_key       = f"{_line}-{_in_out}-fault_low_frequency"
            _f_lfreq_topic     = f"{_prefix}/{self.fault_low_frequency_topic}"
            _f_lfreq_def       = new_message.get("fault_low_frequency_definition", "unknown")
            _f_lfreq_def_topic = f"{_prefix}/{self.fault_low_frequency_def_topic}"
            _f_bypas           = new_message["bypass_mode_active"]
            _f_bypas_key       = f"{_line}-{_in_out}-bypass_mode_active"
            _f_bypas_topic     = f"{_prefix}/{self.bypass_mode_active_topic}"
            _f_bypas_def       = new_message.get("bypass_mode_active_definition", "unknown")
            _f_bypas_def_topic = f"{_prefix}/{self.bypass_mode_active_def_topic}"
            _f_qual           = new_message["qualification_status"]
            _f_qual_key       = f"{_line}-{_in_out}-qualification_status"
            _f_qual_topic     = f"{_prefix}/{self.qualification_status_topic}"
            _f_qual_def       = new_message.get("qualification_status", "unknown")
            _f_qual_def_topic = f"{_prefix}/{self.qualification_status_def_topic}"


            if _f_volt != self.voltage_fault.get(_f_volt_key, "unknown"):
                self.voltage_fault.update(_f_volt_key=_f_volt)
                self.mqtt_support.client.publish(
                    _f_volt_topic, _f_volt, retain=True)
                self.mqtt_support.client.publish(
                    _f_volt_def_topic, _f_volt_def, retain=True)

            if _f_surge != self.fault_surge_protection.get(_f_surge_key, "unknown"):
                self.fault_surge_protection.update(_f_surge_key=_f_surge)
                self.mqtt_support.client.publish(
                    _f_surge_topic, _f_surge, retain=True)
                self.mqtt_support.client.publish(
                    _f_surge_def_topic, _f_surge_def, retain=True)

            if _f_hfreq != self.fault_high_frequency.get(_f_hfreq_key, "unknown"):
                self.fault_high_frequency.update(_f_hfreq_key=_f_hfreq)
                self.mqtt_support.client.publish(
                    _f_hfreq_topic, _f_hfreq, retain=True)
                self.mqtt_support.client.publish(
                    _f_hfreq_def_topic, _f_hfreq_def, retain=True)

            if _f_lfreq != self.fault_low_frequency.get(_f_lfreq_key, "unknown"):
                self.fault_low_frequency.update(_f_lfreq_key=_f_lfreq)
                self.mqtt_support.client.publish(
                    _f_lfreq_topic, _f_lfreq, retain=True)
                self.mqtt_support.client.publish(
                    _f_lfreq_def_topic, _f_lfreq_def, retain=True)

            if _f_bypas != self.bypass_mode_active.get(_f_bypas_key, "unknown"):
                self.bypass_mode_active.update(_f_bypas_key=_f_bypas)
                self.mqtt_support.client.publish(
                    _f_bypas_topic, _f_bypas, retain=True)
                self.mqtt_support.client.publish(
                    _f_bypas_def_topic, _f_bypas_def, retain=True)

            if _f_qual != self.qualification_status.get(_f_qual_key, "unknown"):
                self.qualification_status.update(_f_qual_key=_f_qual)
                self.mqtt_support.client.publish(
                    _f_qual_topic, _f_qual, retain=True)
                self.mqtt_support.client.publish(
                    _f_qual_def_topic, _f_qual_def, retain=True)

            return True

        elif self._is_entry_match(self.rvc_match_inverter_dc_status, new_message):
            self.Logger.debug(f"Msg Match Status: {str(new_message)}")

            if new_message["dc_voltage"] != self.dc_voltage:
                self.dc_voltage = new_message["dc_voltage"]
                self.mqtt_support.client.publish(
                    self.dc_voltage_topic, self.dc_voltage, retain=True)

            if new_message["dc_amperage"] != self.dc_amperage:
                self.dc_amperage = new_message["dc_amperage"]
                self.mqtt_support.client.publish(
                    self.dc_amperage_topic, self.dc_amperage, retain=True)

            return True

        elif self._is_entry_match(self.rvc_match_inverter_temperature_status, new_message):
            self.Logger.debug(f"Msg Match Status: {str(new_message)}")

            if new_message["fet_1_temperature"] != self.fet_1_temperature:
                self.fet_1_temperature = new_message["fet_1_temperature"]
                self.mqtt_support.client.publish(
                    self.fet_1_temperature_topic, self.fet_1_temperature, retain=True)

            if new_message["transformer_temperature"] != self.transformer_temperature:
                self.transformer_temperature = new_message["transformer_temperature"]
                self.mqtt_support.client.publish(
                    self.transformer_temperature_topic, self.transformer_temperature, retain=True)

            if new_message["fet_2_temperature"] != self.fet_2_temperature:
                self.fet_2_temperature = new_message["fet_2_temperature"]
                self.mqtt_support.client.publish(
                    self.fet_2_temperature_topic, self.fet_2_temperature, retain=True)

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

