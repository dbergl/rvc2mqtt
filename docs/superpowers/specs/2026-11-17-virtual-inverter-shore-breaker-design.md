# Virtual inverter: shore breaker size and charge rate readout (1FF95 / 1FF96)

Status: approved by the owner 2026-11-17 (relayed by the firmware session); implemented on branch `virtual-inverter-shore-breaker`.

## Intent

The coach panel's Shore Brkr Size +/− should set the Renogy inverter's AC input
current limit (modbus2mqtt `max_ac_input_current`, register 57884, Renogy
setting 39) and show the value actually in force. The panel writes G12 selector
0x90; the G12 (SA 0x9C) relays the absolute value as
`CHARGER_CONFIGURATION_COMMAND_2` (1FF95), instance 1, byte 3 = whole amps,
all other bytes 0xFF. The panel reads the number back from
`CHARGER_CONFIGURATION_STATUS_2` (1FF96) byte 3, any instance. Nothing on the
coach publishes 1FF96 today, so the panel shows 255 A.

Requested by the firefly-firmware session (BUILD-LOG "v71 Shore Brkr").

## Goals

- The inverter is the authority for the setting (owner's decision, relayed by
  the firmware session 2026-11-17). The G12's copy (selector 0x90) follows it.
- A panel press (1FF95 at the virtual inverter's instance) writes the modbus
  setting.
- 1FF96 is transmitted with the real modbus value so the panel reads it back.
- A change made on the inverter or from Home Assistant reaches the G12, so the
  panel's next +/− (a delta on the G12's copy) starts from the right number.
- The panel's CHARGE RATE readout shows the inverter's DC charge current limit
  as a percentage of the charger's rated output. Display only.

## Non-goals

- Acting on any 1FF95 field other than byte 3. In particular byte 1 (max charge
  current %) is never written to the inverter: the G12 relays a soft-start ramp
  there (rule #8), which would ramp the inverter's charge current.
- A writable Home Assistant entity. modbus2mqtt already publishes one.

## Anti-goals

- Changing bus behaviour for anyone who upgrades without touching their
  floorplan. The whole feature is off until the field is mapped.
- Wearing the inverter's settings memory with repeated identical writes.
- Feeding the G12's unexplained rule (table 0x61 #6: 1FF96 byte 1 → cell 0x84
  for instances 1..2) by accident.

## Approaches

1. **Extend `virtual_inverter` (picked).** It already owns the modbus↔RV-C
   mapping, the source address, the transmit schedule and the charger-side
   frames (1FFCA, 1FFC6). One new field, one new frame, one new command branch.
2. A separate `virtual_charger` entity. Cleaner in RV-C terms, but it would
   duplicate the liveness, scheduling and field-mapping machinery for one byte,
   and floorplan order would decide which of the two sees the command.
3. Do it outside rvc2mqtt (Home Assistant automation, or the G12 entity writing
   MQTT). Splits one device across two places and leaves 1FF96 unpublished.

## Design

### Floorplan

```yaml
  - name: VIRTUAL_INVERTER
    type: virtual_inverter
    instance: 1
    charger_config_2_instance: 3          # instance stamped on the 1FF96 we send
    fields:
      shore_breaker_size: {topic: state/max_ac_input_current, scale: 0.1}
      charge_current_limit: {topic: state/current, scale: 0.1}
    charger_rated_current: 40             # A; owner: max DC output on shore power
```

| Option | Default | Meaning |
|---|---|---|
| `fields.shore_breaker_size` | unmapped | State topic and scale (amps). Unmapped = feature off: no 1FF96 sent, 1FF95 not claimed. |
| `fields.charge_current_limit` | unmapped | DC charge current limit (amps; register 57861). Only feeds 1FF96 byte 1. |
| `charger_rated_current` | — | Charger's maximum DC output in amps. Required when `charge_current_limit` is mapped; startup fails without it. |
| `shore_breaker_set_topic` | `set/max_ac_input_current` | Write topic, relative to `source_topic_base`. |
| `shore_breaker_min` / `shore_breaker_max` | `5` / `30` | Clamp applied to commanded amps. |
| `charger_config_2_instance` | the entity's `instance` | Instance byte of the transmitted 1FF96. Declared in the floorplan because it may deliberately differ from the entity's own (see Risks). |
| `shore_breaker_g12_sync` | `false` | Push the inverter's value into G12 selector 0x90. Coach-specific, so off unless asked for. |
| `g12_source_id` | `9C` | Address the G12's 15FCE report must come from. |
| `shore_breaker_settle` | `2.0` | Seconds to wait after a panel command or a state change before pushing to the G12. |

