"""Serve the repo to the Quest, collect XR stats, and relay the phone app's sessions to the headset.

    python3 tools/serve_xr.py            # http://0.0.0.0:8080, logs to logs/xr-<date>.jsonl
    adb reverse tcp:8080 tcp:8080        # then open http://localhost:8080/vr/gloves.html on the Quest

With HUB_SECRET set, or saved in ~/.config/wax-on-wax-off/hub_secret (and optionally CONVEX_SITE_URL), the server polls the phone app's Convex
backend through brain/convex_bridge.py and the headset plays the rig's part:

    GET  /rig/state   {online, error, estop, now, session, linkCode, player}  times are this laptop's epoch ms
    POST /rig/event   {sessionId, kind: present|hit|miss, arm: left|right, reactionMs?} -> {accepted}
    POST /rig/start   {mode, difficulty} -> {ok, sessionId} or {ok: false, error}  for the linked player

HUB_SECRET stays on this laptop; the headset only ever talks to this server.
"""

import argparse
import json
import os
import sys
import threading
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from brain.convex_bridge import ConvexBridge  # noqa: E402

LOG = ROOT / "logs" / f"xr-{time.strftime('%Y%m%d')}.jsonl"
DEFAULT_SITE = "https://abundant-roadrunner-265.convex.site"
SECRET_FILE = Path.home() / ".config" / "wax-on-wax-off" / "hub_secret"  # used when HUB_SECRET is unset
POLL_S = 0.25


class Rig:
    """Latest Convex state, refreshed by a background poller."""

    def __init__(self, bridge: ConvexBridge | None) -> None:
        self.bridge = bridge
        self.lock = threading.Lock()
        self.state = {"online": False, "error": "HUB_SECRET not set" if bridge is None else "connecting", "estop": False, "session": None, "linkCode": None, "player": None}

    def run(self) -> None:
        while True:
            try:
                estop, s = self.bridge.poll()
                session = None
                if s is not None:
                    session = {
                        "id": s.id,
                        "mode": s.mode,
                        "difficulty": s.difficulty,
                        "durationS": s.duration_s,
                        "startsAt": round(s.starts_at * 1000),
                        "endsAt": round(s.ends_at * 1000),
                        "windowMs": s.window_ms,
                        "maxRun": s.max_run,
                        "gapMs": s.gap_ms,
                    }
                new = {"online": True, "error": None, "estop": estop, "session": session,
                       "linkCode": self.bridge.link_code, "player": self.bridge.player}
            except Exception as e:  # network blips must not kill the poller
                new = {**self.state, "online": False, "error": str(e), "session": None}
            with self.lock:
                if any(new[k] != self.state[k] for k in ("session", "online", "player")):
                    print(f"rig: online={new['online']} estop={new['estop']} player={new['player']} session={new['session'] and new['session']['id']} {new['error'] or ''}")
                self.state = new
            time.sleep(POLL_S)

    def snapshot(self) -> dict:
        with self.lock:
            return {**self.state, "now": round(time.time() * 1000)}

    def event(self, body: dict) -> bool:
        if self.bridge is None:
            return False
        sid, kind, arm = body["sessionId"], body["kind"], body["arm"]
        if kind == "present":
            return self.bridge.present(sid, arm)
        if kind == "hit":
            return self.bridge.hit(sid, arm, float(body.get("reactionMs", 0)))
        if kind == "miss":
            return self.bridge.miss(sid, arm)
        raise ValueError(f"unknown kind {kind!r}")

    def start(self, body: dict) -> dict:
        if self.bridge is None:
            return {"ok": False, "error": "HUB_SECRET not set"}
        return self.bridge.start(body.get("mode", "standard"), body.get("difficulty", "medium"))


class Handler(SimpleHTTPRequestHandler):
    rig: Rig

    def _json(self, code: int, obj: dict) -> None:
        data = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _body(self) -> dict | None:
        try:
            return json.loads(self.rfile.read(int(self.headers.get("content-length", 0))))
        except json.JSONDecodeError:
            return None

    def do_GET(self) -> None:
        if self.path == "/rig/state":
            self._json(200, self.rig.snapshot())
            return
        super().do_GET()

    def do_POST(self) -> None:
        if self.path == "/log":
            body = self._body()
            if body is None:
                self.send_error(400)
                return
            LOG.parent.mkdir(exist_ok=True)
            with LOG.open("a") as f:
                f.write(json.dumps(body) + "\n")
            self.send_response(204)
            self.end_headers()
        elif self.path == "/rig/event":
            body = self._body()
            if body is None or body.get("kind") not in ("present", "hit", "miss") or body.get("arm") not in ("left", "right"):
                self.send_error(400)
                return
            try:
                accepted = self.rig.event(body)
            except Exception as e:
                self._json(502, {"accepted": False, "error": str(e)})
                return
            print(f"rig event {body['kind']} {body['arm']} {body.get('reactionMs', '')} -> {accepted}")
            self._json(200, {"accepted": accepted})
        elif self.path == "/rig/start":
            body = self._body()
            if body is None:
                self.send_error(400)
                return
            try:
                result = self.rig.start(body)
            except Exception as e:
                result = {"ok": False, "error": str(e)}
            print(f"rig start {body} -> {result}")
            self._json(200, result)
        else:
            self.send_error(404)

    def log_message(self, fmt, *args) -> None:
        if self.command != "POST" and not self.path.startswith("/rig/"):
            super().log_message(fmt, *args)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8080)
    a = ap.parse_args()

    secret = os.environ.get("HUB_SECRET")
    if not secret and SECRET_FILE.is_file():
        secret = SECRET_FILE.read_text().strip() or None
    bridge = ConvexBridge(os.environ.get("CONVEX_SITE_URL", DEFAULT_SITE), secret) if secret else None
    Handler.rig = Rig(bridge)
    if bridge:
        threading.Thread(target=Handler.rig.run, daemon=True).start()

    server = ThreadingHTTPServer(("0.0.0.0", a.port), partial(Handler, directory=str(ROOT)))
    print(f"serving {ROOT} on :{a.port}, stats -> {LOG}")
    print(f"rig: {'polling ' + bridge.base if bridge else 'offline (set HUB_SECRET to connect to the phone app)'}")
    server.serve_forever()


if __name__ == "__main__":
    main()
