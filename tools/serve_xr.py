"""Serve the repo to the Quest, collect XR stats, and relay the phone app's sessions to the headset.

    python3 tools/serve_xr.py            # http://0.0.0.0:8080, logs to logs/xr-<date>.jsonl
    adb reverse tcp:8080 tcp:8080        # then open http://localhost:8080/vr/gloves.html on the Quest

With HUB_SECRET set, or saved in ~/.config/wax-on-wax-off/hub_secret (and optionally CONVEX_SITE_URL), the server polls the phone app's Convex
backend through brain/convex_bridge.py and the headset plays the rig's part:

    GET  /rig/state   {online, error, estop, now, session, linkCode, player, audienceCode, reactions}
                      times are this laptop's epoch ms; reactions: [{id, emoji, at}] audience emoji, last ~5 s
    POST /rig/event   {sessionId, kind: present|hit|miss, arm: left|right, reactionMs?} -> {accepted}
    POST /rig/start   {mode, difficulty} -> {ok, sessionId} or {ok: false, error}  for the linked player
    POST /rig/threat  {arm: left|right} -> 204   forwarded to brain/arm/reflex.py (--arm-host)
    POST /coach/plan  {} -> {plan: {difficulty, focus, reason, say}, source: nemotron|rules}: the coach agent
                      reads the player's Convex stats and plans the next round (tools/coach_agent.py)
    POST /coach/speak {text} -> audio/mpeg: any line in the coach's voice
    POST /coach/say   {event: start|miss|slow|hit|streak|crowd|end, ms?} -> audio/mpeg (X-Coach-Line: the text),
                      a line from the player's Convex stats spoken by ElevenLabs; 204 if none (tools/coach_voice.py)
    GET  /rig/pads    {ageMs, left, right}  the real pads from brain/arm/pad_stream.py (udp 9311), each
                      {p, n} in its arm's base frame or null; ageMs null until the first packet

With --arm-host, a 20 Hz UDP heartbeat keeps brain/arm/reflex.py's watchdog fed; stopping this
server stops the heartbeat, which turns the arms' torque off within half a second.

HUB_SECRET stays on this laptop; the headset only ever talks to this server.
"""

import argparse
import json
import os
import socket
import sys
import threading
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from brain.convex_bridge import ConvexBridge  # noqa: E402
import coach_agent  # noqa: E402  (tools/, next to this file)
from coach_voice import Coach  # noqa: E402

LOG = ROOT / "logs" / f"xr-{time.strftime('%Y%m%d')}.jsonl"
DEFAULT_SITE = "https://abundant-roadrunner-265.convex.site"
SECRET_FILE = Path.home() / ".config" / "wax-on-wax-off" / "hub_secret"  # used when HUB_SECRET is unset
POLL_S = 0.25


class Rig:
    """Latest Convex state, refreshed by a background poller."""

    def __init__(self, bridge: ConvexBridge | None) -> None:
        self.bridge = bridge
        self.lock = threading.Lock()
        self.state = {"online": False, "error": "HUB_SECRET not set" if bridge is None else "connecting", "estop": False, "session": None,
                      "linkCode": None, "player": None, "audienceCode": None, "reactions": []}

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
                       "linkCode": self.bridge.link_code, "player": self.bridge.player,
                       "audienceCode": self.bridge.audience_code, "reactions": self.bridge.reactions}
            except Exception as e:  # network blips must not kill the poller
                new = {**self.state, "online": False, "error": str(e), "session": None, "reactions": []}
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


class ArmLink:
    """UDP link to brain/arm/reflex.py: heartbeat for its watchdog, threats from the headset."""

    def __init__(self, host: str | None, port: int = 9310) -> None:
        # host may be IPv4 or IPv6 link-local with a scope (fe80::...%enx...), the direct cable's
        # address whatever the GX10's IPv4 settings are.
        self.host, self.port = host, port
        self.addr = None
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self.error = ""
        self._resolve()

    def _resolve(self) -> None:
        """Look the address up again: a re-plugged USB adapter gets a new interface index, and the
        old link-local scope would stay "unreachable" forever (and the arms' watchdog drop torque)."""
        if not self.host:
            return
        try:
            family, _, _, _, addr = socket.getaddrinfo(self.host, self.port, type=socket.SOCK_DGRAM)[0]
        except OSError:
            return  # adapter not plugged in yet; try again on the next send
        self.sock.close()
        self.sock = socket.socket(family, socket.SOCK_DGRAM)
        self.addr = addr

    def send(self, msg: dict) -> None:
        if not self.host:
            return
        try:
            if self.addr is None:
                raise OSError("no route to the arms' machine yet")
            self.sock.sendto(json.dumps(msg).encode(), self.addr)
            if self.error:
                print("arm link: back")
                self.error = ""
        except OSError as e:
            if str(e) != self.error:  # say it once, not 20 times a second
                print(f"arm link: {e}; retrying")
                self.error = str(e)
            self._resolve()

    def heartbeat(self) -> None:
        while True:
            self.send({"t": "hb"})
            time.sleep(0.05)


