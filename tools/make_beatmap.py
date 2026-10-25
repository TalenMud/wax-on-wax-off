"""Make a rhythm-mode beatmap from your own music: finds the tempo and the beats, then lays pads on them.

    python3 tools/make_beatmap.py ~/Music/song.mp3                  # a pad every other beat
    python3 tools/make_beatmap.py ~/Music/song.mp3 --every 1 --title "Song"

Copies the audio to vr/music/ next to its beatmap (<name>.json) and lists both in
vr/music/library.json, which vr/trainer.html reads. vr/music/ is gitignored: music you own stays
on your machine. A beatmap is plain JSON, so players can also share and import them:

    {"title": str, "audio": "<file in vr/music/>", "bpm": float, "offsetMs": float,
     "durationMs": float, "notes": [{"t": ms from the start of the audio, "side": "left"|"right"}]}

Needs ffmpeg and numpy.
"""

import argparse
import json
import re
import shutil
import subprocess
from pathlib import Path

import numpy as np

MUSIC = Path(__file__).resolve().parent.parent / "vr" / "music"
SR = 22050
HOP = 256
FRAME = 1024
BPM_RANGE = (70.0, 180.0)
ONSET_LAG_S = 0.039  # the analysis window sees a beat this early (measured on a click track)
# Pads per 8 notes; repeats through the song. Pairs and switches feel like combinations.
PATTERN = ["left", "right", "left", "right", "left", "left", "right", "right"]


def decode(path: Path) -> np.ndarray:
    raw = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", str(SR), "-f", "f32le", "-"],
        check=True, capture_output=True,
    ).stdout
    return np.frombuffer(raw, dtype=np.float32)


def onset_envelope(x: np.ndarray) -> np.ndarray:
    """Spectral flux of the log spectrum, one value per HOP samples."""
    n = 1 + (len(x) - FRAME) // HOP
    frames = np.lib.stride_tricks.as_strided(x, (n, FRAME), (x.strides[0] * HOP, x.strides[0]))
    spec = np.log1p(100 * np.abs(np.fft.rfft(frames * np.hanning(FRAME), axis=1)))
    flux = np.maximum(0.0, np.diff(spec, axis=0)).sum(axis=1)
    flux = np.r_[0.0, flux]
    flux -= np.convolve(flux, np.ones(16) / 16, mode="same")  # remove the slow loudness trend
    flux = np.maximum(flux, 0.0)
    return flux / (flux.max() or 1.0)


def tempo(env: np.ndarray) -> float:
    """Beats per minute: the best autocorrelation lag, nudged towards a typical ~115 BPM."""
    fps = SR / HOP
    ac = np.correlate(env, env, mode="full")[len(env) - 1 :]
    best, best_score = 0.0, -1.0
    for bpm in np.arange(BPM_RANGE[0], BPM_RANGE[1], 0.1):
        lag = 60.0 * fps / bpm
        i = int(lag)
        v = ac[i] + (lag - i) * (ac[i + 1] - ac[i])  # interpolated
        score = v * np.exp(-0.5 * (np.log2(bpm / 115.0) / 0.9) ** 2)
        if score > best_score:
            best, best_score = bpm, score
    return float(best)


def grid(env: np.ndarray, bpm: float) -> tuple[float, float]:
    """(seconds to the first beat, score): the phase whose beat grid lands on the most onset energy."""
    fps = SR / HOP
    period = 60.0 * fps / bpm
    k = np.arange(int((len(env) - 1) / period))
    scores = [env[np.minimum(np.round(phase + k * period).astype(int), len(env) - 1)].sum() for phase in np.arange(0, period, 0.25)]
    return float(np.argmax(scores) * 0.25 / fps), float(max(scores))


def refine(env: np.ndarray, bpm: float) -> tuple[float, float]:
    """(bpm, first beat) to 0.01 BPM: over a whole song even 0.2 BPM off drifts audibly."""
    best = (bpm, *grid(env, bpm))
    for b in np.arange(bpm - 0.5, bpm + 0.5, 0.01):
        offset, score = grid(env, b)
        if score > best[2]:
            best = (float(b), offset, score)
    return best[0], best[1]


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("audio", type=Path)
    ap.add_argument("--title")
    ap.add_argument("--every", type=int, default=2, help="a pad every N beats (1 = every beat)")
    ap.add_argument("--start", type=float, default=4.0, help="seconds of intro before the first pad")
    args = ap.parse_args()

    x = decode(args.audio)
    env = onset_envelope(x)
    bpm, offset = refine(env, tempo(env))
    offset += ONSET_LAG_S
    duration = len(x) / SR
    beat = 60.0 / bpm
    fps = SR / HOP
    loud = np.convolve(env, np.ones(int(fps)) / int(fps), mode="same")  # ~1 s of onset energy
    quiet = np.percentile(loud, 5)

    notes, n = [], 0
    t = offset
    while t < duration - 2.0:
        i = int(t * fps)
        if t >= args.start and round((t - offset) / beat) % args.every == 0 and loud[min(i, len(loud) - 1)] > quiet:
            notes.append({"t": round(t * 1000), "side": PATTERN[n % len(PATTERN)]})
            n += 1
        t += beat

    MUSIC.mkdir(parents=True, exist_ok=True)
    name = re.sub(r"[^a-z0-9]+", "-", args.audio.stem.lower()).strip("-") or "song"
    audio_name = name + args.audio.suffix.lower()
    if args.audio.resolve() != (MUSIC / audio_name).resolve():
        shutil.copyfile(args.audio, MUSIC / audio_name)
    beatmap = {"title": args.title or args.audio.stem, "audio": audio_name, "bpm": round(bpm, 2),
               "offsetMs": round(offset * 1000), "durationMs": round(duration * 1000), "notes": notes}
    (MUSIC / f"{name}.json").write_text(json.dumps(beatmap, indent=1))

    lib_path = MUSIC / "library.json"
    library = json.loads(lib_path.read_text()) if lib_path.exists() else []
    library = [s for s in library if s["map"] != f"{name}.json"] + [{"title": beatmap["title"], "map": f"{name}.json"}]
    lib_path.write_text(json.dumps(library, indent=1))
    print(f"{beatmap['title']}: {bpm:.1f} BPM, first beat {offset:.2f} s, {len(notes)} pads over {duration:.0f} s -> vr/music/{name}.json")


if __name__ == "__main__":
    main()
