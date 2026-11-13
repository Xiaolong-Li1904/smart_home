"""The simulated house: sky, simulated nodes that speak the real protocol, a sleeping occupant, and metrics."""

from __future__ import annotations

import math
import random
import time
from dataclasses import dataclass, field

from smarthome.protocol import (
    OUTDOOR_LUX,
    ROOMS,
    SIM_AMBIENT,
    SIM_OCCUPANT,
    alarm_event_topic,
    button_topic,
    clock_str,
    light_set_topic,
    light_state_topic,
    lux_topic,
    motion_topic,
    shutter_set_topic,
    shutter_state_topic,
)
from smarthome.sim.occupant import Night, Occupant
from smarthome.sim.sleep import SleepModel

# Fraction of outdoor (horizontal) illuminance reaching each room's lux sensor. The hallway has no window.
WINDOW_GAIN = {"hallway": 0.0005, "living": 0.03, "bedroom": 0.02}
SHUTTER_ROOMS = ("bedroom",)
SHUTTER_LEAK = 0.02  # a closed Rollladen still lets some light through the slits
LAMP_LUX_PER_LEVEL = 1.2  # full brightness (255) adds ~300 lx at the sensor


class Sky:
    """Outdoor illuminance from the sun's elevation (with civil twilight) times a drifting cloud factor."""

    def __init__(self, seed: int = 0, lat: float = 48.1, lon: float = 11.6) -> None:
        self._seed = seed
        self.lat, self.lon = lat, lon

    def _cloud(self, hour_index: int) -> float:
        return random.Random(self._seed * 1_000_003 + hour_index).uniform(0.1, 1.0)

    def sun_elevation(self, ts: float) -> float:
        """Degrees above the horizon."""
        doy = time.localtime(ts).tm_yday
        decl = math.radians(-23.44 * math.cos(2 * math.pi * (doy + 10) / 365))
        b = 2 * math.pi * (doy - 81) / 364
        eot_min = 9.87 * math.sin(2 * b) - 7.53 * math.cos(b) - 1.5 * math.sin(b)
        solar_h = (ts / 3600) % 24 + self.lon / 15 + eot_min / 60
        hour_angle = math.radians(15 * (solar_h - 12))
        lat = math.radians(self.lat)
        s = math.sin(lat) * math.sin(decl) + math.cos(lat) * math.cos(decl) * math.cos(hour_angle)
        return math.degrees(math.asin(max(-1.0, min(1.0, s))))

    def clear_sky(self, ts: float) -> float:
        elev = self.sun_elevation(ts)
        if elev > 0:
            return 400 + 100_000 * math.sin(math.radians(elev))
        if elev > -6:  # civil twilight: ~400 lx at sunrise down to ~1 lx
            return 400 * 10 ** (elev / 6 * 2.6)
        return 0.0

    def __call__(self, ts: float) -> float:
        k, frac = divmod(ts / 3600, 1)
        c0, c1 = self._cloud(int(k)), self._cloud(int(k) + 1)
        return self.clear_sky(ts) * (c0 + (c1 - c0) * frac)


class LightNode:
    """Simulated dimmable, tunable-white light. A real one: ESP32 + LED driver with warm and cool channels."""

    def __init__(self, bus, room: str) -> None:
        self._bus = bus
        self.room = room
        self.on = False
        self.level = 0
        self.kelvin = 2700
        self.on_count = 0
        bus.subscribe(light_set_topic(room), self._on_set)
        self._publish()

    @property
    def lux(self) -> float:
        return self.level * LAMP_LUX_PER_LEVEL if self.on else 0.0

    def _on_set(self, topic: str, p: dict) -> None:
        was_on = self.on
        if "on" in p:
            self.on = bool(p["on"])
        if "brightness" in p:
            self.level = max(0, min(255, int(p["brightness"])))
        if "kelvin" in p:
            self.kelvin = max(1800, min(6500, int(p["kelvin"])))
        if self.on and self.level == 0:
            self.level = 255
        self.on_count += self.on and not was_on
        self._publish()

    def _publish(self) -> None:
        self._bus.publish(light_state_topic(self.room),
                          {"on": self.on, "brightness": self.level, "kelvin": self.kelvin}, retain=True)


