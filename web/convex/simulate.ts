// Server-side stand-in for the robot hub, so the app can be demoed with no rig connected.
// Mirrors what the real hub does: present a pad on one arm, wait for a punch or the miss
// window, then switch sides according to the difficulty's run rules.
import { v } from "convex/values";
import { internal } from "./_generated/api";
import { internalMutation } from "./_generated/server";
import { DIFFICULTIES, type Arm, type Difficulty } from "./game";
import { recordStrike, setPresented } from "./record";
import { armV } from "./schema";

const REACTION: Record<Difficulty, { mean: number; sd: number; missChance: number }> = {
  easy: { mean: 520, sd: 140, missChance: 0.06 },
  medium: { mean: 480, sd: 130, missChance: 0.12 },
  hard: { mean: 450, sd: 120, missChance: 0.2 },
};

function gaussian(mean: number, sd: number) {
  const u = 1 - Math.random();
  return mean + sd * Math.sqrt(-2 * Math.log(u)) * Math.cos(2 * Math.PI * Math.random());
}

export const present = internalMutation({
  args: { sessionId: v.id("sessions"), arm: armV, run: v.number() },
  handler: async (ctx, { sessionId, arm, run }) => {
    const s = await ctx.db.get(sessionId);
    if (!s || s.status !== "live" || Date.now() >= s.endsAt) return;
    await setPresented(ctx, s, arm);

    const d = DIFFICULTIES[s.difficulty];
    const r = REACTION[s.difficulty];
    const reactionMs = Math.max(250, Math.round(gaussian(r.mean, r.sd)));
    const hit = reactionMs <= d.windowMs && Math.random() > r.missChance;
    await ctx.scheduler.runAfter(hit ? reactionMs : d.windowMs, internal.simulate.resolve, {
      sessionId,
      arm,
      run,
      reactionMs: hit ? reactionMs : undefined,
    });
  },
});

export const resolve = internalMutation({
  args: { sessionId: v.id("sessions"), arm: armV, run: v.number(), reactionMs: v.optional(v.number()) },
  handler: async (ctx, { sessionId, arm, run, reactionMs }) => {
    const s = await ctx.db.get(sessionId);
    if (!s || s.status !== "live") return;
    const ok = await recordStrike(ctx, s, { kind: reactionMs === undefined ? "miss" : "hit", arm, reactionMs });
    if (!ok) return;

    const { maxRun, gapMs } = DIFFICULTIES[s.difficulty];
    const stay = run < maxRun && Math.random() < 0.5;
    const next: Arm = stay ? arm : arm === "left" ? "right" : "left";
    await ctx.scheduler.runAfter(gapMs, internal.simulate.present, { sessionId, arm: next, run: stay ? run + 1 : 1 });
  },
});
