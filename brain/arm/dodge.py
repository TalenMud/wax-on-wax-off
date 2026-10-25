"""Bait-and-dodge controller for the two Metal arms (runs on the machine with the CAN adapters).

Each arm holds its pad out at a bait pose. When the headset sees a glove coming at a pad it
sends a threat (via tools/serve_xr.py), and that arm pulls the pad back to its dodge pose,
holds it, then returns to a bait pose. Poses come from brain/arm/kinematics.py: pad targets in
each arm's own frame (+x straight out from the base towards the player, z up), so the arms only
ever move between these fixed points, and dodges only move the pad back, away from the player.

    python -m brain.arm.dodge plan                    # print the computed poses; no hardware
    python -m brain.arm.dodge read                    # read-only: joints and pad positions now
    python -m brain.arm.dodge nudge --arms left --joint wrist_roll --delta 5   # TORQUE ON: one joint
    python -m brain.arm.dodge live --arms left        # TORQUE ON: asks you to type "go" first

Live safety: the commanded pose moves towards its goal at --speed deg/s, and max_relative_target
(MAX_LEAD_DEG) stops any command getting further than that from where the joint really is; the
Lab's tested MIT gains are used unchanged, torque goes off on Ctrl+C / SIGTERM / a "stop" message,
and on a watchdog when the laptop's heartbeat (UDP, 20 Hz) goes quiet for WATCHDOG_S.
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

from .kinematics import MOTORS, Chain, deg_to_q, q_to_deg, solve_pad

PORTS = {"left": "can0", "right": "can1"}
CALIBRATION = {"left": "goat_metal_left", "right": "goat_metal_right"}
UDP_PORT = 9310
WATCHDOG_S = 0.5
HZ = 50
MAX_LEAD_DEG = 10.0  # max_relative_target: a command never leads the real joint by more than this

# Pad targets in each arm's frame (metres). Bait spots spread a little so the player can't
# pre-aim; the dodge pulls the pad 15 cm back and 8 cm down from wherever it is.
BAIT = [(0.40, 0.00, 0.32), (0.37, 0.06, 0.35), (0.38, -0.06, 0.28)]
DODGE_BACK, DODGE_DOWN = 0.15, 0.08
DODGE_HOLD_S = 0.6
SEED = np.radians([0, -90, 110, -100, 0, 0])  # elbow-up family; IK stays on this side
MAX_IK_ERR = 0.005
LIMIT_MARGIN_DEG = 5.0  # computed poses must stay this far inside the joint limits


def plan(chain: Chain) -> dict:
    """Bait and matching dodge poses (degrees). Raises if any target is unreachable."""
    out = {"bait": [], "dodge": []}
    for x, y, z in BAIT:
        q, err = solve_pad(chain, np.array([x, y, z]), SEED)
        qd, errd = solve_pad(chain, np.array([x - DODGE_BACK, y, z - DODGE_DOWN]), q)
        for name, e in (("bait", err), ("dodge", errd)):
            if e > MAX_IK_ERR:
                raise ValueError(f"{name} for bait {(x, y, z)} is out of reach ({e * 1000:.0f} mm off)")
        for name, qq in (("bait", q), ("dodge", qd)):
            for m, v, (lo, hi) in zip(MOTORS, np.degrees(qq), np.degrees(chain.limits)):
                if not lo + LIMIT_MARGIN_DEG <= v <= hi - LIMIT_MARGIN_DEG:
                    raise ValueError(f"{name} for bait {(x, y, z)}: {m} {v:.0f} deg is within {LIMIT_MARGIN_DEG} deg of its limit")
        out["bait"].append(q_to_deg(q))
        out["dodge"].append(q_to_deg(qd))
    return out


def mirror(pose: dict[str, float]) -> dict[str, float]:
    """The other arm's version of a pose: the arms are mirror images across their gap."""
    return {m: (-v if m in ("shoulder_pan", "wrist_yaw", "wrist_roll") else v) for m, v in pose.items()}


def arm_poses(chain: Chain, side: str) -> dict:
    p = plan(chain)
    # BAIT y > 0 means towards the centre beam for the left arm; mirror it for the right arm.
    if side == "right":
        p = {k: [mirror(x) for x in v] for k, v in p.items()}
    return p


def cmd_plan(args) -> None:
    chain = Chain()
    for side in args.arms:
        print(f"== {side} arm")
        p = arm_poses(chain, side)
        for i, (b, d) in enumerate(zip(p["bait"], p["dodge"])):
            pb, _ = chain.pad(deg_to_q(b))
            pd, _ = chain.pad(deg_to_q(d))
            print(f"  bait {i}: pad {np.round(pb, 3)}  {b}")
            print(f"  dodge {i}: pad {np.round(pd, 3)}  {d}")


def cmd_read(args) -> None:
    """Read-only (Damiao 0x7FF status requests): joints and where that puts each pad."""
    from .dm_probe import open_bus, read_raw, u16_to_rad

    chain = Chain()
    for side in args.arms:
        raw = read_raw(open_bus(PORTS[side]))
        if len(raw) < 6:
            print(f"{side}: only {sorted(raw)} answered")
            continue
        q = np.array([u16_to_rad(raw[i + 1], 2 * math.pi) for i in range(6)])
        p, n = chain.pad(q)
        print(f"{side}: {q_to_deg(q)}\n  pad {np.round(p, 3)} normal {np.round(n, 2)}")


