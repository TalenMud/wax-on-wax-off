"""Serve the repo for the Quest and collect stats the XR pages POST to /log.

    python3 tools/serve_xr.py            # http://0.0.0.0:8080, logs to logs/xr-<date>.jsonl
    adb reverse tcp:8080 tcp:8080        # then open http://localhost:8080/vr/gloves.html on the Quest
"""

import argparse
import json
import time
from functools import partial
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
LOG = ROOT / "logs" / f"xr-{time.strftime('%Y%m%d')}.jsonl"


class Handler(SimpleHTTPRequestHandler):
    def do_POST(self) -> None:
        if self.path != "/log":
            self.send_error(404)
            return
        body = self.rfile.read(int(self.headers.get("content-length", 0)))
        try:
            json.loads(body)
        except json.JSONDecodeError:
            self.send_error(400)
            return
        LOG.parent.mkdir(exist_ok=True)
        with LOG.open("ab") as f:
            f.write(body + b"\n")
        self.send_response(204)
        self.end_headers()

    def log_message(self, fmt, *args) -> None:
        if self.command != "POST":
            super().log_message(fmt, *args)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8080)
    a = ap.parse_args()
    server = ThreadingHTTPServer(("0.0.0.0", a.port), partial(Handler, directory=str(ROOT)))
    print(f"serving {ROOT} on :{a.port}, stats -> {LOG}")
    server.serve_forever()


if __name__ == "__main__":
    main()
