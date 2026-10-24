"""Bridge between the robot hub and the phone app's Convex backend (web/convex/http.ts).

The phone starts sessions in Convex; the hub polls for them and reports every pad
presentation, hit, and miss back. Stdlib only so it runs on the robot laptop as-is.

    CONVEX_SITE_URL=https://<deployment>.convex.site HUB_SECRET=... python -m brain.convex_bridge --mock

In the real hub, create a ConvexBridge and call poll() in the game loop (~4 Hz), then
present()/hit()/miss() as the arm and pose tracker report them. If poll() says estop,
call arm.estop() right away.
"""

import argparse
import json
import os
import random
import time
import urllib.request
from dataclasses import dataclass


@dataclass
class HubSession:
    id: str
    mode: str
    difficulty: str
    duration_s: float
    starts_at: float  # local time.time() seconds, already corrected for server clock skew
    ends_at: float
    window_ms: int  # pad stays up this long before it is a miss
    max_run: int  # most presentations in a row on the same arm
    gap_ms: int  # pause between presentations


class ConvexBridge:
    def __init__(self, site_url: str, secret: str, timeout_s: float = 3.0) -> None:
        self.base = site_url.rstrip("/")
        self.secret = secret
        self.timeout_s = timeout_s
        self.skew_s = 0.0  # server clock minus local clock
        self.link_code: str | None = None  # shown in the headset; a phone enters it to link
        self.player: str | None = None  # name of the account the headset is linked to

    def _request(self, path: str, body: dict | None = None) -> dict:
        req = urllib.request.Request(
            self.base + path,
            data=json.dumps(body).encode() if body is not None else None,
            headers={"Authorization": f"Bearer {self.secret}", "Content-Type": "application/json"},
            method="POST" if body is not None else "GET",
        )
        with urllib.request.urlopen(req, timeout=self.timeout_s) as resp:
            return json.loads(resp.read())

    def poll(self) -> tuple[bool, HubSession | None]:
        """Heartbeat + fetch state. Returns (estop, live session or None)."""
        sent = time.time()
        data = self._request("/hub/poll")
        self.skew_s = data["serverNow"] / 1000 - (sent + time.time()) / 2
        self.link_code = data.get("linkCode")
        self.player = data.get("player")
        s = data["session"]
        if s is None:
            return data["estop"], None
        return data["estop"], HubSession(
            id=s["id"],
            mode=s["mode"],
            difficulty=s["difficulty"],
            duration_s=s["durationS"],
            starts_at=s["startsAt"] / 1000 - self.skew_s,
            ends_at=s["endsAt"] / 1000 - self.skew_s,
            window_ms=s["windowMs"],
            max_run=s["maxRun"],
            gap_ms=s["gapMs"],
        )

    def start(self, mode: str, difficulty: str) -> dict:
        """Start a round for the linked player. Returns {ok, sessionId} or {ok: False, error}."""
        return self._request("/hub/start", {"mode": mode, "difficulty": difficulty})

    def present(self, session_id: str, arm: str) -> bool:
        return self._request("/hub/event", {"sessionId": session_id, "kind": "present", "arm": arm})["accepted"]

    def hit(self, session_id: str, arm: str, reaction_ms: float) -> bool:
        body = {"sessionId": session_id, "kind": "hit", "arm": arm, "reactionMs": reaction_ms}
        return self._request("/hub/event", body)["accepted"]

    def miss(self, session_id: str, arm: str) -> bool:
        return self._request("/hub/event", {"sessionId": session_id, "kind": "miss", "arm": arm})["accepted"]


def next_arm(arm: str, run: int, max_run: int) -> tuple[str, int]:
    """Alternate sides in random runs: stay on the same arm at most max_run times."""
    if run < max_run and random.random() < 0.5:
        return arm, run + 1
    return ("right" if arm == "left" else "left"), 1


def run_mock(bridge: ConvexBridge) -> None:
    """Pretend to be the rig: wait for a session, then present pads and fake punches."""
    print(f"mock rig polling {bridge.base}")
    while True:
        estop, s = bridge.poll()
        if estop or s is None:
            time.sleep(0.25)
            continue
        print(f"session {s.id}: {s.mode}/{s.difficulty}, starts in {s.starts_at - time.time():.1f}s")
        time.sleep(max(0.0, s.starts_at - time.time()))
        arm, run = random.choice(["left", "right"]), 1
        while time.time() < s.ends_at:
            if not bridge.present(s.id, arm):
                break  # stopped or estopped from the phone
            reaction = max(250.0, random.gauss(480, 130))
            if reaction <= s.window_ms and random.random() > 0.12:
                time.sleep(reaction / 1000)
                ok = bridge.hit(s.id, arm, round(reaction))
            else:
                time.sleep(s.window_ms / 1000)
                ok = bridge.miss(s.id, arm)
            if not ok:
                break
            time.sleep(s.gap_ms / 1000)
            arm, run = next_arm(arm, run, s.max_run)
        print("session over")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--mock", action="store_true", help="simulate the arms and the player")
    args = parser.parse_args()
    bridge = ConvexBridge(os.environ["CONVEX_SITE_URL"], os.environ["HUB_SECRET"])
    if args.mock:
        run_mock(bridge)
    else:
        estop, session = bridge.poll()
        print(f"connected. estop={estop} session={session}")
