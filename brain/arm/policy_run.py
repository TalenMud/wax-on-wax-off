"""Run the trained ACT dodge policy on the GX10: smooth, and behind a guard that keeps it off the table.

    python -m brain.arm.policy_run bench MODEL                      # GPU timing on fake inputs, no hardware
    python -m brain.arm.policy_run watch MODEL                      # read-only: move the arms by hand
    python -m brain.arm.policy_run run MODEL --floor-z 0.082,0.055 --arms left --speed 30 \\
        --cam top=/dev/video0 --cam left=/dev/video2 --cam right=/dev/video4

Smoothness: the checkpoint was trained with 100-step chunks, played blind (3.3 s) and then a pause
to infer the next. Here it re-plans every frame with temporal ensembling (overlapping chunks are
blended), or with --chunk N re-plans every N frames. An EMA smooths what is left.

The guard, on every command:
  1. clamps each joint to the range it reached in the training data (stats in the checkpoint)
     and to the URDF limits;
  1b. keeps the elbow REST_CLEARANCE_DEG away from folded (lift ~0 is the demos' ready pose; lift and
      elbow both ~0 is folded onto the base);
  2. caps each joint's speed at --speed deg/s;
  3. holds an arm where it is if the command would put any joint after the shoulder, the gripper or
     the pad below that arm's --floor-z (metres, arm base frame: the lowest point `watch`
     reported with the pad pressed on the table, since the URDF and the real rig disagree by cm);
  4. turns torque off if a MEASURED point comes within TRIP_CLEARANCE of the table or an arm lags its command by more
     than LAG_TRIP_DEG for LAG_TRIP_S (stuck, or fighting something).
Only --arms get torque; the other arm's joints are read with read-only status requests. Ctrl+C or
SIGTERM turns torque off. Every run asks for "go" first.
"""

import argparse
import json
import math
import signal
import sys
import time
from pathlib import Path

import numpy as np

from .dodge import CALIBRATION, MAX_LEAD_DEG
from .kinematics import MOTORS, Chain

SIDES = ("left", "right")
JOINTS = (*MOTORS, "gripper")  # per-arm order in the policy's 14-dim state and action
HZ = 30  # the dataset's fps; temporal ensembling assumes one policy call per recorded frame
LIMIT_MARGIN_DEG = 2.0
REST_CLEARANCE_DEG = 12.0  # elbow stays this far from folded: folded (lift and elbow 0), the arm sits on its base
PARK_SPEED = 15.0  # deg/s back to the starting rest pose at the end of a run
FLOOR_CLEARANCE = 0.03  # metres the command must stay above --floor-z
TRIP_CLEARANCE = 0.01  # a measured point this close to the table turns torque off (it can't go below)
LAG_TRIP_DEG = 25.0
LAG_TRIP_S = 0.3
AMP = False  # bf16 autocast; --amp
LOG_DIR = Path.home() / "wax" / "logs"
CAMERAS = ("top", "left", "right")  # recorded on the left arm, so the policy sees left_top etc.


SERIALS = {"left": "0014001833354B0432333837", "right": "207A37AA45465006"}  # gs_usb CAN adapters


def can_port(side: str) -> str:
    """The CAN interface of an arm's adapter, found by serial: can0/can1 swap when re-plugged."""
    for dev in sorted(Path("/sys/class/net").glob("can*")):
        try:
            if (dev / "device" / ".." / "serial").read_text().strip() == SERIALS[side]:
                return dev.name
        except OSError:
            continue
    raise RuntimeError(f"{side} arm's CAN adapter ({SERIALS[side]}) is not plugged in")


def load_stats(model: Path) -> dict[str, np.ndarray]:
    from safetensors.numpy import load_file

    return load_file(str(model / "policy_postprocessor_step_0_unnormalizer_processor.safetensors"))


