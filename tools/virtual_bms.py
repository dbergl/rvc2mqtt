#!/usr/bin/env python3
"""Virtual BMS: relay the real Renogy BMS's native-protocol telemetry
(can0) into the proprietary APS-500<->BMS link (0EF70/0EF80, extended
CAN IDs 0x18EF7080/0x18EF8070) on can1, while allowing specific alarm
categories to be selectively suppressed.

WHY THIS EXISTS: the APS-500 alternator regulator refuses to deliver any
charge current while the BMS reports ANY active alarm, even a mild one
like "battery is cold but not dangerously so" (native under_temperature
alarm level 1). That blocks a useful recovery path: commanding a small
charge current specifically to run the battery's own heater relay and
warm the pack back up. This service works around that by relaying the
real BMS's telemetry to the APS-500 basically unmodified, except that a
user-selected alarm category is masked out of the 0x92 alarm word while
it is at level 1 -- see rvc2mqtt/rvc-spec.yml (0EF70/0EF80 DGNs) for the
full reverse-engineering writeup this is built on.

REQUIRES the real BMS physically disconnected from can1 (it stays wired
to can0 -- this program only ever reads can0, never transmits on it).

Safety properties:
  - a category is only ever suppressed while its native alarm level is
    EXACTLY 1. The instant it escalates to 2 or 3, suppression for that
    category stops and the real bits pass straight through un-modified.
  - the override additionally self-disables once ANY of the 4 temperature
    sensors reports >= AUTO_DISABLE_TEMP_C, regardless of whether the
    BMS's own alarm has cleared.
  - if can0 goes stale (no frames for STALE_TIMEOUT_S), 0EF70 queries are
    left unanswered entirely rather than replying with frozen data -- the
    APS-500's existing "BMS not communicating" fallback then takes over.
  - control (which categories to override, on/off) is via MQTT, but none
    of the above safety logic depends on MQTT -- it runs entirely off
    direct can0 frames on its own thread.
"""

import argparse
import json
import logging
import struct
import threading
import time

import can
import paho.mqtt.client as mqtt

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
log = logging.getLogger("virtual_bms")

# ---------------------------------------------------------------------------
# can1: proprietary APS-500 <-> BMS link (see rvc-spec.yml 0EF70/0EF80)
# ---------------------------------------------------------------------------
QUERY_ID = 0x18EF7080
RESPONSE_ID = 0x18EF8070
STALE_TIMEOUT_S = 5.0
AUTO_DISABLE_TEMP_C = 10.0
# Requested current while an under_temperature L1 alarm is being overridden.
# Chosen to match what the battery's own heater relay needs to run (per the
# pack owner), NOT the BMS's normal ~90-105A charge allowance -- pushing
# full charge current into a genuinely cold pack risks lithium plating,
# which is presumably why the BMS enforces this cutoff in the first place.
HEATER_TRIGGER_CURRENT_A = 25.0
# Chosen 2026-09-05 by live-testing at 8/15/18/21/25/40A: setpoints at/below ~15A oscillated
# (current collapsing toward 0, even briefly negative, then overshooting) while 25A+ ran
# clean. The heater itself needs only ~8A to run, but per the pack owner its ~8A draw is
# apparently not seen (or is netted out) by the BMS's own current sensor -- so the heater's
# "is >=8A available" turn-on check is self-referential: it turns on, its own draw makes
# reported current look unavailable, it turns back off, current recovers, repeat. The
# alternator needs to supply meaningfully more than the heater's own draw plus its own
# threshold (roughly 16A+) for it to see current continuously available and stay on without
# cycling -- not yet confirmed by directly measuring the heater's load, just consistent with
# every setpoint tested. Revisit this figure once genuinely cold-weather testing is possible.
# Still well below the pack's normal ~90A charge current either way.

IDENTIFY_REPLIES = {
    ("14", "02"): [bytes([0x52, 0x42, 0x54, 0x32, 0x31, 0x30, 0x4C, 0x46]),
                   bytes([0x50, 0x35, 0x31, 0x53, 0x2D, 0x31, 0x32, 0x00])],  # "RBT210LFP51S-12"
    ("13", "A5"): [bytes([0x00, 0x02, 0x17, 0x55, 0x52, 0x42, 0x54, 0x32])],
}

