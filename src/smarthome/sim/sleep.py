"""A deliberately simple sleep model: ~90 min cycles, deep sleep early in the night, more REM towards morning.

Waking is a Poisson process whose rate depends on the stage and on the light reaching the eyes:
    rate = sensitivity[stage] * (base_rate + light_gain * bed_lux)
The numbers are rough and should later be fitted to real data (an exported Apple Health or Garmin night).
"""

from __future__ import annotations

import math
import random

SENSITIVITY = {"light": 1.0, "rem": 0.3, "deep": 0.05}


class SleepModel:
    def __init__(self, rng: random.Random, base_rate: float = 1.5e-5, light_gain: float = 1.7e-5) -> None:
        self.rng = rng
        self.base_rate = base_rate  # per second, in light sleep, in the dark
        self.light_gain = light_gain  # per second per lux (250 lx in light sleep -> wakes within ~4 min)
        self.reset()

    def reset(self) -> None:
        """Forget the night: next fall_asleep starts cycle 1."""
        self.asleep = False
        self.asleep_from = math.inf
        self.cycle_ref: float | None = None
        self.cycle_len = self.rng.uniform(85, 100) * 60

    def fall_asleep(self, t: float) -> None:
        self.asleep = True
        self.asleep_from = t + self.rng.uniform(600, 1200)  # sleep onset latency
        if self.cycle_ref is None:
            self.cycle_ref = self.asleep_from

    def wake_up(self) -> None:
        self.asleep = False

    def is_asleep(self, t: float) -> bool:
        return self.asleep and t >= self.asleep_from

    def stage(self, t: float) -> str:
        if not self.is_asleep(t):
            return "awake"
        x = (t - self.cycle_ref) / self.cycle_len
        n, phase = int(x), x - int(x)
        deep = max(0.0, 0.4 - 0.12 * n)
        rem = min(0.4, 0.1 + 0.08 * n)
        if phase < 0.1:
            return "light"
        if phase < 0.1 + deep:
            return "deep"
        if phase > 1 - rem:
            return "rem"
        return "light"

    def step(self, t: float, dt: float, bed_lux: float) -> bool:
        """Advance by dt; True if the sleeper wakes up during it."""
        stage = self.stage(t)
        if stage == "awake":
            return False
        rate = SENSITIVITY[stage] * (self.base_rate + self.light_gain * max(bed_lux, 0.0))
        if self.rng.random() < -math.expm1(-rate * dt):
            self.asleep = False
            return True
        return False