The example floorplan above gains `shore_breaker_g12_sync: true` on the coach.

### State kept

- `state` — amps from modbus (may be outside min..max; the limits in jayco.csv
  are Home Assistant-side only and the inverter's own range is not known).
- `g12_value` — what the G12's 0x90 holds: set from the G12's 15FCE report of
  the selector and from byte 3 of every 1FF95 received (never from a 0xFF
  byte 3). Unknown at startup and after an unanswered exchange. Our own write
  does not set it; the G12's answer does.
- `target = clamp(round(state), min, max)`.

### Command in (1FF95)

Handled only when `shore_breaker_size` is mapped and the frame's instance equals
the entity's `instance`. Any source address is accepted, as for
`INVERTER_COMMAND`. The frame is always claimed (`True`).

- Byte 3 is read from the raw payload. 0xFF means "no change": nothing happens.
  Bytes 1, 2, 4 and 5-6 are never acted on (byte 1 is a G12 charge-rate
  soft-start ramp; acting on it would ramp the inverter's charge current).
- Otherwise `v = clamp(byte 3)`, and `g12_value := v`.
- **`state` unknown → no write.** The inverter is the authority; when its value
  arrives it is pushed to the G12 (below) and the panel corrects itself.
- **`v == target` → no write.** This one rule absorbs the G12's relay of our own
  push, the G12 boot replay, and re-sends caused by byte 1 changing. It also
  protects an out-of-range inverter value: inverter at 32 → we push 30 → G12
  relays 30 → 30 equals `target`, so 30 is not written over the 32.
- **`v != target` → panel press.** Publish `round(v / scale)` to the set topic
  (25 A → `250`; modbus2mqtt takes the raw register value) and restart the
  settle timer.

### Sync with the G12 (only with `shore_breaker_g12_sync`)

Evaluated in `tick()`, when `state` is known, the modbus source is online and
the settle timer has expired. The settle timer restarts on every state change,
every panel press and every failed exchange.

`g12_value` is learned from the G12's own report of selector 0x90 (15FCE
`90 00 <u16 LE>` from `g12_source_id`, default 9C), which the G12 sends in
answer to every read-back request, and from byte 3 of any 1FF95.

1. `g12_value` unknown → send only the read-back and wait for the report.
2. `target == g12_value` → nothing.
3. Otherwise send the set and the read-back, and wait for the report.

Frames, DGN 1FED9, sent from the bridge's own address like every other
`g12_configuration` write:

    FF 96 90 0F <target u16 LE> D1 EA     the panel's ordinary set
    FF 96 90 0F FF FF D3 FF               read-back

**Never D2** (signed delta on this selector family), and not `D1 FF` (a
periodic-assert form with no read-back).

**Why ask first.** The G12 relays 1FF95 only when 0x90 changes (it compares
against its last-relayed copy). A write of the value it already holds is
silent on 1FF95, so a blind first write could never be confirmed by the relay
and would count as a failure on every restart in the normal in-sync state.
The read-back is always answered (1.0 ms on the coach).

**Confirmation**, within 1 s of a read-back or a set:

- a report arrives after a read-back alone: success;
- a report (or a 1FF95) equal to the value set: success;
- a report or 1FF95 with a different value: failure. `g12_value` takes the
  reported value; a 1FF95 in this window is **not written to the inverter**;
- nothing arrives: failure, and `g12_value` becomes unknown so the next round
  asks before writing.

Three failures in a row turn the sync off until restart or floorplan reload,
with an error in the log; a success resets the count. This bounds the damage
if a write were ever applied as a delta, and covers an absent G12. A real
press that lands inside the 1 s window after a set is dropped and the panel
reverts.

A report never writes the inverter; only a 1FF95 is a press.

**Unsolicited reports restart the settle timer.** A panel press writes the
G12 and reads it back; the G12's report arrives ~2 ms later and the 1FF95
relay only on its next tick (2-10 ms). A report nobody here asked for
therefore means a press is in progress, and pushing in that gap would put the
inverter's old value back over the press and then refuse the relay as a
mismatch. The relay lands inside the settle and is handled as a press. If no
relay follows and the values really differ, the normal push happens when the
settle expires.

**Dispatch.** `g12_configuration` used to claim every 15FCE from the G12. It
now returns `False` for selector 0x90 so the report reaches the virtual
inverter, which claims it only when the sync is on and the sender matches.

Why the settle timer: two quick presses (30→25→20) produce two writes, and
modbus2mqtt reports 25 before 20. Without the wait, the 25 would be pushed back
over the G12's 20 and the panel would bounce. With it, by the time the timer
expires `state` is 20 and equals `g12_value`, so nothing is sent. A normal
single press therefore causes no push at all.

If the inverter refuses a write, `state` stays put, the timer expires, and the
old value is pushed back to the G12 so the panel shows the truth again.

### Status out (1FF96)

Added to the per-interval frame set when either field is mapped and has a
value, from the entity's source address:

    <charger_config_2_instance> <rate> FF <amps> FF FF FF FF

- `amps` (byte 3): shore breaker size, modbus state rounded to whole amps. The
  panel draws this byte raw.
- `rate` (byte 1): `round(min(charge_current_limit / charger_rated_current, 1) * 200)`,
  RV-C 0.5 %/bit, so 200 = 100 %. The panel halves it for CHARGE RATE.
- Whichever of the two is unmapped or not yet received is sent as 0xFF. No
  frame at all while both are unknown.

Both values are modbus state, not the last command, so the panel shows what the
inverter holds. modbus2mqtt publishes the new state right after a successful
write, so the readback follows within one interval.

### Echo

Our own 1FF96 is claimed by name + `charger_config_2_instance` + our source
address, ahead of the instance guard (its instance may not be ours). 1FF95 is
never transmitted by this entity, so it needs no echo entry.

### MQTT / Home Assistant

`<status_topic>/shore_breaker_size` and `<status_topic>/charge_current_limit`
(A), each with a read-only sensor, through the existing numeric mirror table.

### Tests

Decode-round-trip of the 1FF96 frame; press writes `250` for 25 A; 0xFF
ignored; clamp low/high; no write when equal to target; no write when state
unknown; inverter at 32 A with relay of 30 → no write; unmapped → not claimed
and no frame; wrong instance → not claimed; echo claimed only from our source;
no 1FF96 before the first state value. Sync: push on first state; push on state
change after settle; no push after a single press; two quick presses → no push;
refused write → old value pushed back; sync off → no 1FED9 ever; exact frame
bytes (`D1 EA`); relay confirms a push; unconfirmed push retried; mismatched
relay inside the window not written to the inverter; three failures latch the
sync off; 1FF95 with byte 3 = 0xFF leaves `g12_value` alone. Charge rate: 20 A
of 40 → byte 1 = 100; over rated caps at 200; only one field known → other byte
0xFF; mapped without `charger_rated_current` → error.

## Who owns the setting

The inverter. The first design had the panel own it; the owner reversed that.
The G12 powers up before the Pi at system boot, so its boot replay of 1FF95
normally reaches nobody.

## Risks and open items

- **Panel source filter.** None: the panel matches 1FF96 on DGN only (firmware
  session, from code; two publishers of 1FFC6 were seen last-frame-wins). SA
  0x42 is fine.
- **G12 cell 0x84.** Sending 1FF96 at instance 1 or 2 hits G12 rule t61 #6,
  which copies byte 1 into cell 0x84, and nobody knows what the cell does.
  Byte 1 now carries a real value, so deploy with
  `charger_config_2_instance: 3`. That the panel accepts any instance is read
  from code, not seen on the wire.
- **Deployed floorplan** (checked live 2026-11-17 by the firmware session):
  instance 1, no `source_id` override, frames seen from SA 0x42.
- **0x90 absolute write: verified on the coach 2026-11-17** (firefly-firmware
  `captures/sel90-d1-test-2026-11-17.log`). `FF96900F0F00D1EA` with 0x90 at 30
  gave the relay `19FF959C#01FFFF0FFFFFFFFF` after 5.9 ms and a read-back of
  15. Absolute, not delta. The test frame was sent from SA 0x42; the entity
  sends from the bridge address, which the G12 has accepted from other nodes
  but which was not the address used in this test.
- **G12 reboot with a stale value.** Pushes are confirmed, so the G12 normally
  holds the inverter's value. If the sync is off or has latched off and the
  G12 later reboots while the Pi is up, its replay of a stale value looks like
  a panel press and is written to the inverter.
- **Press while modbus is offline is dropped**, then corrected on the panel
  when state returns (with the sync on).
- **Inverter range above 30 A unknown.** Nothing local documents register
  57884's limits. The design is safe either way.
- **Step size.** jayco.csv says step 5; the handler clamps but does not round to
  5 A. The G12 only moves in ±5 from a 5..30 range, so this only matters for
  other senders.
- **Bus tests** change a real inverter setting once this is deployed and
  mapped. Owner's call each time.
