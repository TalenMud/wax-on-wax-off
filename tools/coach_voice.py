"""The trash-talking coach: a line built from the player's Convex stats, spoken by ElevenLabs.

tools/serve_xr.py serves it as POST /coach/say {event, ms?} -> audio/mpeg (204 when there's no key).
Events: start, miss, slow, hit, streak, crowd, end. The material comes from Convex's /hub/coach
(web/convex/coach.ts): this round, the player's history and leaderboard rank, the crowd's emoji.
The ElevenLabs key lives in ~/.config/wax-on-wax-off/elevenlabs_key (or ELEVENLABS_API_KEY) and
never leaves this laptop.
"""

import json
import os
import random
import re
import threading
import time
import urllib.request
from pathlib import Path

KEY_FILE = Path.home() / ".config" / "wax-on-wax-off" / "elevenlabs_key"
VOICE = "0lp4RIz96WD1RUtvEu3Q"  # "Grandfather Joe", an old British gent from the ElevenLabs voice library
MODEL = "eleven_flash_v2_5"  # ~0.2 s to first audio
CONTEXT_TTL_S = 1.5

EMOJI_NAMES = {"🤡": "clowns", "💀": "skulls", "😴": "sleepy faces", "😂": "laughing faces",
               "🔥": "fire emojis", "👏": "claps", "🥊": "boxing gloves", "💪": "flexing arms"}

# {fields} come from facts(); a line is only used when every field it names is known.
LINES = {
    "start": [
        "Right then, {name}. Gloves up. Let's see if you've improved.",
        "{name}. Ranked {rank} out of {of} on the leaderboard. Let's see if you deserve it.",
        "Your best is {best} points, {name}. I've seen better from a pensioner. Off you go.",
        "Your average punch takes {careerMs} milliseconds. Let's try and beat that, shall we?",
        "Right, gloves up. Don't embarrass me.",
    ],
    "miss": [
        "That's {misses} misses. Are you punching or waving, {name}?",
        "Your {weak} hand's missed {weakMisses} already. Has it gone on holiday?",
        "Miss number {misses}. I've had cups of tea with more urgency.",
        "Missed. The pad wasn't even moving, son.",
        "Oh dear. Oh dear oh dear.",
    ],
    "slow": [
        "{ms} milliseconds. I could post you a letter faster than that.",
        "Your {slowSide} hand's averaging {slowAvg} milliseconds. My late wife was quicker, God rest her.",
        "{ms} milliseconds. You normally manage {careerMs}. What happened?",
        "Slower than a Sunday bus, that.",
    ],
    "hit": [
        "Ooh, {ms} milliseconds. Fluke.",
        "{ms} milliseconds. Not bad. Don't let it go to your head.",
    ],
    "streak": [
        "{streak} in a row. Don't get cocky.",
        "Steady on, {streak} on the trot. Even a stopped clock, son.",
        "{streak} straight. Alright, I'm almost impressed. Almost.",
    ],
    "crowd": [
        "The crowd's sent {crowdN} {crowdName}. They've got a point, {name}.",
        "Hear that? {crowdN} {crowdName} from the crowd. They're on my side, son.",
        "{crowdN} {crowdName}. Even the audience can see it.",
    ],
    "end": [
        "{score} points. Your best is {best}. Make of that what you will.",
        "{hits} hits, {misses} misses. I've seen worse. Not often, mind.",
        "Final score {score}. You're ranked {rank} out of {of}. Room for improvement, I'd say.",
        "That's time. Go and have a sit down.",
    ],
}


def facts(c: dict, event: str, ms: float | None) -> dict:
    """Template fields from Convex's /hub/coach context; unknown ones are left out."""
    f: dict = {}
    if c.get("player"):
        f["name"] = c["player"].split()[0]
    if ms:
        f["ms"] = round(ms)
    h = c.get("history") or {}
    if h.get("rounds"):
        f["best"] = h["bestScore"]
        if h.get("avgReactionMs"):
            f["careerMs"] = h["avgReactionMs"]
    r = c.get("rank") or {}
    if r.get("position"):
        f["rank"], f["of"] = r["position"], r["of"]
    rd = c.get("round")
    if rd:
        f.update(score=rd["score"], hits=rd["hits"], misses=rd["misses"])
        if rd["streak"] >= 2:
            f["streak"] = rd["streak"]
        weak = "left" if rd["leftMisses"] >= rd["rightMisses"] else "right"
        if rd[f"{weak}Misses"]:
            f["weak"], f["weakMisses"] = weak, rd[f"{weak}Misses"]
        sides = [(rd["leftAvgMs"], "left"), (rd["rightAvgMs"], "right")]
        sides = [s for s in sides if s[0]]
        if sides:
            f["slowAvg"], f["slowSide"] = max(sides)
    if c.get("crowd"):
        emoji, n = max(c["crowd"].items(), key=lambda kv: kv[1])
        f["crowdN"], f["crowdName"] = n, EMOJI_NAMES.get(emoji, "reactions")
    return f


class Coach:
    def __init__(self, bridge) -> None:
        self.bridge = bridge
        key = os.environ.get("ELEVENLABS_API_KEY") or (KEY_FILE.read_text().strip() if KEY_FILE.is_file() else "")
        self.key = key or None
        self.lock = threading.Lock()
        self.context: dict = {}
        self.context_at = 0.0
        self.audio: dict[str, bytes] = {}  # line -> mp3, so repeats cost nothing
        self.last: dict[str, str] = {}

    def _context(self) -> dict:
        if self.bridge and time.monotonic() - self.context_at > CONTEXT_TTL_S:
            try:
                self.context = self.bridge.coach_context()
            except Exception as e:  # no stats is fine: fall back to stat-free lines
                print(f"coach: context {e}")
            self.context_at = time.monotonic()
        return self.context

    def fresh_context(self) -> dict:
        """The player's stats straight from Convex, skipping the cache (for the coach agent)."""
        self.context_at = 0.0
        return self._context()

    def line(self, event: str, ms: float | None = None) -> str | None:
        f = facts(self._context(), event, ms)
        usable = []
        for t in LINES.get(event, []):
            if all(k in f for k in re.findall(r"{(\w+)}", t)):
                usable.append(t)
        # Prefer lines with stats in them; never the same line twice running.
        usable.sort(key=lambda t: -t.count("{"))
        fresh = [t for t in usable if t != self.last.get(event)] or usable
        if not fresh:
            return None
        pool = fresh[: max(2, len(fresh) // 2)]
        t = random.choice(pool)
        self.last[event] = t
        return t.format(**f)

    def speak(self, text: str) -> bytes:
        with self.lock:
            if text in self.audio:
                return self.audio[text]
        req = urllib.request.Request(
            f"https://api.elevenlabs.io/v1/text-to-speech/{VOICE}/stream?output_format=mp3_44100_64&optimize_streaming_latency=3",
            data=json.dumps({"text": text, "model_id": MODEL, "voice_settings": {"stability": 0.4, "similarity_boost": 0.8, "style": 0.5}}).encode(),
            headers={"xi-api-key": self.key, "Content-Type": "application/json"},
            method="POST",
        )
        with urllib.request.urlopen(req, timeout=8) as resp:
            mp3 = resp.read()
        with self.lock:
            self.audio[text] = mp3
        return mp3

    def say(self, event: str, ms: float | None = None) -> tuple[str, bytes] | None:
        if not self.key:
            return None
        text = self.line(event, ms)
        if not text:
            return None
        return text, self.speak(text)
