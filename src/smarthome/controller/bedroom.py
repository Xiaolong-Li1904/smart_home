"""Bedroom: normal room lighting, plus a sleep mode and a sunrise wake-up using the lamp and the shutter.

Modes
- normal: plain RoomController behaviour.
- sleep:  entered on the "goodnight" button. Lamp off, shutter closed, motion ignored.
- wake:   from `sunrise_min` before the alarm. Bed-level illuminance follows a ramp from 0 to `max_lux`
          while the colour goes from warm to cool. Ends when the alarm is stopped, or `hold_min` after it.

Splitting the target between the shutter and the lamp
    The bed sensor measures daylight + lamp. With a calibrated lamp gain k_lamp (lux per brightness step),
    daylight at the bed is D = measured - k_lamp * level. Daylight is roughly c * outdoor * opening, with c
    learned online. The shutter opens just far enough for daylight to meet the target (only opening, in
    whole steps, so the motor does not chatter); the lamp makes up the rest, using measured D as feedback. When it is too
    dark outside to help, the shutter stays closed and the lamp does everything.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from datetime import datetime, timedelta

from smarthome.controller.room import Command, LightCommand, RoomConfig, RoomController, ShutterCommand


@dataclass
class WakeConfig:
    enabled: bool = True
    alarm: str = "07:00"  # daily, local time
    sunrise_min: float = 30.0
    hold_min: float = 30.0  # keep the end state this long after the alarm unless it is stopped
    max_lux: float = 250.0
    ramp_shape: float = 4.0  # 0 = linear; larger = slower start (brightness perception is ~logarithmic)
    kelvin_start: int = 2000
    kelvin_end: int = 4500
    k_lamp: float = 1.2  # bed lux per brightness step (calibrate once on real hardware)
    c_init: float = 0.02  # first guess: bed lux per outdoor lux with the shutter fully open
    c_rate: float = 0.1  # learning rate for that gain
    shutter_step: float = 10.0  # %; smaller changes are not worth running the motor for
    min_useful_lux: float = 5.0  # don't open the shutter if fully open would add less than this


class BedroomController(RoomController):
    def __init__(self, room: str, cfg: RoomConfig | None = None, wake: WakeConfig | None = None) -> None:
        super().__init__(room, cfg)
        self.wake = wake or WakeConfig()
        self.mode = "normal"
        self.bed_lux: float | None = None  # raw sensor, lamp included
        self.outdoor: float | None = None
        self.shutter_pos: float | None = None
        self.shutter_moving = False
        self.lamp_level = 0
        self.lamp_kelvin: int | None = None
        self.c_hat = self.wake.c_init
        self.target_lux = 0.0  # current ramp target, for logging and plots
        self._alarm_t: float | None = None  # alarm of the wake-up in progress
        self._done_alarm_t: float | None = None  # last alarm already handled

    # ---- events ----------------------------------------------------------

    def on_motion(self, occupied: bool, now: float) -> list[Command]:
        if self.mode == "normal":
            return super().on_motion(occupied, now)
        self.occupied = occupied
        return []

    def on_lux(self, lux: float, now: float) -> list[Command]:
        self.bed_lux = lux
        if self.mode == "normal":
            return super().on_lux(lux, now)
        return []

    def on_outdoor_lux(self, lux: float, now: float) -> list[Command]:
        self.outdoor = lux
        return []

    def on_shutter_state(self, position: float, moving: bool, now: float) -> list[Command]:
        self.shutter_pos, self.shutter_moving = position, moving
        return []

    def on_button(self, action: str, now: float) -> list[Command]:
        if action != "goodnight":
            return []
        self.mode = "sleep"
        cmds: list[Command] = [ShutterCommand(self.room, 0)]
        if self.light_on:
            self._mark_off(now)
            cmds.append(LightCommand(self.room, False))
        return cmds

    def on_alarm_config(self, payload: dict) -> None:
        if "time" in payload:
            self.wake.alarm = str(payload["time"])
        for key in ("enabled", "sunrise_min", "max_lux", "hold_min"):
            if key in payload:
                setattr(self.wake, key, type(getattr(self.wake, key))(payload[key]))

    def on_alarm_event(self, kind: str, now: float) -> list[Command]:
        if kind == "stopped" and self.mode in ("sleep", "wake"):
            return self._finish(now)
        return []

    def tick(self, now: float) -> list[Command]:
        alarm = self._alarm_window(now)
        if self.mode == "wake":
            return self._wake_step(now)
        if self.mode == "sleep":
            if alarm is not None and now > alarm + self.wake.hold_min * 60:
                return self._finish(now)  # nobody stopped the alarm; don't stay in sleep mode all day
            if alarm is not None and self.wake.enabled and now >= alarm - self.wake.sunrise_min * 60:
                self.mode, self._alarm_t = "wake", alarm
                return self._wake_step(now)
            return []
        cmds = super().tick(now)
        # Wake-up also runs without "goodnight", as long as someone is in the bedroom.
        if alarm is not None and self.wake.enabled and self.occupied and now <= alarm:
            self.mode, self._alarm_t = "wake", alarm
            self.off_at = None
            cmds += self._wake_step(now)
        return cmds

    # ---- wake-up ---------------------------------------------------------

    def _alarm_window(self, now: float) -> float | None:
        """The alarm whose [start of sunrise, alarm + hold] window contains `now`, unless already handled."""
        h, m = (int(x) for x in self.wake.alarm.split(":"))
        day = datetime.fromtimestamp(now).replace(hour=h, minute=m, second=0, microsecond=0)
        for d in (0, 1):  # tomorrow's alarm, when the sunrise starts before midnight
            t = (day + timedelta(days=d)).timestamp()
            if t - self.wake.sunrise_min * 60 <= now <= t + self.wake.hold_min * 60 and t != self._done_alarm_t:
                return t
        return None

    def ramp(self, now: float) -> tuple[float, int]:
        """(target bed lux, kelvin) of the sunrise at `now`."""
        w = self.wake
        span = w.sunrise_min * 60
        tau = min(max((now - (self._alarm_t - span)) / span, 0.0), 1.0)
        a = w.ramp_shape
        shape = tau if a == 0 else math.expm1(a * tau) / math.expm1(a)
        return w.max_lux * shape, round(w.kelvin_start + (w.kelvin_end - w.kelvin_start) * tau)

    def _wake_step(self, now: float) -> list[Command]:
        w = self.wake
        if now > self._alarm_t + w.hold_min * 60:
            return self._finish(now)
        target, kelvin = self.ramp(now)
        self.target_lux = target
        cmds: list[Command] = []

        daylight = max(0.0, (self.bed_lux or 0.0) - w.k_lamp * (self.lamp_level if self.light_on else 0))
        pos = self.shutter_pos if self.shutter_pos is not None else 0.0
        outdoor = self.outdoor or 0.0

        # Learn how much of the outdoor light reaches the bed, from the shutter at rest.
        if pos >= 20 and outdoor > 50 and not self.shutter_moving:
            self.c_hat += w.c_rate * (daylight / (outdoor * pos / 100) - self.c_hat)

        # Shutter: feedforward from the outdoor sensor. The target only rises during a sunrise, so the
        # shutter only opens, and only by whole steps: no hunting around a step boundary, few motor starts.
        # Short dips (clouds) are the lamp's job.
        potential = self.c_hat * outdoor  # bed lux with the shutter fully open
        want = min(target / potential, 1.0) * 100 if potential >= w.min_useful_lux else 0.0
        if self.shutter_pos is not None and not self.shutter_moving and want >= pos + w.shutter_step:
            cmds.append(ShutterCommand(self.room, min(100.0, math.floor(want / w.shutter_step) * w.shutter_step)))

        # Lamp: whatever daylight does not cover, with the measured daylight as feedback.
        level = int(round(min(max((target - daylight) / w.k_lamp, 0.0), 255.0)))
        if level < 1:
            if self.light_on:
                self._mark_off(now)
                self.lamp_level = 0
                cmds.append(LightCommand(self.room, False))
        elif (not self.light_on or abs(level - self.lamp_level) >= 2
              or self.lamp_kelvin is None or abs(kelvin - self.lamp_kelvin) >= 100):
            self.light_on, self.lamp_level, self.lamp_kelvin = True, level, kelvin
            cmds.append(LightCommand(self.room, True, level, kelvin))
        return cmds

    def _finish(self, now: float) -> list[Command]:
        self._done_alarm_t = self._alarm_t if self._alarm_t is not None else self._alarm_window(now)
        self.mode, self._alarm_t, self.target_lux = "normal", None, 0.0
        if self.light_on and not self.occupied:
            self.off_at = now + self.cfg.off_delay_s
        return [ShutterCommand(self.room, 100)]

    # Keep lamp bookkeeping in sync with the base class.
    def _turn_on(self, now: float) -> list[Command]:
        cmds = super()._turn_on(now)
        self.lamp_level, self.lamp_kelvin = cmds[0].brightness, cmds[0].kelvin
        return cmds

    def _mark_off(self, now: float) -> None:
        super()._mark_off(now)
        self.lamp_level = 0
