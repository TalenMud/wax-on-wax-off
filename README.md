# Wax On Wax Off

Kung-fu sparring partner on a Seeed reBot B601-RS arm, built at Cal Hacks 13.0.
The arm holds a foam pad and moves it to targets; the player strikes the pad.

| Folder | What |
|---|---|
| `brain/` | Robot control, perception, game logic, WebSocket hub (robot laptop) |
| `web/` | Phone app: sessions, live score, history, leaderboard (Convex). See `web/README.md` |
| `dashboard/` | Single-page live dashboard for the WebSocket hub |
| `vr/` | WebXR score display for the headset |
| `tools/` | Dev tools, including a mock hub |
