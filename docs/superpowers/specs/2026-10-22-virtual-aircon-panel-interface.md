# Virtual air conditioner — Firefly panel interface (v55)

Date: 2026-10-22
Source: Firefly LCD firmware `mcf-dan-v55.bin` (Jayco B-Van, Firefly 13.6), decoded with
`fireflymcf bus-map`; firmware design in `~/projects/rv/myfirmware/docs/2026-10-20-rvc-aircon-climate-design.md`.
RV-C reference: section 6.16 of `~/projects/rv/myfirmware/rv-c/RV-C Specification Full Layer 6-31-25_Final_0.pdf`.

## What to build

A virtual RV-C thermostat/air-conditioner entity, **thermostat instance 7**, that sits between the
panel's Climate page and MQTT/Home Assistant. It is a *device*, like `entity/virtual_inverter.py`:
it receives commands on instance 7 and broadcasts status for instance 7. It is not like
`entity/hvac.py`, which acts as a controller of an existing thermostat.

The physical air conditioner is controlled only through this entity (over MQTT). The G12 still runs
thermostat instance 0; nothing should be done with instance 0, and the existing `hvac` entity must
not be configured for instance 7.

All climate controls in the firmware are **unverified on the coach**. Bench-test with candump/cansend.

## Commands the panel sends (priority 6, source address 0x9F)

Byte 0 is always `07`. Unused fields are all-ones ("no change") per the spec; only act on fields
that are not `0xF…`/`0xFF`.

| Control | Panel group | CAN ID | Payload | Meaning |
|---|---|---|---|---|
| Power (toggle) | 174 | `19FEF99F` | when off: `07F1FFFFFFFFFFFF`; when on: `07F0FFFFFFFFFFFF` | on = mode Cool; off = mode Off |
| Cool | 160 | `19FEF99F` | `07F1FFFFFFFFFFFF` | mode 1 |
| Auto | 161 | `19FEF99F` | `07C3FFFFFFFFFFFF` | mode 3 **and fan mode = auto** (byte 1 bits 4–5 = 00) |
| Dry | 165 | `19FEF99F` | `07F6FFFFFFFFFFFF` | mode 6 (window defrost/dehumidify) |
| Fan | 166 | `19FEF99F` | `07F4FFFFFFFFFFFF` | mode 4 (fan only) |
| Fan 1–5 | 175/182/183/185/190 | `19FEF99F` | `07DFnnFFFFFFFFFF` | fan mode = on, byte 2 = 0x28/0x50/0x78/0xA0/0xC8 (20/40/60/80/100 %, 0.5 % units) |
| Setpoint arrow | 130 | `19FEF99F` | v0 `07FFFFFFFFFCFFFF`, v1 `07FFFFFFFFFAFFFF` | step code in cool setpoint (bytes 5–6, LE): `0xFFFC` / `0xFFFA`; repeats while held |
| Setpoint arrow | 131 | `19FEF99F` | v0 `07FFFFFFFFFBFFFF`, v1 `07FFFFFFFFF9FFFF` | `0xFFFB` / `0xFFF9`; repeats while held |
| Turbo (toggle) | 191 | `19FEF89F` | on `07FFDFFFFFFFFFFF` / off `07FFCFFFFFFFFFFF` | THERMOSTAT_COMMAND_2 byte 2 bits 4–5 |
| Eco (toggle) | 192 | `19FEF89F` | on `07FFF7FFFFFFFFFF` / off `07FFF3FFFFFFFFFF` | byte 2 bits 2–3 |
| Sleep (toggle) | 193 | `19FEF89F` | on `07FFFDFFFFFFFFFF` / off `07FFFCFFFFFFFFFF` | byte 2 bits 0–1 (reduced noise mode) |
| Oscillate (toggle) | 194 | `18FFA09F` | on `07FDFFFFFFFFFFFF` / off `07FCFFFFFFFFFFFF` | proprietary `0FFA0` byte 1 bits 0–1 (**placeholder**) |
| Display (toggle) | 195 | `18FFA09F` | on `07F7FFFFFFFFFFFF` / off `07F3FFFFFFFFFFFF` | `0FFA0` byte 1 bits 2–3 (**placeholder**) |

