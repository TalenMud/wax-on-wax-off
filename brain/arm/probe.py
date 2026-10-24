"""Read-only probe of a reBot B601-RS arm. Never enables torque or sends motion.

    python -m brain.arm.probe can0            # one read of all joints
    python -m brain.arm.probe can0 --watch    # live readout; move the arm by hand

Uses only RobStride type-0 (get device ID) and type-17 (read parameter) frames.
It deliberately avoids RebotB601Follower.connect(), which enables torque.
"""

import argparse
import math
import time

from motorbridge import Controller

from .interface import JOINT_NAMES

# RobStride parameter index for mechanical position (rad), from the RS00/RS06 manuals.
PARAM_MECH_POS = 0x7019
HOST_ID = 0xFD
# Same IDs and models as lerobot's RS_PROFILE.
MOTOR_MODELS = {
    "shoulder_pan": "rs-06",
    "shoulder_lift": "rs-06",
    "elbow_flex": "rs-06",
    "wrist_flex": "rs-00",
    "wrist_yaw": "rs-00",
    "wrist_roll": "rs-00",
    "gripper": "rs-00",
}


def read_all(motors: dict) -> dict[str, float | str]:
    out: dict[str, float | str] = {}
    for name, motor in motors.items():
        try:
            out[name] = math.degrees(motor.robstride_get_param_f32(PARAM_MECH_POS, timeout_ms=100))
        except Exception as e:  # noqa: BLE001 - report every joint, keep going
            out[name] = f"ERR {e}"
    return out


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("channel", help="SocketCAN channel, e.g. can0")
    parser.add_argument("--watch", action="store_true")
    args = parser.parse_args()

    bus = Controller(channel=args.channel)
    motors = {
        name: bus.add_robstride_motor(i, HOST_ID, MOTOR_MODELS[name]) for i, name in enumerate(JOINT_NAMES, start=1)
    }
    try:
        print(f"[{args.channel}] ping:")
        for name, motor in motors.items():
            try:
                print(f"  {name:14s} id={motor.robstride_ping()}")
            except Exception as e:  # noqa: BLE001
                print(f"  {name:14s} NO REPLY ({e})")

        while True:
            pos = read_all(motors)
            line = "  ".join(f"{n}={v:7.2f}" if isinstance(v, float) else f"{n}={v}" for n, v in pos.items())
            print(f"[{args.channel}] {line}", flush=True)
            if not args.watch:
                break
            time.sleep(0.2)
    except KeyboardInterrupt:
        pass
    finally:
        for motor in motors.values():
            motor.close()
        bus.close()


if __name__ == "__main__":
    main()
