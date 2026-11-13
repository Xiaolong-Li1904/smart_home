"""Run the controller against an MQTT broker.

    python -m smarthome.controller              # wall clock (real hardware)
    python -m smarthome.controller --sim-clock  # follow sim/time from `python -m smarthome.sim`
"""

import argparse
import threading

from smarthome.bus import MqttBus
from smarthome.controller import ControllerApp, default_configs


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--host", default="localhost")
    ap.add_argument("--port", type=int, default=1883)
    ap.add_argument("--sim-clock", action="store_true", help="use simulated time from sim/time")
    ap.add_argument("--off-delay", type=float, default=120.0, help="seconds without motion before off")
    ap.add_argument("--dark-lux", type=float, default=50.0, help="below this the room counts as dark")
    args = ap.parse_args()

    bus = MqttBus(args.host, args.port, client_id="controller")
    app = ControllerApp(bus, default_configs(args.off_delay, args.dark_lux), sim_clock=args.sim_clock)
    print(f"controller up ({'sim' if args.sim_clock else 'wall'} clock), Ctrl+C to stop")
    try:
        if args.sim_clock:
            threading.Event().wait()  # sim/time messages drive everything
        else:
            app.run_forever()
    except KeyboardInterrupt:
        pass
    finally:
        bus.close()


if __name__ == "__main__":
    main()
