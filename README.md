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
| `tools/makermodslab/` | [MakerMods Lab](https://github.com/makermods-robotics/makermodslab) (git submodule): arm calibration, teleop, cameras |

## Arm setup with MakerMods Lab

MakerMods Lab is a browser UI for LeRobot arms. Its **Metal** arm family is a 7-DOF Damiao arm on CAN,
which is the same kind of hardware as the reBot B601-RS. Use it to **calibrate the arms, drive them by hand
to check the pad poses, and check the cameras** before running the game.

```bash
git submodule update --init      # first time only (or clone with --recursive)
tools/lab.sh                     # http://localhost:8000; needs uv (brew install uv)
```

It runs in its own environment because it pins its own LeRobot fork. Lab and the game hub **can't share the
CAN bus**, so quit Lab before starting the hub. The real arm's `connect()` calls
`brain.arm.lab.ensure_bus_free()`, which refuses to connect while a Lab session is active.
To update Lab, run `git -C tools/makermodslab pull` and then commit the new submodule pointer.
