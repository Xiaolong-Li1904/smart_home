"""MQTT topics and payloads shared by the controller, simulated nodes and (later) ESP32 firmware.

Every payload is a JSON object.

    home/<room>/motion          node -> controller   {"occupied": bool}
    home/<room>/lux             node -> controller   {"lux": float}
    home/outdoor/lux            node -> controller   {"lux": float}           (sensor outside the shutter)
    home/<room>/light/set       controller -> node   {"on": bool, "brightness": 0-255, "kelvin": int}  (last two optional)
    home/<room>/light/state     node -> controller   {"on": bool, "brightness": 0-255, "kelvin": int}  (retained)
    home/<room>/shutter/set     controller -> node   {"position": 0-100}      (0 = closed, 100 = open)
    home/<room>/shutter/state   node -> controller   {"position": 0-100, "moving": bool}  (retained)
    home/<room>/button          user -> controller   {"action": "goodnight"}  (bedside button or phone shortcut)
    home/<room>/alarm/config    user -> controller   {"time": "07:00", "enabled": bool, "sunrise_min": 30, "max_lux": 250}  (retained)
    home/<room>/alarm/event     user -> controller   {"type": "stopped" | "snoozed"}  (phone alarm, via HTTP bridge later)
    sim/time                    simulator -> all     {"t": unix seconds}  (only when running on simulated time)

Ground truth for visualization only; the controller must never read these (real hardware has no such topics):

    sim/occupant                simulator -> viewer  {"room": "bedroom" | "living" | "hallway" | "away", "asleep": bool}  (retained)
    sim/ambient                 simulator -> viewer  {"outdoor": lux, "rooms": {room: daylight lux}}  (retained)
"""

from __future__ import annotations

from datetime import datetime

ROOMS = ("hallway", "living", "bedroom")

SIM_TIME = "sim/time"
SIM_OCCUPANT = "sim/occupant"
SIM_AMBIENT = "sim/ambient"
OUTDOOR_LUX = "home/outdoor/lux"


def motion_topic(room: str) -> str:
    return f"home/{room}/motion"


def lux_topic(room: str) -> str:
    return f"home/{room}/lux"


def light_set_topic(room: str) -> str:
    return f"home/{room}/light/set"


def light_state_topic(room: str) -> str:
    return f"home/{room}/light/state"


def shutter_set_topic(room: str) -> str:
    return f"home/{room}/shutter/set"


def shutter_state_topic(room: str) -> str:
    return f"home/{room}/shutter/state"


def button_topic(room: str) -> str:
    return f"home/{room}/button"


def alarm_config_topic(room: str) -> str:
    return f"home/{room}/alarm/config"


def alarm_event_topic(room: str) -> str:
    return f"home/{room}/alarm/event"


def room_of(topic: str) -> str:
    """'home/hallway/light/state' -> 'hallway'."""
    return topic.split("/")[1]


def clock_str(ts: float) -> str:
    return datetime.fromtimestamp(ts).strftime("%H:%M:%S")
