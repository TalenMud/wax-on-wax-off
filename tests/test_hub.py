"""Hub unit tests — message building, command handling, estop priority."""

import asyncio
import json
import unittest
from pathlib import Path

import jsonschema

from brain.arm.interface import MockArm
from brain.hub.server import Hub

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "shared" / "schema.json"


class TestHub(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(SCHEMA_PATH) as f:
            schema = json.load(f)
        cls.validator = jsonschema.Draft202012Validator(schema)

    def setUp(self):
        self.arm = MockArm()
        self.arm.connect()
        self.hub = Hub(self.arm, mock=False)

    def test_state_validates_against_schema(self):
        msg = self.hub.build_state()
        self.validator.validate(msg)
        self.assertEqual(msg["type"], "state")
        self.assertIn("joints_deg", msg["arm"])
        self.assertEqual(len(msg["arm"]["joints_deg"]), 7)

    def test_hit_event_validates(self):
        msg = self.hub.build_event("hit", pad_target="high_left", hand="right", reaction_ms=200.0)
        self.validator.validate(msg)

    def test_estop_event_validates(self):
        msg = self.hub.build_event("estop")
        self.validator.validate(msg)

    def test_estop_calls_arm_estop_first(self):
        """estop must call arm.estop() immediately, before anything else."""
        self.assertFalse(self.hub.arm.estopped)
        asyncio.run(self.hub.handle_command({"action": "estop"}))
        self.assertTrue(self.hub.arm.estopped)
        self.assertEqual(self.hub.round_status, "stopped")

    def test_set_difficulty(self):
        asyncio.run(self.hub.handle_command({"action": "set_difficulty", "difficulty": "hard"}))
        self.assertEqual(self.hub.difficulty, "hard")

    def test_reset_score(self):
        self.hub.score["hits"] = 10
        asyncio.run(self.hub.handle_command({"action": "reset_score"}))
        self.assertEqual(self.hub.score["hits"], 0)

    def test_unknown_action_ignored(self):
        asyncio.run(self.hub.handle_command({"action": "dance"}))


if __name__ == "__main__":
    unittest.main()
