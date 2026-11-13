"""The simulated house: daylight, simulated nodes that speak the real protocol, and ground-truth metrics."""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from datetime import datetime

from smarthome.protocol import (
    ROOMS,
    SIM_AMBIENT,
    SIM_OCCUPANT,
    clock_str,
    light_set_topic,
    light_state_topic,
    lux_topic,
    motion_topic,
)
from smarthome.sim.occupant import Occupant

# Fraction of window daylight reaching each room's lux sensor. The hallway has no window.
WINDOW = {"hallway": 0.03, "living": 1.0, "bedroom": 0.5}
LAMP_LUX_PER_LEVEL = 1.2  # full brightness (255) adds ~300 lx at the sensor
PEAK_DAYLIGHT_LUX = 600.0
SUNRISE_H, SUNSET_H = 7.5, 16.5  # roughly November in central Europe


class Daylight:
    """Clear-sky arc times a cloud factor that drifts between hourly random values."""

    def __init__(self, seed: int = 0) -> None:
        self._seed = seed

    def _cloud(self, hour_index: int) -> float:
        return random.Random(self._seed * 1_000_003 + hour_index).uniform(0.3, 1.0)

    def __call__(self, ts: float) -> float:
        dt = datetime.fromtimestamp(ts)
        h = dt.hour + dt.minute / 60 + dt.second / 3600
        if not SUNRISE_H < h < SUNSET_H:
            return 0.0
        clear = PEAK_DAYLIGHT_LUX * math.sin(math.pi * (h - SUNRISE_H) / (SUNSET_H - SUNRISE_H))
        k, frac = divmod(ts / 3600, 1)
        c0, c1 = self._cloud(int(k)), self._cloud(int(k) + 1)
        return clear * (c0 + (c1 - c0) * frac)


class LightNode:
    """Simulated dimmable light. A real one would be an ESP32 driving a MOSFET/LED driver."""

    def __init__(self, bus, room: str) -> None:
        self._bus = bus
        self.room = room
        self.on = False
        self.level = 0
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
        if self.on and self.level == 0:
            self.level = 255
        self.on_count += self.on and not was_on
        self._publish()

    def _publish(self) -> None:
        self._bus.publish(light_state_topic(self.room), {"on": self.on, "brightness": self.level}, retain=True)


@dataclass
class RoomMetrics:
    wasted_s: float = 0.0  # light on, nobody there
    dark_s: float = 0.0  # somebody there, too dark, light off
    vacated: int = 0  # times the occupant left


class World:
    def __init__(self, bus, occupant: Occupant, daylight: Daylight, dark_lux: float = 50.0) -> None:
        self._bus = bus
        self.occupant = occupant
        self.daylight = daylight
        self.dark_lux = dark_lux
        self.lights = {r: LightNode(bus, r) for r in ROOMS}
        self.metrics = {r: RoomMetrics() for r in ROOMS}
        self.location = "?"
        self._occupied: dict[str, bool | None] = {r: None for r in ROOMS}
        self._last_lux: dict[str, tuple[float, float]] = {r: (math.nan, -math.inf) for r in ROOMS}
        self._last_ambient_t = -math.inf

    def ambient(self, room: str, ts: float) -> float:
        return self.daylight(ts) * WINDOW[room]

    def sensor_lux(self, room: str, ts: float) -> float:
        return self.ambient(room, ts) + self.lights[room].lux

    def step(self, ts: float, dt: float) -> None:
        loc = self.occupant.location(ts)
        if loc != self.location:
            self._bus.publish(SIM_OCCUPANT, {"room": loc}, retain=True)
        self.location = loc
        if ts - self._last_ambient_t >= 30:
            self._last_ambient_t = ts
            self._bus.publish(SIM_AMBIENT, {
                "outdoor": round(self.daylight(ts), 1),
                "rooms": {r: round(self.ambient(r, ts), 1) for r in ROOMS},
            }, retain=True)
        for r in ROOMS:
            occ = self.location == r
            if occ != self._occupied[r]:
                if self._occupied[r]:
                    self.metrics[r].vacated += 1
                self._occupied[r] = occ
                self._bus.publish(motion_topic(r), {"occupied": occ})

            # Report on a 5 lx / 10 % change, or at least once a minute.
            lux = self.sensor_lux(r, ts)
            last, last_t = self._last_lux[r]
            if not abs(lux - last) <= max(5.0, 0.1 * last) or ts - last_t >= 60:
                self._last_lux[r] = (lux, ts)
                self._bus.publish(lux_topic(r), {"lux": round(lux, 1)})

            m, on = self.metrics[r], self.lights[r].on
            if on and not occ:
                m.wasted_s += dt
            if occ and not on and self.ambient(r, ts) < self.dark_lux:
                m.dark_s += dt

    def status_line(self, ts: float) -> str:
        parts = []
        for r in ROOMS:
            light = self.lights[r]
            state = f"ON {round(light.level / 2.55):>3}%" if light.on else "off    "
            parts.append(f"{r} {state} {self.sensor_lux(r, ts):4.0f}lx")
        return f"{clock_str(ts)}  @{self.location:<8} | " + " | ".join(parts)

    def summary(self) -> str:
        rows = [f"{'room':<8} {'lights on':>9} {'wasted min':>10} {'dark min':>8}"]
        for r in ROOMS:
            m = self.metrics[r]
            rows.append(f"{r:<8} {self.lights[r].on_count:>9} {m.wasted_s / 60:>10.1f} {m.dark_s / 60:>8.1f}")
        return "\n".join(rows)
