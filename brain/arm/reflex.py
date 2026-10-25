"""Reflex dodge: the headset sees a punch coming, the arm moves to a pose a person taught it.

    python -m brain.arm.reflex teach --arms left        # torque off: push the arm into each pose, Enter
    python -m brain.arm.reflex run --arms left --speed 60
    python -m brain.arm.reflex poke left                # one threat, for tests without the headset

The trigger is vr/trainer.html maybeDodge(): a glove closing fast on a pad becomes POST /rig/threat,
which tools/serve_xr.py (--arm-host) sends here over UDP as {"t": "threat", "arm"}, with a 20 Hz
{"t": "hb"} heartbeat. On a threat the arm goes to one of its taught dodge poses (picked at random),
holds HOLD_S and comes back to guard.

Safety: every pose the arm is sent to is one a person placed it in with torque off (no IK), or a
straight line in joint space between two of them. Taught poses must clear the table and keep the
elbow off the base. Torque turns off on Ctrl+C / SIGTERM, a lost heartbeat (WATCHDOG_S), a measured
point near the table, or an arm lagging its command (stuck or blocked). Every run asks for "go".
"""

import argparse
import json
import math
import random
import signal
import socket
import sys
import time
from pathlib import Path

import numpy as np

from .dodge import ACCEL_TIME_S, CALIBRATION, MAX_LEAD_DEG
from .kinematics import MOTORS, Chain
from .policy_run import FLOOR_CLEARANCE, LAG_TRIP_DEG, LAG_TRIP_S, REST_CLEARANCE_DEG, SIDES, TRIP_CLEARANCE, can_port, read_only_state

POSES = Path.home() / ".config" / "wax-on-wax-off" / "reflex_poses.json"
FLOOR_Z = {"left": 0.082, "right": 0.055}  # table height per arm base frame, measured with policy_run watch
UDP_PORT = 9310
WATCHDOG_S = 0.5
HZ = 50
HOLD_S = 0.6  # matches DODGE_MS in vr/trainer.html
APPROACH_SPEED = 20.0  # deg/s to guard at the start and back to rest at the end
ELBOW = MOTORS.index("elbow_flex")


def pose_problem(chain: Chain, side: str, deg: np.ndarray) -> str | None:
    """Why a pose is unsafe to command, or None."""
    z = float(chain.points(np.radians(deg))[:, 2].min())
    if z < FLOOR_Z[side] + FLOOR_CLEARANCE:
        return f"lowest point {z:.3f} m is within {FLOOR_CLEARANCE * 100:.0f} cm of the table"
    if deg[ELBOW] < REST_CLEARANCE_DEG:
        return f"elbow {deg[ELBOW]:.0f} deg is folded onto the base"
    return None


def cmd_teach(args) -> None:
    chain = Chain()
    poses = json.loads(POSES.read_text()) if POSES.exists() else {}
    print("Torque stays OFF. Push the arm by hand into each pose and press Enter (s + Enter skips).")
    for side in args.arms:
        taught = {"guard": None, "dodges": []}
        for name in ["guard"] + [f"dodge {i + 1}" for i in range(args.dodges)]:
            while True:
                answer = input(f"{side} arm: hold it in {name.upper()}, then Enter: ").strip().lower()
                if answer == "s":
                    break
                deg = read_only_state(side)[0][:6]
                problem = pose_problem(chain, side, deg)
                if problem:
                    print(f"  not saved: {problem}. Try again.")
                    continue
                print(f"  saved {name}: " + ", ".join(f"{m} {v:.0f}" for m, v in zip(MOTORS, deg)))
                if name == "guard":
                    taught["guard"] = [round(float(v), 1) for v in deg]
                else:
                    taught["dodges"].append([round(float(v), 1) for v in deg])
                break
        if taught["guard"] and taught["dodges"]:
            poses[side] = taught
        else:
            print(f"{side}: needs a guard and at least one dodge; nothing saved for it")
    POSES.parent.mkdir(parents=True, exist_ok=True)
    POSES.write_text(json.dumps(poses, indent=1))
    print(f"saved to {POSES}")


