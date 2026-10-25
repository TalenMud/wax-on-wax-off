// Game rules shared by the Convex backend, the phone UI, and (via /hub/poll) the robot hub.
//
// Timing is based on reaction-drill norms: simple visual reaction is ~200-250 ms, and a full
// see-target-then-punch-it cycle is ~400-700 ms for most people (~300 ms for trained fighters).
// Reflex trainers (BlazePod, FitLight) use 30-90 s drills; a boxing round is 3 minutes.

export type Mode = "sprint" | "standard" | "round";
export type Difficulty = "easy" | "medium" | "hard";
export type Arm = "left" | "right";

export const MODES: Record<Mode, { label: string; durationS: number; blurb: string }> = {
  sprint: { label: "Sprint", durationS: 30, blurb: "30 s all-out reflex burst" },
  standard: { label: "Standard", durationS: 60, blurb: "60 s classic reaction drill" },
  round: { label: "Fight Round", durationS: 180, blurb: "3 min boxing-length round" },
};

// windowMs: how long the pad stays presented before an unhit pad counts as a miss.
// maxRun: longest run of presentations on the same arm before it must switch sides.
// gapMs: pause between a pad resolving and the next presentation (arm travel + recovery).
export const DIFFICULTIES: Record<
  Difficulty,
  { label: string; windowMs: number; maxRun: number; gapMs: number; blurb: string }
> = {
  easy: { label: "Easy", windowMs: 2000, maxRun: 2, gapMs: 900, blurb: "Slow arm, short runs" },
  medium: { label: "Medium", windowMs: 1500, maxRun: 3, gapMs: 650, blurb: "Mixed runs" },
  hard: { label: "Hard", windowMs: 1000, maxRun: 4, gapMs: 450, blurb: "Fast arm, long streaks" },
};

export const COUNTDOWN_MS = 3000;

// A headset link lasts this long after it was made or last used, so the next visitor
// doesn't play on someone else's account.
export const LINK_TTL_MS = 10 * 60_000;

export function pointsFor(reactionMs: number, streakBeforeHit: number): number {
  const base = reactionMs < 400 ? 100 : reactionMs < 600 ? 75 : 50;
  return base + Math.min(streakBeforeHit, 10) * 10;
}

export function reactionRating(ms: number): { label: string; tone: "elite" | "good" | "ok" | "slow" } {
  if (ms < 400) return { label: "Lightning", tone: "elite" };
  if (ms < 600) return { label: "Sharp", tone: "good" };
  if (ms < 800) return { label: "Solid", tone: "ok" };
  return { label: "Slow", tone: "slow" };
}

// Personal bests are kept separately for the real rig and the simulator.
export function bestKey(simulated: boolean, mode: Mode, difficulty: Difficulty) {
  return `${simulated ? "sim" : "rig"}:${mode}:${difficulty}`;
}

// Reactions the audience page (waxonwaxoff.ink/audience) can send to the headset.
export const AUDIENCE_EMOJIS = ["🔥", "👏", "🥊", "💪", "😂", "💀", "🤡", "😴"];