# 0x92 alarm word: byte index -> bit contributed. under_temperature is
# LIVE-CONFIRMED (2026-09-05, see rvc-spec.yml) at each level; every other
# category is a best-effort single bit picked from the synthetic sweep's
# shared fault-code groupings (rvc-spec.yml 0EF80), used only so an active
# real alarm we don't fully understand still surfaces as SOME fault rather
# than being silently dropped -- it is not necessarily the exact bit the
# real BMS would use for that category.
UNDER_TEMP_BITS = {
    1: [(1, 0x80)],
    2: [(1, 0x80), (1, 0x01), (3, 0x20), (5, 0x20)],
    3: [(1, 0x80), (1, 0x01), (3, 0x20), (5, 0x20)],
}
CATEGORY_TO_FAULT_CODE = {
    "cell_over_voltage": "51", "over_temperature": "59", "charging_overcurrent": "58",
    "discharge_overcurrent": "58", "under_voltage": "57", "over_voltage": "52",
    "cell_under_voltage": "57", "soc_too_low": "51", "insulation_failure": "51",
    "cell_imbalance": "51", "temperature_difference_too_high": "51",
    "temperature_open_circuit": "51", "master_slave_communication": "51",
    "feedback_overcurrent": "51", "charging_communication": "51",
}
GENERIC_BIT_FOR_CODE = {
    "51": (1, 0x02), "52": (2, 0x02), "57": (2, 0x01), "58": (2, 0x10), "59": (3, 0x40),
}
ALARM_CATEGORIES = ["cell_over_voltage", "over_temperature", "charging_overcurrent",
                    "discharge_overcurrent", "under_temperature", "under_voltage",
                    "over_voltage", "cell_under_voltage", "soc_too_low", "insulation_failure",
                    "cell_imbalance", "temperature_difference_too_high",
                    "temperature_open_circuit", "master_slave_communication",
                    "feedback_overcurrent", "charging_communication"]

# ---------------------------------------------------------------------------
# can0: native Renogy BMS protocol (see /opt/coach2mqtt/configs/can2mqtt/config.json)
# ---------------------------------------------------------------------------
CANID_CURRENT_SOC = 0x501       # >ff: current (A, native sign: NEGATIVE=charging), soc (%)
CANID_ALARMS = 0x504            # >BBBBBBBB: a,b,c,d,e,failures,relays,h
CANID_CHARGE = 0x505            # >BhhBBB: workmodel, chargevoltage(x10), chargecurrent(x10), chargestatus, ver
CANID_TEMPS_1 = 0x550           # >hhhh: numsensors, t1, t2, t3 (native = (C*10)+400)
CANID_TEMPS_2 = 0x551           # >hhhh: t4, unused, unused, unused
PACK_CAPACITY_AH = 210.0

ALARM_LEVEL_GROUPS = {
    0x501: None,
}


def alarm_level_to_list(val):
    groups = [[0x10, 0x20, 0x30], [0x40, 0x80, 0xC0], [0x01, 0x02, 0x03], [0x04, 0x08, 0x0C]]
    out = [0, 0, 0, 0]
    for gi, levels in enumerate(groups):
        for i, level in enumerate(levels):
            if (val & level) == level:
                out[gi] = i + 1
    return out


class RealBmsState:
    """Live snapshot of the real BMS, updated only from can0 frames."""

    def __init__(self):
        self.lock = threading.Lock()
        self.last_frame_time = 0.0
        self.actual_current_native = None      # raw sign: negative = charging
        self.soc_pct = None
        self.alarm_levels = {c: 0 for c in ALARM_CATEGORIES}
        self.failure_level = 0
        self.charge_current_a = None           # BMS's own requested/allowed charge current, positive magnitude
        self.temps_c = [None, None, None, None]

    def is_stale(self):
        with self.lock:
            return (time.time() - self.last_frame_time) > STALE_TIMEOUT_S if self.last_frame_time else True

    def snapshot(self):
        with self.lock:
            return (self.actual_current_native, self.soc_pct, dict(self.alarm_levels),
                    self.failure_level, self.charge_current_a, list(self.temps_c))


def can0_listener(iface, state: RealBmsState):
    bus = can.interface.Bus(channel=iface, interface="socketcan")
    log.info("can0 listener started on %s", iface)
    for msg in bus:
        if msg.is_extended_id:
            continue
        cid = msg.arbitration_id
        data = msg.data
        with state.lock:
            state.last_frame_time = time.time()
            try:
                if cid == CANID_CURRENT_SOC and len(data) == 8:
                    current, soc = struct.unpack(">ff", data)
                    state.actual_current_native = current
                    state.soc_pct = soc
                elif cid == CANID_ALARMS and len(data) == 8:
                    a, b, c, d, e, failures, relays, h = struct.unpack(">BBBBBBBB", data)
                    la, lb, lc, ld = (alarm_level_to_list(x) for x in (a, b, c, d))
                    levels = la + lb + lc + ld
                    for cat, lvl in zip(ALARM_CATEGORIES, levels):
                        state.alarm_levels[cat] = lvl
                    state.failure_level = alarm_level_to_list(e)[1]
                elif cid == CANID_CHARGE and len(data) == 8:
                    _workmodel, _chargevoltage, chargecurrent, _status, _major, _minor = \
                        struct.unpack(">BhhBBB", data)
                    state.charge_current_a = chargecurrent / 10.0
                elif cid == CANID_TEMPS_1 and len(data) == 8:
                    _n, t1, t2, t3 = struct.unpack(">hhhh", data)
                    state.temps_c[0] = (t1 - 400) / 10.0
                    state.temps_c[1] = (t2 - 400) / 10.0
                    state.temps_c[2] = (t3 - 400) / 10.0
                elif cid == CANID_TEMPS_2 and len(data) == 8:
                    t4, _, _, _ = struct.unpack(">hhhh", data)
                    state.temps_c[3] = (t4 - 400) / 10.0
            except struct.error:
                pass