class Guard:
    def __init__(self, model: Path, floor_z: tuple[float, float], speed: float) -> None:
        self.chain = Chain()
        s = load_stats(model)
        lo, hi = s["action.min"].astype(float), s["action.max"].astype(float)
        urdf = np.degrees(self.chain.limits)
        for a in range(2):
            for j in range(6):
                k = a * 7 + j
                lo[k] = max(lo[k], urdf[j, 0] + LIMIT_MARGIN_DEG)
                hi[k] = min(hi[k], urdf[j, 1] - LIMIT_MARGIN_DEG)
            lo[a * 7 + 2] = max(lo[a * 7 + 2], REST_CLEARANCE_DEG)  # elbow_flex: 0 is folded
        self.lo, self.hi = lo, hi
        self.floor = floor_z
        self.step = speed / HZ

    def lowest(self, arm6_deg: np.ndarray) -> float:
        return float(self.chain.points(np.radians(arm6_deg))[:, 2].min())

    def filter(self, target: np.ndarray, last: np.ndarray, active: tuple[int, ...]) -> tuple[np.ndarray, list[str]]:
        """The command to send (14) given the policy's target and the last command sent."""
        cmd = np.clip(target, self.lo, self.hi)
        cmd = last + np.clip(cmd - last, -self.step, self.step)
        notes = []
        for a in active:
            sl = slice(a * 7, a * 7 + 6)
            z = self.lowest(cmd[sl])
            if z < self.floor[a] + FLOOR_CLEARANCE:
                cmd[a * 7 : a * 7 + 7] = last[a * 7 : a * 7 + 7]
                notes.append(f"{SIDES[a]} held: command reaches z={z:.3f}")
        return cmd, notes


def read_only_state(side: str, bus=None, stand_in: dict[int, float] | None = None) -> tuple[np.ndarray, object]:
    """7 joint angles (deg; gripper reported as 0) from Damiao status requests. No torque.
    stand_in: {motor id: deg} used for motors that don't answer (limp arms only: a test aid)."""
    from .dm_probe import open_bus, read_raw, u16_to_rad

    bus = bus or open_bus(can_port(side))
    raw: dict[int, int] = {}
    for _ in range(3):  # a motor now and then misses a reply; ask again before giving up
        raw.update(read_raw(bus))
        if all(i + 1 in raw for i in range(6)):
            break
    q = [math.degrees(u16_to_rad(raw[i + 1], 2 * math.pi)) if i + 1 in raw else (stand_in or {}).get(i + 1) for i in range(6)]
    if any(v is None for v in q):
        raise RuntimeError(f"{side} arm: only motors {sorted(raw)} answered")
    return np.array([*q, 0.0]), bus


def stand_ins(side: str) -> dict[int, float]:
    """The saved rest pose (~/.config/wax-on-wax-off/rest_pose.json) as stand-ins, by motor id."""
    from .kinematics import MOTORS

    p = Path.home() / ".config" / "wax-on-wax-off" / "rest_pose.json"
    rest = json.loads(p.read_text())[side]
    return {i + 1: rest[m] for i, m in enumerate(MOTORS)}


def load_policy(model: Path, chunk: int, coeff: float):
    import torch

    torch.backends.cudnn.benchmark = True
    from lerobot.configs.policies import PreTrainedConfig
    from lerobot.policies.act.modeling_act import ACTPolicy
    from lerobot.policies.factory import make_pre_post_processors

    cfg = PreTrainedConfig.from_pretrained(model)
    cfg.device = "cuda"
    if chunk:
        cfg.n_action_steps, cfg.temporal_ensemble_coeff = chunk, None
    else:
        cfg.n_action_steps, cfg.temporal_ensemble_coeff = 1, coeff
    policy = ACTPolicy.from_pretrained(model, config=cfg).to("cuda").eval()
    pre, post = make_pre_post_processors(
        cfg, pretrained_path=str(model), preprocessor_overrides={"device_processor": {"device": "cuda"}}
    )
    return policy, pre, post


