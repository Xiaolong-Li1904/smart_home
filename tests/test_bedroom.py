from datetime import datetime

import pytest

from smarthome.controller import BedroomController, LightCommand, ShutterCommand, WakeConfig

D = datetime(2026, 11, 13)
ALARM = datetime(2026, 11, 13, 7, 0).timestamp()
NIGHT = datetime(2026, 11, 13, 2, 0).timestamp()


def asleep(**wake) -> BedroomController:
    rc = BedroomController("bedroom", wake=WakeConfig(**wake))
    rc.on_shutter_state(100, False, NIGHT)
    rc.on_motion(True, NIGHT)
    rc.on_button("goodnight", NIGHT)
    rc.on_shutter_state(0, False, NIGHT)
    return rc


def lights(cmds):
    return [c for c in cmds if isinstance(c, LightCommand)]


def shutters(cmds):
    return [c for c in cmds if isinstance(c, ShutterCommand)]


def test_goodnight_turns_off_and_closes():
    rc = BedroomController("bedroom")
    rc.on_lux(0, NIGHT)
    rc.on_motion(True, NIGHT)
    cmds = rc.on_button("goodnight", NIGHT + 1)
    assert ShutterCommand("bedroom", 0) in cmds
    assert LightCommand("bedroom", False) in cmds
    assert rc.mode == "sleep"


def test_motion_in_sleep_mode_does_not_light_up():
    rc = asleep()
    assert rc.on_motion(False, NIGHT + 60) == []
    assert rc.on_motion(True, NIGHT + 300) == []  # back from the bathroom
    assert rc.tick(NIGHT + 600) == []


def test_sunrise_starts_on_time_and_ramps_up():
    rc = asleep()
    assert rc.tick(ALARM - 31 * 60) == []
    rc.on_lux(0, ALARM - 30 * 60)
    levels, kelvins = [], []
    for minutes_left in range(30, -1, -1):
        now = ALARM - minutes_left * 60
        for c in lights(rc.tick(now)):
            levels.append(c.brightness)
            kelvins.append(c.kelvin)
            rc.on_lux(c.brightness * 1.2, now)  # dark outside: the sensor sees only the lamp
    assert rc.mode == "wake"
    assert levels == sorted(levels) and kelvins == sorted(kelvins)
    assert kelvins[0] < 2300 and kelvins[-1] > 4300
    assert abs(levels[-1] * 1.2 - 250) < 5  # reaches max_lux at the alarm


def test_dark_outside_keeps_shutter_closed():
    rc = asleep()
    rc.on_outdoor_lux(1.0, ALARM - 600)
    for s in range(0, 600, 10):
        assert shutters(rc.tick(ALARM - 600 + s)) == []


def test_bright_outside_opens_shutter_and_dims_lamp():
    rc = asleep(c_init=0.02)
    rc.on_outdoor_lux(10_000, ALARM - 300)  # fully open would give 200 lx at the bed
    rc.on_lux(5, ALARM - 300)
    cmds = rc.tick(ALARM - 300)
    (sh,) = shutters(cmds)
    assert 0 < sh.position < 100
    # Pretend the shutter got there and daylight now covers most of the target.
    rc.on_shutter_state(sh.position, False, ALARM - 280)
    target, _ = rc.ramp(ALARM - 280)
    rc.on_lux(target * 0.9 + 1.2 * rc.lamp_level, ALARM - 280)  # the sensor sees daylight + lamp
    (lamp,) = lights(rc.tick(ALARM - 280)) or [None]
    assert lamp is None or lamp.brightness * 1.2 < target * 0.3


def test_shutter_never_closes_during_sunrise():
    rc = asleep()
    rc.on_outdoor_lux(20_000, ALARM - 600)
    positions = []
    for s in range(0, 600, 5):
        now = ALARM - 600 + s
        rc.on_outdoor_lux(20_000 if (s // 60) % 2 else 2_000, now)  # passing clouds
        for c in shutters(rc.tick(now)):
            positions.append(c.position)
            rc.on_shutter_state(c.position, False, now)
    assert positions == sorted(positions)


def test_alarm_stopped_ends_wake_and_opens():
    rc = asleep()
    rc.tick(ALARM - 600)
    assert rc.mode == "wake"
    assert rc.on_alarm_event("stopped", ALARM - 60) == [ShutterCommand("bedroom", 100)]
    assert rc.mode == "normal"
    assert rc.tick(ALARM) == []  # does not restart for the same alarm


def test_disabled_wake_stays_dark_until_alarm_stopped():
    rc = asleep(enabled=False)
    for s in range(0, 1800, 30):
        assert rc.tick(ALARM - 1800 + s) == []
    assert rc.on_alarm_event("stopped", ALARM + 30) == [ShutterCommand("bedroom", 100)]


@pytest.mark.parametrize("payload, attr, value", [
    ({"time": "06:15"}, "alarm", "06:15"),
    ({"enabled": False}, "enabled", False),
    ({"max_lux": 300}, "max_lux", 300.0),
])
def test_alarm_config(payload, attr, value):
    rc = BedroomController("bedroom")
    rc.on_alarm_config(payload)
    assert getattr(rc.wake, attr) == value
