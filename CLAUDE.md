# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

`rvc2mqtt` is a bidirectional bridge between an RV's CAN bus (using the RV-C protocol) and an MQTT broker, enabling smart home integration (primarily Home Assistant) for RV devices.

## Development Setup

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
pip install -r requirements.dev.txt
```

## Commands

**Run tests:**
```bash
pytest -v --html=pytest_report.html --self-contained-html --cov=rvc2mqtt --cov-report html:cov_html
```

**Run a single test file:**
```bash
pytest test/light_switch_test.py -v
```

**Run the application:**
```bash
python3 -m rvc2mqtt.app
```

**Virtual CAN for local testing (no hardware):**
```bash
sudo ip link add dev vcan0 type vcan
sudo ip link set vcan0 up
python3 -m rvc2mqtt.app -i vcan0
```

## Configuration

The app is configured via environment variables or CLI flags:

| Variable | Default | Purpose |
|----------|---------|---------|
| `CAN_INTERFACE_NAME` | `can0` | CAN interface name |
| `FLOORPLAN_FILE_1` | — | Primary floorplan YAML path |
| `FLOORPLAN_FILE_2` | — | Optional secondary floorplan YAML path |
| `MQTT_HOST` | — | MQTT broker hostname |
| `MQTT_PORT` | `1883` | MQTT broker port |
| `MQTT_USERNAME` / `MQTT_PASSWORD` | — | MQTT credentials |
| `MQTT_TOPIC_BASE` | `rvc2mqtt` | Root MQTT topic |
| `MQTT_CLIENT_ID` | `bridge` | MQTT client ID |
| `MQTT_CA` / `MQTT_CERT` / `MQTT_KEY` | — | TLS files |
| `LOG_CONFIG_FILE` | — | Python logging config YAML |

**Floorplan files** (YAML) map RVC DGNs to entities:
```yaml
floorplan:
  - name: DC_LOAD_STATUS
    instance: 1
    type: light_switch
    instance_name: "Bedroom Light"
```

## Architecture

```
RV CAN Bus
    ↕ (python-can, socketcan)
CAN_Watcher thread  [can_support.py]
    ↕ (rx_queue / tx_queue)
app.py main loop
    ↕
RVC decoder  [rvc.py]  ←  rvc-spec.yml (DGN definitions)
    ↕
