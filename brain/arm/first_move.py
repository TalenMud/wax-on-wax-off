"""First powered motion: one joint, a few degrees, slow, then torque off.

    python -m brain.arm.first_move --channel can0 --motor 6 --delta 5

Sequence: read position -> enable ONE motor -> hold current position while stiffness ramps
up over 0.5 s -> move +delta at --speed -> hold 1 s -> move back -> hold 0.5 s -> disable.
Aborts (and disables) on: Ctrl+C, SIGTERM, missing feedback > 100 ms, tracking error > 10 deg,
or position leaving start +- (delta + 10 deg). Hard caps below can only be raised by editing code.
"""

import argparse
import json
import math
import signal
import sys
import time
from pathlib import Path

from .dm_bus import DmBus, encode_mit

MAX_DELTA_DEG = 10.0
MAX_SPEED_DEG_S = 10.0
MAX_KP = 20.0
MAX_KD = 2.0
MAX_STEP_DEG = 0.5  # per 100 Hz tick, like max_relative_target
TRACK_ERR_DEG = 10.0
FEEDBACK_TIMEOUT_S = 0.1
RATE_HZ = 100


class Abort(Exception):
    pass


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--channel", required=True)
    ap.add_argument("--motor", type=int, required=True)
    ap.add_argument("--delta", type=float, default=5.0)
    ap.add_argument("--speed", type=float, default=5.0, help="deg/s")
    ap.add_argument("--kp", type=float, default=10.0)
    ap.add_argument("--kd", type=float, default=1.0)
    a = ap.parse_args()
    if abs(a.delta) > MAX_DELTA_DEG or a.speed > MAX_SPEED_DEG_S or a.kp > MAX_KP or a.kd > MAX_KD:
        sys.exit(f"refusing: caps are delta<={MAX_DELTA_DEG} speed<={MAX_SPEED_DEG_S} kp<={MAX_KP} kd<={MAX_KD}")

    def on_signal(signum, _frame):
        raise Abort(f"signal {signum}")

    signal.signal(signal.SIGINT, on_signal)
    signal.signal(signal.SIGTERM, on_signal)

    log_path = Path("logs") / f"first_move-{time.strftime('%Y%m%d-%H%M%S')}.jsonl"
    log_path.parent.mkdir(exist_ok=True)
    log = log_path.open("w")
    bus = DmBus(a.channel)
    mid = a.motor
    try:
        lim = bus.load_limits(mid)
        fb = bus.query(mid)
        if fb is None:
            raise Abort("no feedback before enable")
        if fb.err not in (0, 1):  # Damiao: 0 disabled, 1 enabled; >=8 are faults
            raise Abort(f"motor reports error code {fb.err:#x}")
        start = fb.pos_rad
        q = encode_mit(start, a.kp, a.kd, lim)
        echo = ((q[0] << 8) | q[1]) / 65535 * 2 * lim.pmax - lim.pmax
        if abs(echo - start) > math.radians(0.1):
            raise Abort(f"encode/decode mismatch {math.degrees(echo - start):.3f} deg")
        print(f"limits {lim}", flush=True)
        delta = math.radians(a.delta)
        print(f"start {math.degrees(start):.2f} deg; enabling motor {mid} on {a.channel}", flush=True)

        bus.enable(mid)
        cmd = start
        t0 = time.monotonic()
        # (phase, duration_s, goal_rad, stiffness ramp)
        phases = [
            ("soft_start", 0.5, start, True),
            ("out", abs(a.delta) / a.speed, start + delta, False),
            ("hold_out", 1.0, start + delta, False),
            ("back", abs(a.delta) / a.speed, start, False),
            ("hold_back", 0.5, start, False),
        ]
        for name, dur, goal, ramp_kp in phases:
            p_start, ph_t0 = cmd, time.monotonic()
            print(f"phase {name}", flush=True)
            while (el := time.monotonic() - ph_t0) < dur:
                frac = min(1.0, el / dur)
                target = p_start + (goal - p_start) * frac
                step = max(-math.radians(MAX_STEP_DEG), min(math.radians(MAX_STEP_DEG), target - cmd))
                cmd += step
                kp = a.kp * frac if ramp_kp else a.kp
                t_send = time.monotonic()
                bus.send_mit(mid, cmd, kp, a.kd)
                time.sleep(1 / RATE_HZ)
                bus.poll()
                fb = bus.feedback.get(mid)
                now = time.monotonic()
                if fb is None or now - fb.t > FEEDBACK_TIMEOUT_S:
                    raise Abort("feedback timeout")
                err = math.degrees(fb.pos_rad - cmd)
                off = math.degrees(fb.pos_rad - start)
                log.write(json.dumps({"t": now - t0, "phase": name, "cmd_deg": math.degrees(cmd),
                                      "pos_deg": math.degrees(fb.pos_rad), "kp": kp,
                                      "fb_age_ms": (now - fb.t) * 1e3, "send_t": t_send - t0}) + "\n")
                if abs(err) > TRACK_ERR_DEG:
                    raise Abort(f"tracking error {err:.1f} deg")
                if abs(off) > abs(a.delta) + 10:
                    raise Abort(f"left safe window: {off:.1f} deg from start")
        end = bus.query(mid)
        print(f"done; final {math.degrees(end.pos_rad) if end else float('nan'):.2f} deg", flush=True)
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
