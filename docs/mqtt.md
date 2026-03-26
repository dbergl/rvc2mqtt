# MQTT 

This details the usage of the MQTT protocol for information, status and command sharing.

MQTT is infinitely flexible so this is intended to provide insight into usage by the rvc2mqtt project. 

## Config and requirements

This project does not provide an MQTT broker.

This project requires a network connection to an existing broker
and credentials that allow publish/subscribe privileges to at least the rvc
base topic. 

This schema can support multiple rvc2mqtt bridges
using the client-id to provide an isolated namespace.  Please make sure this is unique if you
have more than one bridge 

Setting the config for MQTT can be done as command line parameters or thru environment variables.  For Docker env is suggested.

## Topic hierarchy

rvc2mqtt uses the following topic hierarchy.
Information about the bridge device (this device)
is located at here:
`rvc2mqtt/<client-id>`  

More specifically:
`rvc2mqtt/<client-id>/state`       - this reports the connected state of our bridge to the mqtt broker (`online` or `offline`)
`rvc2mqtt/<client-id>/info`  - contains json defined metadata about this bridge and the rvc2mqtt software

Devices managed by rvc2mqtt are listed by their unique device id
`rvc2mqtt/<client-id>/d/<device-id>`

### Light Switch

The Light Switch object is used to describe an switch.
A light can have on / off

| Topic             | rvc2mqtt operation | Description                     |
|---                | :---:              | ---                             |
|`<device-id>/state`| publish            | status of light (`on` or `off`) |
|`<device-id>/cmd`  | subscribe          | command the light with payload `on` or `off` |



### Temperature Sensor

A very simple RVC device that reports temperature in C
This sensor has no configuration and will just have a state value in C
It does not subscribe to any topics
It only updates the mqtt topic when the temperature changes.

| Topic                         | rvc2mqtt operation | Description                     |
|---                            | :---:              | ---                             |
|`<device-id>/state`            | publish            | temperature in C |


### HVAC — Elwell Timberline 1.5 (`hvac` / `TIMBERLINE_CONTROLLER`)

The Timberline entity consolidates water heater, circulation pump, furnace fan, and
thermostat functions into a single device.  All topics are relative to the
`status_topic` / `command_topic` set in the floorplan entry.

**Status topics** (published by rvc2mqtt, retained):

| Sub-topic | Description |
|-----------|-------------|
| `/heatsource` | Active heat source (integer) |
| `/heatsource_definition` | Heat source as text |
| `/heat_exchanger_temperature` | Water temperature (°C) |
| `/heat_exchanger_temperaturef` | Water temperature (°F) |
| `/burner_status` | Burner state (integer) |
| `/burner_status_definition` | Burner state as text |
| `/ac_element_status` | AC element state (integer) |
| `/ac_element_status_definition` | AC element state as text |
| `/failure_to_ignite_status` | Ignition failure flag |
| `/failure_to_ignite_status_definition` | Ignition failure as text |
| `/hot_water_priority` | Hot water priority flag |
| `/hot_water_priority_definition` | Hot water priority as text |
| `/pump_status` | Circulation pump state (integer) |
| `/pump_status_definition` | Circulation pump state as text |
| `/fan_mode` | Furnace fan mode (integer) |
| `/fan_mode_definition` | Furnace fan mode as text |
| `/fan_speed` | Furnace fan speed |
| `/fan_manual_speed` | Manual fan speed setting |
| `/mode` | Thermostat operating mode (integer) |
| `/mode_definition` | Thermostat operating mode as text |
| `/schedule/schedule_mode` | Schedule mode (integer) |
| `/schedule/schedule_mode_definition` | Schedule mode as text |
| `/set_point_temperature` | Thermostat setpoint (°C) |
| `/set_point_temperaturef` | Thermostat setpoint (°F) |
| `/current_schedule_instance` | Active schedule — `0`=sleep, `1`=wake |
| `/current_schedule_instance_definition` | Active schedule as text |
| `/schedule/sleep/start_time` | Sleep schedule start time |
| `/schedule/sleep/set_point_temperature` | Sleep setpoint (°C) |
| `/schedule/sleep/set_point_temperaturef` | Sleep setpoint (°F) |
| `/schedule/wake/start_time` | Wake schedule start time |
| `/schedule/wake/set_point_temperature` | Wake setpoint (°C) |
| `/schedule/wake/set_point_temperaturef` | Wake setpoint (°F) |
| `/solenoid` | Solenoid state (integer) |
| `/solenoid_definition` | Solenoid state as text |
| `/temperature_sensor` | Selected temperature sensor (integer) |
| `/temperature_sensor_definition` | Temperature sensor as text |
| `/tank_temperature` | Tank temperature (°C) |
| `/tank_temperaturef` | Tank temperature (°F) |
| `/heater_temperature` | Heater temperature (°C) |
| `/heater_temperaturef` | Heater temperature (°F) |
| `/timers/system` | System run timer (minutes) |
| `/timers/water_priority` | Domestic water priority timer |
| `/timers/pump_override` | Pump override timer |
| `/info/heater/minutes` | Total heater run time (minutes) |
| `/info/heater/version` | Heater firmware version |
| `/info/panel/minutes` | Panel run time (minutes) |
| `/info/panel/version` | Panel firmware version |
| `/info/hcu/version` | HCU firmware version |
| `/info/system_limit` | System run-time limit |
| `/info/water_limit` | Water priority run-time limit |
| `/fault/code` | DM_RV fault code |
| `/fault/description` | DM_RV fault description |
| `/fault/lamp` | DM_RV lamp state |

**Command topics** (subscribed by rvc2mqtt):

| Sub-topic | Description |
|-----------|-------------|
| `/heatsource` | Set heat source |
| `/pump_test` | Trigger pump test |
| `/fan_mode` | Set furnace fan mode |
| `/fan_speed` | Set furnace fan speed |
| `/mode` | Set thermostat operating mode |
| `/schedule/schedule_mode` | Set schedule mode |
| `/set_point_temperature` | Set thermostat setpoint (°C) |
| `/set_point_temperaturef` | Set thermostat setpoint (°F) |
| `/schedule/sleep/start_time` | Set sleep schedule start time |
| `/schedule/sleep/set_point_temperature` | Set sleep setpoint (°C) |
| `/schedule/sleep/set_point_temperaturef` | Set sleep setpoint (°F) |
| `/schedule/wake/start_time` | Set wake schedule start time |
| `/schedule/wake/set_point_temperature` | Set wake setpoint (°C) |
| `/schedule/wake/set_point_temperaturef` | Set wake setpoint (°F) |
| `/clear_errors` | Clear controller errors |
| `/hot_water_priority` | Set hot water priority |
| `/temperature_sensor` | Select temperature sensor |
| `/timers/system_limit` | Set system run-time limit |
| `/timers/water_limit` | Set water priority run-time limit |

**Floorplan entry example:**

```yaml
floorplan:
  - name: TIMBERLINE_CONTROLLER
    type: hvac
    instance: 1
    source_id: 'A0'
    instance_name: Timberline Controller
    status_topic: rvc/state/timberline
    command_topic: rvc/set/timberline
```

## Home Assistant Integration

Home assistant has created mqtt auto-discovery.  This describes how rvc2mqtt integrates
with mqtt auto-discovery.


follows path like: `<discovery_prefix>/<component>/<unique_device_id>/<entity_id>/config`

`homeassistant` is the discovery prefix  
`component` is one of the home assistant component types  
`unique_device_id` is the sensors unique id.  This will be a concatination that includes the rvc2mqtt_client-id_object  
`entity_id` is the entity id within the device

config payload is json that matches HA config (at least all required)

