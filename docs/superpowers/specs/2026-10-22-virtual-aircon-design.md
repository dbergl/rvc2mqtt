# Virtual Air Conditioner — design

**Date:** 2026-10-22
**Status:** approved in brainstorming, awaiting implementation plan
**Branch:** `virtual-aircon` (cut from `unknown-dgns`, carrying the uncommitted
`rvc-spec.yml` 6.16 edits — keep them)
**Panel interface (read first):** [2026-10-22-virtual-aircon-panel-interface.md](2026-10-22-virtual-aircon-panel-interface.md)
— every frame the v55 Firefly panel sends and reads. This document does not repeat it.

## Why

A Firefly-paneled van (built by Dan for a friend) has a Bluetooth air conditioner.
The panel's new Climate page speaks RV-C thermostat **instance 7**, but nothing on
the bus is that thermostat. The AC is reachable only through the friend's Home
Assistant, which already has it as a climate entity via a Bluetooth integration and
can read everything the panel needs (power, mode, fan speed, setpoint, room
temperature from the AC's onboard thermostat, Turbo/Eco/Sleep, Oscillate, Display — per Dan; upstream velit-hass covers less, see below).

Goal: make the AC appear on the RV-C bus as thermostat instance 7, so the panel can
show it and control it.

**Handoff matters.** Dan does not have this Home Assistant and cannot test that
side end to end. The friend takes the code over afterwards and will fix bugs and
integration details himself, so the code and the MQTT contract should be plain,
documented and easy to change. Prefer clarity over cleverness.

## The AC side (from velit-hass)

The friend's HA integration is based on
[JohnFreeborg/velit-hass](https://github.com/JohnFreeborg/velit-hass) (Countrymod Pro /
Velit AC), plus his own modifications that we haven't seen. What upstream
`custom_components/velit/climate.py` does, and what follows for this design:

- **HVAC modes:** `off`, `cool`, `fan_only`. No `auto` and no `dry`.
- **Eco / Sleep / Turbo are one preset**, not three toggles. They are AC operation modes
  4/5/6 and are only meaningful in cool mode. The preset names are `Cooling` (none),
  `Eco`, `Sleep` and `Turbo`.
- **Fan:** `1`–`5` only. No fan-auto.
- **Setpoint:** whole degrees, with a range of 17–30 °C. HA presents it in °C. If the AC's
  own display is in °F, the integration rounds °C to whole °F.
- **No Oscillate or Display** entities.
- **Confirmation timing:** the integration polls every 30 s by default. After a command
  it polls every 5 s for 6 polls, so a command is confirmed (or not) within about 30 s.
  It uses its own optimistic-then-revert pattern for the same reason.

The friend's modifications may add some of the missing features. So rvc2mqtt still
publishes every panel command; one the integration can't act on simply goes unconfirmed
and reverts (see Behaviour). The MQTT doc must list which commands upstream velit-hass
supports.

## Shape

New entity plugin `rvc2mqtt/entity/virtual_aircon.py`, modelled on
`entity/virtual_inverter.py` (a *device*: it receives commands and broadcasts status).
`entity/hvac.py` is the opposite, a controller, and must not be configured for instance 7.
Nothing touches thermostat instance 0 (the G12 runs it).

```
Firefly panel ──1FEF9/1FEF8/0FFA0 (SA 0x9F, inst 7)──▶ virtual_aircon ──set topics──▶ HA automation ──BT──▶ AC
Firefly panel ◀──1FFE2/1FEFA/1FF9C/0FFA1 (inst 7)──── virtual_aircon ◀──state topics── HA automation ◀──BT── AC
```

- **rvc2mqtt is plumbing only.** No Home Assistant discovery and no climate card
  (Dan's decision). The AC already has a climate entity; a second one would drift.
  The friend's HA automations publish the AC's real state to the state topics and
  turn the set topics into Bluetooth calls.
- **The AC's report is the source of truth.** Changes made from the AC's remote
  or app show up on the panel because the state topics drive the broadcast status.

## MQTT contract

One configurable base, `topic_base` (default `rvc2mqtt/aircon`), with one plain topic
per field. Override any individual topic in the floorplan, the same way as the
inverter's `fields` map. Topics and payloads must be documented in the module
docstring and in a short `docs/virtual-aircon-mqtt.md` the friend can write his
automations from.

| Field | State topic (HA → rvc2mqtt, retained) | Set topic (rvc2mqtt → HA) | Payload |
|---|---|---|---|
| mode | `state/mode` | `set/mode` | `off` `cool` `auto` `dry` `fan_only` (HA hvac_mode strings; upstream velit supports only off/cool/fan_only) |
| fan | `state/fan` | `set/fan` | `1`–`5`, or `auto` (not in upstream velit) |
| setpoint | `state/setpoint` | `set/setpoint` | **integer**, °C by default |
| room temperature | `state/temperature` | — | number, same unit |
| preset | `state/preset` | `set/preset` | `none` `eco` `sleep` `turbo` (one at a time, like velit's preset; accept velit's `Cooling`/`Eco`/`Sleep`/`Turbo` case-insensitively on state) |
| oscillate | `state/oscillate` | `set/oscillate` | `on` / `off` |
| display | `state/display` | `set/display` | `on` / `off` |

- Power is just mode: panel Power-on sends `cool`, Power-off sends `off`.
- **Temperature unit is configurable** (`temperature_unit: C|F`, default C) in case
  his integration reports °F. RV-C on the bus is always the standard encoding; the
  panel converts to °F itself.
- Accept lenient payloads where cheap (`ON`/`1`/`true`, numeric strings, `fan_only`
  or `fan`). Log and ignore anything unparseable; never raise out of the MQTT callback.
- Set topics are not retained.
- Optional `availability_topic`. Lesson from the virtual inverter: HA may publish on
  change only, so message recency is **not** liveness. Don't time out on silence.

## Behaviour

**Commands from the panel.** Decode from the raw `data` bytes, not the decoded fields,
because the setpoint step codes `0xFFF9`–`0xFFFC` are not temperatures. Only act on
fields that aren't "no change" (all ones). Byte 0 must be the configured instance (7).
Accept commands from any source address, and log the source. `0FFA0` is not in
`rvc-spec.yml`, so match the decoder's `UNKNOWN-0FFA0` name or add the proprietary
`0FFA0`/`0FFA1` entries to the spec (builder's call). Keep the firmware's placeholder
bit layout.

**Optimistic update, confirm or revert (per field).** On a panel command, set that
field's optimistic value, publish the set topic, and broadcast the new status
**immediately**. The panel picks each toggle's payload from the last status it saw, so a
slow echo makes a second tap repeat the first command. The optimistic value then holds
until one of two things happens:
- a state report **matches** it (confirmed; the optimistic value is cleared), or
- `confirm_timeout` passes (default 35 s, just over velit's ~30 s fast-poll window).
  The field then reverts to the last reported value, and the revert is logged at info
  level.
While a field is pending, reports that don't match are recorded as "last reported" but
not shown. This stops a late report of the old setpoint snapping a held arrow back.
State reports for fields that aren't pending apply immediately (remote/app changes).
This is the same pattern velit-hass uses internally, so the friend will recognise it.
Because of this, his automations don't need to re-publish state after commands; they
only have to publish on change, which is the HA norm.

**Presets.** The panel treats Turbo/Eco/Sleep as independent toggles, but the AC has one
preset. Turning one on sets `preset` to it, so the other two read off in `1FEFA`.
Turning the active one off sets `preset` to `none`. Turning off one that isn't active
does nothing.

**Setpoint arrows.** The entity owns the arithmetic. Each step code moves the current
(optimistic) setpoint by **one whole degree** in `temperature_unit`, and only the
resulting absolute setpoint is published on `set/setpoint`, as an integer. Every repeat
of a held arrow is one step from the optimistic value, so a hold never stalls on a
rounded report. The direction of each code is a floorplan map, because the mapping isn't
confirmed. Default guess: `0xFFFC`/`0xFFFA` = up and `0xFFFB`/`0xFFF9` = down. The
variant (the panel's °F/°C setting) is ignored for step size, because the AC only takes
whole °C through HA. Log every step code at info level so the bench capture settles it.
*Update 2026-10-22, confirmed in firefly-emulator:* group 130 = up and 131 = down. The
variant follows the panel's Temp Units setting: in °C it sends `0xFFFC` up / `0xFFFB` down,
and in °F it sends `0xFFFA` up / `0xFFF9` down. So the default map is correct, and the °F
codes mean a 1 °F step. How the °F codes should step is Dan's call; until then all four
step one whole degree.
Clamp to `setpoint_min`/`setpoint_max` (default 17–30 °C, velit's range). If no setpoint
has been reported yet, step from `setpoint_default` (default 24 °C). Absolute cool
setpoints in bytes 5–6 from another controller are accepted and rounded to an integer.

**Status to the panel.** Broadcast `1FFE2`, `1FEFA`, `1FF9C` and `0FFA1` for instance 7
on every state change and at least every 2 s (`interval`, default 1 s is fine). Use the
standard RV-C temperature encoding, and add `encode_temperature_u16` to `rvc_encode.py`.
Send the heat setpoint as `0xFFFF`.

- **Fan bars.** Byte 2 carries the AC's reported speed (1–5 → 40/80/120/160/200 in
  0.5 % units, so bar n lights at ≥ 40·n). For `auto`, or no numeric speed reported,
  send 0 and leave the bars dark. Command decode maps the panel's 0x28…0xC8 back to 1–5.
  The panel's Auto button also requests fan-auto (byte 1 bits 4–5). Publish
  `set/fan auto` with it; upstream velit will leave it unconfirmed and it reverts.
- **1FEFA byte 3** is derived from `preset`: at most one of Sleep/Eco/Turbo reads `01`,
  and the other two read `00`.
- **Before the AC has reported:** broadcast mode Off with everything else "not available",
  so the panel shows Off rather than "--". (This differs from the inverter, which goes
  silent until its first status. Here a silent thermostat would leave the Climate page dead.)
- If `availability_topic` reports offline, keep broadcasting but report mode Off (the
  builder may choose silence instead if it bench-tests better; document which).

**Source address.** Configurable `source_id`, default `58` (spec thermostat range
0x58–0x5D). It must not collide with anything on the friend's coach. Note this in the docs.

**Own echoes / dispatch.** Claim our own status DGNs at instance 7 (return `True`) so
they stay out of the unhandled log, but return `False` for everything else.
First-match-wins dispatch (see CLAUDE.md) means the match must be narrow: instance 7
and these DGNs only. Ignore `1FEF9 000000FF…` (instance 0, Options screen); that
falls out of the instance check.

## Floorplan entry (sketch)

```yaml
- name: VIRTUAL_AIRCON
  type: virtual_aircon
  instance: 7
  instance_name: "Air Conditioner"
  source_id: '58'
  topic_base: rvc2mqtt/aircon
  temperature_unit: C
  setpoint_min: 16
  setpoint_max: 30
  # step_codes: {0xFFFC: {dir: up, step: 1, unit: C}, ...}   # until bench-confirmed
  # setpoint_default: 24
  # confirm_timeout: 35
  # availability_topic: ...
  # fields: {mode: {state: ..., set: ...}, ...}              # per-topic overrides
```

## Testing

- **Unit tests** (`test/virtual_aircon_test.py`): every panel frame in the interface
  spec → correct state change and set-topic publish; each status frame encoded
  byte-for-byte for each lit state, including the fan thresholds, 0 for auto, mode
  Off before first report, and the toggle immediate-echo; MQTT state ingest including
  °F conversion and bad payloads; setpoint stepping (integer, held-arrow repeats,
  no snap-back from a stale report) and clamping; preset mutual exclusion;
  confirm-on-match and revert-on-timeout per field; the instance-0
  Options frame ignored. The existing 810 tests must still pass.
- **Bench script** `tools/virtual_aircon_bench.sh`: one `cansend vcan0 …` per panel
  frame, with a comment giving the expected `candump` status reply. Use it on vcan,
  then on the coach, to confirm the Climate page lights every control and the Home box
  shows the mode text and setpoint. Use the same session to capture the arrow step-code
  meaning.

## Goals / non-goals

- **Goal:** the panel Climate page fully drives and reflects the AC through HA.
- **Non-goal:** HA discovery or any HA-side automation. The friend writes those against
  the documented contract. An example automation in the MQTT doc is welcome.
- **Non-goal:** firmware changes. If the `0FFA0`/`0FFA1` layout changes, the firmware
  project must change too, so don't change it.
- **Anti-goal:** anything that touches thermostat instance 0 or starves other entities
  in dispatch.

## Left to the builder

Internal structure, the exact config key names (keep them close to the sketch), whether
`0FFA0`/`0FFA1` go in `rvc-spec.yml`, payload leniency details, and log levels.