class Pads:
    """Latest packet from brain/arm/pad_stream.py, which multicasts on the wired link to the GX10."""

    def __init__(self, port: int = 9311) -> None:
        self.sock = socket.socket(socket.AF_INET6, socket.SOCK_DGRAM)
        self.sock.bind(("::", port))
        self.last: dict = {}
        self.at = 0.0

    def run(self) -> None:
        while True:
            data, _ = self.sock.recvfrom(4096)
            try:
                msg = json.loads(data)
            except ValueError:
                continue
            if msg.get("t") == "pads":
                self.last, self.at = msg, time.monotonic()

    def snapshot(self) -> dict:
        age = round((time.monotonic() - self.at) * 1000) if self.at else None
        return {"ageMs": age, "left": self.last.get("left"), "right": self.last.get("right")}


class Handler(SimpleHTTPRequestHandler):
    rig: Rig
    pads: Pads
    coach: Coach
    arm: ArmLink

    def _json(self, code: int, obj: dict) -> None:
        data = json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Cache-Control", "no-store")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _mp3(self, text: str, mp3: bytes) -> None:
        self.send_response(200)
        self.send_header("Content-Type", "audio/mpeg")
        self.send_header("Content-Length", str(len(mp3)))
        self.send_header("X-Coach-Line", text.encode("ascii", "replace").decode())
        self.end_headers()
        self.wfile.write(mp3)

    def _body(self) -> dict | None:
        try:
            return json.loads(self.rfile.read(int(self.headers.get("content-length", 0))))
        except json.JSONDecodeError:
            return None

    def do_GET(self) -> None:
        if self.path == "/rig/state":
            self._json(200, self.rig.snapshot())
            return
        if self.path == "/rig/pads":
            self._json(200, self.pads.snapshot())
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
        elif self.path == "/coach/say":
            body = self._body()
            if body is None:
                self.send_error(400)
                return
            try:
                said = self.coach.say(str(body.get("event", "")), body.get("ms"))
            except Exception as e:  # a voice hiccup must not break the game
                print(f"coach: {e}")
                said = None
            if not said:
                self.send_response(204)
                self.end_headers()
                return
            text, mp3 = said
            print(f"coach [{body.get('event')}]: {text}")
            self._mp3(text, mp3)
        elif self.path == "/coach/plan":
            result = coach_agent.plan(self.coach.fresh_context())
            print(f"coach agent [{result['source']}]: {result['plan']}")
            self._json(200, result)
        elif self.path == "/coach/speak":
            body = self._body()
            text = str((body or {}).get("text", ""))[:300]
            if not text or not self.coach.key:
                self.send_response(204)
                self.end_headers()
                return
            try:
                self._mp3(text, self.coach.speak(text))
            except Exception as e:
                print(f"coach: {e}")
                self.send_response(204)
                self.end_headers()
        elif self.path == "/rig/threat":
            body = self._body()
            if body is None or body.get("arm") not in ("left", "right"):
                self.send_error(400)
                return
            self.arm.send({"t": "threat", "arm": body["arm"]})
            self.send_response(204)
            self.end_headers()
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
    ap.add_argument("--arm-host", help="the GX10 running brain/arm/reflex.py: IPv4, or IPv6 link-local with its scope, "
                    "e.g. fe80::d293:20c9:afcc:fe9%%enx349971eb0d92")
    a = ap.parse_args()

    secret = os.environ.get("HUB_SECRET")
    if not secret and SECRET_FILE.is_file():
        secret = SECRET_FILE.read_text().strip() or None
    bridge = ConvexBridge(os.environ.get("CONVEX_SITE_URL", DEFAULT_SITE), secret) if secret else None
    Handler.rig = Rig(bridge)
    if bridge:
        threading.Thread(target=Handler.rig.run, daemon=True).start()

    Handler.arm = ArmLink(a.arm_host)
    if a.arm_host:
        threading.Thread(target=Handler.arm.heartbeat, daemon=True).start()
        print(f"arms: heartbeat + threats -> udp {a.arm_host}:9310")

    Handler.coach = Coach(bridge)
    print(f"coach voice: {'ElevenLabs' if Handler.coach.key else 'off (no ElevenLabs key)'}")
    Handler.pads = Pads()
    threading.Thread(target=Handler.pads.run, daemon=True).start()

    server = ThreadingHTTPServer(("0.0.0.0", a.port), partial(Handler, directory=str(ROOT)))
    print(f"serving {ROOT} on :{a.port}, stats -> {LOG}")
    print(f"rig: {'polling ' + bridge.base if bridge else 'offline (set HUB_SECRET to connect to the phone app)'}")
    server.serve_forever()


if __name__ == "__main__":
    main()
