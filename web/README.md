# Wax On Wax Off: phone app

Phone-first web app for the sparring rig. A friend or coach holds the phone while the player wears the
headset: pick a session, start it, watch hits land live, hit E-STOP if anything goes wrong. Every
session is saved to the player's account with personal bests and a leaderboard.

Built on **Convex** (database, auth, real-time sync, scheduled jobs, HTTP endpoints for the robot)
with React + Vite.

## How it fits together

```
 phone (React)  ──live queries/mutations──▶  Convex  ◀──HTTP /hub/poll, /hub/event──  robot laptop
                                              │                                        brain/convex_bridge.py
                                              └─ scheduler ends each session on time
```

- The phone never talks to the robot directly, so the app can live on HTTPS (Vercel) and the robot
  laptop only needs outbound internet.
- Convex is the clock: a session's `startsAt`/`endsAt` are set on the server, a scheduled function
  finishes it, and strikes outside the window are rejected.
- Only one arm presents at a time. Sides alternate in random runs (`maxRun` per difficulty).
- No robot? The app defaults to a **simulated rig** (`convex/simulate.ts`) so it is always demoable.
- **Rig PIN:** anyone can sign up on the public URL, so starting a session on the real arms (or
  resetting E-STOP) needs `RIG_PIN`, which should be shown on a sign at the booth. Each phone remembers it after the first use.
  Practice sessions and E-STOP itself never need it.

## Sessions and scoring (`convex/game.ts`)

| Mode | Length |   | Difficulty | Pad up for | Max run on one side |
|---|---|---|---|---|---|
| Sprint | 30 s | | Easy | 1.5 s | 2 |
| Standard | 60 s | | Medium | 1.0 s | 3 |
| Fight Round | 3 min | | Hard | 0.7 s | 4 |

A hit scores 100 if under 400 ms, 75 if under 600 ms, otherwise 50, plus 10 per hit of current streak (capped at +100).
A miss resets the streak. Personal bests and the leaderboard are tracked per mode + difficulty.
Sessions ended early or by E-STOP are saved but not ranked. Robot and practice (simulated) sessions have separate
leaderboards and personal bests.

These numbers come from reaction-drill norms. Simple visual reaction takes about 200–250 ms. Seeing a target and
punching it takes about 400–700 ms for most people and about 300 ms for trained fighters. Reflex trainers run 30–90 s drills.

## Run it locally

```bash
cd web
npm install
npx convex dev            # first run: log in / create a project; leave it running
node scripts/setup-auth.mjs http://localhost:5173 <hub-secret> <rig-pin>   # once per deployment
npm run dev               # http://localhost:5173 (also on your LAN IP for a phone)
```

To test on a phone, open the Network URL Vite prints, with the phone on the same Wi-Fi. A local Convex backend is proxied
through the Vite dev server. Venue Wi-Fi often blocks device-to-device traffic, so use a hotspot or deploy instead.

## Deploy (GitHub Pages)

`.github/workflows/pages.yml` deploys on every push to `main` that touches `web/`. It pushes the Convex
functions to prod and publishes the site to `https://<owner>.github.io/wax-on-wax-off/`.

Prod backend: `https://abundant-roadrunner-265.convex.cloud` (robot endpoints on `.convex.site`).
Its `HUB_SECRET` and `RIG_PIN` are set in the Convex dashboard (prod → Settings → Environment Variables).

One-time setup:
1. In the GitHub repo, go to Settings → Pages and set Source to **GitHub Actions**.
2. Optional: so backend changes deploy on push too, generate a **deploy key** in the Convex dashboard (prod → Settings)
   and add it to the repo as the secret `CONVEX_DEPLOY_KEY`. Without it, run `npx convex deploy` by hand after changing `convex/`.

To start over on a new Convex project: run `npx convex deploy`, then
`node scripts/setup-auth.mjs --prod https://<owner>.github.io/wax-on-wax-off/ [hub-secret] [rig-pin]`, then update
`VITE_CONVEX_URL` in the workflow.

## Robot hub contract

Both endpoints need the header `Authorization: Bearer $HUB_SECRET` and live on the `.convex.site` URL.

- `GET /hub/poll`: heartbeat ("Rig online" on the phone) plus state:
  `{ serverNow, estop, session: null | { id, mode, difficulty, durationS, startsAt, endsAt, windowMs, maxRun, gapMs } }`.
  Poll about 4×/s. If `estop` is true, stop the arms immediately.
- `POST /hub/event` `{ sessionId, kind: "present" | "hit" | "miss", arm: "left" | "right", reactionMs? }`.
  Send `present` when a pad goes up, then exactly one `hit` (with reaction time from presentation) or `miss`.
  Returns `{ accepted: false }` once the session is over or stopped, so the hub should stop then.

`brain/convex_bridge.py` wraps both endpoints (stdlib only). Try it without the arms:

```bash
CONVEX_SITE_URL=https://<deployment>.convex.site HUB_SECRET=<hub-secret> python -m brain.convex_bridge --mock
```