Entity instances  [entity/*.py]  ← loaded via plugin system
    ↕
MQTT_Support  [mqtt.py]  (paho-mqtt, HA auto-discovery)
    ↕
MQTT Broker → Home Assistant
```

### Key Components

- **`app.py`** — Orchestrates everything. Runs a tight 1ms poll loop processing RX/TX queues. Reads config, loads plugins, connects MQTT.
- **`rvc.py`** — Decodes CAN frames to RVC dicts and encodes back. Loads `rvc-spec.yml` for DGN definitions. DGNs are 5-digit hex identifiers.
- **`can_support.py`** — Background thread wrapping python-can's socketcan interface with RX/TX queues.
- **`mqtt.py`** — paho-mqtt wrapper with Home Assistant auto-discovery support. Topic pattern: `rvc2mqtt/<client_id>/d/<device_id>/<field>/state|set`.
- **`plugin_support.py` + `entity_factory_support.py`** — Plugin loader scans for `EntityPluginBaseClass` subclasses in `rvc2mqtt/entity/` and optional extra paths. Factory matches floorplan entries to entity classes via `FACTORY_MATCH_ATTRIBUTES`.
- **`entity/__init__.py`** — `EntityPluginBaseClass` base class all entities inherit.
- **`entity/*.py`** — One file per device type (lights, HVAC, generator, inverter, solar controller, tanks, thermostats, water heater/pump, etc.).

### Adding a New Entity

1. Create `rvc2mqtt/entity/my_device.py` subclassing `EntityPluginBaseClass`
2. Set `FACTORY_MATCH_ATTRIBUTES` dict with `name` (DGN) and `type` fields
3. Implement `process_rvc_msg(msg)` for incoming CAN messages
4. Implement `initialize()` to register MQTT topics
5. Add corresponding test in `test/my_device_test.py`

### Publishing from an Entity

Always publish via `self.publish(...)` from `EntityPluginBaseClass`. Never call
`self.mqtt_support.client.publish(...)` from an entity — a test enforces this
(`test/entity_publish_test.py::TestNoReachThrough`).

```python
self.publish(topic, payload, retain=True, force=None, key=None,
             value=_UNSET, deadband=None, properties=None) -> bool
```

It publishes **only when the value changed**, and returns whether it did.

- Don't write your own `if new != self.x:` guard — that's what this replaces.
  Keep a mirror attribute only when something else genuinely reads it, via
  `if self.publish(t, v): self.x = v`.
- **`retain=False` implies `force=True`.** HA discovery configs and RPC-style
  responses therefore keep re-firing on every boot, floorplan reload and HA
  birth message with no extra thought. The reload stale-detection in `app.py`
  depends on this.
- `force=True` publishes regardless, and still records the value so the next
  un-forced publish of it is suppressed. Use it for an optimistic echo of a
  received MQTT command.
- `publish_forget(key)` drops a cached value so the next publish goes out —
  for when something outside our view invalidated the broker's retained copy.
- `value=` gates on something other than the payload: a raw RVC field while
  publishing its `.title()`'d definition string, or a number while publishing
  JSON.
- `deadband=` is a numeric tolerance, measured from the last *published* value
  so a slow drift still eventually reports. Use it for noisy analog readings.
- `value_changed(key, value)` is the underlying primitive. Reach for it when one
  change signature must gate a group of publishes that move as a unit — e.g.
  `diagnostic.py`, where two topics carry the whole decoded frame and so differ
  on every message.
- `note_published(key, value)` records a value without sending, for seeding the
  cache from a retained value the broker hands back on startup (see
  `dimmer_switch.py`).

A first value of `0`, `False`, `""` or `None` always publishes — presence in the
cache decides, not truthiness. Don't reintroduce sentinel init values like
`self.level = 999999` to work around a first-reading problem.

Set `RVC2MQTT_PUBLISH_ALWAYS=1` to disable all gating and restore the un-gated
firehose, for A/B comparison against a live rig.

Entity tests must stub `make_device_topic_string` with a `side_effect` returning
a **distinct topic per field**. A single `return_value` collapses every topic to
one string, which silently merges unrelated fields onto one cache key.

### RVC Spec (`rvc-spec.yml`)

DGN entries define how to decode CAN payloads:
```yaml
1FFBD:
  name: DC_LOAD_STATUS
  parameters:
    - byte: 0
      name: "Operating Status"
      type: uint8
      unit: pct
      values:
        0: "Off"
        100: "On"
```

Units include: `pct`, `deg c`, `v` (volts), `a` (amps), `hz`, `sec`, `bitmap`, `hex`.

Some DGNs use `usefirstbyte: true`, meaning the first byte of the payload selects a message sub-type and is decoded as `message_type`.

### Floorplan Advanced Options

Entities can filter by CAN source node using `source_id` (hex string), override MQTT topics with `status_topic` / `command_topic`, and cross-reference other entities via `link_id` / `entity_links`.

```yaml
floorplan:
  - name: G12
    type: g12_configuration
    source_id: '9C'
    instance_name: "Generator Controller"
    status_topic: "rvc/g12/config"
    command_topic: "rvc/g12/set"
```

### Dev Tools (`tools/`)

- **`rvc_decode.py`** — Decode a raw DGN + hex payload from the command line: `python3 tools/rvc_decode.py 1FFBD FF00FF00FF00FF00`
- **`can_monitor.py`** — Live TUI monitor for a single CAN arbitration ID; highlights byte changes, useful for reverse-engineering unknown DGNs: `python3 tools/can_monitor.py --interface can_rvc --can-id 0x195FCE9C`
- **`rvc_reverse.py`** — Additional reverse-engineering helper