class ReflexArm:
    """One arm: holds guard, dodges to a taught pose on a threat, comes back."""

    def __init__(self, side: str, poses: dict, speed: float) -> None:
        from lerobot.robots.metal_follower import MetalFollower, MetalFollowerConfig

        self.side = side
        self.guard = np.array(poses["guard"])
        self.dodges = [np.array(d) for d in poses["dodges"]]
        self.speed = speed
        self.v = 0.0
        self.robot = MetalFollower(
            MetalFollowerConfig(
                id=CALIBRATION[side],
                port=can_port(side),
                can_interface="socketcan",
                max_relative_target=MAX_LEAD_DEG,
                disable_torque_on_disconnect=True,
            )
        )
        self.state, self.until = "approach", 0.0
        self.lag_since: float | None = None

    def measured(self) -> np.ndarray:
        o = self.robot.get_observation()
        return np.array([o[f"{m}.pos"] for m in MOTORS])

    def connect(self) -> None:
        self.robot.connect(calibrate=False)
        o = self.robot.get_observation()
        self.gripper = o["gripper.pos"]  # holds the pad as mounted
        self.rest = np.array([o[f"{m}.pos"] for m in MOTORS])
        self.cmd = self.rest.copy()
        self.goal = self.guard

    def move_towards(self, goal: np.ndarray, speed: float) -> bool:
        """One tick along the straight joint-space line to goal: the leading joint ramps up to
        speed and brakes in time (trapezoid), all joints arrive together. True on arrival."""
        delta = goal - self.cmd
        dist = float(np.abs(delta).max())
        accel = speed / ACCEL_TIME_S
        self.v = min(speed, self.v + accel / HZ, math.sqrt(2 * accel * dist))
        step = self.v / HZ
        done = dist <= max(step, 0.05)
        self.cmd = goal.copy() if done else self.cmd + delta * (step / dist)
        if done:
            self.v = 0.0
        action = {f"{m}.pos": float(v) for m, v in zip(MOTORS, self.cmd)}
        action["gripper.pos"] = self.gripper
        self.robot.send_action(action)
        return done

    def threat(self) -> bool:
        if self.state != "guard":
            return False
        self.goal = random.choice(self.dodges)
        self.state = "out"
        return True

    def tick(self, now: float) -> None:
        if self.state == "approach":
            if self.move_towards(self.guard, APPROACH_SPEED):
                self.state = "guard"
                print(f"{self.side}: in guard, dodging on threats", flush=True)
        elif self.state == "guard":
            self.move_towards(self.guard, self.speed)
        elif self.state == "out":
            if self.move_towards(self.goal, self.speed):
                self.state, self.until = "hold", now + HOLD_S
        elif self.state == "hold":
            self.move_towards(self.goal, self.speed)
            if now >= self.until:
                self.state = "back"
        elif self.state == "back":
            if self.move_towards(self.guard, self.speed):
                self.state = "guard"

    def trip(self, chain: Chain, now: float) -> str | None:
        """A reason to turn torque off now, from the measured joints."""
        q = self.measured()
        z = float(chain.points(np.radians(q))[:, 2].min())
        if z < FLOOR_Z[self.side] + TRIP_CLEARANCE:
            return f"{self.side} measured z={z:.3f} m, at the table"
        lag = float(np.abs(q - self.cmd).max())
        if lag > LAG_TRIP_DEG:
            self.lag_since = self.lag_since or now
            if now - self.lag_since > LAG_TRIP_S:
                return f"{self.side} lags its command by {lag:.0f} deg"
        else:
            self.lag_since = None
        return None

    def park(self) -> None:
        """Back to where it started (resting), slowly, before torque goes off. Gives up after 10 s."""
        end = time.monotonic() + 10.0
        while not self.move_towards(self.rest, APPROACH_SPEED) and time.monotonic() < end:
            time.sleep(1 / HZ)

    def stop(self) -> None:
        try:
            self.robot.disconnect()  # disable_torque_on_disconnect=True
        except Exception as e:  # keep going: the other arm's torque must still go off
            print(f"{self.side}: disconnect error {e}", file=sys.stderr)


