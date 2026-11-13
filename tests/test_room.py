from datetime import datetime

from smarthome.controller import LightCommand, RoomConfig, RoomController

NOON = datetime(2026, 11, 13, 12, 0).timestamp()
MIDNIGHT = datetime(2026, 11, 13, 0, 30).timestamp()


def make(**kw) -> RoomController:
    return RoomController("hall", RoomConfig(off_delay_s=60, dark_lux=50, **kw))


def test_dark_motion_turns_on_full_by_day():
    rc = make()
    rc.on_lux(10, NOON)
    assert rc.on_motion(True, NOON) == [LightCommand("hall", True, 255, 4000)]


def test_dim_at_night():
    rc = make()
    rc.on_lux(0, MIDNIGHT)
    assert rc.on_motion(True, MIDNIGHT) == [LightCommand("hall", True, 26, 2200)]


def test_bright_room_stays_off():
    rc = make()
    rc.on_lux(300, NOON)
    assert rc.on_motion(True, NOON) == []


def test_off_after_delay_and_not_before():
    rc = make()
    rc.on_lux(0, NOON)
    rc.on_motion(True, NOON)
    rc.on_motion(False, NOON + 10)
    assert rc.tick(NOON + 69) == []
    assert rc.tick(NOON + 70) == [LightCommand("hall", False)]


def test_return_cancels_countdown():
    rc = make()
    rc.on_lux(0, NOON)
    rc.on_motion(True, NOON)
    rc.on_motion(False, NOON + 10)
    assert rc.on_motion(True, NOON + 30) == []  # already on, nothing to send
    assert rc.tick(NOON + 1000) == []


def test_own_lamp_does_not_count_as_daylight():
    """The HA bug: re-trigger while lit must not be blocked by the lamp's own light."""
    rc = make()
    rc.on_lux(0, NOON)
    rc.on_motion(True, NOON)
    rc.on_lux(300, NOON + 1)  # the sensor now sees the lamp
    rc.on_motion(False, NOON + 5)
    rc.on_motion(True, NOON + 10)
    rc.on_motion(False, NOON + 20)
    assert rc.tick(NOON + 80) == [LightCommand("hall", False)]


def test_reentry_right_after_off_uses_no_stale_lux():
    rc = make()
    rc.on_lux(0, NOON)
    rc.on_motion(True, NOON)
    rc.on_lux(300, NOON + 1)
    rc.on_motion(False, NOON + 2)
    rc.tick(NOON + 62)  # off
    rc.on_lux(300, NOON + 62.5)  # stale reading from before the lamp went dark
    assert rc.on_motion(True, NOON + 63) == [LightCommand("hall", True, 255, 4000)]


def test_getting_dark_while_occupied_turns_on():
    rc = make()
    rc.on_lux(200, NOON)
    rc.on_motion(True, NOON)
    assert rc.on_lux(30, NOON + 600) == [LightCommand("hall", True, 255, 4000)]


def test_manual_on_in_empty_room_still_times_out():
    rc = make()
    rc.on_light_state(True, NOON)
    assert rc.tick(NOON + 60) == [LightCommand("hall", False)]
