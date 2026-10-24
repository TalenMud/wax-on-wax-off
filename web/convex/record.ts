import { internal } from "./_generated/api";
import type { Doc, Id } from "./_generated/dataModel";
import type { MutationCtx, QueryCtx } from "./_generated/server";
import { COUNTDOWN_MS, LINK_TTL_MS, MODES, pointsFor, type Arm, type Difficulty, type Mode } from "./game";

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

const emptySide = { hits: 0, misses: 0, reactionSumMs: 0 };

export async function createSession(
  ctx: MutationCtx,
  a: { userId: Id<"users">; mode: Mode; difficulty: Difficulty; simulate: boolean },
): Promise<{ sessionId: Id<"sessions">; serverNow: number }> {
  const now = Date.now();
  const durationS = MODES[a.mode].durationS;
  const startsAt = now + COUNTDOWN_MS;
  const endsAt = startsAt + durationS * 1000;
  const sessionId = await ctx.db.insert("sessions", {
    userId: a.userId,
    mode: a.mode,
    difficulty: a.difficulty,
    durationS,
    status: "live",
    simulated: a.simulate,
    createdAt: now,
    startsAt,
    endsAt,
    hits: 0,
    misses: 0,
    score: 0,
    streak: 0,
    bestStreak: 0,
    reactionSumMs: 0,
    left: emptySide,
    right: emptySide,
  });
  await ctx.scheduler.runAt(endsAt, internal.sessions.finish, { sessionId });
  if (a.simulate) {
    await ctx.scheduler.runAt(startsAt, internal.simulate.present, {
      sessionId,
      arm: Math.random() < 0.5 ? "left" : "right",
      run: 1,
    });
  }
  return { sessionId, serverNow: now };
}

// Headset link codes: 6 characters without look-alikes (no 0/O, 1/I/L), fresh every 15 minutes.
const CODE_ALPHABET = "ABCDEFGHJKMNPQRSTUVWXYZ23456789";
export const LINK_CODE_TTL_MS = 15 * 60_000;

export function newLinkCode(): string {
  let code = "";
  for (let i = 0; i < 6; i++) code += CODE_ALPHABET[Math.floor(Math.random() * CODE_ALPHABET.length)];
  return code;
}

export function linkedPlayer(rig: Doc<"rigs">, now: number): Id<"users"> | null {
  return rig.playerId && now - (rig.playerAt ?? 0) < LINK_TTL_MS ? rig.playerId : null;
}

export async function displayName(ctx: QueryCtx, userId: Id<"users">) {
  const user = await ctx.db.get(userId);
  return user?.name || user?.email?.split("@")[0] || "Player";
}
