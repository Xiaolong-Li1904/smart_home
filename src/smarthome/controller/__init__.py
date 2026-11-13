from smarthome.controller.app import ControllerApp
from smarthome.controller.room import LightCommand, RoomConfig, RoomController
from smarthome.protocol import ROOMS


def default_configs(off_delay_s: float = 120.0, dark_lux: float = 50.0) -> dict[str, RoomConfig]:
    return {room: RoomConfig(off_delay_s=off_delay_s, dark_lux=dark_lux) for room in ROOMS}


__all__ = ["ControllerApp", "LightCommand", "RoomConfig", "RoomController", "default_configs"]
