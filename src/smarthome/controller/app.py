"""Wires RoomControllers to a bus and a clock."""

from __future__ import annotations

import threading
import time
from typing import Callable

from smarthome.controller.room import LightCommand, RoomConfig, RoomController
from smarthome.protocol import SIM_TIME, clock_str, light_set_topic, room_of


class ControllerApp:
    """With `sim_clock=True`, time comes from `sim/time` messages and each one triggers a tick.
    Otherwise the wall clock is used and `run_forever` ticks it."""

    def __init__(
        self,
        bus,
        configs: dict[str, RoomConfig],
        sim_clock: bool = False,
        log: Callable[[str], None] | None = print,
    ) -> None:
        self._bus = bus
        self._rooms = {room: RoomController(room, cfg) for room, cfg in configs.items()}
        self._sim_clock = sim_clock
        self._sim_now: float | None = None
        self._log = log
        self._lock = threading.RLock()

        bus.subscribe("home/+/motion", lambda t, p: self._handle(t, lambda rc, now: rc.on_motion(bool(p["occupied"]), now)))
        bus.subscribe("home/+/lux", lambda t, p: self._handle(t, lambda rc, now: rc.on_lux(float(p["lux"]), now)))
        bus.subscribe("home/+/light/state", lambda t, p: self._handle(t, lambda rc, now: rc.on_light_state(bool(p["on"]), now)))
        if sim_clock:
            bus.subscribe(SIM_TIME, self._on_sim_time)

    def now(self) -> float | None:
        return self._sim_now if self._sim_clock else time.time()

    def tick(self) -> None:
        with self._lock:
            now = self.now()
            if now is None:
                return
            for rc in self._rooms.values():
                self._send(rc.tick(now), now)

    def run_forever(self, period_s: float = 0.5) -> None:
        while True:
            self.tick()
            time.sleep(period_s)

    def _on_sim_time(self, topic: str, payload: dict) -> None:
        with self._lock:
            self._sim_now = float(payload["t"])
        self.tick()

    def _handle(self, topic: str, event: Callable[[RoomController, float], list[LightCommand]]) -> None:
        rc = self._rooms.get(room_of(topic))
        if rc is None:
            return
        with self._lock:
            now = self.now()
            if now is None:  # simulated time has not started yet
                return
            self._send(event(rc, now), now)

    def _send(self, cmds: list[LightCommand], now: float) -> None:
        for c in cmds:
            payload = {"on": c.on, "brightness": c.brightness} if c.on else {"on": False}
            self._bus.publish(light_set_topic(c.room), payload)
            if self._log:
                state = f"ON {round(c.brightness / 2.55)}%" if c.on else "off"
                self._log(f"[ctrl {clock_str(now)}] {c.room}: {state}")
