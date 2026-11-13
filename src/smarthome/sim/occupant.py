"""One occupant following a randomized weekday routine.

Locations: 'bedroom', 'living', 'hallway', 'away'. Every room connects through the hallway, so moving
between two other locations passes through it for a few seconds.
"""

from __future__ import annotations

import bisect
import math
import random
from datetime import datetime, timedelta


def _hm(h: float, m: float = 0) -> float:
    return h * 3600 + m * 60


def day_plan(rng: random.Random) -> list[tuple[float, str]]:
    """(seconds since midnight, location) waypoints for one day."""
    plan = [(0.0, "bedroom")]

    if rng.random() < 0.5:  # night trip to the kitchen
        t = _hm(3) + rng.uniform(-3600, 3600)
        plan += [(t, "hallway"), (t + rng.uniform(60, 240), "bedroom")]

    wake = _hm(7) + rng.uniform(-1200, 1200)
    plan.append((wake, "living"))  # breakfast
    t = wake + rng.uniform(1800, 2700)
    plan.append((t, "bedroom"))  # get dressed
    t += rng.uniform(300, 900)
    plan.append((t, "away"))

    back = _hm(18) + rng.uniform(-3600, 3600)
    bed = _hm(23) + rng.uniform(-1800, 1800)
    plan.append((back, "living"))
    t = back
    while True:  # evening: mostly living room, with short trips
        t += rng.uniform(1200, 3600)
        if t > bed - 600:
            break
        if rng.random() < 0.3:
            plan.append((t, "bedroom"))
            t += rng.uniform(120, 600)
        else:
            plan.append((t, "hallway"))
            t += rng.uniform(60, 300)
        plan.append((t, "living"))
    plan.append((bed, "bedroom"))
    return plan


def with_transits(plan: list[tuple[float, str]], rng: random.Random) -> list[tuple[float, str]]:
    out: list[tuple[float, str]] = []
    prev = None
    for t, loc in plan:
        if prev is not None and loc != prev and "hallway" not in (loc, prev):
            out.append((t, "hallway"))
            t += rng.uniform(8, 20)
        out.append((t, loc))
        prev = loc
    return out


class Occupant:
    def __init__(self, start_ts: float, hours: float, seed: int = 0) -> None:
        rng = random.Random(seed)
        midnight = datetime.fromtimestamp(start_ts).replace(hour=0, minute=0, second=0, microsecond=0)
        n_days = math.ceil((start_ts - midnight.timestamp() + hours * 3600) / 86400)
        events: list[tuple[float, str]] = []
        for d in range(n_days):
            day0 = (midnight + timedelta(days=d)).timestamp()
            events += [(day0 + t, loc) for t, loc in with_transits(day_plan(rng), rng)]
        events.sort(key=lambda e: e[0])
        self._times = [t for t, _ in events]
        self._locs = [loc for _, loc in events]

    def location(self, ts: float) -> str:
        i = bisect.bisect_right(self._times, ts) - 1
        return self._locs[max(i, 0)]
