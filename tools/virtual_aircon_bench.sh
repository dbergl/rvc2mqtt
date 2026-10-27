#!/usr/bin/env bash
# Bench test for the virtual air conditioner (rvc2mqtt/entity/virtual_aircon.py).
#
# Sends every frame the Firefly v55 panel's Climate page sends (source 0x9F,
# thermostat instance 7) and says what to expect.  See
# docs/superpowers/specs/2026-10-22-virtual-aircon-panel-interface.md and
# docs/virtual-aircon-mqtt.md.
#
# Setup (vcan, no hardware):
#   sudo ip link add dev vcan0 type vcan && sudo ip link set vcan0 up
#   floorplan with only:  - {name: VIRTUAL_AIRCON, type: virtual_aircon, instance: 7}
#   python3 -m rvc2mqtt.app -i vcan0 -f <that floorplan> ...
#
# In two other terminals:
#   mosquitto_sub -v -t 'rvc2mqtt/aircon/#'
#   candump vcan0,19FFE258:1FFFFFFF,19FEFA58:1FFFFFFF,19FF9C58:1FFFFFFF,18FFA158:1FFFFFFF
#     (1FFE2 THERMOSTAT_STATUS_1, 1FEFA STATUS_2, 1FF9C AMBIENT, 0FFA1 ours; all from 0x58)
#
# Usage: tools/virtual_aircon_bench.sh [IFACE]   (default vcan0)
# Status frames: byte 1 low nibble = mode (0 off, 1 cool, 3 auto, 4 fan, 6 dry),
# byte 2 = fan (0x28*n), bytes 5-6 = cool setpoint LE; 1FEFA byte 3 = C0 none,
# C1 sleep, C4 eco, D0 turbo; 0FFA1 byte 1 = F0 | osc | display<<2.

set -euo pipefail
IFACE="${1:-vcan0}"

send() {  # send <can-id> <data> <expectation>
    echo
    echo ">>> cansend $IFACE $1#$2"
    echo "    expect: $3"
    cansend "$IFACE" "$1#$2"
    sleep 1
}

echo "Seed state first (optional), e.g.:"
echo "  mosquitto_pub -r -t rvc2mqtt/aircon/state/setpoint -m 24"
echo "  mosquitto_pub -r -t rvc2mqtt/aircon/state/temperature -m 22.5"

# THERMOSTAT_COMMAND_1 (1FEF9) modes
send 19FEF99F 07F1FFFFFFFFFFFF "set/mode cool; 1FFE2 byte1 low nibble 1 (Power on / Cool)"
send 19FEF99F 07C3FFFFFFFFFFFF "set/mode auto + set/fan auto; 1FFE2 byte1 03, byte2 00"
send 19FEF99F 07F6FFFFFFFFFFFF "set/mode dry; byte1 low nibble 6"
send 19FEF99F 07F4FFFFFFFFFFFF "set/mode fan_only; byte1 low nibble 4"

# Fan speeds 1-5
send 19FEF99F 07DF28FFFFFFFFFF "set/fan 1; 1FFE2 byte1 bits4-5 01, byte2 28"
send 19FEF99F 07DF50FFFFFFFFFF "set/fan 2; byte2 50"
send 19FEF99F 07DF78FFFFFFFFFF "set/fan 3; byte2 78"
send 19FEF99F 07DFA0FFFFFFFFFF "set/fan 4; byte2 A0"
send 19FEF99F 07DFC8FFFFFFFFFF "set/fan 5; byte2 C8"

# Setpoint arrows (confirmed in firefly-emulator: group 130 up, 131 down; v0 when the
# panel is in degC, v1 in degF; all four currently step 1 whole degree)
send 19FEF99F 07FFFFFFFFFCFFFF "upper arrow, panel in C (0xFFFC, up): set/setpoint 25 if it was 24"
send 19FEF99F 07FFFFFFFFFBFFFF "lower arrow, panel in C (0xFFFB, down): set/setpoint back down one"
send 19FEF99F 07FFFFFFFFFAFFFF "upper arrow, panel in F (0xFFFA, up)"
send 19FEF99F 07FFFFFFFFF9FFFF "lower arrow, panel in F (0xFFF9, down)"
send 19FEF99F 07FFFFFFFF2025FF "absolute 24 C from another controller: set/setpoint 24"

# THERMOSTAT_COMMAND_2 (1FEF8) presets
send 19FEF89F 07FFDFFFFFFFFFFF "Turbo on: set/preset turbo; 1FEFA byte3 D0"
send 19FEF89F 07FFF7FFFFFFFFFF "Eco on: set/preset eco; byte3 C4 (Turbo goes dark)"
send 19FEF89F 07FFF3FFFFFFFFFF "Eco off: set/preset none; byte3 C0"
send 19FEF89F 07FFFDFFFFFFFFFF "Sleep on: set/preset sleep; byte3 C1"
send 19FEF89F 07FFFCFFFFFFFFFF "Sleep off: set/preset none; byte3 C0"

# Proprietary 0FFA0 (ours): Oscillate, Display
send 18FFA09F 07FDFFFFFFFFFFFF "Oscillate on: set/oscillate on; 0FFA1 byte1 F1"
send 18FFA09F 07FCFFFFFFFFFFFF "Oscillate off: set/oscillate off; byte1 F0"
send 18FFA09F 07F7FFFFFFFFFFFF "Display on: set/display on; byte1 F4"
send 18FFA09F 07F3FFFFFFFFFFFF "Display off: set/display off; byte1 F0"

# Must be ignored
send 19FEF99F 000000FFFFFFFFFF "instance 0 (Options screen): NOTHING published, no status change"

send 19FEF99F 07F0FFFFFFFFFFFF "Power off: set/mode off; byte1 low nibble 0, byte2 FF (fan bars dark)"

echo
echo "Done. Unconfirmed commands revert after confirm_timeout (35 s) unless state topics echo them."
