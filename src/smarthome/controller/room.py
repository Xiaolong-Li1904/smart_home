"""Per-room lighting logic as a pure state machine: events in, light commands out. No I/O, no clock.

Rules
- Occupied and dark -> on. Brightness and colour follow the time of day (dim and warm at night).
- Becoming dark while occupied also turns it on.
- Empty for `off_delay_s` -> off. Returning before that cancels the countdown.
- The lux sensor sees our own lamp, so lux is ignored while the light is on and for
  `lux_settle_s` after it goes off. Until a fresh reading arrives, the room counts as dark:
  a light that comes on needlessly is better than one that stays off when needed.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True)
class LightCommand:
    room: str
    on: bool
    brightness: int = 0  # 0-255, used only when on
    kelvin: int | None = None  # colour temperature; None = leave as is


@dataclass(frozen=True)
class ShutterCommand:
    room: str
    position: float  # 0 = closed, 100 = open


Command = LightCommand | ShutterCommand


@dataclass
class RoomConfig:
    off_delay_s: float = 120.0
    dark_lux: float = 50.0
    day_brightness: int = 255
    night_brightness: int = 26  # ~10 %
    night_start_h: int = 23
    night_end_h: int = 6
    evening_start_h: int = 19
    day_kelvin: int = 4000
    evening_kelvin: int = 2700
    night_kelvin: int = 2200
    lux_settle_s: float = 2.0


class RoomController:
    def __init__(self, room: str, cfg: RoomConfig | None = None) -> None:
        self.room = room
        self.cfg = cfg or RoomConfig()
        self.occupied = False
        self.light_on = False
        self.lux: float | None = None  # daylight-only reading; None = unknown
        self.off_at: float | None = None
        self._lux_valid_from = float("-inf")

    # ---- events ----------------------------------------------------------

    def on_motion(self, occupied: bool, now: float) -> list[Command]:
        self.occupied = occupied
        if occupied:
            self.off_at = None
            if not self.light_on and self._is_dark():
                return self._turn_on(now)
        elif self.light_on:
            self.off_at = now + self.cfg.off_delay_s
        return []

    def on_lux(self, lux: float, now: float) -> list[Command]:
        if self.light_on or now < self._lux_valid_from:
            return []
        self.lux = lux
        if self.occupied and self._is_dark():
            return self._turn_on(now)
        return []

    def on_light_state(self, on: bool, now: float) -> list[Command]:
        """The light reports what it is actually doing; e.g. a wall switch was used."""
        if on == self.light_on:
            return []
        if on:
            self.light_on = True
            if not self.occupied:
                self.off_at = now + self.cfg.off_delay_s
        else:
            self._mark_off(now)
        return []

    def tick(self, now: float) -> list[Command]:
        if self.off_at is not None and now >= self.off_at:
            self._mark_off(now)
            return [LightCommand(self.room, False)]
        return []

    # ---- helpers ---------------------------------------------------------

    def _is_dark(self) -> bool:
        return self.lux is None or self.lux < self.cfg.dark_lux

    def _is_night(self, now: float) -> bool:
        h = datetime.fromtimestamp(now).hour
        return h >= self.cfg.night_start_h or h < self.cfg.night_end_h

    def _brightness(self, now: float) -> int:
        return self.cfg.night_brightness if self._is_night(now) else self.cfg.day_brightness

    def _kelvin(self, now: float) -> int:
        if self._is_night(now):
            return self.cfg.night_kelvin
        if datetime.fromtimestamp(now).hour >= self.cfg.evening_start_h:
            return self.cfg.evening_kelvin
        return self.cfg.day_kelvin

    def _turn_on(self, now: float) -> list[Command]:
        self.light_on = True
        return [LightCommand(self.room, True, self._brightness(now), self._kelvin(now))]

    def _mark_off(self, now: float) -> None:
        self.light_on = False
        self.off_at = None
        self.lux = None  # last reading included the lamp
        self._lux_valid_from = now + self.cfg.lux_settle_s