def infer(policy, pre, post, state: np.ndarray, images: dict[str, np.ndarray]) -> np.ndarray:
    import torch

    from lerobot.common.control_utils import predict_action

    obs = {"observation.state": state.astype(np.float32)}
    obs.update({f"observation.images.left_{k}": v for k, v in images.items()})
    a = predict_action(obs, policy, torch.device("cuda"), pre, post, use_amp=AMP)
    return a.squeeze(0).cpu().numpy().astype(float)


def cmd_bench(args) -> None:
    policy, pre, post = load_policy(args.model, args.chunk, args.coeff)
    state = load_stats(args.model)["observation.state.mean"].astype(np.float32)
    rng = np.random.default_rng(0)
    times = []
    for i in range(60):
        images = {k: rng.integers(0, 255, (480, 640, 3), dtype=np.uint8) for k in CAMERAS}
        t0 = time.perf_counter()
        infer(policy, pre, post, state, images)
        times.append(time.perf_counter() - t0)
    t = np.array(times[10:]) * 1000
    mode = f"chunk {args.chunk}" if args.chunk else f"temporal ensembling {args.coeff}"
    print(f"{mode}: per step median {np.median(t):.1f} ms, p95 {np.percentile(t, 95):.1f} ms, "
          f"max {t.max():.1f} ms (budget {1000 / HZ:.0f} ms)")


def cmd_watch(args) -> None:
    """Read-only: print each arm's lowest point and whether the guard would allow the pose."""
    guard = Guard(args.model, args.floor_z, args.speed)
    buses = {}
    print("read-only, no torque. Move the arms by hand; Ctrl+C to stop.")
    try:
        while True:
            out = []
            for a, side in enumerate(SIDES):
                try:
                    q, buses[side] = read_only_state(side, buses.get(side))
                except RuntimeError as e:
                    out.append(str(e))
                    continue
                z = guard.lowest(q[:6])
                ok = "ok" if z >= guard.floor[a] + FLOOR_CLEARANCE else "BLOCKED"
                rng = "in range" if np.all((q[:6] >= guard.lo[a * 7 : a * 7 + 6]) & (q[:6] <= guard.hi[a * 7 : a * 7 + 6])) else "OUT OF RANGE"
                out.append(f"{side}: lowest z {z:+.3f} m {ok}, {rng}")
            print("   ".join(out), flush=True)
            time.sleep(0.2)
    except KeyboardInterrupt:
        pass


