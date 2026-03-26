# Configuration

There are three different files used for configuration.  These are in yaml format (json is valid yaml).  

## Floor plan 1 or 2

These two files are both optional but without some floor plan nodes this software doesn't do anything.  These files contain a `floorplan` node and then have subnodes with the different devices in your RV.  A device should only be defined in one floor plan file. The main reason to allow for
two input files is to easily support a "HA addon" where a main file might exist and then user entered
text from the WebUI might be written to floor plan 2.

### Common floorplan entry fields

| Field | Required | Description |
|-------|----------|-------------|
| `name` | yes | RV-C DGN name (e.g. `DC_LOAD_STATUS`) |
| `type` | yes | Entity type used to select the plugin (e.g. `light_switch`) |
| `instance` | yes* | RV-C instance number. Some entities omit this if the DGN has no instance field |
| `instance_name` | yes | Human-readable label shown in Home Assistant |
| `status_topic` | no | Override the default MQTT state topic |
| `command_topic` | no | Override the default MQTT command/set topic base |
| `source_id` | no | Hex string — only process CAN frames from this source node |
| `link_id` / `entity_links` | no | Cross-reference another entity by its `link_id` |

### G12 tank level sensor (`g12_tank_level`)

Reads raw sensor counts broadcast by the Firefly G12 controller (`G12_TANK_LEVEL_SENSOR` DGN).

| Field | Required | Description |
|-------|----------|-------------|
| `minimum_change` | no | Minimum raw count change before publishing (default: `1`) |
| `33_custom_threshold` | no* | Raw sensor count at which the tank is considered 33% full |
| `66_custom_threshold` | no* | Raw sensor count at which the tank is considered 66% full |
| `100_custom_threshold` | no* | Raw sensor count at which the tank is considered 100% full |

\* All three thresholds must be provided together.  When set, the entity publishes a
`custlvl` percentage topic (`0`, `1`, `33`, `66`, or `100`) in addition to the raw
sensor value.  It also publishes the threshold values themselves as retained topics and
exposes them as editable `number` entities in Home Assistant.

Threshold values sent via MQTT command topics are **persisted automatically** to the
floorplan override file so they survive container restarts and reloads.

**Threshold topics** (when `command_topic: rvc/set/tanks/fresh` is set):

| Topic | Direction | Description |
|-------|-----------|-------------|
| `{status_topic}/sensorlvl` | publish | Raw sensor count |
| `{status_topic}/custlvl` | publish | Calculated fill percentage |
| `{status_topic}/cust_threshold_33` | publish | Current 33% threshold value |
| `{status_topic}/cust_threshold_66` | publish | Current 66% threshold value |
| `{status_topic}/cust_threshold_100` | publish | Current 100% threshold value |
| `{command_topic}/cust_threshold_33` | subscribe | Set the 33% threshold |
| `{command_topic}/cust_threshold_66` | subscribe | Set the 66% threshold |
| `{command_topic}/cust_threshold_100` | subscribe | Set the 100% threshold |

#### Example

```yaml
floorplan:
  - name: G12_TANK_LEVEL
    instance: 1
    type: g12_tank_level
    instance_name: fresh water tank
    status_topic: rvc/state/tanks/fresh
    command_topic: rvc/set/tanks/fresh
    minimum_change: 100
    33_custom_threshold: 57400
    66_custom_threshold: 44400
    100_custom_threshold: 22000
```

### G12 controller (`g12_configuration`)

Monitors and controls the Firefly G12 controller (source_id `9C`).  Decodes
`G12_CONFIGURATION` messages (AES settings, voltages, quiet time, tank thresholds,
floorplan selection, etc.) and assembles product identification from multi-packet
transport messages.

`source_id` is required so that only frames from the G12 node are matched.
`command_topic` is optional — omit it if you only want to monitor.

**Status topics** (relative to `status_topic`):

