"""Build the Devpost video: narration in your ElevenLabs voice, ManimGL animation timed to it, one MP4.

    python3 video/make_video.py --voice <ElevenLabs voice id>     # narrate, render, mux
    python3 video/make_video.py --skip-tts                        # re-render with the existing narration

Steps: each line of video/narration.json -> video/audio/<id>.mp3 (ElevenLabs, key from
~/.config/wax-on-wax-off/elevenlabs_key), lengths -> video/audio/durations.json, which video/pitch.py
reads to time its sections; ManimGL renders video/pitch.py; ffmpeg lines the clips up (each padded
to its section length) and muxes -> video/out/wax-on-wax-off.mp4.
"""

import argparse
import json
import os
import subprocess
import urllib.request
from pathlib import Path

HERE = Path(__file__).resolve().parent
AUDIO = HERE / "audio"
OUT = HERE / "out"
KEY_FILE = Path.home() / ".config" / "wax-on-wax-off" / "elevenlabs_key"
GAP_S = 0.8  # must match pitch.py GAP_S
MANIMGL = HERE / ".venv" / "bin" / "manimgl"


def tts(text: str, voice: str, key: str, out: Path) -> None:
    req = urllib.request.Request(
        f"https://api.elevenlabs.io/v1/text-to-speech/{voice}?output_format=mp3_44100_128",
        data=json.dumps({"text": text, "model_id": "eleven_multilingual_v2",
                         "voice_settings": {"stability": 0.5, "similarity_boost": 0.85, "style": 0.3, "speed": 0.9}}).encode(),
        headers={"xi-api-key": key, "Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=120) as resp:
        out.write_bytes(resp.read())


def length(path: Path) -> float:
    out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
                         check=True, capture_output=True, text=True).stdout
    return float(out.strip())


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--voice", help="ElevenLabs voice id for the narration")
    ap.add_argument("--skip-tts", action="store_true")
    ap.add_argument("--quality", default="--hd", help="manimgl quality flag, e.g. --hd or --uhd or -l")
    args = ap.parse_args()
    lines = json.loads((HERE / "narration.json").read_text())
    AUDIO.mkdir(exist_ok=True)
    OUT.mkdir(exist_ok=True)

    if not args.skip_tts:
        if not args.voice:
            raise SystemExit("--voice is required (or --skip-tts to reuse video/audio/)")
        key = os.environ.get("ELEVENLABS_API_KEY") or KEY_FILE.read_text().strip()
        for line in lines:
            print(f"narrating {line['id']}...", flush=True)
            tts(line["text"], args.voice, key, AUDIO / f"{line['id']}.mp3")
    durations = {line["id"]: round(length(AUDIO / f"{line['id']}.mp3"), 3) for line in lines}
    (AUDIO / "durations.json").write_text(json.dumps(durations, indent=1))
    print(f"narration: {sum(durations.values()) + GAP_S * len(lines):.1f} s")

    # One narration track: each clip padded with silence to its section's length.
    padded = []
    for line in lines:
        p = AUDIO / f"{line['id']}.padded.wav"
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(AUDIO / f"{line['id']}.mp3"), "-af", f"apad=pad_dur={GAP_S}",
                        "-ar", "44100", "-ac", "2", str(p)], check=True)
        padded.append(p)
    concat = AUDIO / "concat.txt"
    concat.write_text("".join(f"file '{p}'\n" for p in padded))
    narration = AUDIO / "narration.wav"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(concat), "-c", "copy", str(narration)], check=True)

    print("rendering...", flush=True)
    subprocess.run([str(MANIMGL), str(HERE / "pitch.py"), "Pitch", "-w", args.quality, "--color", "#121012",
                    "--video_dir", str(OUT)], check=True, cwd=HERE)
    silent = OUT / "Pitch.mp4"
    final = OUT / "wax-on-wax-off.mp4"
    subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(silent), "-i", str(narration), "-c:v", "copy", "-c:a", "aac",
                    "-b:a", "192k", "-shortest", str(final)], check=True)
    print(f"done: {final} ({length(final):.1f} s)")


if __name__ == "__main__":
    main()
