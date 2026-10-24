"""Round state-machine and scoring for Wax On Wax Off.

States
------
idle → countdown → active → paused → stopped
                                 ↑        ↓
                                 └────────┘  (pause/unpause)

Each round picks pad targets from ``PAD_TARGETS`` and calls
``arm.goto(pad)``.  The hub's vision system calls ``register_hit``
when a player's hand enters the active pad region.
"""

from __future__ import annotations

import asyncio
import logging
import random
import time
from typing import TYPE_CHECKING, Callable, Awaitable, Optional

from brain.arm.interface import MockArm, PAD_TARGETS

if TYPE_CHECKING:
    from brain.hub.server import Hub

logger = logging.getLogger(__name__)

# Difficulty presets  (pad_timeout_s, targets_per_round, arm_move_time_s)
_DIFF = {
    "easy":   (3.0, 8,  0.8),
    "medium": (2.2, 12, 0.6),
    "hard":   (1.5, 16, 0.4),
}


class GameEngine:
    """Drives rounds, pad selection, and scoring.

    Parameters
    ----------
    arm : MockArm
        Arm to move between pads.
    hub : Hub
        Reference back to the hub so the engine can push state changes
        and broadcast events.
    """

    COUNTDOWN_S = 3
    ROUND_DURATION_S = 60

    def __init__(self, arm: MockArm, hub: Hub) -> None:
        self.arm = arm
        self.hub = hub
        self.difficulty: str = "easy"

        self._round_task: asyncio.Task | None = None
        self._paused = asyncio.Event()
        self._paused.set()  # not paused
        self._hit_event = asyncio.Event()
        self._reaction_times: list[float] = []

    # ── Public API (called from Hub.handle_command) ───────────────────

    async def start_round(self) -> None:
        if self.hub.round_status not in ("idle", "stopped"):
            return

        self.arm.reset_estop()
        if not self.arm.connected:
            self.arm.connect()

        self.hub.round_number += 1
        self.hub.round_status = "countdown"
        await self.hub.broadcast(
            self.hub.build_event("round_start", pad_target=None)
        )

        for remaining in range(self.COUNTDOWN_S, 0, -1):
            self.hub.time_left_s = float(remaining)
            await asyncio.sleep(1)

        self.hub.round_status = "active"
        self.hub.time_left_s = float(self.ROUND_DURATION_S)
        self._round_task = asyncio.create_task(self._run_round())

    def pause(self) -> None:
        if self.hub.round_status == "active":
            self.hub.round_status = "paused"
            self._paused.clear()
        elif self.hub.round_status == "paused":
            self.hub.round_status = "active"
            self._paused.set()

    def stop(self) -> None:
        self.hub.round_status = "stopped"
        if self._round_task and not self._round_task.done():
            self._round_task.cancel()

    def reset_score(self) -> None:
        self.hub.score = {
            "hits": 0,
            "misses": 0,
            "combo_streak": 0,
            "avg_reaction_ms": None,
        }
        self._reaction_times.clear()
        self.hub.round_number = 0

    def set_difficulty(self, level: str) -> None:
        if level in _DIFF:
            self.difficulty = level

    # ── Hit registration (called by VisionTracker) ────────────────────

    def register_hit(self, hit_time: float, hand: str = "right") -> None:
        """Record a successful strike.

        Parameters
        ----------
        hit_time : float
            ``time.time()`` when the hand entered the pad region.
        hand : str
            ``"left"`` or ``"right"``.
        """
        arrived = self.arm.arrived_at()
        if self.hub.round_status != "active" or arrived is None:
            return

        reaction_ms = (hit_time - arrived) * 1000
        if reaction_ms < 0:
            return  # struck before the arm arrived — ignore

        self.hub.score["hits"] += 1
        self.hub.score["combo_streak"] += 1
        self._reaction_times.append(reaction_ms)
        self.hub.score["avg_reaction_ms"] = (
            sum(self._reaction_times) / len(self._reaction_times)
        )

        pad = self.arm.current_target()
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(
                self.hub.broadcast(
                    self.hub.build_event(
                        "hit",
                        pad_target=pad,
                        hand=hand,
                        reaction_ms=reaction_ms,
                    )
                )
            )

            streak = self.hub.score["combo_streak"]
            if streak > 0 and streak % 5 == 0:
                loop.create_task(
                    self.hub.broadcast(
                        self.hub.build_event("block", pad_target=pad, message=f"{streak}-hit combo!")
                    )
                )
        except RuntimeError:
            pass

        self._hit_event.set()

    # ── Internal round loop ──────────────────────────────────────────

    def _pick_targets(self) -> list[str]:
        _, count, _ = _DIFF[self.difficulty]
        targets: list[str] = []
        prev: str | None = None
        for _ in range(count):
            pool = [p for p in PAD_TARGETS if p != prev]
            pad = random.choice(pool)
            targets.append(pad)
            prev = pad
        return targets

    async def _run_round(self) -> None:
        timeout_s, _, _ = _DIFF[self.difficulty]
        targets = self._pick_targets()

        try:
            for pad in targets:
                await self._paused.wait()
                if self.hub.round_status not in ("active",):
                    return

                self._hit_event.clear()
                self.arm.goto(pad)

                # Wait for the arm to arrive
                while self.arm.is_moving():
                    await asyncio.sleep(0.02)

                # Now wait for hit or timeout
                try:
                    await asyncio.wait_for(
                        self._wait_for_hit(), timeout=timeout_s
                    )
                except asyncio.TimeoutError:
                    # Miss
                    self.hub.score["misses"] += 1
                    self.hub.score["combo_streak"] = 0
                    await self.hub.broadcast(
                        self.hub.build_event("miss", pad_target=pad)
                    )

            # Round complete
            self.hub.round_status = "stopped"
            await self.hub.broadcast(
                self.hub.build_event("round_end")
            )
        except asyncio.CancelledError:
            pass

    async def _wait_for_hit(self) -> None:
        """Block until ``register_hit`` fires ``_hit_event``."""
        while not self._hit_event.is_set():
            await asyncio.sleep(0.005)