**Setpoint step codes — open question.** The firmware picks variant 0 or 1 of groups 130/131
itself, and the selector is not yet traced. Unconfirmed reading: one group is up, the other down,
and the variant follows the panel's °F/°C setting (1 °F vs 1 °C step). Handle all four codes as
steps, log them, and make the mapping configurable until it is captured on the bench. Also accept
absolute cool setpoints (normal RV-C values) in bytes 5–6 from other controllers.

**Toggles.** Every tick the panel chooses which payload a toggle sends from the status it last
received: status off → it sends "on", status on → it sends "off". Broadcast the new status
immediately after acting on a command, or a second tap repeats the first command.

**Ignore:** the Options/floorplan screens send `1FEF9` `000000FFFFFFFFFF` to instance 0.

The `0FFA0`/`0FFA1` layout is ours to define (J1939 Proprietary B). Keep the firmware's
placeholder layout unless there is a reason to change it; any change must be mirrored in the
firmware project (`osc-f`/`disp-f` filters and groups 194/195).

## Status the panel reads (every filter requires byte 0 == 0x07)

| Var | DGN | Field read | Panel use |
|---|---|---|---|
| 13 | `1FFE2` THERMOSTAT_STATUS_1 | byte 1 bits 0–3, operating mode | Power lit when ≠ 0; Cool = 1, Auto = 3, Fan = 4, Dry = 6; Home text Off/Cool/Auto/Fan/Dry, else "--" |
| 14 | `1FFE2` | bytes 5–6 u16 cool setpoint | Climate and Home "Set" readout |
| 322 | `1FFE2` | byte 2 fan speed | bar n lit when speed ≥ 40·n; > 250 (0xFF) reads as off |
| 9 | `1FF9C` THERMOSTAT_AMBIENT_STATUS | bytes 1–2 u16 | Room temperature readout |
| 323 | `1FEFA` THERMOSTAT_STATUS_2 | byte 3 bits 0–1 | Sleep lit when 01 |
| 324 | `1FEFA` | byte 3 bits 2–3 | Eco lit when 01 |
| 325 | `1FEFA` | byte 3 bits 4–5 | Turbo lit when 01 |
| 326 | `0FFA1` (CAN ID `18FFA1xx`) | byte 1 bits 0–1 | Oscillate lit when 01 |
| 327 | `0FFA1` | byte 1 bits 2–3 | Display lit when 01 |

- Temperatures: standard RV-C, u16, 0.03125 °C/bit, offset −273 °C (`rvc_encode` helpers). The
  panel converts to °F itself.
- The panel ignores the heat setpoint (bytes 3–4); send a sensible value or `0xFFFF`.
- Each panel value goes stale ~30 s after its last frame. Spec cadence: `1FFE2` on change and every
  2 s (max gap 5 s); `1FEFA` on change, max gap 5 s. Broadcast all four status DGNs on change and
  at least every 2 s.
- Fan speed in fan-mode auto (e.g. after Auto): the spec says 0 = automatic, but the bars light
  from byte 2. Prefer reporting the unit's actual speed so the bars reflect reality; decide and
  document.
- Use a thermostat source address (spec default 88–93 / 0x58–0x5D) that nothing else on the bus
  uses.

## rvc-spec.yml

`1FEFA` byte 3 Eco/Turbo bits and `1FEF8` byte 2 (reduced noise/Eco/Turbo) and byte 1 value 251
were added from spec section 6.16 on 2026-10-22 (uncommitted in the working tree). `0FFA0`/`0FFA1`
are proprietary and not in the file; add them if the entity decodes via the spec.

## MQTT / Home Assistant (suggested)

An MQTT `climate` entity via discovery:

- `modes`: off, cool, auto, dry, fan_only
- `fan_modes`: 1–5 (and auto)
- `swing_modes`: on/off → Oscillate
- `preset_modes`: boost (Turbo), eco (Eco), sleep (Sleep) — or separate switches, since the panel
  treats them as independent toggles
- Display as a separate `switch`
- `current_temperature` from the room sensor feeding `1FF9C`; `temperature` = cool setpoint

Where the room temperature comes from, and the MQTT topics that drive the real unit, are for the
owner to define.

## Verification

- Unit tests: decode each panel frame above into the right state change; encode status frames
  byte-for-byte for each lit state (including the fan ≥ thresholds and 0xFF).
- Bench (vcan or the coach): send the panel frames with `cansend`, check status echo, then check
  that the Climate page lights every control and that the Home box shows the setpoint and mode text.
