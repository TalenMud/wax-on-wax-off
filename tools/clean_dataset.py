"""Clean a LeRobot dodge dataset for training: cut the folded rest pose out, split at it.

    python tools/clean_dataset.py SRC_DIR                  # dry run: what would be kept
    python tools/clean_dataset.py SRC_DIR --out DST_DIR    # write the cleaned dataset

A frame is "resting" when BOTH arms are folded (shoulder_lift and elbow_flex within REST_DEG of
0, in the action and the state). Each episode is split into the stretches between rests, with
MARGIN_S of rest kept either side so the policy still sees how a move starts and ends. Rests
shorter than GAP_S don't split, stretches shorter than MIN_S are dropped, and each stretch becomes
its own episode. Long recordings that were merged into one episode come apart this way too.

The output is written with LeRobot's own writer (videos re-encoded), so lerobot-train loads it
like any recorded dataset and recomputes the stats the policy normalises with.
"""

import argparse
import sys
from pathlib import Path

import numpy as np

REST_DEG = 8.0
MARGIN_S = 0.5
GAP_S = 1.0
MIN_S = 1.5
LIFT, ELBOW = 1, 2  # joint index within an arm's 7 (pan, lift, elbow, wrist_flex, yaw, roll, gripper)


def resting(x: np.ndarray) -> np.ndarray:
    """Per frame: both arms folded. x is (n, 14)."""
    folded = [
        (np.abs(x[:, a * 7 + LIFT]) < REST_DEG) & (np.abs(x[:, a * 7 + ELBOW]) < REST_DEG) for a in range(2)
    ]
    return folded[0] & folded[1]


def runs(mask: np.ndarray) -> list[tuple[int, int]]:
    """[start, end) of each run of True."""
    d = np.diff(np.concatenate([[0], mask.astype(int), [0]]))
    return list(zip(np.flatnonzero(d == 1), np.flatnonzero(d == -1)))


def segments(rest: np.ndarray, fps: int) -> list[tuple[int, int]]:
    active = ~rest
    for s, e in runs(rest):  # short rests inside a move are part of it
        if 0 < s and e < len(rest) and e - s < GAP_S * fps:
            active[s:e] = True
    m = int(MARGIN_S * fps)
    out = []
    for s, e in runs(active):
        s, e = max(0, s - m), min(len(rest), e + m)
        if out and s <= out[-1][1]:
            out[-1] = (out[-1][0], e)
        else:
            out.append((s, e))
    return [(s, e) for s, e in out if e - s >= MIN_S * fps]


def decode(path: Path, t0: float, n: int, fps: int) -> list[np.ndarray]:
    """n consecutive frames (HWC uint8 RGB) starting at time t0 in the video file."""
    import av

    frames = []
    with av.open(str(path)) as c:
        st = c.streams.video[0]
        c.seek(int(max(0.0, t0 - 1.0) / st.time_base), stream=st, backward=True)
        for f in c.decode(st):
            if f.time is None or f.time < t0 - 0.5 / fps:
                continue
            frames.append(f.to_ndarray(format="rgb24"))
            if len(frames) == n:
                break
    if len(frames) != n:
        raise RuntimeError(f"{path}: wanted {n} frames from {t0:.2f}s, got {len(frames)}")
    return frames


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("src", type=Path)
    ap.add_argument("--out", type=Path, help="write the cleaned dataset here (must not exist)")
    args = ap.parse_args()

    import pandas as pd
    from lerobot.datasets.dataset_metadata import LeRobotDatasetMetadata

    meta = LeRobotDatasetMetadata(args.src.name, root=args.src)
    fps = meta.fps
    df = pd.concat(pd.read_parquet(p) for p in sorted((args.src / "data").glob("*/*.parquet")))
    df = df.sort_values("index").reset_index(drop=True)
    tasks = {int(i): t for t, i in meta.tasks["task_index"].items()}
    vkeys = [k for k, f in meta.features.items() if f["dtype"] == "video"]

    plan = []
    total = kept = 0
    for ep in meta.episodes:
        e = df[df.episode_index == ep["episode_index"]]
        act, st = np.stack(e["action"].values), np.stack(e["observation.state"].values)
        segs = segments(resting(act) & resting(st), fps)
        n_kept = sum(b - a for a, b in segs)
        total, kept = total + len(e), kept + n_kept
        print(f"episode {ep['episode_index']}: {len(e) / fps:6.1f} s -> {len(segs)} segments, "
              f"{n_kept / fps:6.1f} s kept ({', '.join(f'{(b - a) / fps:.1f}' for a, b in segs)})")
        plan += [(ep, e.iloc[a:b], a) for a, b in segs]
    print(f"total {total / fps / 60:.1f} min -> {len(plan)} episodes, {kept / fps / 60:.1f} min kept "
          f"({100 * kept / max(total, 1):.0f}%)")
    if not args.out:
        return
    if args.out.exists():
        sys.exit(f"{args.out} exists; pick a new --out")

    from lerobot.datasets.lerobot_dataset import LeRobotDataset
    from lerobot.utils.constants import DEFAULT_FEATURES

    features = {k: v for k, v in meta.features.items() if k not in DEFAULT_FEATURES}
    dst = LeRobotDataset.create(
        args.out.name, fps, features, root=args.out, robot_type=meta.robot_type, use_videos=True
    )
    for i, (ep, rows, start) in enumerate(plan):
        video = {
            k: decode(
                args.src / meta.get_video_file_path(ep["episode_index"], k),
                ep[f"videos/{k}/from_timestamp"] + start / fps,
                len(rows),
                fps,
            )
            for k in vkeys
        }
        for j, (_, r) in enumerate(rows.iterrows()):
            frame = {k: np.asarray(r[k], dtype=np.float32) for k in features if k not in vkeys}
            frame.update({k: video[k][j] for k in vkeys})
            frame["task"] = tasks[int(r["task_index"])]
            dst.add_frame(frame)
        dst.save_episode()
        print(f"wrote episode {i + 1}/{len(plan)} ({len(rows)} frames)", flush=True)
    dst.finalize()
    print(f"done: {args.out}")


if __name__ == "__main__":
    main()
