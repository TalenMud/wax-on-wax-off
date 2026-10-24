"""Minimal Damiao-protocol MIT driver over raw SocketCAN for our B601 arms.

The motors reply as Damiao: status frames from 0x10+id, data[0] = id | err << 4, then
pos u16, vel u12, tau u12, T_mos, T_rotor. Per-motor PMAX/VMAX/TMAX are read from the
motor's registers (0x7FF, cmd 0x33) instead of assumed.

Special commands are only FF*7 + FC/FD/FB/FE. Any other 8-byte frame to a motor id is an
MIT command, so never send "mode switch" style FF*6 xx FC frames.
"""

import socket
import struct
import time
from dataclasses import dataclass

KP_MAX = 500.0
KD_MAX = 5.0
MGMT_ID = 0x7FF
REG_PMAX, REG_VMAX, REG_TMAX, REG_CTRL_MODE = 21, 22, 23, 10
CTRL_MODE_MIT = 1


@dataclass
class Limits:
    pmax: float
    vmax: float
    tmax: float


@dataclass
class Feedback:
    pos_rad: float
    err: int
    t: float  # time.monotonic() when received


def _to_uint(x: float, lo: float, hi: float, bits: int) -> int:
    x = max(lo, min(hi, x))
    return int((x - lo) / (hi - lo) * ((1 << bits) - 1))


def encode_mit(pos_rad: float, kp: float, kd: float, lim: Limits) -> bytes:
    q = _to_uint(pos_rad, -lim.pmax, lim.pmax, 16)
    dq = _to_uint(0.0, -lim.vmax, lim.vmax, 12)
    kp_u = _to_uint(kp, 0.0, KP_MAX, 12)
    kd_u = _to_uint(kd, 0.0, KD_MAX, 12)
    tau = _to_uint(0.0, -lim.tmax, lim.tmax, 12)
    return bytes(
        [
            q >> 8,
            q & 0xFF,
            dq >> 4,
            ((dq & 0xF) << 4) | (kp_u >> 8),
            kp_u & 0xFF,
            kd_u >> 4,
            ((kd_u & 0xF) << 4) | (tau >> 8),
            tau & 0xFF,
        ]
    )


class DmBus:
    def __init__(self, channel: str) -> None:
        self.channel = channel
        self.sock = socket.socket(socket.AF_CAN, socket.SOCK_RAW, socket.CAN_RAW)
        self.sock.setsockopt(socket.SOL_CAN_RAW, socket.CAN_RAW_LOOPBACK, 0)
        self.sock.bind((channel,))
        self.sock.setblocking(False)
        self.feedback: dict[int, Feedback] = {}
        self.limits: dict[int, Limits] = {}
        self._regs: dict[tuple[int, int], bytes] = {}

    def _send(self, can_id: int, data: bytes) -> None:
        self.sock.send(struct.pack("=IB3x8s", can_id, 8, data))

    def poll(self) -> None:
        """Drain received frames into self.feedback / register replies."""
        while True:
            try:
                raw = self.sock.recv(16)
            except BlockingIOError:
                return
            data = raw[8:16]
            if data[2] == 0x33:
                self._regs[(data[0], data[3])] = data[4:8]
                continue
            mid = data[0] & 0x0F
            lim = self.limits.get(mid)
            if lim is None:
                continue
            q = (data[1] << 8) | data[2]
            self.feedback[mid] = Feedback(q / 65535 * 2 * lim.pmax - lim.pmax, data[0] >> 4, time.monotonic())

    def read_register(self, motor_id: int, rid: int, timeout: float = 0.1) -> bytes | None:
        self._regs.pop((motor_id, rid), None)
        self._send(MGMT_ID, bytes([motor_id, 0, 0x33, rid, 0, 0, 0, 0]))
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            self.poll()
            if (motor_id, rid) in self._regs:
                return self._regs[(motor_id, rid)]
            time.sleep(0.001)
        return None

    def load_limits(self, motor_id: int) -> Limits:
        """Read PMAX/VMAX/TMAX and check the motor is in MIT control mode."""
        vals = {}
        for rid in (REG_PMAX, REG_VMAX, REG_TMAX, REG_CTRL_MODE):
            raw = self.read_register(motor_id, rid)
            if raw is None:
                raise RuntimeError(f"motor {motor_id}: register {rid} not readable")
            vals[rid] = raw
        mode = struct.unpack("<I", vals[REG_CTRL_MODE])[0]
        if mode != CTRL_MODE_MIT:
            raise RuntimeError(f"motor {motor_id}: CTRL_MODE={mode}, expected MIT ({CTRL_MODE_MIT})")
        lim = Limits(*(struct.unpack("<f", vals[r])[0] for r in (REG_PMAX, REG_VMAX, REG_TMAX)))
        if not (1.0 < lim.pmax < 20 and 0 < lim.vmax < 100 and 0 < lim.tmax < 100):
            raise RuntimeError(f"motor {motor_id}: implausible limits {lim}")
        self.limits[motor_id] = lim
        return lim

    def query(self, motor_id: int, timeout: float = 0.05) -> Feedback | None:
        """Read-only status request on the management channel."""
        self.feedback.pop(motor_id, None)
        self._send(MGMT_ID, bytes([motor_id, 0, 0xCC, 0, 0, 0, 0, 0]))
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            self.poll()
            if motor_id in self.feedback:
                return self.feedback[motor_id]
            time.sleep(0.001)
        return None

    def enable(self, motor_id: int) -> None:
        self._send(motor_id, bytes([0xFF] * 7 + [0xFC]))

    def disable(self, motor_id: int) -> None:
        self._send(motor_id, bytes([0xFF] * 7 + [0xFD]))

    def disable_all(self, ids=range(1, 8)) -> None:
        """Send disable twice to every motor; never raises."""
        for _ in range(2):
            for mid in ids:
                try:
                    self.disable(mid)
                except OSError:
                    pass
            time.sleep(0.005)

    def send_mit(self, motor_id: int, pos_rad: float, kp: float, kd: float) -> None:
        self._send(motor_id, encode_mit(pos_rad, kp, kd, self.limits[motor_id]))

    def close(self) -> None:
        self.sock.close()
