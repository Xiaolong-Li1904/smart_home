"""Wires room controllers to a bus and a clock."""

from __future__ import annotations

import threading
import time
from typing import Callable

from smarthome.controller.bedroom import BedroomController, WakeConfig
from smarthome.controller.room import Command, LightCommand, RoomConfig, RoomController
from smarthome.protocol import OUTDOOR_LUX, SIM_TIME, clock_str, light_set_topic, room_of, shutter_set_topic

Event = Callable[[RoomController, float], list[Command]]


def _if_has(method: str, *args) -> Event:
    """Call rc.<method>(*args, now) on controllers that implement it; others ignore the event."""
    def call(rc: RoomController, now: float) -> list[Command]:
        fn = getattr(rc, method, None)
        return fn(*args, now) if fn else []
    return call


class ControllerApp:
    """With `sim_clock=True`, time comes from `sim/time` messages and each one triggers a tick.
    Otherwise the wall clock is used and `run_forever` ticks it."""

    def __init__(
        self,
        bus,
        configs: dict[str, RoomConfig],
        wake: WakeConfig | None = None,
        sim_clock: bool = False,
        log: Callable[[str], None] | None = print,
    ) -> None:
        self._bus = bus
        self.rooms: dict[str, RoomController] = {
            room: BedroomController(room, cfg, wake) if room == "bedroom" else RoomController(room, cfg)
            for room, cfg in configs.items()
        }
        self._sim_clock = sim_clock
        self._sim_now: float | None = None
        self._log = log
        self._lock = threading.RLock()

        sub = bus.subscribe
        sub("home/+/motion", lambda t, p: self._handle(t, lambda rc, now: rc.on_motion(bool(p["occupied"]), now)))
        sub("home/+/lux", lambda t, p: self._handle(t, lambda rc, now: rc.on_lux(float(p["lux"]), now)))
        sub("home/+/light/state", lambda t, p: self._handle(t, lambda rc, now: rc.on_light_state(bool(p["on"]), now)))
        sub("home/+/shutter/state", lambda t, p: self._handle(
            t, _if_has("on_shutter_state", float(p["position"]), bool(p.get("moving", False)))))
        sub("home/+/button", lambda t, p: self._handle(t, _if_has("on_button", str(p.get("action", "")))))
        sub("home/+/alarm/config", self._on_alarm_config)
        sub("home/+/alarm/event", lambda t, p: self._handle(t, _if_has("on_alarm_event", str(p.get("type", "")))))
        sub(OUTDOOR_LUX, self._on_outdoor)
        if sim_clock:
            sub(SIM_TIME, self._on_sim_time)

    def now(self) -> float | None:
        return self._sim_now if self._sim_clock else time.time()

    def tick(self) -> None:
        with self._lock:
            now = self.now()
            if now is None:
                return
            for rc in self.rooms.values():
                self._send(rc.tick(now), now)

    def run_forever(self, period_s: float = 0.5) -> None:
        while True:
            self.tick()
            time.sleep(period_s)

    def _on_sim_time(self, topic: str, payload: dict) -> None:
        with self._lock:
            self._sim_now = float(payload["t"])
        self.tick()

    def _on_alarm_config(self, topic: str, payload: dict) -> None:
        """Settings, not events: applied even before (simulated) time has started."""
        rc = self.rooms.get(room_of(topic))
        if isinstance(rc, BedroomController):
            with self._lock:
                rc.on_alarm_config(payload)

    def _on_outdoor(self, topic: str, payload: dict) -> None:
        with self._lock:
            now = self.now()
            if now is None:
                return
            for rc in self.rooms.values():
                self._send(_if_has("on_outdoor_lux", float(payload["lux"]))(rc, now), now)

    def _handle(self, topic: str, event: Event) -> None:
        rc = self.rooms.get(room_of(topic))
        if rc is None:
            return
        with self._lock:
            now = self.now()
            if now is None:  # simulated time has not started yet
                return
            self._send(event(rc, now), now)

    def _send(self, cmds: list[Command], now: float) -> None:
        for c in cmds:
            if isinstance(c, LightCommand):
                payload: dict = {"on": c.on}
                if c.on:
                    payload["brightness"] = c.brightness
                    if c.kelvin is not None:
                        payload["kelvin"] = c.kelvin
                self._bus.publish(light_set_topic(c.room), payload)
                text = f"light ON {round(c.brightness / 2.55)}% {c.kelvin or ''}K" if c.on else "light off"
            else:
                self._bus.publish(shutter_set_topic(c.room), {"position": c.position})
                text = f"shutter -> {c.position:.0f}%"
            if self._log:
                self._log(f"[ctrl {clock_str(now)}] {c.room}: {text}")