class ShutterNode:
    """Simulated Rollladen: a tubular motor running up or down at constant speed.

    A real one has no position sensor; the ESP32 estimates position from run time, re-zeroing at the
    end stops. Here the position is exact."""

    def __init__(self, bus, room: str, travel_s: float = 20.0) -> None:
        self._bus = bus
        self.room = room
        self.position = 100.0
        self.target = 100.0
        self.speed = 100.0 / travel_s
        self.runs = 0  # motor starts, i.e. relay wear
        bus.subscribe(shutter_set_topic(room), self._on_set)
        self._publish(False)

    @property
    def light_fraction(self) -> float:
        return SHUTTER_LEAK + (1 - SHUTTER_LEAK) * self.position / 100

    def _on_set(self, topic: str, p: dict) -> None:
        target = max(0.0, min(100.0, float(p["position"])))
        if target != self.position and target != self.target:
            self.runs += 1
        self.target = target
        self._publish(self.position != self.target)

    def step(self, dt: float) -> None:
        if self.position == self.target:
            return
        delta = self.target - self.position
        self.position = self.target if abs(delta) <= self.speed * dt else self.position + math.copysign(self.speed * dt, delta)
        self._publish(self.position != self.target)

    def _publish(self, moving: bool) -> None:
        self._bus.publish(shutter_state_topic(self.room),
                          {"position": round(self.position, 1), "moving": moving}, retain=True)


@dataclass
class RoomMetrics:
    wasted_s: float = 0.0  # light on, nobody there
    dark_s: float = 0.0  # somebody there and awake-ish (not in bed), too dark, light off
    vacated: int = 0  # times the occupant left


@dataclass
class WakeRecord:
    alarm: float
    wake_t: float
    cause: str  # 'light' | 'spontaneous' | 'alarm'
    stage: str  # sleep stage just before waking
    bed_lux: float  # at the moment of waking


@dataclass
class SleepMetrics:
    wakes: list[WakeRecord] = field(default_factory=list)
    lux_at_alarm: dict[float, float] = field(default_factory=dict)  # alarm time -> bed lux then
    night_awakenings: int = 0  # woke up and fell asleep again more than an hour before the alarm
    lit_sleep_s: float = 0.0  # asleep with the bedroom lamp on, before the last hour (which is the sunrise's)


