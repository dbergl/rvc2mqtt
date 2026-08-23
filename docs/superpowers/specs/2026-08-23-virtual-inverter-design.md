# Virtual Inverter — design

**Date:** 2026-08-23
**Status:** approved in brainstorming, awaiting implementation plan

## Problem

Lithium-model coaches (Jayco Swift Li, Entegra Ethos Li, Terrain, Launch) have a
Renogy/SRNE inverter-charger that speaks Modbus RTU only. The coach's RV-C
touchscreen/panel expects an RV-C inverter at **instance 1**, so today the
panel cannot show or switch the inverter. `modbus2mqtt` already exposes the
inverter on MQTT (`modbus/inverter/state/*`, `modbus/inverter/set/*`).

Goal: make the Renogy inverter appear on the RV-C bus as a normal inverter node
(status, AC/DC readings, on/off control) without adding CAN support to
`modbus2mqtt`.

## Decisions (from brainstorming)

- Bridge lives in **rvc2mqtt** as a new entity plugin. `modbus2mqtt` is untouched.
- The virtual inverter **reuses instance 1**. Generator-model coaches have a real
  RV-C `12v-inverter` at instance 1; Lithium coaches have none. A coach never
  has both, so the Lithium override floorplan replaces the `INVERTER_STATUS`
  entry with a `VIRTUAL_INVERTER` entry.
- Consumers on the bus need **on/off + status + AC/DC readings**: emit
  `INVERTER_STATUS`, `INVERTER_AC_STATUS_1` (input and output), `INVERTER_DC_STATUS`.
- MQTT source topics are a **configurable map in the floorplan entry** with
  defaults matching `jayco.csv`. Unmapped fields transmit RV-C "data not
  available".
- The entity also **mirrors to `rvc/state/inverter/*`** and honours
  `rvc/set/inverter/enable`, the same contract as the real inverter entity, so
  dashboards are model-agnostic.
- Periodic transmit is driven by a new **`tick()` hook** called from the app
  main loop (no threads).
- Docker: no compose changes. rvc2mqtt already runs `network_mode: host` and
  owns `can_rvc`; modbus2mqtt stays on the bridge network.

## Architecture

```
modbus/inverter/state/*  ──MQTT──▶ VirtualInverter (rvc2mqtt entity, instance 1)
rvc/set/inverter/enable  ──MQTT──▶     │
                                       ├─ tick() every `interval` ──▶ send_queue ──▶ can_rvc
INVERTER_COMMAND (panel) ◀──RV-C───────┤
                                       ├──▶ modbus/inverter/set/onoff   (MQTT)
                                       └──▶ rvc/state/inverter/*        (MQTT mirror, retained)
```

rvc2mqtt remains **one RV-C node**. Frames are sent with rvc2mqtt's existing
default source address `0x82` unless the entry overrides `source_id`. No
address-claim work in this change.

## Floorplan entry

```yaml
- name: VIRTUAL_INVERTER
  type: virtual_inverter
  instance: 1
  instance_name: renogy
  status_topic: rvc/state/inverter        # mirror base (same as real entity)
  command_topic: rvc/set/inverter         # entity subscribes to <base>/enable
  source_topic_base: modbus/inverter      # default
  interval: 1.0                           # seconds between frame sets, default 1.0
  stale_timeout: 30.0                     # seconds, default 30.0
  source_id: "82"                         # hex, default = RVC_Decoder.DEFAULT_SOURCE_ID
  fields:                                 # every key optional; defaults shown
    status:           {topic: state/status}
    enabled:          {topic: state/onoff}
    fault:            {topic: state/fault}
    ac_in_voltage:    {topic: state/AC_Input_Voltage, scale: 0.1}
    ac_out_voltage:   ~
    ac_out_current:   ~
    ac_out_frequency: ~
    dc_voltage:       ~
    dc_current:       ~
```

- A field value may be a string (topic, scale 1.0) or a mapping
  `{topic: <relative or absolute>, scale: <float>}`.
- Topic join rule: **if the value already starts with `source_topic_base + "/"`
  it is used verbatim; otherwise it is joined as `source_topic_base/<value>`**.
- `~`/null/omitted → field never populated → encoded as "not available".
- `scale` multiplies the parsed numeric payload before use (CSV templates
  apply `/10` only for HA display; raw MQTT payloads are unscaled).
- Unknown key under `fields:` → `ValueError` at construction (surfaces through
  `entity_factory` as an "Unsupported entry" error).
