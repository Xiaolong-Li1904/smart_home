"""Simulator and controller in one process on a LocalBus: a full day in a few seconds, no broker needed.

    python -m smarthome.offline --hours 24 --seed 3 -v
    python -m smarthome.offline --start "2026-06-21 00:00" --hours 9 --no-wake    # summer, no sunrise
"""

import argparse

from smarthome.bus import LocalBus
from smarthome.controller import ControllerApp, WakeConfig, default_configs
from smarthome.protocol import alarm_config_topic
from smarthome.sim import Occupant, Sky, World, parse_start, run


def simulate(start: float, hours: float, seed: int = 0, off_delay: float = 120.0, dark_lux: float = 50.0,
             alarm: str = "07:00", wake: bool = True, verbose: bool = False,
             status_every_s: float | None = 3600.0) -> World:
    bus = LocalBus()
    world = World(bus, Occupant(start, hours, seed, alarm), Sky(seed), dark_lux=dark_lux, seed=seed)
    ControllerApp(bus, default_configs(off_delay, dark_lux), WakeConfig(), sim_clock=True,
                  log=print if verbose else None)
    bus.publish(alarm_config_topic("bedroom"), {"time": alarm, "enabled": wake}, retain=True)
    run(bus, world, start, hours, status_every_s=status_every_s or 1e18, out=print if status_every_s else None)
    return world


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--start", default=None, help="'YYYY-MM-DD HH:MM' (default: today 00:00)")
    ap.add_argument("--hours", type=float, default=24.0)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--off-delay", type=float, default=120.0)
    ap.add_argument("--dark-lux", type=float, default=50.0)
    ap.add_argument("--alarm", default="07:00", help="daily alarm, HH:MM")
    ap.add_argument("--no-wake", action="store_true", help="alarm only, no sunrise")
    ap.add_argument("--status-every", type=float, default=3600.0, help="simulated seconds; 0 = off")
    ap.add_argument("-v", "--verbose", action="store_true", help="print every controller command")
    args = ap.parse_args()

    world = simulate(parse_start(args.start), args.hours, args.seed, args.off_delay, args.dark_lux,
                     args.alarm, not args.no_wake, args.verbose, args.status_every)
    print()
    print(world.summary())


if __name__ == "__main__":
    main()
