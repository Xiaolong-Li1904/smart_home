"""Simulator and controller in one process on a LocalBus: a full day in a few seconds, no broker needed.

    python -m smarthome.offline --hours 24 --seed 3 -v
"""

import argparse

from smarthome.bus import LocalBus
from smarthome.controller import ControllerApp, default_configs
from smarthome.sim import Daylight, Occupant, World, parse_start, run


def simulate(start: float, hours: float, seed: int, off_delay: float, dark_lux: float,
             verbose: bool = False, status_every_s: float | None = 3600.0) -> World:
    bus = LocalBus()
    world = World(bus, Occupant(start, hours, seed), Daylight(seed), dark_lux=dark_lux)
    ControllerApp(bus, default_configs(off_delay, dark_lux), sim_clock=True, log=print if verbose else None)
    run(bus, world, start, hours, status_every_s=status_every_s or 1e18, out=print if status_every_s else None)
    return world


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--start", default=None, help="'YYYY-MM-DD HH:MM' (default: today 00:00)")
    ap.add_argument("--hours", type=float, default=24.0)
    ap.add_argument("--seed", type=int, default=0)
    ap.add_argument("--off-delay", type=float, default=120.0)
    ap.add_argument("--dark-lux", type=float, default=50.0)
    ap.add_argument("--status-every", type=float, default=3600.0, help="simulated seconds; 0 = off")
    ap.add_argument("-v", "--verbose", action="store_true", help="print every controller command")
    args = ap.parse_args()

    world = simulate(parse_start(args.start), args.hours, args.seed, args.off_delay, args.dark_lux,
                     args.verbose, args.status_every)
    print()
    print(world.summary())


if __name__ == "__main__":
    main()
