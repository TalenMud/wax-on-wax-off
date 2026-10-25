"""Leader -> follower teleoperation for both Metal arms, as MakerMods Lab does it, on SocketCAN.

    python -m brain.arm.teleop identify      # read-only: wiggle the LEFT leader, see its port
    python -m brain.arm.teleop run --left-leader /dev/ttyUSB1 --right-leader /dev/ttyUSB0

The followers use brain/arm/dodge.py's settings (Lab gains, max_relative_target lead cap, torque
off on exit); the Lab's slow startup sync brings each follower to its leader gently before full
speed tracking. Ctrl+C or SIGTERM turns torque off.
"""

import argparse
import glob
import signal
import time

from .dodge import CALIBRATION, MAX_LEAD_DEG
from .policy_run import can_port

HZ = 60


def leader(port: str, side: str):
    from lerobot.teleoperators.rebot_102_leader.config_rebot_102_leader_metal import (
        RebotArm102LeaderMetalTeleopConfig,
    )
    from lerobot.teleoperators.rebot_102_leader import RebotArm102Leader

    return RebotArm102Leader(RebotArm102LeaderMetalTeleopConfig(id=CALIBRATION[side], port=port))


def cmd_identify(args) -> None:
    ports = sorted(glob.glob("/dev/ttyUSB*"))
    leaders = {p: leader(p, "left") for p in ports}
    for p, ld in leaders.items():
        ld.connect(calibrate=False)
    print(f"Leaders on {ports}. Wiggle the LEFT leader for the next 6 s...")
    lo, hi = {}, {}
    end = time.monotonic() + 6
    while time.monotonic() < end:
        for p, ld in leaders.items():
            for k, v in ld.get_action().items():
                lo[(p, k)] = min(lo.get((p, k), v), v)
                hi[(p, k)] = max(hi.get((p, k), v), v)
        time.sleep(0.02)
    for p in ports:
        moved = max(hi[(p, k)] - lo[(p, k)] for (pp, k) in lo if pp == p)
        print(f"  {p}: moved up to {moved:.1f} deg")
    for ld in leaders.values():
        ld.disconnect()


def cmd_run(args) -> None:
    from lerobot.robots.metal_follower import MetalFollower, MetalFollowerConfig

    pairs = {}
    for side, port in (("left", args.left_leader), ("right", args.right_leader)):
        f = MetalFollower(
            MetalFollowerConfig(
                id=CALIBRATION[side],
                port=can_port(side),
                can_interface="socketcan",
                max_relative_target=MAX_LEAD_DEG,
                disable_torque_on_disconnect=True,
            )
        )
        pairs[side] = (leader(port, side), f)
    stopping = False

    def on_signal(*_):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGTERM, on_signal)
    try:
        for ld, f in pairs.values():
            ld.connect(calibrate=False)
            f.connect(calibrate=False)
        print("teleop running; Ctrl+C to stop", flush=True)
        n = 0
        while not stopping:
            t0 = time.monotonic()
            for ld, f in pairs.values():
                f.send_action(ld.get_action())
            n += 1
            if n % (HZ * 10) == 0:
                print(f"teleop ok, {n // HZ} s", flush=True)
            time.sleep(max(0.0, 1 / HZ - (time.monotonic() - t0)))
    finally:
        for ld, f in pairs.values():
            for dev in (f, ld):
                try:
                    dev.disconnect()
                except Exception as e:  # keep going: the other arm's torque must still go off
                    print(f"disconnect error: {e}")
        print("torque off", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["identify", "run"])
    ap.add_argument("--left-leader", default="/dev/ttyUSB1")
    ap.add_argument("--right-leader", default="/dev/ttyUSB0")
    args = ap.parse_args()
    {"identify": cmd_identify, "run": cmd_run}[args.cmd](args)


if __name__ == "__main__":
    main()