| Sub-topic | Description |
|-----------|-------------|
| `/aes/enabled` | AES on/off |
| `/aes/max_engine_run_time` | Max generator run time (minutes) |
| `/aes/time_at_start_volts` | Time at start voltage (seconds) |
| `/aes/stop_at_voltage` | Stop voltage (V) |
| `/aes/time_at_stop_volts` | Time at stop voltage (seconds) |
| `/aes/quiet_time_start` | Quiet time start (HH:MM) |
| `/aes/quiet_time_stop` | Quiet time stop (HH:MM) |
| `/aes/start_at_voltage` | Start voltage (V) |
| `/ags/low_volts_trigger` | AGS low voltage trigger |
| `/ags/gen_start_retries` | AGS start retry count |
| `/ags/config_mode` | AGS configuration mode |
| `/ags/retry_interval` | AGS retry interval |
| `/tanks/threshold_33_pct` | Global 33% tank threshold |
| `/tanks/threshold_66_pct` | Global 66% tank threshold |
| `/tanks/threshold_100_pct` | Global 100% tank threshold |
| `/tanks/black_setting` | Black tank setting |
| `/gen/mode` | Generator AES mode |
| `/floorplan` | Selected floorplan number |
| `/batteries/count` | Number of batteries |
| `/go_power/controller_count` | Go Power controller count |
| `/inverter/progressive` | Progressive inverter setting |
| `/fans/bath` | Bath fan setting |
| `/lights/cargo_bath_ch25` | Cargo/bath light channel 25 |
| `/lights/bunk_accent` | Bunk accent light setting |
| `/engine/running` | Engine relay state (on/off) |
| `/fault/code` | DM_RV fault code |
| `/fault/description` | DM_RV fault description |
| `/fault/lamp` | DM_RV lamp state |
| `/product_id` | Product identification string |
| `/input/<n>/active` | G12 input n active state |

**Command topics** (relative to `command_topic`):

| Sub-topic | Description |
|-----------|-------------|
| `/aes/enabled` | Enable/disable AES (`on`/`off`) |
| `/aes/max_engine_run_time` | Set max engine run time |
| `/aes/time_at_start_volts` | Set time at start voltage |
| `/aes/stop_at_voltage` | Set stop voltage |
| `/aes/time_at_stop_volts` | Set time at stop voltage |
| `/aes/quiet_time_start` | Set quiet time start |
| `/aes/quiet_time_stop` | Set quiet time stop |
| `/aes/start_at_voltage` | Set start voltage |
| `/ags/low_volts_trigger` | Set AGS low voltage trigger |
| `/tanks/threshold_33_pct` | Set global 33% threshold |
| `/tanks/threshold_66_pct` | Set global 66% threshold |
| `/tanks/threshold_100_pct` | Set global 100% threshold |
| `/tanks/black_setting` | Set black tank setting |
| `/gen/mode` | Set generator AES mode |
| `/floorplan` | Set selected floorplan |
| `/batteries/count` | Set battery count |
| `/go_power/controller_count` | Set Go Power controller count |
| `/inverter/progressive` | Set progressive inverter |
| `/fans/bath` | Set bath fan |
| `/lights/cargo_bath_ch25` | Set cargo/bath light channel |
| `/lights/bunk_accent` | Set bunk accent light |
| `/ags/retry_interval` | Set AGS retry interval |
| `/engine/start` | Start/stop engine |

**Floorplan entry example:**

```yaml
floorplan:
  - name: G12
    type: g12_configuration
    source_id: '9C'
    instance_name: Generator Controller
    status_topic: rvc/state/g12
    command_topic: rvc/set/g12
```

### G12 DC system (`dc_system` / `DC_SOURCE_STATUS_G12`)

Reads voltage and current from the Firefly G12's proprietary `DC_SOURCE_STATUS_G12`
DGN (functionally equivalent to the standard `DC_SOURCE_STATUS_1`).

**Status topics:**

| Sub-topic | Description |
|-----------|-------------|
| `/voltage` | DC voltage (V, 2 decimal places) |
| `/current` | DC current (A) |

Both sensors are exposed as Home Assistant sensor entities with device class
`voltage` / `current`.

**Floorplan entry example:**

```yaml
floorplan:
  - name: DC_SOURCE_STATUS_G12
    type: dc_system
    instance: 1
    instance_name: G12 Battery
    status_topic: rvc/state/g12/battery
```

### Example

``` yaml

floorplan:
  - name: DC_LOAD_STATUS
    instance: 1
    type: light_switch
    instance_name: bedroom light

  - name: DC_LOAD_STATUS
    instance: 2
    type: light_switch
    instance_name: living room light

  - name: DC_LOAD_STATUS
    instance: 8
    type: light_switch
    instance_name: awning light

  - name: THERMOSTAT_AMBIENT_STATUS
    instance: 2
    type: temperature
    instance_name: bedroom temperature

  - name: TANK_STATUS
    instance: 0
    type: tank_level
    instance_name: fresh water tank

  - name: TANK_STATUS
    instance: 1
    type: tank_level
    instance_name: black waste tank

  - name: TANK_STATUS
    instance: 2
    type: tank_level
    instance_name: rear gray waste tank

  - name: TANK_STATUS
    instance: 18
    type: tank_level
    instance_name: galley gray waste tank

  - name: TANK_STATUS
    instance: 20
    type: tank_level
    instance_name: what tank is this 20

  - name: TANK_STATUS
    instance: 21
    type: tank_level
    instance_name: what tank is this 21

  - name: WATER_PUMP_STATUS
    type: water_pump
    instance_name: fresh water pump

  - name: WATERHEATER_STATUS
    type: waterheater
    instance: 1
    instance_name: main waterheater

  - name: DC_LOAD_STATUS
    type: tank_warmer
    instance: 34
    instance_name: waste tank heater

  - name: DC_LOAD_STATUS
    type: tank_warmer
    instance: 35
    instance_name: fresh water tank heater

```


