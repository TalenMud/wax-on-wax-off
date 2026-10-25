"""Stream both pads' positions to the laptop so the XR coach's pads sit on the real ones. Read-only.

    python -m brain.arm.pad_stream                  # multicast on the GX10's wired link, port 9311
    python -m brain.arm.pad_stream --iface enP7s7

Listens to the motors' replies to whatever is driving the arms (teleop, policy_run); when a bus has
been quiet for QUIET_S it asks with the read-only Damiao status request (dm_probe.py), so it also
works with the arms limp. Never sends a motion frame.

Each packet, HZ times a second, to ff02::1 (every host on the link, so the laptop's address doesn't
matter) and tools/serve_xr.py:
    {"t": "pads", "ts": unix s, "left": {"p": [x, y, z], "n": [x, y, z]} | null, "right": ...}
p is the pad centre and n its face normal, in that arm's base frame (URDF base_link, z up, metres).
"""

import argparse
import json
import socket
import struct
import time

import numpy as np

from .dm_probe import PMAX, u16_to_rad
from .kinematics import Chain
from .policy_run import SIDES, can_port

PORT = 9311
HZ = 30
QUIET_S = 0.1  # no motor replies for this long: ask for them ourselves
STALE_S = 0.5  # a joint not heard from for this long makes its arm unknown
PAD_IN_CLAW = 0.06  # metres from gripper_base to the pad held between the claw's fingers (estimate)


class Bus:
    """One arm's CAN bus: latest position of each motor."""

    def __init__(self, side: str) -> None:
        self.side = side
        self.sock: socket.socket | None = None
        self.q: dict[int, tuple[float, float]] = {}  # motor id -> (rad, time)
        self.heard = 0.0
        self.error = ""

    def poll(self, now: float) -> None:
        try:
            if self.sock is None:
                s = socket.socket(socket.AF_CAN, socket.SOCK_RAW, socket.CAN_RAW)
                s.setsockopt(socket.SOL_CAN_RAW, socket.CAN_RAW_LOOPBACK, 0)  # our requests stay off other local sockets
                s.bind((can_port(self.side),))
                s.setblocking(False)
                self.sock = s
            while True:
                try:
                    frame = self.sock.recv(16)
                except BlockingIOError:
                    break
                can_id = struct.unpack("=I", frame[:4])[0] & 0x7FF
                data = frame[8:16]
                if not 0x11 <= can_id <= 0x17 or data[2] == 0x33:  # motor replies only; skip register replies
                    continue
                mid = data[0] & 0x0F
                self.q[mid] = (u16_to_rad((data[1] << 8) | data[2], PMAX), now)
                self.heard = now
            if now - self.heard > QUIET_S:
                for mid in range(1, 8):
                    self.sock.send(struct.pack("=IB3x8s", 0x7FF, 8, bytes([mid, 0, 0xCC, 0, 0, 0, 0, 0])))
        except OSError as e:  # bus down or adapter re-plugged: reopen next tick
            if self.sock is not None:
                self.sock.close()
            self.sock = None
            if str(e) != self.error:
                print(f"{self.side}: {e}", flush=True)
            self.error = str(e)

    def angles(self, now: float) -> np.ndarray | None:
        q = [self.q.get(m) for m in range(1, 7)]
        if any(v is None or now - v[1] > STALE_S for v in q):
            return None
        return np.array([v[0] for v in q])


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--iface", default="enP7s7", help="the wired link to the laptop")
    ap.add_argument("--pad-offset", type=float, default=PAD_IN_CLAW, help="gripper_base to pad centre, metres")
    args = ap.parse_args()

    chain = Chain()
    buses = {side: Bus(side) for side in SIDES}
    out = socket.socket(socket.AF_INET6, socket.SOCK_DGRAM)
    dest = ("ff02::1", PORT, 0, socket.if_nametoindex(args.iface))
    print(f"streaming pads to [ff02::1%{args.iface}]:{PORT} at {HZ} Hz; read-only", flush=True)
    n = 0
    while True:
        t0 = time.monotonic()
        msg = {"t": "pads", "ts": time.time()}
        for side, bus in buses.items():
            bus.poll(t0)
            q = bus.angles(t0)
            if q is None:
                msg[side] = None
                continue
            p, nrm = chain.pad(q, args.pad_offset)
            msg[side] = {"p": [round(float(v), 4) for v in p], "n": [round(float(v), 3) for v in nrm]}
        try:
            out.sendto(json.dumps(msg).encode(), dest)
        except OSError as e:
            print(f"send: {e}", flush=True)
        n += 1
        if n % (HZ * 30) == 0:
            print(f"left {'ok' if msg['left'] else '--'}  right {'ok' if msg['right'] else '--'}", flush=True)
        time.sleep(max(0.0, 1 / HZ - (time.monotonic() - t0)))


if __name__ == "__main__":
    main()
