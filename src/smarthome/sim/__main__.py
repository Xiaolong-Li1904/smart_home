"""Simulated house on a real MQTT broker. Start `python -m smarthome.controller --sim-clock` alongside it.

    python -m smarthome.sim --speed 60 --start "2026-11-13 17:00" --hours 6
"""

import argparse

from smarthome.bus import MqttBus
from smarthome.sim import Daylight, Occupant, World, parse_start, run


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default="localhost")
    ap.add_argument("--port", type=int, default=1883)
    ap.add_argument("--speed", type=float, default=60.0, help="simulated seconds per wall second")
    ap.add_argument("--start", default=None, help="'YYYY-MM-DD HH:MM' (default: today 00:00)")
    ap.add_argument("--hours", type=float, default=24.0)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--status-every", type=float, default=600.0, help="simulated seconds between status lines")
    args = ap.parse_args()

    start = parse_start(args.start)
    bus = MqttBus(args.host, args.port, client_id="sim")
    world = World(bus, Occupant(start, args.hours, args.seed), Daylight(args.seed))
    try:
        run(bus, world, start, args.hours, speed=args.speed, status_every_s=args.status_every)
    except KeyboardInterrupt:
        pass
    finally:
        print()
        print(world.summary())
        bus.close()


if __name__ == "__main__":
    main()
