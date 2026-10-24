"""Entry-point: ``python -m brain.hub [--mock]``."""

import argparse
import asyncio
import logging
import sys

from brain.arm.interface import MockArm
from brain.hub.server import Hub


def main() -> None:
    ap = argparse.ArgumentParser(description="Wax On Wax Off – WebSocket Hub")
    ap.add_argument("--mock", action="store_true",
                    help="Send fake state at 20 Hz (no hardware needed)")
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--log-level", default="INFO",
                    choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    args = ap.parse_args()

    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s [%(name)s] %(levelname)s  %(message)s",
        stream=sys.stderr,
    )

    arm = MockArm()
    hub = Hub(arm, mock=args.mock)

    # If not --mock, try wiring up the full game engine
    if not args.mock:
        try:
            from brain.game.engine import GameEngine
            engine = GameEngine(arm, hub)
            hub.attach_game_engine(engine)
            logging.getLogger(__name__).info("Game engine attached")
        except Exception as exc:
            logging.getLogger(__name__).warning(
                "Game engine not available: %s", exc
            )

    try:
        asyncio.run(hub.run(host=args.host, port=args.port))
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
