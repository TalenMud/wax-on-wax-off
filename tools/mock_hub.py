# /// script
# requires-python = ">=3.10"
# dependencies = ["websockets>=13"]
# ///
"""Mock hub: sends fake game state so web/ and vr/ can be built without the arm.

    uv run tools/mock_hub.py

Clients connect to ws://<this-machine-ip>:8765. It speaks the same protocol as the
real hub in brain/ (see shared/schema.json once it lands on main).
"""

import argparse
import asyncio
import json
import logging
import math
import random
import time

import websockets

logger = logging.getLogger("mock_hub")

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
STATE_HZ = 20


class Hub:
    def __init__(self) -> None:
        self.clients: set = set()
        self.commands: asyncio.Queue = asyncio.Queue()

    async def handler(self, ws) -> None:
        self.clients.add(ws)
        logger.info(f"client connected ({len(self.clients)} total)")
        try:
            async for raw in ws:
                try:
                    msg = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if msg.get("type") == "command":
                    await self.commands.put(msg)
        finally:
            self.clients.discard(ws)
            logger.info(f"client disconnected ({len(self.clients)} total)")

    def broadcast(self, msg: dict) -> None:
        websockets.broadcast(self.clients, json.dumps(msg))


class MockGame:
    """Fake game loop so the VR and web clients can be built without the arm."""

    def __init__(self, hub: Hub) -> None:
        self.hub = hub
        self.status = "idle"
        self.round_number = 0
        self.round_end = 0.0
        self.difficulty = "medium"
        self.hits = 0
        self.misses = 0
        self.streak = 0
        self.reactions: list[float] = []
        self.pad_target = PAD_TARGETS[0]
        self.next_strike = 0.0

    def handle(self, cmd: dict) -> None:
        action = cmd.get("action")
        if action == "start_round":
            self.status = "active"
            self.round_number += 1
            self.round_end = time.time() + 60
            self.hub.broadcast({"type": "event", "t": time.time(), "kind": "round_start"})
        elif action in ("stop", "estop"):
            self.status = "stopped"
            if action == "estop":
                self.hub.broadcast({"type": "event", "t": time.time(), "kind": "estop"})
        elif action == "pause":
            self.status = "paused"
        elif action == "reset_score":
            self.hits = self.misses = self.streak = 0
            self.reactions.clear()
        elif action == "set_difficulty" and cmd.get("difficulty"):
            self.difficulty = cmd["difficulty"]

    def tick(self, now: float) -> dict:
        if self.status == "active":
            if now >= self.round_end:
                self.status = "idle"
                self.hub.broadcast({"type": "event", "t": now, "kind": "round_end"})
            elif now >= self.next_strike:
                self._fake_strike(now)

        phase = now * 0.8
        joints = {name: round(30 * math.sin(phase + i), 2) for i, name in enumerate(JOINT_NAMES)}
        return {
            "type": "state",
            "t": now,
            "round": {
                "status": self.status,
                "number": self.round_number,
                "time_left_s": max(0.0, round(self.round_end - now, 1)) if self.status == "active" else 0.0,
                "difficulty": self.difficulty,
            },
            "arm": {"connected": False, "estop": self.status == "stopped", "joints_deg": joints, "pad_target": self.pad_target},
            "player": {
                "tracked": True,
                "left_hand": [0.45, 0.2 + 0.05 * math.sin(phase * 3), 1.2],
                "right_hand": [0.45, -0.2 + 0.05 * math.cos(phase * 3), 1.2],
                "head": [0.6, 0.0, 1.6],
            },
            "score": {
                "hits": self.hits,
                "misses": self.misses,
                "combo_streak": self.streak,
                "avg_reaction_ms": round(sum(self.reactions) / len(self.reactions)) if self.reactions else None,
            },
            "coach": {"combo": ["jab", "jab", "cross"], "line": "Keep your guard up."},
            "latency_ms": {"camera": 17.0, "pose": random.uniform(8, 20), "control": random.uniform(1, 3)},
        }

    def _fake_strike(self, now: float) -> None:
        hand = random.choice(("left", "right"))
        if random.random() < 0.8:
            reaction = random.uniform(250, 600)
            self.hits += 1
            self.streak += 1
            self.reactions.append(reaction)
            self.hub.broadcast(
                {"type": "event", "t": now, "kind": "hit", "hand": hand, "pad_target": self.pad_target, "reaction_ms": round(reaction)}
            )
        else:
            self.misses += 1
            self.streak = 0
            self.hub.broadcast({"type": "event", "t": now, "kind": "miss", "pad_target": self.pad_target})
        self.pad_target = random.choice(PAD_TARGETS)
        self.next_strike = now + random.uniform(0.8, 1.6)


async def run_mock(hub: Hub) -> None:
    game = MockGame(hub)
    while True:
        while not hub.commands.empty():
            game.handle(hub.commands.get_nowait())
        hub.broadcast(game.tick(time.time()))
        await asyncio.sleep(1 / STATE_HZ)


async def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="0.0.0.0")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()

    hub = Hub()
    async with websockets.serve(hub.handler, args.host, args.port):
        logger.info(f"mock hub listening on ws://{args.host}:{args.port}")
        await run_mock(hub)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    asyncio.run(main())