class World:
    def __init__(self, bus, occupant: Occupant, sky: Sky, dark_lux: float = 50.0, seed: int = 0) -> None:
        self._bus = bus
        self.occupant = occupant
        self.sky = sky
        self.dark_lux = dark_lux
        self.rng = random.Random(seed + 7919)
        self.lights = {r: LightNode(bus, r) for r in ROOMS}
        self.shutters = {r: ShutterNode(bus, r) for r in SHUTTER_ROOMS}
        self.metrics = {r: RoomMetrics() for r in ROOMS}
        self.sleep_metrics = SleepMetrics()
        self.sleep = SleepModel(self.rng)
        self.location = "?"
        self._outdoor = 0.0
        self._occupied: dict[str, bool | None] = {r: None for r in ROOMS}
        self._last_lux: dict[str, tuple[float, float]] = {r: (math.nan, -math.inf) for r in (*ROOMS, "outdoor")}
        self._last_ambient_t = -math.inf
        self._night: Night | None = None
        self._woke_final = False
        self._out_of_bed = False
        self._pending: list[tuple[float, str, dict]] = []  # (time, topic, payload) the occupant will send
        self._published_loc: str | None = None
        self._asleep_published: bool | None = None

    # ---- physics ---------------------------------------------------------

    def ambient(self, room: str, ts: float | None = None) -> float:
        """Daylight at the room's sensor. Uses the outdoor value of the current step."""
        a = self._outdoor * WINDOW_GAIN[room]
        if room in self.shutters:
            a *= self.shutters[room].light_fraction
        return a

    def sensor_lux(self, room: str, ts: float | None = None) -> float:
        return self.ambient(room) + self.lights[room].lux

    # ---- simulation step -------------------------------------------------

    def step(self, ts: float, dt: float) -> None:
        self._outdoor = self.sky(ts)
        for s in self.shutters.values():
            s.step(dt)

        loc = self.occupant.location(ts)
        self.location = loc
        self._update_sleep(ts, dt, loc)
        night = self._night
        if night is not None and night.alarm <= ts < night.alarm + dt:
            self.sleep_metrics.lux_at_alarm[night.alarm] = self.sensor_lux("bedroom")
        asleep = self.sleep.is_asleep(ts)
        if loc != self._published_loc or asleep != self._asleep_published:
            self._published_loc, self._asleep_published = loc, asleep
            self._bus.publish(SIM_OCCUPANT, {"room": loc, "asleep": asleep}, retain=True)
        if ts - self._last_ambient_t >= 30:
            self._last_ambient_t = ts
            self._bus.publish(SIM_AMBIENT, {
                "outdoor": round(self._outdoor, 1),
                "rooms": {r: round(self.ambient(r), 1) for r in ROOMS},
            }, retain=True)

        while self._pending and self._pending[0][0] <= ts:
            _, topic, payload = self._pending.pop(0)
            self._bus.publish(topic, payload)

        self._report_lux("outdoor", OUTDOOR_LUX, self._outdoor, ts)
        in_bed = self._night is not None and loc == "bedroom"
        for r in ROOMS:
            occ = loc == r
            if occ != self._occupied[r]:
                if self._occupied[r]:
                    self.metrics[r].vacated += 1
                self._occupied[r] = occ
                self._bus.publish(motion_topic(r), {"occupied": occ})
            self._report_lux(r, lux_topic(r), self.sensor_lux(r), ts)

            m, on = self.metrics[r], self.lights[r].on
            if on and not occ:
                m.wasted_s += dt
            if occ and not on and not (in_bed and r == "bedroom") and self.ambient(r) < self.dark_lux:
                m.dark_s += dt
        if asleep and self.lights["bedroom"].on and night is not None and ts < night.alarm - 3600:
            self.sleep_metrics.lit_sleep_s += dt

    def _report_lux(self, key: str, topic: str, lux: float, ts: float) -> None:
        """Report on a 1 lx / 5 % change, or at least once a minute."""
        last, last_t = self._last_lux[key]
        if not abs(lux - last) <= max(1.0, 0.05 * last) or ts - last_t >= 60:
            self._last_lux[key] = (lux, ts)
            self._bus.publish(topic, {"lux": round(lux, 1)})

    def _update_sleep(self, ts: float, dt: float, loc: str) -> None:
        night = self.occupant.night_at(ts)
        if night != self._night:
            self._night = night
            if night is not None:  # bedtime: press goodnight, start a fresh night
                self._bus.publish(button_topic("bedroom"), {"action": "goodnight"})
                self.sleep.reset()
                self._woke_final = False
                self._out_of_bed = loc != "bedroom"
                if loc == "bedroom":
                    self.sleep.fall_asleep(ts)
            else:
                self.sleep.wake_up()
        if night is None or self._woke_final:
            return
        if loc != "bedroom":  # night trip
            self.sleep.wake_up()
            self._out_of_bed = True
            return
        if self._out_of_bed:
            self._out_of_bed = False
            self.sleep.fall_asleep(ts)

        bed_lux = self.sensor_lux("bedroom")
        stage = self.sleep.stage(ts)
        if self.sleep.step(ts, dt, bed_lux):
            if ts >= night.alarm - 3600:
                self._final_wake(ts, night, "light" if bed_lux >= 10 else "spontaneous", stage, bed_lux)
            else:
                self.sleep_metrics.night_awakenings += 1
                self.sleep.fall_asleep(ts)
        elif ts >= night.alarm:
            self._final_wake(ts, night, "alarm", stage, bed_lux)

    def _final_wake(self, ts: float, night: Night, cause: str, stage: str, bed_lux: float) -> None:
        self._woke_final = True
        self.sleep.wake_up()
        self.sleep_metrics.wakes.append(WakeRecord(night.alarm, ts, cause, stage, bed_lux))
        # Awake: turn the phone alarm off (before it rings, if woken by the light).
        self._pending.append((ts + self.rng.uniform(20, 90), alarm_event_topic("bedroom"), {"type": "stopped"}))
        self._pending.sort(key=lambda e: e[0])

    # ---- reporting -------------------------------------------------------

    def status_line(self, ts: float) -> str:
        parts = []
        for r in ROOMS:
            light = self.lights[r]
            state = f"ON {round(light.level / 2.55):>3}%" if light.on else "off    "
            parts.append(f"{r} {state} {self.sensor_lux(r):5.0f}lx")
        shutter = self.shutters["bedroom"].position
        who = self.location + ("(zz)" if self.sleep.is_asleep(ts) else "")
        return (f"{clock_str(ts)}  @{who:<12} | " + " | ".join(parts)
                + f" | shutter {shutter:3.0f}% | outdoor {self._outdoor:6.0f}lx")

    def summary(self) -> str:
        rows = [f"{'room':<8} {'lights on':>9} {'wasted min':>10} {'dark min':>8}"]
        for r in ROOMS:
            m = self.metrics[r]
            rows.append(f"{r:<8} {self.lights[r].on_count:>9} {m.wasted_s / 60:>10.1f} {m.dark_s / 60:>8.1f}")
        sm = self.sleep_metrics
        rows.append("")
        rows.append(f"sleep: night awakenings {sm.night_awakenings}, asleep with lamp on {sm.lit_sleep_s / 60:.1f} min, "
                    f"shutter motor runs {self.shutters['bedroom'].runs}")
        for w in sm.wakes:
            early = (w.alarm - w.wake_t) / 60
            when = f"{early:4.1f} min before alarm" if early > 0 else "at alarm"
            at_alarm = sm.lux_at_alarm.get(w.alarm)
            rows.append(f"  alarm {clock_str(w.alarm)[:5]}: woke {clock_str(w.wake_t)} ({when}) by {w.cause:<11} "
                        f"from {w.stage:<5} sleep, bed {w.bed_lux:4.0f} lx"
                        + (f", {at_alarm:4.0f} lx at alarm" if at_alarm is not None else ""))
        return "\n".join(rows)
