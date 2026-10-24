"""WebSocket hub — the central nervous system of Wax On Wax Off.

Broadcasts ``state`` at 20 Hz and ``event``s to every connected client.
Accepts ``command`` messages (start_round | pause | stop | estop | reset_score | set_difficulty).

Run with:  python -m brain.hub --mock
"""

from __future__ import annotations

import asyncio
import json
import logging
import random
import time
from pathlib import Path
from typing import TYPE_CHECKING, Set

import websockets
from websockets.server import WebSocketServerProtocol

from brain.arm.interface import MockArm, PAD_TARGETS, JOINT_NAMES

if TYPE_CHECKING:
    from brain.game.engine import GameEngine

logger = logging.getLogger(__name__)

SCHEMA_PATH = Path(__file__).resolve().parent.parent.parent / "shared" / "schema.json"

VALID_ACTIONS = frozenset(
    {"start_round", "pause", "stop", "estop", "reset_score", "set_difficulty"}
)

DIFFICULTY_LEVELS = ("easy", "medium", "hard")


class Hub:
    """Async WebSocket hub that owns the game loop and arm reference.

    Parameters
    ----------
    arm : MockArm
        The arm (real or mock) to drive.
    mock : bool
        When *True* the hub fabricates player/score data at 20 Hz so
        front-end developers can work without hardware.
    """

    def __init__(self, arm: MockArm, *, mock: bool = False) -> None:
        self.arm = arm
        self.mock = mock
        self.clients: Set[WebSocketServerProtocol] = set()

        # Round / game state --------------------------------------------------
        self.round_status: str = "idle"          # idle|countdown|active|paused|stopped
        self.round_number: int = 0
        self.time_left_s: float = 0.0
        self.difficulty: str = "easy"

        # Score ----------------------------------------------------------------
        self.score = {
            "hits": 0,
            "misses": 0,
            "combo_streak": 0,
            "avg_reaction_ms": None,
        }

        # Player tracking (filled by VisionTracker or mock) --------------------
        self.player = {
            "tracked": False,
            "left_hand": None,
            "right_hand": None,
            "head": None,
        }

        # Coach (filled by CoachAdvisor) ---------------------------------------
        self.coach = {"combo": [], "line": ""}

        # Latency bookkeeping --------------------------------------------------
        self.latency_ms: dict[str, float | None] = {}

        # Internal -------------------------------------------------------------
        self._running = False
        self._game_engine: GameEngine | None = None
        self._server = None

    # ── Attach optional subsystems ────────────────────────────────────

    def attach_game_engine(self, engine: GameEngine) -> None:
        self._game_engine = engine

    # ── Message builders (match shared/schema.json v1) ────────────────

    def build_state(self) -> dict:
        return {
            "type": "state",
            "t": time.time(),
            "round": {
                "status": self.round_status,
                "number": self.round_number,
                "time_left_s": self.time_left_s,
                "difficulty": self.difficulty,
            },
            "arm": {
                "connected": self.arm.connected,
                "estop": self.arm.estopped,
                "joints_deg": self.arm.read_joints_deg(),
                "pad_target": self.arm.current_target(),
            },
            "player": self.player.copy(),
            "score": self.score.copy(),
            "coach": self.coach.copy(),
            "latency_ms": self.latency_ms.copy(),
        }

    def build_event(self, kind: str, **extra) -> dict:
        msg: dict = {"type": "event", "t": time.time(), "kind": kind}
        msg.update(extra)
        return msg

    # ── Broadcasting ─────────────────────────────────────────────────

    async def broadcast(self, message: dict) -> None:
        if not self.clients:
            return
        payload = json.dumps(message)
        gone: set[WebSocketServerProtocol] = set()
        for ws in self.clients:
            try:
                await ws.send(payload)
            except websockets.ConnectionClosed:
                gone.add(ws)
        self.clients -= gone

    # ── Command handling ─────────────────────────────────────────────

    async def handle_command(self, data: dict) -> None:
        action = data.get("action")
        if action not in VALID_ACTIONS:
            logger.warning("Unknown action: %s", action)
            return

        # ── ESTOP: call arm.estop() IMMEDIATELY, before anything else ──
        if action == "estop":
            self.arm.estop()
            self.round_status = "stopped"
            await self.broadcast(self.build_event("estop"))
            logger.warning("ESTOP triggered")
            return

        if action == "start_round":
            if self._game_engine:
                await self._game_engine.start_round()
            elif self.mock:
                self.round_status = "active"
                self.round_number += 1
                self.time_left_s = 60.0
                self.arm.connect()
                await self.broadcast(
                    self.build_event("round_start", pad_target=None)
                )

        elif action == "pause":
            if self._game_engine:
                self._game_engine.pause()
            elif self.round_status == "active":
                self.round_status = "paused"
            elif self.round_status == "paused":
                self.round_status = "active"

        elif action == "stop":
            if self._game_engine:
                self._game_engine.stop()
            else:
                self.round_status = "stopped"
            await self.broadcast(self.build_event("round_end"))

        elif action == "reset_score":
            self.score = {
                "hits": 0,
                "misses": 0,
                "combo_streak": 0,
                "avg_reaction_ms": None,
            }
            if self._game_engine:
                self._game_engine.reset_score()

        elif action == "set_difficulty":
            diff = data.get("difficulty", "easy")
            if diff in DIFFICULTY_LEVELS:
                self.difficulty = diff
                if self._game_engine:
                    self._game_engine.set_difficulty(diff)

    # ── Per-client handler ───────────────────────────────────────────

    async def _ws_handler(self, websocket: WebSocketServerProtocol) -> None:
        self.clients.add(websocket)
        logger.info("Client connected (%d total)", len(self.clients))
        try:
            async for raw in websocket:
                try:
                    data = json.loads(raw)
                except json.JSONDecodeError:
                    logger.warning("Bad JSON from client")
                    continue
                if data.get("type") == "command":
                    await self.handle_command(data)
        except websockets.ConnectionClosed:
            pass
        finally:
            self.clients.discard(websocket)
            logger.info("Client disconnected (%d total)", len(self.clients))

    # ── Mock 20 Hz loop ──────────────────────────────────────────────

    async def _mock_loop(self) -> None:
        """Fabricate fake player/score data and broadcast state at 20 Hz."""
        interval = 1.0 / 20
        tick = 0

        while self._running:
            t0 = time.monotonic()

            if self.round_status == "active":
                # Countdown timer
                self.time_left_s = max(0.0, self.time_left_s - interval)
                if self.time_left_s <= 0:
                    self.round_status = "stopped"
                    await self.broadcast(self.build_event("round_end"))

                # Fake player body
                self.player = {
                    "tracked": True,
                    "left_hand": [
                        random.uniform(-0.5, 0.5),
                        random.uniform(0.8, 1.6),
                        random.uniform(0.3, 1.0),
                    ],
                    "right_hand": [
                        random.uniform(-0.5, 0.5),
                        random.uniform(0.8, 1.6),
                        random.uniform(0.3, 1.0),
                    ],
                    "head": [0.0, 1.7, 0.6],
                }

                # Every ~2 s pick a new pad, score a random hit/miss
                tick += 1
                if tick % 40 == 0:
                    pad = random.choice(PAD_TARGETS)
                    self.arm.goto(pad)

                    if random.random() < 0.7:
                        self.score["hits"] += 1
                        self.score["combo_streak"] += 1
                        r_ms = random.uniform(180, 550)
                        prev = self.score["avg_reaction_ms"]
                        n = self.score["hits"]
                        self.score["avg_reaction_ms"] = (
                            r_ms if prev is None else (prev * (n - 1) + r_ms) / n
                        )
                        await self.broadcast(
                            self.build_event(
                                "hit",
                                pad_target=pad,
                                hand=random.choice(["left", "right"]),
                                reaction_ms=r_ms,
                            )
                        )
                    else:
                        self.score["misses"] += 1
                        self.score["combo_streak"] = 0
                        await self.broadcast(
                            self.build_event("miss", pad_target=pad)
                        )

                self.latency_ms = {
                    "frame_captured": random.uniform(1, 4),
                    "pose_done": random.uniform(8, 16),
                    "event_emitted": random.uniform(0.1, 0.8),
                }

            else:
                self.player = {
                    "tracked": False,
                    "left_hand": None,
                    "right_hand": None,
                    "head": None,
                }

            await self.broadcast(self.build_state())
            elapsed = time.monotonic() - t0
            await asyncio.sleep(max(0, interval - elapsed))

    # ── Server lifecycle ─────────────────────────────────────────────

    async def run(self, host: str = "0.0.0.0", port: int = 8765) -> None:
        self._running = True
        logger.info("Hub starting on ws://%s:%d  (mock=%s)", host, port, self.mock)

        async with websockets.serve(self._ws_handler, host, port) as server:
            self._server = server
            tasks: list[asyncio.Task] = []
            if self.mock:
                tasks.append(asyncio.create_task(self._mock_loop()))

            try:
                await asyncio.Future()  # run forever
            except asyncio.CancelledError:
                pass
            finally:
                self._running = False
                for t in tasks:
                    t.cancel()

    async def shutdown(self) -> None:
        self._running = False
        if self._server:
            self._server.close()
