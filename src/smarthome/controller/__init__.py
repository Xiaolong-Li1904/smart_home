from smarthome.controller.app import ControllerApp
from smarthome.controller.bedroom import BedroomController, WakeConfig
from smarthome.controller.room import Command, LightCommand, RoomConfig, RoomController, ShutterCommand
from smarthome.protocol import ROOMS


def default_configs(off_delay_s: float = 120.0, dark_lux: float = 50.0) -> dict[str, RoomConfig]:
    return {room: RoomConfig(off_delay_s=off_delay_s, dark_lux=dark_lux) for room in ROOMS}


__all__ = [
    "BedroomController", "Command", "ControllerApp", "LightCommand", "RoomConfig", "RoomController",
    "ShutterCommand", "WakeConfig", "default_configs",
]