## Floorplan override file

When `FLOORPLAN_FILE_1` is set, the app automatically checks for a companion override
file named `<basename>.override.<ext>` in the same directory (e.g.
`floorplan.yml` → `floorplan.override.yml`).  No extra configuration is needed.

The override file lets you customise the primary floorplan without editing it — useful
when the base file is shared or managed externally.  It uses an `overrides:` top-level
key (not `floorplan:`).

Overrides are matched by **`name` + `type` + `instance`** (all three; `instance`
defaults to `null` when omitted).  Only the fields you list are changed; all other
fields from the base entry are preserved.

The override file is re-read on every SIGHUP reload, so changes take effect without
restarting the container.

### Override operations

**Update fields** — list only the keys you want to change:

```yaml
overrides:
  - name: DC_LOAD_STATUS
    type: light_switch
    instance: 1
    instance_name: "Master Bedroom"   # only this field is changed
```

**Remove an entry** — add `_remove: true`:

```yaml
overrides:
  - name: DC_LOAD_STATUS
    type: light_switch
    instance: 3
    _remove: true
```

**Add a new entry** — include an entry that doesn't match anything in the base file;
it is appended:

```yaml
overrides:
  - name: TANK_STATUS
    type: tank_level
    instance: 5
    instance_name: "Gray Tank 2"
    status_topic: rvc/state/tanks/gray2
```

### Full example

```yaml
overrides:
  # Rename an existing light
  - name: DC_LOAD_STATUS
    type: light_switch
    instance: 1
    instance_name: "Master Bedroom"

  # Remove an entry that doesn't exist in this coach
  - name: SOLAR_CONTROLLER_STATUS
    type: solar
    instance: 1
    _remove: true

  # Override tank thresholds with coach-specific calibration values
  - name: G12_TANK_LEVEL
    type: g12_tank_level
    instance: 1
    command_topic: rvc/set/tanks/fresh
    33_custom_threshold: 57400
    66_custom_threshold: 44400
    100_custom_threshold: 22000
```

## Log Config File

This is optional and allows for complex logging to be setup.  If provided the yaml file needs to follow 
<https://docs.python.org/3/library/logging.config.html#logging-config-dictschema>

If not provided the app will do basic docker logging.


## Example

This example setups up 3 log files and a basic logger to console.  It assumes you have a volume mapped at 
`/config` of the container.  

`RVC2MQTT.log` is a basic INFO level logger for the app
`RVC_FULL_BUS_TRACE.log` will capture all rvc messages (in/out)  
`UNHANDLED_RVC.log` will capture all the rvc messages that are not handled by an object.

``` yaml
#
# Logging info
# See https://docs.python.org/3/library/logging.config.html#logging-config-dictschema
#
logger:
  version: 1
  handlers:
    debug_console_handler:
      level: INFO
      class: logging.StreamHandler
      formatter: brief
      stream: ext://sys.stdout

    debug_file_handler:
      class : logging.handlers.RotatingFileHandler
      formatter: default
      maxBytes: 10485760   #10 mb
      backupCount: 1
      level: INFO
      filename: /config/RVC2MQTT.log
      mode: w

    unhandled_file_handler:
      class : logging.handlers.RotatingFileHandler
      formatter: trace
      maxBytes: 10485760   #10 mb
      backupCount: 1
      level: DEBUG
      filename: /config/UNHANDLED_RVC.log

    rvc_bus_trace_handler:
      class : logging.handlers.RotatingFileHandler
      formatter: trace
      filename: /config/RVC_FULL_BUS_TRACE.log
      maxBytes: 10485760   #10 mb
      backupCount: 3
      level: DEBUG

  loggers:
    "": # root logger
      handlers:
        - debug_console_handler
        - debug_file_handler
      level: DEBUG
      propagate: False

    "unhandled_rvc": # unhandled messages
      handlers:
        - unhandled_file_handler
      level: DEBUG
      propagate: False

    "rvc_bus_trace": # all bus messages
      handlers:
        - rvc_bus_trace_handler
      level: DEBUG
      propagate: False

  formatters:
    brief:
      format: "%(message)s"
    default:
      format: "%(asctime)s %(levelname)-8s %(name)-15s %(message)s"
      datefmt: "%Y-%m-%d %H:%M:%S"
    trace:
      format: "%(asctime)s %(message)s"
      datefmt: "%Y-%m-%d %H:%M:%S"


```