- `interval` and `stale_timeout` must be `> 0`.

The entity also subscribes to `<source_topic_base>/connected`
(`online`/`offline`, published by modbus2mqtt).

## Components

### `EntityPluginBaseClass.tick(now: float)` — new hook

Optional, default no-op. `app.py` main loop calls `entity.tick(time.monotonic())`
for every entity once per iteration, after `message_rx_loop()` and before
`message_tx_loop()`. `_do_reload()` needs no change: the replaced entity list
is what gets ticked.

### `rvc2mqtt/rvc_encode.py` — three helpers

Inverse of `RVC_Decoder._convert_unit` for `uint16`:

| helper | formula | None → |
|---|---|---|
| `encode_voltage_u16(v)` | `round(v / 0.05)` | `0xFFFF` |
| `encode_current_u16(a)` | `round((a + 1600) / 0.05)` | `0xFFFF` |
| `encode_frequency_u16(hz)` | `round(hz * 128)` | `0xFFFF` |

Results are clamped to `0..0xFFFE`. Little-endian byte order (RV-C). Nothing
else goes in this module now; it is the seed for a future generic encoder.

### `rvc2mqtt/entity/virtual_inverter.py` — `VirtualInverter`

`FACTORY_MATCH_ATTRIBUTES = {"name": "VIRTUAL_INVERTER", "type": "virtual_inverter"}`
`id = "virtual-inverter-1FFD4-i<instance>"`

**State** (written by MQTT callbacks on the paho thread, read by `tick()` on
the main thread; single-item dict assignment is atomic in CPython and each
frame reads each value once, so no lock):

- `status: int | None` (SRNE code), `enabled: bool | None`, `fault: bool | None`
- numeric fields: `float | None` each
- `connected: bool` (default `True` until an `offline` is seen)
- `last_status_update: float` (monotonic; set whenever `status` or `enabled`
  arrives)
- `next_tx: float`

**MQTT inputs**: parse `status` as `int`, `enabled`/`fault` as `0/1`/`true/false`
(case-insensitive), numerics as `float` × `scale`. Parse failure → warning,
state unchanged.

**Modbus → RV-C status mapping** (`INVERTER_STATUS` byte 1):

| SRNE code | meaning | RV-C `status` |
|---|---|---|
| 4 | Mains powered operation | 2 `ac passthru` |
| 5 | Inverter powered operation | 1 `invert` |
| 3, 6, 7 | Soft start, Inverter→mains, Mains→inverter | 5 `waiting to invert` |
| 0, 1, 2, 10 | Power-up delay, Waiting, Initialization, Shutdown | 0 `disabled` |
| 11 | Fault | 0 `disabled` |
| other / `None` | unknown | 0 `disabled` (warn once per distinct code) |

If `fault` is `True` the RV-C status is forced to 0.

`INVERTER_STATUS` (DGN `1FFD4`) bytes:
- 0: instance
- 1: status per table
- 2: bits 0-1 battery temp sensor `11` (n/a); bits 2-3 load sense `11`;
  bits 4-5 inverter enabled `01`/`00` from `enabled` (`11` if `None`);
  bits 6-7 pass-through `01` when status is passthru else `00`
- 3: bits 0-1 generator support `11`; rest `1`
- 4-7: `0xFF`

`INVERTER_AC_STATUS_1` (DGN `1FFD7`), sent twice per tick:
- byte 0: `instance & 0x0F | line(00) << 4 | io << 6` with io `00` input / `01` output
- bytes 1-2 rms voltage, 3-4 rms current, 5-6 frequency (`encode_*`)
- byte 7: `0xFF` (faults n/a)
- input frame uses `ac_in_voltage` only (current/frequency n/a)
- output frame uses `ac_out_voltage`, `ac_out_current`, `ac_out_frequency`
- a frame whose three values are all `None` is still sent (panel sees the
  instance exists) — only stale/offline suppresses frames.

`INVERTER_DC_STATUS` (DGN `1FEE8`): byte 0 instance, 1-2 `dc_voltage`,
3-4 `dc_current`, 5-7 `0xFF`.

**`tick(now)`**: if `now < next_tx` return. Set `next_tx = now + interval`.
If `not connected` or `now - last_status_update > stale_timeout` return
(logging the transition into/out of silence at info level once). Otherwise
put the four frames on `send_queue` as `{"dgn", "data", "source_id"}` dicts
(the existing tx contract; `app.py` fills `arbitration_id`).

