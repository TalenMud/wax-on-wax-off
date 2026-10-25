"""Forward and inverse kinematics for the Metal arm, from its URDF (brain/arm/urdf/).

Motor angles go into the URDF as-is: joint1..joint6 = shoulder_pan..wrist_roll in radians,
no sign flips or zero offsets (the vendor ROS controller and MakerMods Lab's 3D view do the
same, see tools/makermodslab/makermodslab/arms/urdf.py). Zero is the upright pose the Lab
calibrated.

    python -m brain.arm.kinematics                # FK of the zero pose
    python -m brain.arm.kinematics 16 0 42 -80 34 0  # FK of a pose in degrees

Frames: "arm" is the URDF base_link (z up). The pad is a point PAD_OFFSET along the
gripper's pointing axis, and its face normal is that same axis.
"""

import math
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import numpy as np

URDF = Path(__file__).with_name("urdf") / "metal_with_gripper.urdf"
JOINTS = ("joint1", "joint2", "joint3", "joint4", "joint5", "joint6")
MOTORS = ("shoulder_pan", "shoulder_lift", "elbow_flex", "wrist_flex", "wrist_yaw", "wrist_roll")
TIP_LINK = "gripper_base"
PAD_OFFSET = 0.10  # metres from gripper_base to the pad face; measure on the real pad


def _rpy(r: float, p: float, y: float) -> np.ndarray:
    cr, sr, cp, sp, cy, sy = math.cos(r), math.sin(r), math.cos(p), math.sin(p), math.cos(y), math.sin(y)
    return np.array(
        [
            [cy * cp, cy * sp * sr - sy * cr, cy * sp * cr + sy * sr],
            [sy * cp, sy * sp * sr + cy * cr, sy * sp * cr - cy * sr],
            [-sp, cp * sr, cp * cr],
        ]
    )


def _axis_angle(axis: np.ndarray, a: float) -> np.ndarray:
    x, y, z = axis / np.linalg.norm(axis)
    c, s, C = math.cos(a), math.sin(a), 1 - math.cos(a)
    return np.array(
        [
            [c + x * x * C, x * y * C - z * s, x * z * C + y * s],
            [y * x * C + z * s, c + y * y * C, y * z * C - x * s],
            [z * x * C - y * s, z * y * C + x * s, c + z * z * C],
        ]
    )


def _tf(R: np.ndarray, p) -> np.ndarray:
    T = np.eye(4)
    T[:3, :3] = R
    T[:3, 3] = p
    return T


