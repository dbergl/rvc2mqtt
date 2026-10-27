# Virtual air conditioner — MQTT contract

`rvc2mqtt/entity/virtual_aircon.py` makes an air conditioner that Home Assistant controls
(over Bluetooth, via [velit-hass](https://github.com/JohnFreeborg/velit-hass)) appear on
the RV-C bus as **thermostat instance 7**, the instance the Firefly panel's Climate page
uses.

```
Firefly panel ──1FEF9/1FEF8/0FFA0──▶ virtual_aircon ──set topics──▶ your HA automation ──BT──▶ AC
Firefly panel ◀──1FFE2/1FEFA/1FF9C/0FFA1── virtual_aircon ◀──state topics── your HA automation ◀──BT── AC
```

rvc2mqtt is **plumbing only**. It creates no Home Assistant entities (no discovery), because
the AC already has its own climate entity. Your HA automations do the rest:

1. **State:** publish the AC's real state to the *state* topics, retained, whenever it changes.
2. **Commands:** turn messages on the *set* topics into calls on the AC's climate entity.

Design background: `docs/superpowers/specs/2026-10-22-virtual-aircon-design.md`.

## Topics

All topics hang off `topic_base`, which defaults to `rvc2mqtt/aircon`.

| Field | State topic (HA → rvc2mqtt, **retained**) | Set topic (rvc2mqtt → HA, not retained) | Payloads | velit-hass support |
|---|---|---|---|---|
| mode | `state/mode` | `set/mode` | `off` `cool` `auto` `dry` `fan_only` | all five in your integration (upstream has only `off` `cool` `fan_only`) |
| fan | `state/fan` | `set/fan` | `1`–`5`, `auto` | `1`–`5` only; **no `auto`** |
| setpoint | `state/setpoint` | `set/setpoint` | integer, in `temperature_unit` | whole °C, 17–30 |
| room temperature | `state/temperature` | — | number, in `temperature_unit` | yes (`current_temperature`) |
| preset | `state/preset` | `set/preset` | `none` `eco` `sleep` `turbo` | yes, as `Cooling` `Eco` `Sleep` `Turbo` |
| oscillate | `state/oscillate` | `set/oscillate` | `on` `off` | **not supported** |
| display | `state/display` | `set/display` | `on` `off` | **not supported** |
| availability (optional) | `availability_topic` | — | `online` `offline` | the integration's availability |

**What rvc2mqtt accepts on the state topics:**
- Mode: also `fan` (→ `fan_only`) and `heat_cool` (→ `auto`).
- Preset: velit's `Cooling`/`Eco`/`Sleep`/`Turbo`, plus `boost` and `energy_saving`.
- On/off: `on/off/1/0/true/false`.
- Numbers formatted like `24.0` (the setpoint is rounded to an integer).
- Everything case-insensitive.
- HA's `unavailable`/`unknown` are ignored quietly, and the last value is kept. Other junk
  logs one warning per field.

The panel still sends commands for features upstream velit-hass doesn't have, and rvc2mqtt
still publishes them, in case your modified integration supports them. If it doesn't, nothing
confirms them and they revert (see below).

## Confirm or revert

When the panel sends a command, rvc2mqtt shows the new value on the panel **at once**. The
panel's toggles choose "on"/"off" from the last status they saw, so a slow echo would make a
second tap repeat the first command. The new value then stays until:

- **the matching value arrives on the state topic.** It's confirmed and nothing more happens.
- **`confirm_timeout` (default 35 s) passes without that.** The field reverts to the last
  reported value, and an info line `<field>: ... not confirmed within 35.0s, reverting to ...`
  is logged.

While a field waits for confirmation, a *different* reported value is noted but not shown.
This stops a late report of the old setpoint snapping a held arrow back. Reports for fields
that aren't waiting (for example, changes made from the AC's own remote) show immediately.

So your automations only need to publish on change, retained. They don't need to re-publish
after each command.

## Panel behaviour worth knowing

- **Setpoint arrows:** rvc2mqtt does the arithmetic. Each press, and each repeat while the
  button is held, moves the setpoint one whole degree. At the limit, nothing is published. It is clamped to
  `setpoint_min`–`setpoint_max` and published as an integer on `set/setpoint`. Before any
  setpoint has been reported, stepping starts from `setpoint_default`.
  The arrow codes were confirmed in the firmware emulator. Upper arrow = up, lower = down.
  The code depends on the panel's Temp Units setting: in °C the panel sends `0xFFFC`
  (up) / `0xFFFB` (down), and in °F it sends `0xFFFA` (up) / `0xFFF9` (down). The °F codes
  mean "1 °F", but rvc2mqtt deliberately steps one whole degree in `temperature_unit` for all
  four, because the AC takes whole °C only. So with the panel in °F, each press moves the
  readout by 1–2 °F (75 → 77 → 78). Each press is logged as
  `setpoint step code 0xfffc (up): 24 -> 25`.
- **Turbo/Eco/Sleep:** the panel has three independent toggles, but the AC has one preset.
  Turning one on selects it, which turns the other two off. Turning off the active one sends
  `none`.
- **Power:** on sends `set/mode cool`; off sends `set/mode off`.
- **Auto button:** it sends both `set/mode auto` and `set/fan auto`.
- **Fan bars:** they show the reported speed (1–5). They stay dark for `auto` or an unknown
  speed, and always while the mode is Off (fan speed sent as 0xFF). The real speed shows again
  as soon as a mode turns on.
- **Before anything is reported, or while availability is `offline`:** the panel is told the
  mode is Off, so it shows "Off" rather than "--".

## Floorplan entry

```yaml
floorplan:
  - name: VIRTUAL_AIRCON
    type: virtual_aircon
    instance: 7                  # the panel's Climate page uses 7; never 0 (the G12's)
    instance_name: "Air Conditioner"
    source_id: '58'              # RV-C address we transmit from; must be unused on the bus
    topic_base: rvc2mqtt/aircon
    temperature_unit: C          # C or F: the unit of setpoint/temperature on MQTT
    # setpoint_min: 17           # F defaults: 62
    # setpoint_max: 30           # F defaults: 86
    # setpoint_default: 24       # F defaults: 75
    # confirm_timeout: 35        # seconds before an unconfirmed command reverts
    # interval: 1.0              # seconds between status broadcasts (also sent on every change)
    # availability_topic: velit/aircon/availability
    # step_codes:                # arrow step code -> up/down (merged over these defaults)
    #   0xFFFC: up
    #   0xFFFA: up
    #   0xFFFB: down
    #   0xFFF9: down
    # fields:                    # per-field topic overrides, relative to topic_base
    #   setpoint: {state: my/state/sp, set: my/set/sp}
```

**Source address:** `58` is the first address in the RV-C thermostat range (0x58–0x5D).
Before you settle on it, run `candump can0` on the coach and check that nothing else sends
from `58` (the last two hex digits of the CAN ID).

Do not configure the existing `hvac` entity for instance 7. That entity *controls* a
thermostat, whereas this one *is* the thermostat.

## Example Home Assistant automations (untested)

These are a starting point only; nobody has run them yet. Replace `climate.velit_ac` with
your entity id.

```yaml
# Commands: rvc2mqtt -> AC (everything except the setpoint)
- alias: "aircon: rvc2mqtt set -> climate"
  mode: queued
  max: 20
  trigger:
    - platform: mqtt
      topic: rvc2mqtt/aircon/set/+
  condition: "{{ trigger.topic.split('/')[-1] != 'setpoint' }}"
  action:
    - variables:
        field: "{{ trigger.topic.split('/')[-1] }}"
        value: "{{ trigger.payload }}"
    - choose:
        - conditions: "{{ field == 'mode' }}"
          sequence:
            - service: climate.set_hvac_mode    # passes off/cool/auto/dry/fan_only through
              target: {entity_id: climate.velit_ac}
              data: {hvac_mode: "{{ value }}"}
        - conditions: "{{ field == 'fan' and value != 'auto' }}"
          sequence:
            - service: climate.set_fan_mode
              target: {entity_id: climate.velit_ac}
              data: {fan_mode: "{{ value }}"}
        - conditions: "{{ field == 'preset' }}"
          sequence:
            - service: climate.set_preset_mode
              target: {entity_id: climate.velit_ac}
              data:
                preset_mode: >-
                  {{ {'none': 'Cooling', 'eco': 'Eco', 'sleep': 'Sleep', 'turbo': 'Turbo'}[value] }}

# Setpoint: debounced, because a held arrow publishes one value per repeat.
# mode: restart + delay sends only the last value once the arrow is released.
- alias: "aircon: rvc2mqtt setpoint -> climate"
  mode: restart
  trigger:
    - platform: mqtt
      topic: rvc2mqtt/aircon/set/setpoint
  action:
    - delay: {milliseconds: 700}
    - service: climate.set_temperature
      target: {entity_id: climate.velit_ac}
      data: {temperature: "{{ trigger.payload | int }}"}

# State: AC -> rvc2mqtt.  Read attributes with state_attr() directly (a dict held
# in a script variable doesn't survive HA's template rendering).  Skip while the
# AC is unavailable, so good retained values aren't overwritten with junk.
- alias: "aircon: climate -> rvc2mqtt state"
  mode: queued
  trigger:
    - platform: state
      entity_id: climate.velit_ac        # also fires on attribute changes
    - platform: homeassistant
      event: start
  condition: "{{ states('climate.velit_ac') not in ['unavailable', 'unknown'] }}"
  action:
    - service: mqtt.publish
      data: {topic: rvc2mqtt/aircon/state/mode, retain: true,
             payload: "{{ states('climate.velit_ac') }}"}
    - service: mqtt.publish
      data: {topic: rvc2mqtt/aircon/state/setpoint, retain: true,
             payload: "{{ state_attr('climate.velit_ac', 'temperature') }}"}
    - service: mqtt.publish
      data: {topic: rvc2mqtt/aircon/state/temperature, retain: true,
             payload: "{{ state_attr('climate.velit_ac', 'current_temperature') }}"}
    - service: mqtt.publish
      data: {topic: rvc2mqtt/aircon/state/fan, retain: true,
             payload: "{{ state_attr('climate.velit_ac', 'fan_mode') }}"}
    - service: mqtt.publish
      data: {topic: rvc2mqtt/aircon/state/preset, retain: true,
             payload: "{{ state_attr('climate.velit_ac', 'preset_mode') or 'Cooling' }}"}
```

`climate.velit_ac` reports `preset_mode` only in cool mode (velit returns None otherwise),
so the `or 'Cooling'` maps that to `none`. To make the panel show Off while the AC is
unreachable, publish `online`/`offline` to an `availability_topic`. The state automation's
condition deliberately leaves the last good state in place.

## Bench testing

`tools/virtual_aircon_bench.sh [IFACE]` sends every panel frame with `cansend` and prints
what to expect on MQTT and in `candump`. Run it on vcan first, then on the coach. Use the
same session to check the arrows step the right way under both Temp Units settings.

## Open items

- **`0FFA0`/`0FFA1`** (Oscillate/Display) are our own proprietary layout, mirrored in the
  panel firmware. Change it in both places or neither.
- **Not verified on the coach:** all the panel's climate controls.
