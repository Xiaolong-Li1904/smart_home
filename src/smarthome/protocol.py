"""MQTT topics and payloads shared by the controller, simulated nodes and (later) ESP32 firmware.

Every payload is a JSON object.

    home/<room>/motion        node -> controller   {"occupied": bool}
    home/<room>/lux           node -> controller   {"lux": float}
    home/<room>/light/set     controller -> node   {"on": bool, "brightness": 0-255}  (brightness optional)
    home/<room>/light/state   node -> controller   {"on": bool, "brightness": 0-255}  (retained)
    sim/time                  simulator -> all     {"t": unix seconds}  (only when running on simulated time)
"""

from __future__ import annotations

from datetime import datetime

ROOMS = ("hallway", "living", "bedroom")

SIM_TIME = "sim/time"


def motion_topic(room: str) -> str:
    return f"home/{room}/motion"


def lux_topic(room: str) -> str:
    return f"home/{room}/lux"


def light_set_topic(room: str) -> str:
    return f"home/{room}/light/set"


def light_state_topic(room: str) -> str:
    return f"home/{room}/light/state"


def room_of(topic: str) -> str:
    """'home/hallway/light/state' -> 'hallway'."""
    return topic.split("/")[1]


def clock_str(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%H:%M:%S")
