from datetime import datetime

import pytest

from smarthome.bus import LocalBus, topic_matches
from smarthome.offline import simulate
from smarthome.protocol import ROOMS

START = datetime(2026, 11, 13).timestamp()


def test_topic_matches():
    assert topic_matches("home/+/motion", "home/hallway/motion")
    assert not topic_matches("home/+/motion", "home/hallway/light/state")
    assert topic_matches("home/#", "home/hallway/light/state")
    assert not topic_matches("home/+", "home/a/b")


def test_local_bus_queues_nested_publishes():
    bus, seen = LocalBus(), []
    bus.subscribe("a", lambda t, p: (seen.append("a"), bus.publish("b", {})))
    bus.subscribe("a", lambda t, p: seen.append("a2"))
    bus.subscribe("b", lambda t, p: seen.append("b"))
    bus.publish("a", {})
    assert seen == ["a", "a2", "b"]  # 'b' waits until every 'a' handler has run


@pytest.mark.parametrize("seed", [0, 1, 2])
def test_full_day(seed):
    off_delay = 120
    world = simulate(START, 24, seed, off_delay, 50, status_every_s=None)
    for r in ROOMS:
        m = world.metrics[r]
        # Each departure wastes at most the off delay (+1 s step granularity).
        assert m.wasted_s <= m.vacated * (off_delay + 1), r
        # The light reacts within a step of entering a dark room.
        assert m.dark_s <= 2 * world.lights[r].on_count + 5, r
    assert world.lights["hallway"].on_count > 0