class Chain:
    """The base_link -> gripper_base chain: fixed origins interleaved with revolute joints."""

    def __init__(self, urdf: Path = URDF) -> None:
        by_child = {}
        for j in ET.parse(urdf).getroot().findall("joint"):
            o = j.find("origin")
            xyz = [float(v) for v in (o.get("xyz", "0 0 0") if o is not None else "0 0 0").split()]
            rpy = [float(v) for v in (o.get("rpy", "0 0 0") if o is not None else "0 0 0").split()]
            a = j.find("axis")
            lim = j.find("limit")
            by_child[j.find("child").get("link")] = {
                "name": j.get("name"),
                "type": j.get("type"),
                "parent": j.find("parent").get("link"),
                "origin": _tf(_rpy(*rpy), xyz),
                "axis": np.array([float(v) for v in (a.get("xyz") if a is not None else "0 0 1").split()]),
                "limits": (float(lim.get("lower")), float(lim.get("upper"))) if lim is not None else None,
            }
        steps, link = [], TIP_LINK
        while link in by_child and by_child[link]["parent"] != "world":
            steps.append(by_child[link])
            link = by_child[link]["parent"]
        self.steps = steps[::-1]
        names = [s["name"] for s in self.steps if s["type"] == "revolute"]
        assert tuple(names) == JOINTS, names
        self.limits = np.array([s["limits"] for s in self.steps if s["type"] == "revolute"])

    def tip(self, q: np.ndarray) -> np.ndarray:
        """4x4 pose of gripper_base in the arm frame for joint angles q (rad, 6)."""
        T, i = np.eye(4), 0
        for s in self.steps:
            T = T @ s["origin"]
            if s["type"] == "revolute":
                T = T @ _tf(_axis_angle(s["axis"], q[i]), [0, 0, 0])
                i += 1
        return T

    def pad(self, q: np.ndarray, offset: float = PAD_OFFSET) -> tuple[np.ndarray, np.ndarray]:
        """Pad centre and face normal (unit, pointing away from the arm) in the arm frame."""
        T = self.tip(q)
        n = T[:3, 0]  # gripper_base +x points out of the gripper
        return T[:3, 3] + offset * n, n

    def ik(
        self,
        target: np.ndarray,
        normal: np.ndarray | None,
        q0: np.ndarray,
        offset: float = PAD_OFFSET,
        lock: tuple[int, ...] = (5,),
        iters: int = 300,
        tol: float = 1e-3,
    ) -> tuple[np.ndarray, float]:
        """Joint angles that put the pad at target (and face normal along normal, if given).

        Damped least squares from q0, so the answer stays on q0's side (elbow up/down does not
        flip). Joints in lock keep q0's value (wrist_roll by default: a round pad does not care).
        Returns (q, position error in metres); q always respects the URDF limits.
        """
        q = q0.astype(float).copy()
        free = [i for i in range(6) if i not in lock]
        lo, hi = self.limits[:, 0], self.limits[:, 1]
        err = float("inf")
        for _ in range(iters):
            p, n = self.pad(q, offset)
            e = [target - p]
            if normal is not None:
                e.append(0.15 * (normal / np.linalg.norm(normal) - n))  # weight: 1 rad ~ 15 cm
            e = np.concatenate(e)
            err = float(np.linalg.norm(target - p))
            if err < tol and (normal is None or np.linalg.norm(e[3:]) < 0.15 * 0.05):
                break
            J = np.zeros((len(e), len(free)))
            for k, i in enumerate(free):
                dq = q.copy()
                dq[i] += 1e-5
                p2, n2 = self.pad(dq, offset)
                d = [(p2 - p) / 1e-5]
                if normal is not None:
                    d.append(0.15 * (n2 - n) / 1e-5)
                J[:, k] = -np.concatenate(d)
            lam = 0.02
            step = -np.linalg.solve(J.T @ J + lam * np.eye(len(free)), J.T @ e)
            step = np.clip(step, -0.1, 0.1)
            for k, i in enumerate(free):
                q[i] = min(hi[i], max(lo[i], q[i] + step[k]))
        return q, err


def solve_pad(chain: Chain, target: np.ndarray, seed: np.ndarray, offset: float = PAD_OFFSET):
    """Pad at target with its face pointing horizontally straight out from the arm base.

    The base pan aims at the target and wrist_yaw/wrist_roll stay at seed's values, which leaves a
    planar 3-joint problem (lift, elbow, wrist_flex) that has no wrist singularities to fall into.
    """
    pan = math.atan2(target[1], target[0])
    q0 = seed.astype(float).copy()
    q0[0] = pan
    return chain.ik(target, np.array([math.cos(pan), math.sin(pan), 0.0]), q0, offset, lock=(0, 4, 5))


def deg_to_q(deg: dict[str, float]) -> np.ndarray:
    return np.radians([deg[m] for m in MOTORS])


def q_to_deg(q: np.ndarray) -> dict[str, float]:
    return {m: round(math.degrees(v), 2) for m, v in zip(MOTORS, q)}


if __name__ == "__main__":
    chain = Chain()
    q = np.radians([float(v) for v in sys.argv[1:7]]) if len(sys.argv) >= 7 else np.zeros(6)
    p, n = chain.pad(q)
    print("pad centre (m):", np.round(p, 3), " normal:", np.round(n, 3))
    print("gripper_base (m):", np.round(chain.tip(q)[:3, 3], 3))