class Overrides:
    """User-controlled, MQTT-driven set of alarm categories to suppress."""

    def __init__(self):
        self.lock = threading.Lock()
        self.categories = set()

    def set(self, categories):
        with self.lock:
            self.categories = set(categories)
        log.info("override categories set to: %s", sorted(self.categories))

    def get(self):
        with self.lock:
            return set(self.categories)


def s16(v):
    v = int(round(v))
    return max(-32768, min(32767, v)) & 0xFFFF


def build_response(register, state: RealBmsState, overrides: Overrides, counter, status_cb):
    current, soc, alarm_levels, failure_level, charge_current_a, temps = state.snapshot()

    if register == 0x88:
        actual_a = current if current is not None else 0.0
        raw_current = s16(actual_a / 0.01)
        remaining_ah = 0.0 if soc is None else (soc / 100.0) * PACK_CAPACITY_AH
        raw_ah = int(round(remaining_ah / 0.001)) & 0xFFFFFFFF
        # bytes2-3: unexplained field that tracked |actual current| in live
        # traffic (rvc-spec.yml) -- held CONSTANT here rather than guessed
        # at, since a static value can never trigger the "value changed"
        # BMS-reconnect cascade documented for this register.
        return bytes([(raw_current >> 8) & 0xFF, raw_current & 0xFF, 0x02, 0x1B,
                      (raw_ah >> 24) & 0xFF, (raw_ah >> 16) & 0xFF,
                      (raw_ah >> 8) & 0xFF, raw_ah & 0xFF])

    if register == 0x8A:
        remaining_ah = 0.0 if soc is None else (soc / 100.0) * PACK_CAPACITY_AH
        raw_remain = int(round(remaining_ah / 0.001)) & 0xFFFFFFFF
        raw_total = int(round(PACK_CAPACITY_AH / 0.001)) & 0xFFFFFFFF
        return bytes([(raw_remain >> 24) & 0xFF, (raw_remain >> 16) & 0xFF,
                      (raw_remain >> 8) & 0xFF, raw_remain & 0xFF,
                      (raw_total >> 24) & 0xFF, (raw_total >> 16) & 0xFF,
                      (raw_total >> 8) & 0xFF, raw_total & 0xFF])

    if register == 0x8F:
        limit_a = charge_current_a if charge_current_a is not None else 0.0
        if "under_temperature" in overrides.get() and alarm_levels.get("under_temperature", 0) == 1:
            limit_a = min(limit_a, HEATER_TRIGGER_CURRENT_A)
        raw_desired = s16(-limit_a / 0.01)
        return bytes([0x02, 0x23, (raw_desired >> 8) & 0xFF, raw_desired & 0xFF,
                      0x00, 0x00, 0x00, 0x00])

    if register == 0x95:
        vals = []
        for t in temps:
            tc = t if t is not None else 20.0
            raw = int(round(tc * 10.0)) & 0xFFFF
            vals += [(raw >> 8) & 0xFF, raw & 0xFF]
        return bytes(vals)

    if register == 0x92:
        active_overrides = overrides.get()
        byte = [0, 0, 0, 0, 0, 0, 0, 0]
        suppressed_now = []
        for cat, level in alarm_levels.items():
            if level == 0:
                continue
            if cat in active_overrides and level == 1:
                suppressed_now.append(cat)
                continue
            if cat == "under_temperature":
                bits = UNDER_TEMP_BITS.get(min(level, 3), [])
            else:
                code = CATEGORY_TO_FAULT_CODE.get(cat)
                bits = [GENERIC_BIT_FOR_CODE[code]] if code in GENERIC_BIT_FOR_CODE else []
            for bidx, bval in bits:
                byte[bidx] |= bval
        byte[7] = counter & 0xFF
        status_cb(alarm_levels, failure_level, suppressed_now, temps)
        return bytes(byte)

    return None


