from __future__ import annotations

import time
from datetime import datetime
from typing import Callable

from smarthome.protocol import SIM_TIME
from smarthome.sim.world import World


def parse_start(s: str | None) -> float:
    """'2026-11-13 06:00' -> unix seconds; None -> today 00:00 local."""
    if s is None:
        return datetime.now().replace(hour=0, minute=0, second=0, microsecond=0).timestamp()
    return datetime.fromisoformat(s).timestamp()


def run(
    bus,
    world: World,
    start_ts: float,
    hours: float,
    dt: float = 1.0,
    speed: float | None = None,
    status_every_s: float = 3600.0,
    out: Callable[[str], None] | None = print,
) -> None:
    """Advance simulated time in `dt` steps. `speed` = simulated seconds per wall second; None = flat out."""
    steps = int(hours * 3600 / dt)
    next_status = start_ts
    wall0 = time.monotonic()
    for i in range(steps):
        t = start_ts + i * dt
        bus.publish(SIM_TIME, {"t": t})  # controller ticks first, then the world reacts
        world.step(t, dt)
        if out and t >= next_status:
            out(world.status_line(t))
            next_status += status_every_s
        if speed:
            delay = wall0 + (i + 1) * dt / speed - time.monotonic()
            if delay > 0:
                time.sleep(delay)
