"""Read-only probe for RobStride motors in MIT-protocol mode (how our B601-RS arms ship).

    python -m brain.arm.mit_probe can0 can1              # one reading
    python -m brain.arm.mit_probe can0 can1 --seconds 20 # track min/max while you move an arm by hand

Sends only the MIT fault-status query (standard frame, data FF*6 00 FB), which never
enables torque. Positions are printed in degrees assuming the RS00 range (+-12.57 rad);
RS06 joints (1-3) also show the alternative +-112.5 rad decode until we confirm which is right.
"""

import argparse
import math
import socket
import struct
import time

from .interface import JOINT_NAMES

QUERY = bytes([0xFF] * 6 + [0x00, 0xFB])
PMAX_RS00 = 12.57
PMAX_O6 = 112.5


def u16_to_rad(q: int, pmax: float) -> float:
    return q / 65535 * 2 * pmax - pmax


def open_bus(ch: str) -> socket.socket:
    s = socket.socket(socket.AF_CAN, socket.SOCK_RAW, socket.CAN_RAW)
    s.setsockopt(socket.SOL_CAN_RAW, socket.CAN_RAW_LOOPBACK, 0)
    s.bind((ch,))
    s.settimeout(0.005)
    return s


def read_raw(s: socket.socket) -> dict[int, int]:
    """Query motors 1..7 and return {motor_id: position u16}."""
    out: dict[int, int] = {}
    for mid in range(1, 8):
        s.send(struct.pack("=IB3x8s", mid, 8, QUERY))
        end = time.monotonic() + 0.02
        while mid not in out and time.monotonic() < end:
            try:
                raw = s.recv(16)
            except socket.timeout:
                continue
            data = raw[8:16]
            out[data[0]] = (data[1] << 8) | data[2]
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("channels", nargs="+")
    ap.add_argument("--seconds", type=float, default=0)
    a = ap.parse_args()

    buses = {ch: open_bus(ch) for ch in a.channels}
    first = {ch: read_raw(s) for ch, s in buses.items()}
    lo = {ch: dict(r) for ch, r in first.items()}
    hi = {ch: dict(r) for ch, r in first.items()}
    end = time.time() + a.seconds
    while time.time() < end:
        for ch, s in buses.items():
            for mid, q in read_raw(s).items():
                lo[ch][mid] = min(lo[ch].get(mid, q), q)
                hi[ch][mid] = max(hi[ch].get(mid, q), q)
        time.sleep(0.02)

    for ch in buses:
        print(f"[{ch}] {len(first[ch])}/7 motors")
        for mid in range(1, 8):
            name = JOINT_NAMES[mid - 1]
            if mid not in first[ch]:
                print(f"  {mid} {name:14s} NO REPLY")
                continue
            q = first[ch][mid]
            deg = math.degrees(u16_to_rad(q, PMAX_RS00))
            alt = f"  (O6 decode {math.degrees(u16_to_rad(q, PMAX_O6)):8.1f})" if mid <= 3 else ""
            moved = ""
            if a.seconds:
                span = math.degrees(u16_to_rad(hi[ch][mid], PMAX_RS00) - u16_to_rad(lo[ch][mid], PMAX_RS00))
                moved = f"  moved {span:6.1f} deg"
            print(f"  {mid} {name:14s} raw={q:5d} {deg:8.1f} deg{alt}{moved}")


if __name__ == "__main__":
    main()
