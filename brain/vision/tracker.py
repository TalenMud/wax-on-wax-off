"""Vision pipeline — webcam → MediaPipe Pose/Hands → body tracking + hit detection.

Runs as an asyncio task alongside the hub. Feeds ``left_hand``,
``right_hand``, and ``head`` positions into ``Hub.player`` and calls
``GameEngine.register_hit`` when a hand enters the active pad region.
"""

from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from brain.game.engine import GameEngine
    from brain.hub.server import Hub

logger = logging.getLogger(__name__)

PAD_REGIONS_PATH = Path(__file__).parent / "pad_regions.json"


def _lm_to_vec3(landmark) -> list[float]:
    """Convert a MediaPipe landmark to a ``[x, y, z]`` list (schema vec3)."""
    return [float(landmark.x), float(landmark.y), float(landmark.z)]


def _point_in_region(point: list[float], region: dict) -> bool:
    """Check if a normalised ``[x, y, z]`` point falls inside a rectangular region."""
    return (
        region["x_min"] <= point[0] <= region["x_max"]
        and region["y_min"] <= point[1] <= region["y_max"]
    )


class VisionTracker:
    """MediaPipe Pose + Hands tracker with pad-region hit detection.

    Parameters
    ----------
    hub : Hub
        The hub whose ``player`` and ``latency_ms`` dicts we update.
    engine : GameEngine | None
        If provided, ``register_hit`` is called on strike detection.
    camera_index : int
        OpenCV camera index (default ``0``).
    """

    def __init__(
        self,
        hub: Hub,
        engine: Optional[GameEngine] = None,
        camera_index: int = 0,
    ) -> None:
        self.hub = hub
        self.engine = engine
        self._camera_index = camera_index
        self._running = False
        self._pad_regions: dict[str, dict] = {}
        self._last_hit_pad: Optional[str] = None
        self._load_pad_regions()

    def _load_pad_regions(self) -> None:
        if PAD_REGIONS_PATH.exists():
            try:
                with open(PAD_REGIONS_PATH) as f:
                    self._pad_regions = json.load(f)
                logger.info("Loaded %d pad regions from calibration", len(self._pad_regions))
            except Exception as e:
                logger.warning("Failed to load pad regions: %s", e)
        else:
            logger.info("No pad calibration found at %s", PAD_REGIONS_PATH)

    async def run(self) -> None:
        """Capture frames, run MediaPipe, update hub, detect hits."""
        try:
            import cv2
            import mediapipe as mp
        except ImportError:
            logger.warning(
                "Vision requires opencv-python and mediapipe. "
                "Install with: pip install 'wax-on-wax-off[vision]'"
            )
            return

        cap = cv2.VideoCapture(self._camera_index)
        if not cap.isOpened():
            logger.warning("Cannot open camera %d", self._camera_index)
            return

        mp_pose = mp.solutions.pose
        mp_hands = mp.solutions.hands
        self._running = True

        pose = mp_pose.Pose(
            model_complexity=0,  # lite
            min_detection_confidence=0.5,
            min_tracking_confidence=0.5,
        )
        hands = mp_hands.Hands(
            model_complexity=0,  # lite
            max_num_hands=2,
            min_detection_confidence=0.5,
            min_tracking_confidence=0.5,
        )

        try:
            while self._running:
                # ── 1. Capture ────────────────────────────────────
                t_frame = time.perf_counter()
                ret, frame = cap.read()
                if not ret:
                    await asyncio.sleep(0.01)
                    continue
                frame_captured_ms = (time.perf_counter() - t_frame) * 1000

                # ── 2. MediaPipe inference ────────────────────────
                t_pose = time.perf_counter()
                rgb = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                rgb.flags.writeable = False
                pose_results = pose.process(rgb)
                hand_results = hands.process(rgb)
                pose_done_ms = (time.perf_counter() - t_pose) * 1000

                # ── 3. Extract body points ────────────────────────
                left_hand = None
                right_hand = None
                head = None

                if pose_results.pose_landmarks:
                    nose = pose_results.pose_landmarks.landmark[0]
                    head = _lm_to_vec3(nose)

                if hand_results.multi_hand_landmarks and hand_results.multi_handedness:
                    for hlm, hclass in zip(
                        hand_results.multi_hand_landmarks,
                        hand_results.multi_handedness,
                    ):
                        wrist = hlm.landmark[0]
                        point = _lm_to_vec3(wrist)
                        label = hclass.classification[0].label
                        # MediaPipe mirrors left/right
                        if label == "Left":
                            right_hand = point
                        else:
                            left_hand = point

                self.hub.player = {
                    "tracked": head is not None,
                    "left_hand": left_hand,
                    "right_hand": right_hand,
                    "head": head,
                }

                # ── 4. Hit detection ──────────────────────────────
                t_event = time.perf_counter()
                active_pad = self.hub.arm.current_target()
                arrived = self.hub.arm.arrived_at()

                if (
                    active_pad
                    and arrived is not None
                    and active_pad in self._pad_regions
                    and active_pad != self._last_hit_pad
                    and self.engine
                ):
                    region = self._pad_regions[active_pad]
                    for hand_point, hand_label in [
                        (left_hand, "left"),
                        (right_hand, "right"),
                    ]:
                        if hand_point and _point_in_region(hand_point, region):
                            self.engine.register_hit(time.time(), hand=hand_label)
                            self._last_hit_pad = active_pad
                            break

                # Reset last-hit tracker when pad changes
                if active_pad != self._last_hit_pad and self._last_hit_pad is not None:
                    if active_pad != self.hub.arm.current_target():
                        self._last_hit_pad = None

                event_emitted_ms = (time.perf_counter() - t_event) * 1000

                # ── 5. Latency bookkeeping ────────────────────────
                self.hub.latency_ms = {
                    "frame_captured": frame_captured_ms,
                    "pose_done": pose_done_ms,
                    "event_emitted": event_emitted_ms,
                }

                # Yield — target ≈ camera FPS
                await asyncio.sleep(0.001)

        finally:
            pose.close()
            hands.close()
            cap.release()
            self._running = False

    def stop(self) -> None:
        self._running = False
