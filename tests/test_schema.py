"""Validate outgoing hub messages against shared/schema.json using unittest."""

import json
import time
import unittest
from pathlib import Path

import jsonschema

SCHEMA_PATH = Path(__file__).resolve().parent.parent / "shared" / "schema.json"


def _base_state(**overrides) -> dict:
    msg = {
        "type": "state",
        "t": time.time(),
        "round": {
            "status": "idle",
            "number": 0,
            "time_left_s": 0.0,
            "difficulty": "easy",
        },
        "arm": {
            "connected": True,
            "estop": False,
            "joints_deg": {
                "shoulder_pan": 0.0,
                "shoulder_lift": 0.0,
                "elbow_flex": 0.0,
                "wrist_flex": 0.0,
                "wrist_yaw": 0.0,
                "wrist_roll": 0.0,
                "gripper": 0.0,
            },
            "pad_target": None,
        },
        "player": {
            "tracked": False,
            "left_hand": None,
            "right_hand": None,
            "head": None,
        },
        "score": {
            "hits": 0,
            "misses": 0,
            "combo_streak": 0,
            "avg_reaction_ms": None,
        },
        "coach": {"combo": [], "line": ""},
        "latency_ms": {},
    }
    msg.update(overrides)
    return msg


class TestSchemaValidation(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with open(SCHEMA_PATH) as f:
            schema = json.load(f)
        cls.validator = jsonschema.Draft202012Validator(schema)

    def test_idle_state_valid(self):
        self.validator.validate(_base_state())

    def test_active_state_with_player(self):
        msg = _base_state(
            round={
                "status": "active",
                "number": 1,
                "time_left_s": 45.0,
                "difficulty": "medium",
            },
            player={
                "tracked": True,
                "left_hand": [0.3, 1.2, 0.5],
                "right_hand": [-0.4, 1.5, 0.6],
                "head": [0.0, 1.7, 0.6],
            },
            score={
                "hits": 5,
                "misses": 2,
                "combo_streak": 3,
                "avg_reaction_ms": 350.0,
            },
            coach={
                "combo": ["high_left", "mid_right"],
                "line": "Wax on, wax off!",
            },
            latency_ms={
                "frame_captured": 3.2,
                "pose_done": 12.1,
                "event_emitted": 0.5,
            },
        )
        self.validator.validate(msg)

    def test_invalid_status_rejected(self):
        msg = _base_state()
        msg["round"]["status"] = "INVALID"
        with self.assertRaises(jsonschema.ValidationError):
            self.validator.validate(msg)

    def test_missing_required_field_rejected(self):
        msg = {"type": "state", "t": 1.0}
        with self.assertRaises(jsonschema.ValidationError):
            self.validator.validate(msg)

    def test_hit_event(self):
        msg = {
            "type": "event",
            "t": time.time(),
            "kind": "hit",
            "pad_target": "high_left",
            "hand": "right",
            "reaction_ms": 280.5,
        }
        self.validator.validate(msg)

    def test_estop_event(self):
        msg = {"type": "event", "t": time.time(), "kind": "estop"}
        self.validator.validate(msg)

    def test_miss_event(self):
        msg = {
            "type": "event",
            "t": time.time(),
            "kind": "miss",
            "pad_target": "mid_right",
        }
        self.validator.validate(msg)

    def test_invalid_kind_rejected(self):
        msg = {"type": "event", "t": time.time(), "kind": "invalid_event"}
        with self.assertRaises(jsonschema.ValidationError):
            self.validator.validate(msg)

    def test_start_round_command(self):
        msg = {"type": "command", "action": "start_round"}
        self.validator.validate(msg)

    def test_set_difficulty_command(self):
        msg = {"type": "command", "action": "set_difficulty", "difficulty": "hard"}
        self.validator.validate(msg)

    def test_estop_command(self):
        msg = {"type": "command", "action": "estop"}
        self.validator.validate(msg)

    def test_invalid_action_rejected(self):
        msg = {"type": "command", "action": "invalid_cmd"}
        with self.assertRaises(jsonschema.ValidationError):
            self.validator.validate(msg)


if __name__ == "__main__":
    unittest.main()