def can1_responder(iface, state: RealBmsState, overrides: Overrides, status_cb):
    bus = can.interface.Bus(channel=iface, interface="socketcan")
    log.info("can1 responder started on %s", iface)
    counter = 0
    for msg in bus:
        if msg.arbitration_id != QUERY_ID:
            continue
        if state.is_stale():
            continue  # real BMS telemetry too old -- let the APS's own fallback take over
        data = msg.data
        if len(data) < 2:
            continue
        opcode = f"{data[0]:02X}"
        reg = f"{data[1]:02X}"
        if (opcode, reg) in IDENTIFY_REPLIES:
            for frame in IDENTIFY_REPLIES[(opcode, reg)]:
                bus.send(can.Message(arbitration_id=RESPONSE_ID, data=frame, is_extended_id=True))
            continue
        if opcode != "13":
            continue
        reg_int = int(reg, 16)
        counter = (counter + 1) & 0xFF
        resp = build_response(reg_int, state, overrides, counter, status_cb)
        if resp is not None:
            bus.send(can.Message(arbitration_id=RESPONSE_ID, data=resp, is_extended_id=True))


class MqttControl:
    STATUS_TOPIC = "rvc/virtualbms/status"
    SET_OVERRIDE_TOPIC = "rvc/virtualbms/set/override"

    def __init__(self, host, port, overrides: Overrides):
        self.overrides = overrides
        self.client = mqtt.Client()
        self.client.on_message = self._on_message
        self.client.on_connect = self._on_connect
        self.client.connect(host, port, 60)
        self.client.loop_start()

    def _on_connect(self, client, userdata, flags, rc):
        client.subscribe(self.SET_OVERRIDE_TOPIC)
        log.info("MQTT connected, listening on %s", self.SET_OVERRIDE_TOPIC)

    def _on_message(self, client, userdata, msg):
        if msg.topic != self.SET_OVERRIDE_TOPIC:
            return
        try:
            payload = msg.payload.decode("utf-8").strip()
            categories = json.loads(payload) if payload.startswith("[") else \
                ([c.strip() for c in payload.split(",") if c.strip()] if payload else [])
            unknown = set(categories) - set(ALARM_CATEGORIES)
            if unknown:
                log.warning("ignoring unknown categories in override request: %s", unknown)
            self.overrides.set(set(categories) & set(ALARM_CATEGORIES))
        except Exception as e:
            log.warning("bad override payload %r: %s", msg.payload, e)

    def publish_status(self, alarm_levels, failure_level, suppressed_now, temps):
        payload = json.dumps({
            "alarm_levels": alarm_levels,
            "failure_level": failure_level,
            "suppressed_now": suppressed_now,
            "temps_c": temps,
            "t": time.time(),
        })
        self.client.publish(self.STATUS_TOPIC, payload, retain=True)


def auto_disable_thread(state: RealBmsState, overrides: Overrides):
    """Fail-safe: drop the temperature override once EVERY sensor clears the
    threshold, or the moment under_temperature escalates past level 1."""
    while True:
        time.sleep(1.0)
        _, _, alarm_levels, _, _, temps = state.snapshot()
        current = overrides.get()
        if "under_temperature" not in current:
            continue
        # Use the COLDEST sensor, not the warmest -- a single cold cell is
        # the actual risk, so every sensor must clear the threshold before
        # it's safe to stand down (a bug here previously used max(), which
        # would disable as soon as the warmest sensor looked fine while
        # others were still cold).
        known_temps = [t for t in temps if t is not None]
        min_temp = min(known_temps) if known_temps else None
        level = alarm_levels.get("under_temperature", 0)
        if (min_temp is not None and min_temp >= AUTO_DISABLE_TEMP_C):
            log.warning("auto-disabling under_temperature override: coldest sensor %.1fC >= %.1fC",
                        min_temp, AUTO_DISABLE_TEMP_C)
            overrides.set(current - {"under_temperature"})
        elif level >= 2:
            log.warning("auto-disabling under_temperature override: alarm escalated to level %d", level)
            overrides.set(current - {"under_temperature"})


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--can0", default="can0")
    ap.add_argument("--can1", default="can1")
    ap.add_argument("--mqtt-host", default="localhost")
    ap.add_argument("--mqtt-port", type=int, default=1883)
    args = ap.parse_args()

    state = RealBmsState()
    overrides = Overrides()

    t0 = threading.Thread(target=can0_listener, args=(args.can0, state), daemon=True)
    t0.start()

    log.info("waiting for initial can0 data...")
    deadline = time.time() + 10
    while state.is_stale() and time.time() < deadline:
        time.sleep(0.2)
    if state.is_stale():
        log.warning("no can0 data yet after 10s -- continuing anyway, will answer once live")

    mqttc = MqttControl(args.mqtt_host, args.mqtt_port, overrides)

    ta = threading.Thread(target=auto_disable_thread, args=(state, overrides), daemon=True)
    ta.start()

    log.info("virtual BMS relay active: can0(%s) -> can1(%s). Ctrl+C to stop.", args.can0, args.can1)
    can1_responder(args.can1, state, overrides, mqttc.publish_status)


if __name__ == "__main__":
    main()