class Arm:
    """One Metal follower driven through LeRobot with the Lab's calibration and gains."""

    def __init__(self, side: str, speed_deg_s: float) -> None:
        from lerobot.robots.metal_follower import MetalFollower, MetalFollowerConfig

        cfg = MetalFollowerConfig(
            id=CALIBRATION[side],
            port=PORTS[side],
            can_interface="socketcan",
            max_relative_target=MAX_LEAD_DEG,
            disable_torque_on_disconnect=True,
        )
        self.side = side
        self.step = speed_deg_s / HZ
        self.robot = MetalFollower(cfg)
        self.poses: dict = {}
        self.target: dict[str, float] = {}
        self.state, self.bait_i, self.until = "bait", 0, 0.0

    def connect(self) -> None:
        self.robot.connect(calibrate=False)
        now = self.robot.get_observation()
        self.gripper = now["gripper.pos"]
        self.target = {m: now[f"{m}.pos"] for m in MOTORS}
        self.cmd = dict(self.target)  # where we are commanding each joint right now

    def move_towards(self, goal: dict[str, float]) -> bool:
        """One tick: step the command at most self.step deg per joint towards goal. True when there."""
        done = True
        for m in MOTORS:
            d = goal[m] - self.cmd[m]
            if abs(d) > self.step:
                d, done = math.copysign(self.step, d), False
            self.cmd[m] += d
        action = {f"{m}.pos": self.cmd[m] for m in MOTORS}
        action["gripper.pos"] = self.gripper
        self.robot.send_action(action)
        return done

    def tick(self, now: float) -> None:
        if self.state == "dodge" and now >= self.until:
            self.state = "bait"
            self.bait_i = random.randrange(len(self.poses["bait"]))
        self.move_towards(self.poses["dodge" if self.state == "dodge" else "bait"][self.bait_i])

    def threat(self, now: float) -> None:
        if self.state != "dodge":
            self.state, self.until = "dodge", now + DODGE_HOLD_S

    def stop(self) -> None:
        try:
            self.robot.disconnect()  # disable_torque_on_disconnect=True
        except Exception as e:  # never let one arm's error keep the other's torque on
            print(f"{self.side}: disconnect error {e}", file=sys.stderr)


def cmd_nudge(args) -> None:
    """First powered motion: hold the arm where it is, move ONE joint by --delta, back, torque off."""
    side = args.arms[0]
    print(f"{side} arm: torque on holding its current pose, {args.joint} moves {args.delta:+.0f} deg at")
    print(f"{args.speed:.0f} deg/s, holds 1 s, moves back, torque off. Someone must be at the arm power.")
    if input('Type "go" to enable torque: ').strip() != "go":
        print("Not started.")
        return
    arm = Arm(side, args.speed)
    stopping = False

    def on_signal(*_):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGTERM, on_signal)
    try:
        arm.connect()
        start = dict(arm.target)
        goal = {**start, args.joint: start[args.joint] + args.delta}
        for pose, secs in ((start, 1.0), (goal, abs(args.delta) / args.speed + 1.0), (start, abs(args.delta) / args.speed + 1.0)):
            end = time.monotonic() + secs
            while time.monotonic() < end and not stopping:
                arm.move_towards(pose)
                time.sleep(1 / HZ)
            obs = arm.robot.get_observation()
            print(f"  {args.joint}: target {pose[args.joint]:.1f}, now {obs[args.joint + '.pos']:.1f}")
            if stopping:
                break
    finally:
        arm.stop()
        print("torque off")


def cmd_live(args) -> None:
    chain = Chain()
    print(f"Arms {args.arms} will enable torque and move to bait pose 0 at most {args.speed:.0f} deg/s,")
    print("then dodge on threats from the laptop. Ctrl+C, a stop message, or losing the laptop's")
    print("heartbeat for 0.5 s turns torque off. Someone must be at the arm power the whole time.")
    if input('Type "go" to enable torque: ').strip() != "go":
        print("Not started.")
        return

    arms = {side: Arm(side, args.speed) for side in args.arms}
    for side, arm in arms.items():
        arm.poses = arm_poses(chain, side)
    stopping = False

    def on_signal(*_):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGTERM, on_signal)
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    sock.bind(("0.0.0.0", UDP_PORT))
    sock.setblocking(False)
    last_hb = time.monotonic() + 3.0  # grace period to start the laptop side
    try:
        for arm in arms.values():
            arm.connect()
        print(f"torque on; listening on udp/{UDP_PORT}")
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
                    arms[msg["arm"]].threat(t0)
                    print(f"threat {msg['arm']}")
                elif msg.get("t") == "stop":
                    print("stop message")
                    stopping = True
            if t0 - last_hb > WATCHDOG_S:
                print("laptop heartbeat lost: torque off")
                break
            for arm in arms.values():
                arm.tick(t0)
            time.sleep(max(0.0, 1 / HZ - (time.monotonic() - t0)))
    finally:
        for arm in arms.values():
            arm.stop()
        print("torque off")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["plan", "read", "nudge", "live"])
    ap.add_argument("--arms", nargs="+", choices=["left", "right"], default=["left", "right"])
    ap.add_argument("--speed", type=float, default=30.0, help="max joint speed, deg/s (start slow)")
    ap.add_argument("--joint", choices=list(MOTORS), default="wrist_roll", help="nudge: which joint")
    ap.add_argument("--delta", type=float, default=5.0, help="nudge: degrees (at most 10)")
    args = ap.parse_args()
    if abs(args.delta) > 10:
        ap.error("--delta is capped at 10 degrees")
    {"plan": cmd_plan, "read": cmd_read, "nudge": cmd_nudge, "live": cmd_live}[args.cmd](args)


if __name__ == "__main__":
    main()
