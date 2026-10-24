"""Gravity test: hold joints 1-6 of one arm where they are, raise one joint by --delta, return.

    python -m brain.arm.lift_test --channel can0 --joint 2 --delta 15

Sequence: read all joints -> enable 1-6 -> soft-start (stiffness 0 -> full over 1 s, holding
current positions) -> move --joint by --delta at --speed -> hold 2 s -> move back -> hold 1 s ->
disable all. Gripper (7) stays disabled. Aborts and disables on Ctrl+C/SIGTERM, missing
feedback > 100 ms on any joint, tracking error > 10 deg on any joint, or the moving joint
leaving start +- (|delta| + 10).
"""

import argparse
import json
import math
import signal
import sys
import time
from pathlib import Path

from .dm_bus import DmBus
from .interface import JOINT_NAMES

ARM_IDS = range(1, 7)
# Approved 2026-10-24: MakerMods' settled Metal gains (kp 100 / kd 5) on shoulder_lift and
# elbow_flex, which carry the arm against gravity; the rest stay soft and just hold.
KP = {1: 20.0, 2: 100.0, 3: 100.0, 4: 20.0, 5: 10.0, 6: 10.0}
KD = {1: 1.0, 2: 5.0, 3: 5.0, 4: 1.0, 5: 0.5, 6: 0.5}
MAX_DELTA_DEG = 20.0
MAX_SPEED_DEG_S = 10.0
MAX_STEP_DEG = 0.5
TRACK_ERR_DEG = 10.0
FEEDBACK_TIMEOUT_S = 0.1
RATE_HZ = 100


class Abort(Exception):
    pass


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--channel", required=True)
    ap.add_argument("--joint", type=int, required=True, choices=list(ARM_IDS))
    ap.add_argument("--delta", type=float, required=True)
    ap.add_argument("--speed", type=float, default=5.0)
    a = ap.parse_args()
    if abs(a.delta) > MAX_DELTA_DEG or a.speed > MAX_SPEED_DEG_S:
        sys.exit(f"refusing: caps are delta<={MAX_DELTA_DEG} speed<={MAX_SPEED_DEG_S}")

    def on_signal(signum, _frame):
        raise Abort(f"signal {signum}")

    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGTERM, on_signal)

    log_path = Path("logs") / f"lift_test-{time.strftime('%Y%m%d-%H%M%S')}.jsonl"
    log_path.parent.mkdir(exist_ok=True)
    log = log_path.open("w")
    bus = DmBus(a.channel)
    try:
        start = {}
        for mid in ARM_IDS:
            bus.load_limits(mid)
            fb = bus.query(mid)
            if fb is None or fb.err not in (0, 1):
                raise Abort(f"motor {mid}: no feedback or fault before enable ({fb})")
            start[mid] = fb.pos_rad
        print("start " + " ".join(f"{JOINT_NAMES[m - 1]}={math.degrees(p):.1f}" for m, p in start.items()), flush=True)

        cmd = dict(start)
        j, delta = a.joint, math.radians(a.delta)
        phases = [
            ("soft_start", 1.0, start[j], True),
            ("out", abs(a.delta) / a.speed, start[j] + delta, False),
            ("hold_out", 2.0, start[j] + delta, False),
            ("back", abs(a.delta) / a.speed, start[j], False),
            ("hold_back", 1.0, start[j], False),
        ]
        for mid in ARM_IDS:
            bus.enable(mid)
        t0 = time.monotonic()
        for name, dur, goal, ramp in phases:
            p_start, ph_t0 = cmd[j], time.monotonic()
            print(f"phase {name}", flush=True)
            while (el := time.monotonic() - ph_t0) < dur:
                frac = min(1.0, el / dur)
                target = p_start + (goal - p_start) * frac
                step_lim = math.radians(MAX_STEP_DEG)
                cmd[j] += max(-step_lim, min(step_lim, target - cmd[j]))
                for mid in ARM_IDS:
                    kp = KP[mid] * frac if ramp else KP[mid]
                    bus.send_mit(mid, cmd[mid], kp, KD[mid])
                time.sleep(1 / RATE_HZ)
                bus.poll()
                now = time.monotonic()
                row = {"t": now - t0, "phase": name}
                for mid in ARM_IDS:
                    fb = bus.feedback.get(mid)
                    if fb is None or now - fb.t > FEEDBACK_TIMEOUT_S:
                        raise Abort(f"motor {mid}: feedback timeout")
                    err = math.degrees(fb.pos_rad - cmd[mid])
                    row[f"err{mid}"] = round(err, 2)
                    row[f"pos{mid}"] = round(math.degrees(fb.pos_rad), 2)
                    if abs(err) > TRACK_ERR_DEG and not (ramp and frac < 0.5):
                        raise Abort(f"motor {mid}: tracking error {err:.1f} deg")
                log.write(json.dumps(row) + "\n")
                if abs(math.degrees(bus.feedback[j].pos_rad - start[j])) > abs(a.delta) + 10:
                    raise Abort("moving joint left safe window")
        print("done", flush=True)
    except Abort as e:
        print(f"ABORT: {e}", flush=True)
    finally:
        signal.signal(signal.SIGINT, signal.SIG_IGN)
        signal.signal(signal.SIGTERM, signal.SIG_IGN)
        bus.disable_all()
        print("torque disabled on all motors of this bus", flush=True)
        bus.close()
        log.close()
        print(f"log: {log_path}")


if __name__ == "__main__":
    main()