def cmd_run(args) -> None:
    from lerobot.cameras.opencv import OpenCVCamera, OpenCVCameraConfig
    from lerobot.robots.metal_follower import MetalFollower, MetalFollowerConfig

    cams = dict(c.split("=", 1) for c in args.cam)
    missing = [k for k in CAMERAS if k not in cams]
    if missing and not args.blank_missing:
        sys.exit(f"no --cam for {missing}; the policy was trained with {CAMERAS} (or pass --blank-missing)")
    active = tuple(SIDES.index(s) for s in args.arms)
    guard = Guard(args.model, args.floor_z, args.speed)
    mode = f"re-plans every {args.chunk} frames" if args.chunk else "re-plans every frame (temporal ensembling)"
    print(f"Arms {list(args.arms)} get torque and follow the ACT policy, {mode}, at most {args.speed:.0f} deg/s per joint,")
    print(f"joints clamped to the training range, held if any part would come within {FLOOR_CLEARANCE * 100:.0f} cm of the table;")
    print("torque off if a measured point crosses the floor or an arm lags its command. "
          f"Runs {args.seconds:.0f} s. Someone must be at the arm power.")
    if missing:
        print(f"cameras {missing} are fed black frames: expect worse behaviour.")

    def limp_stand_in(side: str) -> dict[int, float] | None:  # never for an arm that gets torque
        return stand_ins(side) if args.stand_in and SIDES.index(side) not in active else None

    for side in SIDES:  # pre-flight, read-only: both buses up and every motor answering
        try:
            read_only_state(side, stand_in=limp_stand_in(side))
        except (OSError, RuntimeError) as e:
            sys.exit(f"pre-flight: {side} arm ({can_port(side)}) not readable: {e}. No torque was enabled.")
    policy, pre, post = load_policy(args.model, args.chunk, args.coeff)
    cameras = {}
    for k, dev in cams.items():
        cameras[k] = OpenCVCamera(OpenCVCameraConfig(index_or_path=Path(dev), fps=30, width=640, height=480, fourcc="MJPG"))  # raw YUYV overloads the shared hub
        cameras[k].connect()
    if args.shadow:
        print("SHADOW: no torque, nothing is sent to the motors; logging what the policy wants.")
        answer = "go"
    else:
        try:
            answer = input('Type "go" to enable torque: ').strip()
        except EOFError:
            answer = ""
    if answer != "go":
        for c in cameras.values():
            c.disconnect()
        return

    stopping = False

    def on_signal(*_):
        nonlocal stopping
        stopping = True

    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGTERM, on_signal)
    robots, buses = {}, {}
    log = {k: [] for k in ("t", "state", "target", "cmd")}
    try:
        for a in () if args.shadow else active:
            side = SIDES[a]
            robots[a] = MetalFollower(
                MetalFollowerConfig(
                    id=CALIBRATION[side],
                    port=can_port(side),
                    can_interface="socketcan",
                    max_relative_target=MAX_LEAD_DEG,
                    disable_torque_on_disconnect=True,
                )
            )
            robots[a].connect(calibrate=False)

        def state() -> np.ndarray:
            s = np.zeros(14)
            for a, side in enumerate(SIDES):
                if a in robots:
                    o = robots[a].get_observation()
                    s[a * 7 : a * 7 + 7] = [o[f"{j}.pos"] for j in JOINTS]
                else:
                    s[a * 7 : a * 7 + 7], buses[side] = read_only_state(side, buses.get(side), limp_stand_in(side))
            if args.pretend:  # shadow only: what would the policy do from this left-arm pose?
                s[:7] = args.pretend
            return s

        last = state()
        start = last.copy()  # the rest pose to park in at the end
        smooth = last.copy()
        lag_since = {a: None for a in active}
        print("shadow running" if args.shadow else "torque on", flush=True)
        end = time.monotonic() + args.seconds
        n = 0
        while not stopping and time.monotonic() < end:
            t0 = time.monotonic()
            s = state()
            tripped = False
            for a in active:
                z = guard.lowest(s[a * 7 : a * 7 + 6])
                if z < guard.floor[a] + TRIP_CLEARANCE:
                    print(f"TRIP: {SIDES[a]} measured z={z:.3f}, at the table", flush=True)
                    tripped = True
                lag = np.abs(s[a * 7 : a * 7 + 6] - last[a * 7 : a * 7 + 6]).max()
                if lag > LAG_TRIP_DEG:
                    lag_since[a] = lag_since[a] or t0
                    if t0 - lag_since[a] > LAG_TRIP_S:
                        print(f"TRIP: {SIDES[a]} lags its command by {lag:.0f} deg", flush=True)
                        tripped = True
                else:
                    lag_since[a] = None
            if tripped and not args.shadow:  # shadow only reports trips
                stopping = True
                break
            images = {k: (cameras[k].async_read() if k in cameras else np.zeros((480, 640, 3), np.uint8)) for k in CAMERAS}
            target = infer(policy, pre, post, s, images)
            smooth = args.ema * target + (1 - args.ema) * smooth
            want = s.copy()  # inactive arm: command = where it is (never sent)
            for a in active:
                want[a * 7 : a * 7 + 6] = smooth[a * 7 : a * 7 + 6]
                want[a * 7 + 6] = start[a * 7 + 6]  # gripper holds the pad as mounted; demos had it shut
            cmd, notes = guard.filter(want, last, active)
            for note in notes:
                print(note, flush=True)
            for a in robots:
                robots[a].send_action({f"{j}.pos": float(cmd[a * 7 + i]) for i, j in enumerate(JOINTS)})
            for k, v in (("t", t0), ("state", s), ("target", target), ("cmd", cmd)):
                log[k].append(v)
            last = cmd
            n += 1
            dt = time.monotonic() - t0
            if dt > 1.5 / HZ:
                print(f"slow tick {dt * 1000:.0f} ms", flush=True)
            if n % (HZ * 5) == 0:
                print(f"{n // HZ} s", flush=True)
            time.sleep(max(0.0, 1 / HZ - dt))
        if not stopping and robots:  # time is up: lower slowly back to rest instead of dropping at torque off
            print("parking", flush=True)
            step = PARK_SPEED / HZ
            while not stopping and np.abs(start - last).max() > 0.5:
                last = last + np.clip(start - last, -step, step)
                for a in active:
                    robots[a].send_action({f"{j}.pos": float(last[a * 7 + i]) for i, j in enumerate(JOINTS)})
                time.sleep(1 / HZ)
    finally:
        for a, r in robots.items():
            try:
                r.disconnect()
            except Exception as e:  # keep going: the other arm's torque must still go off
                print(f"{SIDES[a]}: disconnect error {e}", file=sys.stderr)
        for c in cameras.values():
            try:
                c.disconnect()
            except Exception:
                pass
        print("torque off", flush=True)
        if log["t"]:  # also when the run stopped early: the log is how we see what happened
            LOG_DIR.mkdir(parents=True, exist_ok=True)
            out = LOG_DIR / time.strftime(f"{'shadow' if args.shadow else 'run'}-%H%M%S.npz")
            np.savez(out, **{k: np.array(v) for k, v in log.items()}, active=np.array(active))
            print(f"log: {out}", flush=True)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("cmd", choices=["bench", "watch", "run"])
    ap.add_argument("model", type=Path)
    ap.add_argument("--floor-z", help="LEFT,RIGHT table height in each arm's base frame, metres (from `watch`)")
    ap.add_argument("--arms", nargs="+", choices=SIDES, default=["left"])
    ap.add_argument("--speed", type=float, default=30.0, help="max deg/s per joint")
    ap.add_argument("--chunk", type=int, default=0, help="re-plan every N frames instead of temporal ensembling")
    ap.add_argument("--coeff", type=float, default=0.01, help="temporal ensembling coefficient")
    ap.add_argument("--ema", type=float, default=0.5, help="output smoothing, 1 = off")
    ap.add_argument("--cam", action="append", default=[], help="NAME=DEVICE for top, left, right")
    ap.add_argument("--blank-missing", action="store_true")
    ap.add_argument("--shadow", action="store_true", help="no torque: run the policy on live inputs and log it")
    ap.add_argument("--stand-in", action="store_true", help="limp arms: use the saved rest pose for motors that don't answer")
    ap.add_argument("--pretend", type=lambda v: [float(x) for x in v.split(",")], help="shadow only: 7 left-arm joint values to report instead of the real ones")
    ap.add_argument("--seconds", type=float, default=20.0)
    ap.add_argument("--amp", action="store_true", help="bf16 autocast: faster inference")
    args = ap.parse_args()
    global AMP
    AMP = args.amp
    if args.pretend and not args.shadow:
        ap.error("--pretend only works with --shadow")
    if args.cmd == "run" and args.floor_z is None:
        ap.error("--floor-z is required: measure it with `watch` first")
    args.floor_z = tuple(float(v) for v in args.floor_z.split(",")) if args.floor_z else (-1.0, -1.0)
    {"bench": cmd_bench, "watch": cmd_watch, "run": cmd_run}[args.cmd](args)


if __name__ == "__main__":
    main()
