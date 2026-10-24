"""Arm interface shared by the hub/game (brain/hub, brain/game) and the real arm (brain/arm).

Everything outside brain/arm/ talks to the arm only through ArmInterface. Use MockArm
when the robot is not connected; it has the same timing behaviour, roughly.
"""

import math
import threading
import time
from typing import Protocol

JOINT_NAMES = (
    "shoulder_pan",
    "shoulder_lift",
    "elbow_flex",
    "wrist_flex",
    "wrist_yaw",
    "wrist_roll",
    "gripper",
)
PAD_TARGETS = ("high_left", "high_right", "mid_left", "mid_right")


class ArmInterface(Protocol):
    connected: bool
    estopped: bool

    def connect(self) -> None: ...

    def disconnect(self) -> None:
        """Disable torque and close the bus."""

    def read_joints_deg(self) -> dict[str, float]:
        """Latest joint positions keyed by JOINT_NAMES. Never blocks on the bus."""

    def goto(self, pad: str) -> None:
        """Start moving to a taught pad pose. Returns immediately. Ignored while estopped."""

    def current_target(self) -> str | None: ...

    def is_moving(self) -> bool: ...

    def arrived_at(self) -> float | None:
        """time.time() when the arm reached current_target, or None while moving."""

    def estop(self) -> None:
        """Disable torque right away and latch. Only reset_estop() clears it."""

    def reset_estop(self) -> None: ...


class MockArm:
    """Fake arm: each goto() takes MOVE_S seconds and interpolates fake joint angles."""

    MOVE_S = 0.6
    _POSES = {
        pad: {name: 20 * math.sin(i + j) for j, name in enumerate(JOINT_NAMES)} for i, pad in enumerate(PAD_TARGETS)
    }

    def __init__(self) -> None:
        self.connected = False
        self.estopped = False
        self._lock = threading.Lock()
        self._target: str | None = None
        self._from = dict.fromkeys(JOINT_NAMES, 0.0)
        self._move_start = 0.0

    def connect(self) -> None:
        self.connected = True

    def disconnect(self) -> None:
        self.connected = False

    def _progress(self, now: float) -> float:
        return min(1.0, (now - self._move_start) / self.MOVE_S)

    def read_joints_deg(self) -> dict[str, float]:
        with self._lock:
            if self._target is None:
                return dict(self._from)
            p = self._progress(time.time())
            goal = self._POSES[self._target]
            return {n: self._from[n] + (goal[n] - self._from[n]) * p for n in JOINT_NAMES}

    def goto(self, pad: str) -> None:
        if pad not in PAD_TARGETS:
            raise ValueError(f"unknown pad {pad!r}")
        if self.estopped:
            return
        current = self.read_joints_deg()
        with self._lock:
            self._from = current
            self._target = pad
            self._move_start = time.time()

    def current_target(self) -> str | None:
        return self._target

    def is_moving(self) -> bool:
        return self._target is not None and self._progress(time.time()) < 1.0

    def arrived_at(self) -> float | None:
        if self._target is None or self.is_moving():
            return None
        return self._move_start + self.MOVE_S

    def estop(self) -> None:
        self.estopped = True

    def reset_estop(self) -> None:
        self.estopped = False
