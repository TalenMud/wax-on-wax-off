"""Minimal RobStride MIT-protocol driver over raw SocketCAN for our B601-RS arms.

Frame formats follow lerobot.motors.robstride (standard 11-bit frames, arbitration id =
motor id; replies carry the motor id in data[0]). Position uses the measured +-2pi range,
not lerobot's +-12.57 (see mit_probe.py). Velocity and torque feed-forward are always 0,
so their (model-specific) ranges don't matter here.
"""

import math
import socket
import struct
import time
from dataclasses import dataclass

PMAX = 2 * math.pi
KP_MAX = 500.0
KD_MAX = 5.0

CMD_ENABLE = 0xFC
CMD_DISABLE = 0xFD
FAULT_QUERY = bytes([0xFF] * 6 + [0x00, 0xFB])
MODE_MIT = bytes([0xFF] * 6 + [0x00, 0xFC])


@dataclass
class Feedback:
    pos_rad: float
    t: float  # time.monotonic() when received


def _to_uint(x: float, lo: float, hi: float, bits: int) -> int:
    x = max(lo, min(hi, x))
    return int((x - lo) / (hi - lo) * ((1 << bits) - 1))


def encode_mit(pos_rad: float, kp: float, kd: float) -> bytes:
    q = _to_uint(pos_rad, -PMAX, PMAX, 16)
    dq = _to_uint(0.0, -1.0, 1.0, 12)  # zero velocity: midpoint of any symmetric range
    kp_u = _to_uint(kp, 0.0, KP_MAX, 12)
    kd_u = _to_uint(kd, 0.0, KD_MAX, 12)
    tau = _to_uint(0.0, -1.0, 1.0, 12)
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


class MitBus:
    def __init__(self, channel: str) -> None:
        self.channel = channel
        self.sock = socket.socket(socket.AF_CAN, socket.SOCK_RAW, socket.CAN_RAW)
        self.sock.setsockopt(socket.SOL_CAN_RAW, socket.CAN_RAW_LOOPBACK, 0)
        self.sock.bind((channel,))
        self.sock.setblocking(False)
        self.feedback: dict[int, Feedback] = {}

    def _send(self, motor_id: int, data: bytes) -> None:
        self.sock.send(struct.pack("=IB3x8s", motor_id, 8, data))

    def poll(self) -> None:
        """Drain received frames into self.feedback."""
        while True:
            try:
                raw = self.sock.recv(16)
            except BlockingIOError:
                return
            data = raw[8:16]
            q = (data[1] << 8) | data[2]
            self.feedback[data[0]] = Feedback(q / 65535 * 2 * PMAX - PMAX, time.monotonic())

    def query(self, motor_id: int, timeout: float = 0.05) -> Feedback | None:
        """Read-only position read."""
        self.feedback.pop(motor_id, None)
        self._send(motor_id, FAULT_QUERY)
        end = time.monotonic() + timeout
        while time.monotonic() < end:
            self.poll()
            if motor_id in self.feedback:
                return self.feedback[motor_id]
            time.sleep(0.001)
        return None

    def enable(self, motor_id: int) -> None:
        self._send(motor_id, bytes([0xFF] * 7 + [CMD_ENABLE]))
        time.sleep(0.01)
        self._send(motor_id, MODE_MIT)
        time.sleep(0.01)
        self.poll()

    def disable(self, motor_id: int) -> None:
        self._send(motor_id, bytes([0xFF] * 7 + [CMD_DISABLE]))

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
        self._send(motor_id, encode_mit(pos_rad, kp, kd))

    def close(self) -> None:
        self.sock.close()
