import type { Doc } from "./_generated/dataModel";
import type { MutationCtx } from "./_generated/server";
import { pointsFor, type Arm } from "./game";

// Late events are accepted for a short grace period so a punch landing on the buzzer still counts.
const GRACE_MS = 500;

export function acceptsEvents(session: Doc<"sessions">, now: number): boolean {
  return session.status === "live" && now >= session.startsAt && now <= session.endsAt + GRACE_MS;
}

export async function setPresented(ctx: MutationCtx, session: Doc<"sessions">, arm: Arm | undefined) {
  await ctx.db.patch(session._id, { activeArm: arm, activeSince: arm ? Date.now() : undefined });
}

export async function recordStrike(
  ctx: MutationCtx,
  session: Doc<"sessions">,
  e: { kind: "hit" | "miss"; arm: Arm; reactionMs?: number },
) {
  const now = Date.now();
  if (!acceptsEvents(session, now)) return false;

  const side = { ...session[e.arm] };
  let { hits, misses, score, streak, bestStreak, reactionSumMs } = session;
  let points = 0;
  if (e.kind === "hit") {
    const reactionMs = Math.max(0, Math.round(e.reactionMs ?? 0));
    points = pointsFor(reactionMs, streak);
    hits += 1;
    score += points;
    streak += 1;
    bestStreak = Math.max(bestStreak, streak);
    reactionSumMs += reactionMs;
    side.hits += 1;
    side.reactionSumMs += reactionMs;
    e = { ...e, reactionMs };
  } else {
    misses += 1;
    streak = 0;
    side.misses += 1;
  }

  await ctx.db.insert("events", { sessionId: session._id, kind: e.kind, arm: e.arm, reactionMs: e.reactionMs, points, t: now });
  await ctx.db.patch(session._id, {
    hits,
    misses,
    score,
    streak,
    bestStreak,
    reactionSumMs,
    [e.arm]: side,
    activeArm: undefined,
    activeSince: undefined,
  });
  return true;
}
