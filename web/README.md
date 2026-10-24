# Clients: web dashboard and VR score display

Both pages connect to the hub over WebSocket (port 8765) and read the same
`state` and `event` messages. Neither page has a build step.

| Page | What it shows |
|---|---|
| `web/index.html` | Live score, round timer, coach combo, recent events, raw state, and control buttons (start, pause, reset, E-STOP) |
| `vr/index.html` | Floating score panel in the headset, passthrough on so the player always sees the real arm. Flashes green on a hit and red on a miss. |

## Run against fake data (no robot needed)

```bash
uv run tools/mock_hub.py            # ws://0.0.0.0:8765
python3 -m http.server 8000         # from the repo root
```

Open http://localhost:8000/web/ for the dashboard.

To use the real hub on the robot laptop, add `?hub=ws://<robot-laptop-ip>:8765`
to either page's URL.

## VR headset (Quest)

WebXR only works on a secure origin. `http://localhost` counts as secure, so
forward the port over USB instead of setting up HTTPS:

```bash
adb reverse tcp:8000 tcp:8000
adb reverse tcp:8765 tcp:8765       # only when the hub runs on this Mac
```

Then open http://localhost:8000/vr/ in the Quest browser and press "Enter (passthrough)".
When the hub runs on the robot laptop, open
http://localhost:8000/vr/?hub=ws://<robot-laptop-ip>:8765 instead.
