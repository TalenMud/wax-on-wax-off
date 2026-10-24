"""Game engine unit tests — state machine, scoring, hit registration."""

import time
import unittest

from brain.arm.interface import MockArm
from brain.hub.server import Hub
from brain.game.engine import GameEngine


class TestGame(unittest.TestCase):
    def setUp(self):
        self.arm = MockArm()
        self.arm.connect()
        self.hub = Hub(self.arm, mock=False)
        self.engine = GameEngine(self.arm, self.hub)
        self.hub.attach_game_engine(self.engine)

    def test_initial_score(self):
        self.assertEqual(self.hub.score["hits"], 0)
        self.assertEqual(self.hub.score["misses"], 0)
        self.assertEqual(self.hub.score["combo_streak"], 0)
        self.assertIsNone(self.hub.score["avg_reaction_ms"])

    def test_register_hit_updates_score(self):
        self.hub.round_status = "active"
        self.arm.goto("high_left")
        # Wait for mock arm to "arrive" (MOVE_S = 0.6s)
        time.sleep(0.7)
        self.engine.register_hit(time.time(), hand="right")
        self.assertEqual(self.hub.score["hits"], 1)
        self.assertEqual(self.hub.score["combo_streak"], 1)
        self.assertIsNotNone(self.hub.score["avg_reaction_ms"])

    def test_register_hit_before_arrival_ignored(self):
        self.hub.round_status = "active"
        self.arm.goto("mid_left")
        # Don't wait — arm is still moving
        self.engine.register_hit(time.time(), hand="left")
        self.assertEqual(self.hub.score["hits"], 0)

    def test_reset_score(self):
        self.hub.score["hits"] = 5
        self.hub.score["combo_streak"] = 3
        self.engine.reset_score()
        self.assertEqual(self.hub.score["hits"], 0)
        self.assertEqual(self.hub.score["combo_streak"], 0)

    def test_set_difficulty(self):
        self.engine.set_difficulty("hard")
        self.assertEqual(self.engine.difficulty, "hard")

    def test_invalid_difficulty_ignored(self):
        self.engine.set_difficulty("impossible")
        self.assertEqual(self.engine.difficulty, "easy")

    def test_pause_toggles(self):
        self.hub.round_status = "active"
        self.engine.pause()
        self.assertEqual(self.hub.round_status, "paused")
        self.engine.pause()
        self.assertEqual(self.hub.round_status, "active")

    def test_pause_from_idle_does_nothing(self):
        self.hub.round_status = "idle"
        self.engine.pause()
        self.assertEqual(self.hub.round_status, "idle")


if __name__ == "__main__":
    unittest.main()
