"""Does a trained ACT checkpoint predict the dodges in its own training data? No hardware.

    python tools/replay_eval.py CHECKPOINT DATASET_DIR [--n 30]

Finds frames just before the human teleoperator started a fast move (left or right arm), gives the
policy that frame's recorded images and joint state, and compares the chunk it predicts with what
the human actually did next. Held (still) frames are the control. If it predicts the recorded
dodges here but not live, the live scene differs from the recordings; if not even here, it hasn't
learned them.
"""

import argparse
from pathlib import Path

import numpy as np
import torch

FAST_DEG_S = 60.0  # a joint moving faster than this starts a "dodge"
LEAD = 3  # frames before the move starts that the policy gets to see


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("checkpoint", type=Path)
    ap.add_argument("dataset", type=Path)
    ap.add_argument("--n", type=int, default=30)
    args = ap.parse_args()

    from lerobot.configs.policies import PreTrainedConfig
    from lerobot.datasets.lerobot_dataset import LeRobotDataset
    from lerobot.policies.act.modeling_act import ACTPolicy
    from lerobot.policies.factory import make_pre_post_processors

    torch.backends.mkldnn.enabled = False
    cfg = PreTrainedConfig.from_pretrained(args.checkpoint)
    cfg.device = "cuda"
    policy = ACTPolicy.from_pretrained(args.checkpoint, config=cfg).to("cuda").eval()
    pre, post = make_pre_post_processors(cfg, pretrained_path=str(args.checkpoint),
                                         preprocessor_overrides={"device_processor": {"device": "cuda"}})
    horizon = cfg.chunk_size

    ds = LeRobotDataset(args.dataset.name, root=args.dataset)
    actions = np.stack(ds.hf_dataset["action"]).astype(float)
    episodes = np.array(ds.hf_dataset["episode_index"])
    fps = ds.fps
    speed = np.r_[0, np.abs(np.diff(actions, axis=0))[:, [0, 1, 2, 3, 4, 5, 7, 8, 9, 10, 11, 12]].max(1) * fps]
    same_ep = np.r_[False, episodes[1:] == episodes[:-1]]
    starts = np.flatnonzero((speed > FAST_DEG_S) & same_ep & (np.r_[0, speed[:-1]] < FAST_DEG_S / 3))
    ok = [i - LEAD for i in starts if i - LEAD >= 0 and i + horizon < len(actions) and (episodes[i - LEAD : i + horizon] == episodes[i]).all()]
    still = np.flatnonzero(speed < 2)
    still = [i for i in still if i + horizon < len(actions) and (episodes[i : i + horizon] == episodes[i]).all()]
    rng = np.random.default_rng(0)
    picks = {"dodge": rng.choice(ok, min(args.n, len(ok)), replace=False),
             "still": rng.choice(still, min(args.n, len(still)), replace=False)}
    print(f"{len(starts)} fast-move onsets found; testing {len(picks['dodge'])} dodges, {len(picks['still'])} still frames")

    for kind, idx in picks.items():
        got, want, err = [], [], []
        for i in idx:
            item = ds[int(i)]
            obs = {k: v.unsqueeze(0) for k, v in item.items() if k.startswith("observation.")}
            with torch.inference_mode():
                chunk = policy.predict_action_chunk(pre(obs))  # (1, horizon, 14) normalised
                chunk = post(chunk).squeeze(0).float().cpu().numpy()
            state = item["observation.state"].numpy().astype(float)
            real = actions[i : i + horizon]
            arm = slice(0, 6) if np.abs(real[:, :6] - state[:6]).max() >= np.abs(real[:, 7:13] - state[7:13]).max() else slice(7, 13)
            got.append(np.abs(chunk[:, arm] - state[arm]).max())  # how far the prediction moves that arm
            want.append(np.abs(real[:, arm] - state[arm]).max())  # how far the human moved it
            err.append(np.abs(chunk[:, arm] - real[:, arm]).mean())
        got, want, err = map(np.array, (got, want, err))
        print(f"{kind:5s}: human moved {np.median(want):5.1f} deg (median), model predicts {np.median(got):5.1f} deg; "
              f"tracking error {np.median(err):5.1f} deg; model moves >10 deg in {np.mean(got > 10) * 100:.0f}% of cases")


if __name__ == "__main__":
    main()
