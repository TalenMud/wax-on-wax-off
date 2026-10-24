"""Interactive calibration tool for pad regions.

Usage::

    python -m brain.vision.calibration [--camera 0]

While the arm holds each pad pose, click the **top-left** then
**bottom-right** corner of the region where the player's hand should
reach to register a hit. Results are saved to
``brain/vision/pad_regions.json``.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

PAD_REGIONS_PATH = Path(__file__).parent / "pad_regions.json"


def run_calibration(camera_index: int = 0) -> None:
    try:
        import cv2
    except ImportError:
        print("OpenCV required: pip install opencv-python", file=sys.stderr)
        return

    from brain.arm.interface import PAD_TARGETS

    cap = cv2.VideoCapture(camera_index)
    if not cap.isOpened():
        print(f"Cannot open camera {camera_index}", file=sys.stderr)
        return

    regions: dict[str, dict] = {}
    clicks: list[tuple[int, int]] = []

    def on_mouse(event: int, x: int, y: int, flags: int, param: object) -> None:
        if event == cv2.EVENT_LBUTTONDOWN:
            clicks.append((x, y))

    win = "Wax On Wax Off – Pad Calibration"
    cv2.namedWindow(win)
    cv2.setMouseCallback(win, on_mouse)

    print("\n╔══════════════════════════════════════╗")
    print("║   Pad Region Calibration             ║")
    print("╠══════════════════════════════════════╣")
    print("║  Click TOP-LEFT then BOTTOM-RIGHT    ║")
    print("║  's' = skip pad  |  'q' = quit       ║")
    print("╚══════════════════════════════════════╝\n")

    for pad in PAD_TARGETS:
        print(f"  → Calibrating: {pad}")
        clicks.clear()

        while len(clicks) < 2:
            ret, frame = cap.read()
            if not ret:
                continue
            h, w = frame.shape[:2]

            # HUD
            cv2.putText(frame, f"Pad: {pad}", (10, 30),
                        cv2.FONT_HERSHEY_SIMPLEX, 1.0, (0, 255, 0), 2)
            cv2.putText(frame, f"Clicks: {len(clicks)}/2", (10, 65),
                        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 0), 2)

            for cx, cy in clicks:
                cv2.circle(frame, (cx, cy), 6, (0, 0, 255), -1)

            # Draw already-saved regions
            for name, reg in regions.items():
                x1 = int(reg["x_min"] * w)
                y1 = int(reg["y_min"] * h)
                x2 = int(reg["x_max"] * w)
                y2 = int(reg["y_max"] * h)
                cv2.rectangle(frame, (x1, y1), (x2, y2), (0, 255, 0), 2)
                cv2.putText(frame, name, (x1, y1 - 5),
                            cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 255, 0), 1)

            cv2.imshow(win, frame)
            key = cv2.waitKey(1) & 0xFF
            if key == ord("s"):
                print(f"    ⏭  Skipped {pad}")
                break
            if key == ord("q"):
                print("    ✖  Aborted")
                cap.release()
                cv2.destroyAllWindows()
                return

        if len(clicks) >= 2:
            ret, frame = cap.read()
            if ret:
                h, w = frame.shape[:2]
                x1, y1 = clicks[0]
                x2, y2 = clicks[1]
                regions[pad] = {
                    "x_min": min(x1, x2) / w,
                    "y_min": min(y1, y2) / h,
                    "x_max": max(x1, x2) / w,
                    "y_max": max(y1, y2) / h,
                }
                print(f"    ✓  Saved region for {pad}")

    cap.release()
    cv2.destroyAllWindows()

    with open(PAD_REGIONS_PATH, "w") as f:
        json.dump(regions, f, indent=2)

    print(f"\n  ✓ Saved {len(regions)}/{len(PAD_TARGETS)} regions → {PAD_REGIONS_PATH}\n")


def main() -> None:
    ap = argparse.ArgumentParser(description="Calibrate pad hit regions")
    ap.add_argument("--camera", type=int, default=0)
    args = ap.parse_args()
    run_calibration(args.camera)


if __name__ == "__main__":
    main()