**`process_rvc_msg(msg)`**: match `{"name": "INVERTER_COMMAND", "instance": N}`.
`inverter_enable` `"01"` → publish `"1"`, `"00"` → `"0"` to
`<source_topic_base>/set/onoff` (qos 0, not retained). `"11"`/`"10"` → no
publish. Other bits logged at debug. Return `True`. Also match
`INVERTER_STATUS`/`INVERTER_AC_STATUS_1`/`INVERTER_DC_STATUS` for this
instance and return `True` without acting, so a stray frame (our own echo
via another local socket, or a misconfigured real node at the same instance)
is logged at debug rather than landing in `unhandled_rvc`. Everything else →
`False`.

**`process_mqtt_msg(topic, payload)`** for `<command_topic>/enable`:
accepts `on/off/1/0/true/false` → publish to `set/onoff` as above.

**Mirror** (`<status_topic>/…`, retained, publish on change only), names
matching `entity/inverter.py`: `status` (RV-C code), `status_definition`,
`enabled` (`on`/`off`), `fault` (`on`/`off`), `line1/input/rms_voltage`,
`line1/output/rms_voltage`, `line1/output/rms_current`,
`line1/output/frequency`, `dc_voltage`, `dc_amperage`. Unmapped fields are
never published.

**HA discovery** (`publish_ha_discovery_config`): one device with a status
sensor (enum), enable switch (`command_topic` = `<command_topic>/enable`),
fault binary sensor, and one sensor per mapped numeric field. `unique_id`
derived from `unique_device_id`; availability from
`get_availability_discovery_info_for_ha()`.

**Coexistence guard**: `app.py`, after building `entity_list`, logs an error
if a `VirtualInverter` and an `InverterCharger_INVERTER_STATUS` share an
instance. Both stay loaded (the user may be mid-migration), but the log makes
the topic collision obvious.

## Lifecycle

- `initialize()`: `next_tx = 0`, `last_status_update = -inf`, so the first
  tick sends nothing until modbus2mqtt has published a status.
- `teardown()`: base behaviour only; no timers or threads to stop.
- Floorplan reload: existing path unsubscribes and rebuilds entities.

## Testing (`test/virtual_inverter_test.py`)

Follow `test/generator_test.py`: `MagicMock()` for `MQTT_Support`, capture
`register` callbacks, real `queue.Queue` as `send_queue`, decode emitted
frames with `RVC_Decoder` + `rvc-spec.yml` to assert fields.

1. Encoders: V/A/Hz round-trip through `_convert_unit` for 0, typical, max;
   `None → 0xFFFF`; clamping.
2. Status mapping: every SRNE code in the table; `fault=True` forces 0;
   unknown code warns once.
3. Cadence: fake `now` — no frames before `interval`, one set at/after,
   nothing while `connected=False` or stale; resumes after fresh status.
4. Frame content: decode `INVERTER_STATUS`, both `INVERTER_AC_STATUS_1`,
   `INVERTER_DC_STATUS`; assert instance, line/io, status, enable bits,
   voltages, n/a for unmapped.
5. Command path: `INVERTER_COMMAND` `01`/`00`/`11` → `"1"`/`"0"`/none on
   `modbus/inverter/set/onoff`; other instance → `False`;
   `rvc/set/inverter/enable` `on`/`off` → same publishes.
6. MQTT inputs: bad payloads leave state unchanged; `scale` applied;
   absolute vs relative topic join; unknown field key raises `ValueError`;
   non-positive `interval` raises.
7. Mirror: changed values publish retained once; unchanged do not republish.
8. `app.py`: `tick` hook invoked per loop iteration (small test with a stub
   entity), and the coexistence warning fires.

## Docs

- `docs/configuration.md`: new "Virtual inverter" section — entry schema,
  field table with defaults, SRNE→RV-C mapping, stale/offline behaviour.
- coach2mqtt: add the `VIRTUAL_INVERTER` override example and a note in the
  topics doc that on Lithium coaches `rvc/state/inverter/*` is fed from
  Modbus (separate repo; tracked as a follow-up, not part of this plan).

## Out of scope

- RV-C address claim / dedicated source address.
- Generic spec-driven `rvc_encode()`.
- New Modbus registers in `jayco.csv` (user adds from the SRNE register doc;
  the `fields:` map absorbs them without code changes).
- `INVERTER_AC_STATUS_2..4`, `INVERTER_TEMPERATURE_STATUS`, load-sense and
  pass-through commands.
