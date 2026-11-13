"""One occupant following a randomized weekday routine.

Locations: 'bedroom', 'living', 'hallway', 'away'. Every room connects through the hallway, so moving
between two other locations passes through it for a few seconds.

Each night runs from pressing "goodnight" to getting up a few minutes after the alarm. Whether and when
the occupant actually wakes is decided by the world's sleep model, not here.
"""

from __future__ import annotations

import bisect
import math
import random
from datetime import datetime, timedelta
from typing import NamedTuple


class Night(NamedTuple):
    goodnight: float  # presses the goodnight button
    alarm: float
    getup: float  # leaves the bedroom


def _hm(h: float, m: float = 0) -> float:
    return h * 3600 + m * 60


def parse_hhmm(s: str) -> float:
    h, m = s.split(":")
    return _hm(int(h), int(m))


def day_plan(rng: random.Random, alarm_s: float) -> tuple[list[tuple[float, str]], float, float]:
    """(waypoints as (seconds since midnight, location), getup, goodnight) for one day."""
    plan = [(0.0, "bedroom")]

    if rng.random() < 0.5:  # night trip to the kitchen
        t = _hm(3) + rng.uniform(-3600, 3600)
        plan += [(t, "hallway"), (t + rng.uniform(60, 240), "bedroom")]

    getup = alarm_s + rng.uniform(180, 600)
    plan.append((getup, "living"))  # breakfast
    t = getup + rng.uniform(1800, 2700)
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
    goodnight = bed + rng.uniform(300, 1200)  # reads a bit first
    return plan, getup, goodnight


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
    def __init__(self, start_ts: float, hours: float, seed: int = 0, alarm: str = "07:00") -> None:
        rng = random.Random(seed)
        alarm_s = parse_hhmm(alarm)
        midnight = datetime.fromtimestamp(start_ts).replace(hour=0, minute=0, second=0, microsecond=0)
        n_days = math.ceil((start_ts - midnight.timestamp() + hours * 3600) / 86400)
        events: list[tuple[float, str]] = []
        self.nights: list[Night] = []
        goodnight = midnight.timestamp() - 3600  # already in bed when the simulation starts
        for d in range(n_days + 1):
            day0 = (midnight + timedelta(days=d)).timestamp()
            plan, getup, next_goodnight = day_plan(rng, alarm_s)
            self.nights.append(Night(goodnight, day0 + alarm_s, day0 + getup))
            if d < n_days:
                events += [(day0 + t, loc) for t, loc in with_transits(plan, rng)]
            goodnight = day0 + next_goodnight
        events.sort(key=lambda e: e[0])
        self._times = [t for t, _ in events]
        self._locs = [loc for _, loc in events]

    def location(self, ts: float) -> str:
        i = bisect.bisect_right(self._times, ts) - 1
        return self._locs[max(i, 0)]

    def night_at(self, ts: float) -> Night | None:
        for n in self.nights:
            if n.goodnight <= ts < n.getup:
                return n
        return None