def cmd_run(args) -> None:
    chain = Chain()
    if not POSES.exists():
        sys.exit(f"no taught poses: run `python -m brain.arm.reflex teach` first ({POSES})")
    poses = json.loads(POSES.read_text())
    missing = [s for s in args.arms if s not in poses]
    if missing:
        sys.exit(f"no taught poses for {missing}: run teach for them first")
    for side in args.arms:  # taught poses are re-checked: the floor values may have changed since
        for deg in [poses[side]["guard"], *poses[side]["dodges"]]:
            problem = pose_problem(chain, side, np.array(deg))
            if problem:
                sys.exit(f"{side} taught pose {deg} is unsafe now: {problem}. Teach it again.")
        read_only_state(side)  # pre-flight: every motor answers
    print(f"Arms {list(args.arms)} get torque, move at {APPROACH_SPEED:.0f} deg/s to their taught guard, then on each")
    print(f"threat move at up to {args.speed:.0f} deg/s to a taught dodge pose, hold {HOLD_S} s and come back.")
    print("Torque off on Ctrl+C, " + ("" if args.no_heartbeat else f"no laptop heartbeat for {WATCHDOG_S} s, ")
          + "a point near the table, or an arm lagging its command. Someone must be at the arm power.")
    try:
        answer = input('Type "go" to enable torque: ').strip()
    except EOFError:
        answer = ""
    if answer != "go":
        print("Not started.")
        return

    stopping = False

    def on_signal(*_):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGTERM, on_signal)
    sock = socket.socket(socket.AF_INET6, socket.SOCK_DGRAM)
    sock.setsockopt(socket.IPPROTO_IPV6, socket.IPV6_V6ONLY, 0)  # IPv4 and IPv6 (link-local) senders
    sock.bind(("::", UDP_PORT))
    sock.setblocking(False)
    arms: dict[str, ReflexArm] = {}
    tripped = False
    try:
        for side in args.arms:
            speed = args.right_speed if side == "right" and args.right_speed else args.speed
            arms[side] = ReflexArm(side, poses[side], speed)
            arms[side].connect()
        print(f"torque on; listening on udp/{UDP_PORT}", flush=True)
        last_hb = time.monotonic() + 3.0  # grace period to start the laptop side
        while not stopping:
            t0 = time.monotonic()
            while True:
                try:
                    msg = json.loads(sock.recv(256))
                except BlockingIOError:
                    break
                except ValueError:
                    continue
                if msg.get("t") == "hb":
                    last_hb = t0
                elif msg.get("t") == "threat" and msg.get("arm") in arms:
                    if arms[msg["arm"]].threat():
                        print(f"dodge {msg['arm']}", flush=True)
                elif msg.get("t") == "stop":
                    print("stop message", flush=True)
                    stopping = True
            if not args.no_heartbeat and t0 - last_hb > WATCHDOG_S:
                print("laptop heartbeat lost: torque off", flush=True)
                tripped = True
                break
            for arm in arms.values():
                reason = arm.trip(chain, t0)
                if reason:
                    print(f"TRIP: {reason}", flush=True)
                    tripped = True
            if tripped:
                break
            for arm in arms.values():
                arm.tick(t0)
            time.sleep(max(0.0, 1 / HZ - (time.monotonic() - t0)))
        if not tripped and stopping:  # Ctrl+C from a person: park gently unless they press it again
            print("parking (Ctrl+C again to drop torque now)", flush=True)
            signal.signal(signal.SIGINT, signal.default_int_handler)
            for arm in arms.values():
                arm.park()
    except KeyboardInterrupt:
        pass
    finally:
        for arm in arms.values():
            arm.stop()
        print("torque off", flush=True)


def cmd_poke(args) -> None:
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.sendto(json.dumps({"t": "threat", "arm": args.side}).encode(), ("127.0.0.1", UDP_PORT))
    print(f"threat sent: {args.side}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)
    t = sub.add_parser("teach")
    t.add_argument("--arms", nargs="+", choices=SIDES, default=["left"])
    t.add_argument("--dodges", type=int, default=3, help="dodge poses to teach per arm")
    r = sub.add_parser("run")
    r.add_argument("--arms", nargs="+", choices=SIDES, default=["left"])
    r.add_argument("--speed", type=float, default=30.0, help="deg/s for dodges")
    r.add_argument("--right-speed", type=float, help="deg/s for the right arm's dodges, if different")
    r.add_argument("--no-heartbeat", action="store_true", help="no laptop needed (poke tests); Ctrl+C still stops")
    p = sub.add_parser("poke")
    p.add_argument("side", choices=SIDES)
    args = ap.parse_args()
    {"teach": cmd_teach, "run": cmd_run, "poke": cmd_poke}[args.cmd](args)


if __name__ == "__main__":
    main()
