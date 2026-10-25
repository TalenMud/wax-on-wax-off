"""Generate the crowd's sound effects with ElevenLabs, once, into vr/sfx/crowd/ (committed).

    python3 tools/make_crowd_sfx.py           # skips sounds that already exist
    python3 tools/make_crowd_sfx.py --force

vr/trainer.html plays one when audience emoji arrive (waxonwaxoff.ink/audience), at most one
every CROWD_SFX_GAP_MS. Key: ~/.config/wax-on-wax-off/elevenlabs_key or ELEVENLABS_API_KEY.
"""

import argparse
import json
import os
import urllib.request
from pathlib import Path

OUT = Path(__file__).resolve().parent.parent / "vr" / "sfx" / "crowd"
KEY_FILE = Path.home() / ".config" / "wax-on-wax-off" / "elevenlabs_key"

# file name (also the emoji's key in trainer.html) -> prompt, seconds
SOUNDS = {
    "clown": ("a silly clown bicycle horn honking twice, comedic", 1.5),
    "laugh": ("a small crowd bursting into laughter at a boxing match", 2.5),
    "skull": ("a sad trombone wah wah wah waaah, comedic fail", 2.5),
    "fire": ("a boxing crowd going ooooh, impressed", 2.0),
    "clap": ("enthusiastic applause from a small crowd", 2.5),
    "glove": ("a boxing ring bell ding ding", 1.5),
    "flex": ("a crowd cheering loudly with whistles", 2.5),
    "sleep": ("a loud cartoon snore", 2.0),
}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    key = os.environ.get("ELEVENLABS_API_KEY") or KEY_FILE.read_text().strip()
    OUT.mkdir(parents=True, exist_ok=True)
    for name, (prompt, seconds) in SOUNDS.items():
        path = OUT / f"{name}.mp3"
        if path.exists() and not args.force:
            continue
        req = urllib.request.Request(
            "https://api.elevenlabs.io/v1/sound-generation?output_format=mp3_44100_64",
            data=json.dumps({"text": prompt, "duration_seconds": seconds, "prompt_influence": 0.6}).encode(),
            headers={"xi-api-key": key, "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=60) as resp:
            path.write_bytes(resp.read())
        print(f"{name}: {path.stat().st_size // 1024} KB  ({prompt})")


if __name__ == "__main__":
    main()
