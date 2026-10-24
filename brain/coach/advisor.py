"""AI coach — llama.cpp server with JSON-schema-constrained output.

Runs as a background ``asyncio`` task. Queues requests and never
blocks the hub or the game control loop.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from brain.hub.server import Hub

logger = logging.getLogger(__name__)

# JSON-schema constraint sent to llama.cpp for structured output
COACH_RESPONSE_SCHEMA = {
    "type": "object",
    "required": ["combo", "line"],
    "properties": {
        "combo": {
            "type": "array",
            "items": {"type": "string"},
            "description": "Suggested combo pad sequence",
        },
        "line": {
            "type": "string",
            "description": "Short motivational coaching line",
        },
    },
}

SYSTEM_PROMPT = """\
You are Sensei, the AI coach for Wax On Wax Off — a reflex-training \
game where a robot arm holds a pad and the player must strike it.

Analyse the player's live performance stats, then respond with JSON:
  {"combo": ["pad1","pad2",...], "line": "short motivational quote"}

Available pads: high_left, high_right, mid_left, mid_right.
Keep the coaching line under 80 characters.
Be encouraging but push the player. Channel Mr. Miyagi.\
"""


class CoachAdvisor:
    """Non-blocking LLM coaching via a llama.cpp ``/v1/chat/completions``
    endpoint.

    Parameters
    ----------
    hub : Hub
        The hub whose ``coach`` dict is updated with the latest advice.
    server_url : str
        Base URL of the llama.cpp server (default ``http://localhost:8080``).
    poll_interval_s : float
        Minimum seconds between LLM calls (default 5).
    """

    def __init__(
        self,
        hub: Hub,
        server_url: str = "http://localhost:8080",
        poll_interval_s: float = 5.0,
    ) -> None:
        self.hub = hub
        self._url = server_url.rstrip("/") + "/v1/chat/completions"
        self._poll_s = poll_interval_s
        self._running = False
        self._task: asyncio.Task | None = None

    def start(self) -> None:
        """Launch the background coaching loop (call once)."""
        self._running = True
        self._task = asyncio.create_task(self._loop())
        logger.info("Coach advisor started (server=%s)", self._url)

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass

    async def _loop(self) -> None:
        try:
            import aiohttp
        except ImportError:
            logger.warning("Coach requires aiohttp: pip install aiohttp")
            return

        async with aiohttp.ClientSession() as session:
            while self._running:
                try:
                    if self.hub.round_status == "active":
                        advice = await self._ask(session)
                        if advice:
                            self.hub.coach = advice
                except asyncio.CancelledError:
                    raise
                except Exception:
                    logger.debug("Coach request failed", exc_info=True)

                await asyncio.sleep(self._poll_s)

    async def _ask(self, session) -> Optional[dict]:
        score = self.hub.score
        prompt = (
            f"Player stats — Hits: {score['hits']}, "
            f"Misses: {score['misses']}, "
            f"Combo: {score['combo_streak']}, "
            f"Avg reaction: {score['avg_reaction_ms']}"
            f"ms, Difficulty: {self.hub.difficulty}"
        )

        payload = {
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.7,
            "max_tokens": 200,
            "response_format": {
                "type": "json_object",
                "schema": COACH_RESPONSE_SCHEMA,
            },
        }

        import aiohttp

        async with session.post(
            self._url,
            json=payload,
            timeout=aiohttp.ClientTimeout(total=10),
        ) as resp:
            if resp.status != 200:
                logger.debug("llama.cpp returned %d", resp.status)
                return None
            data = await resp.json()

        content = data["choices"][0]["message"]["content"]
        return json.loads(content)
