import { getAuthUserId } from "@convex-dev/auth/server";
import { ConvexError, v } from "convex/values";
import { internal } from "./_generated/api";
import type { Doc, Id } from "./_generated/dataModel";
import { internalMutation, mutation, query, type MutationCtx, type QueryCtx } from "./_generated/server";
import { bestKey, COUNTDOWN_MS, MODES } from "./game";
import { difficultyV, modeV } from "./schema";

const RIG = "main";
const emptySide = { hits: 0, misses: 0, reactionSumMs: 0 };

async function requireUser(ctx: QueryCtx | MutationCtx): Promise<Id<"users">> {
  const userId = await getAuthUserId(ctx);
  if (!userId) throw new ConvexError("Please sign in.");
  return userId;
}

async function ensureRig(ctx: MutationCtx): Promise<Doc<"rigs">> {
  const rig = await ctx.db.query("rigs").withIndex("by_name", (q) => q.eq("name", RIG)).unique();
  if (rig) return rig;
  const id = await ctx.db.insert("rigs", { name: RIG, lastSeenAt: 0, estop: false });
  return (await ctx.db.get(id))!;
}

async function liveSessions(ctx: QueryCtx) {
  return await ctx.db.query("sessions").withIndex("by_status", (q) => q.eq("status", "live")).collect();
}

// The one session driving the real arms, if any. Simulated sessions never touch the rig, so
// several can run at once alongside it.
async function rigSession(ctx: QueryCtx) {
  return (await liveSessions(ctx)).find((s) => !s.simulated) ?? null;
}

// Anyone can sign up on the public URL, so moving the real arms (or un-latching E-STOP) needs
// the rig PIN shown at the booth. Unset RIG_PIN disables the check for local dev.
function checkPin(pin: string | undefined) {
  const expected = process.env.RIG_PIN;
  if (!expected) return;
  if (!pin) throw new ConvexError({ code: "PIN_REQUIRED", message: "Enter the rig PIN from the booth." });
  if (pin.trim() !== expected) throw new ConvexError({ code: "PIN_WRONG", message: "Wrong rig PIN." });
}

async function displayName(ctx: QueryCtx, userId: Id<"users">) {
  const user = await ctx.db.get(userId);
  return user?.name || user?.email?.split("@")[0] || "Player";
}

export const me = query({
  args: {},
  handler: async (ctx) => {
    const userId = await getAuthUserId(ctx);
    if (!userId) return null;
    const user = await ctx.db.get(userId);
    return user && { _id: user._id, name: await displayName(ctx, userId), email: user.email ?? "" };
  },
});

export const rig = query({
  args: {},
  handler: async (ctx) => {
    const rig = await ctx.db.query("rigs").withIndex("by_name", (q) => q.eq("name", RIG)).unique();
    return { lastSeenAt: rig?.lastSeenAt ?? 0, estop: rig?.estop ?? false };
  },
});

export const live = query({
  args: {},
  handler: async (ctx) => {
    const userId = await getAuthUserId(ctx);
    const live = await liveSessions(ctx);
    // My own session takes priority; otherwise show whoever is on the real arms.
    const session = live.find((s) => s.userId === userId) ?? live.find((s) => !s.simulated);
    if (!session) return null;
    const recent = await ctx.db
      .query("events")
      .withIndex("by_session", (q) => q.eq("sessionId", session._id))
      .order("desc")
      .take(6);
    return { session, recent, mine: session.userId === userId, player: await displayName(ctx, session.userId) };
  },
});

export const start = mutation({
  args: { mode: modeV, difficulty: difficultyV, simulate: v.boolean(), pin: v.optional(v.string()) },
  handler: async (ctx, { mode, difficulty, simulate, pin }) => {
    const userId = await requireUser(ctx);
    const now = Date.now();
    for (const s of await liveSessions(ctx)) {
      if (s.endsAt + 2000 < now) {
        await ctx.db.patch(s._id, { status: "finished", endedAt: s.endsAt, activeArm: undefined });
      } else if (s.userId === userId) {
        throw new ConvexError("You already have a session running.");
      } else if (!simulate && !s.simulated) {
        throw new ConvexError("The rig is busy with another session.");
      }
    }
    if (!simulate) {
      checkPin(pin);
      const rig = await ensureRig(ctx);
      if (rig.estop) throw new ConvexError("E-STOP is latched. Reset it before starting.");
    }

    const durationS = MODES[mode].durationS;
    const startsAt = now + COUNTDOWN_MS;
    const endsAt = startsAt + durationS * 1000;
    const sessionId = await ctx.db.insert("sessions", {
      userId,
      mode,
      difficulty,
      durationS,
      status: "live",
      simulated: simulate,
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
    if (simulate) {
      await ctx.scheduler.runAt(startsAt, internal.simulate.present, {
        sessionId,
        arm: Math.random() < 0.5 ? "left" : "right",
        run: 1,
      });
    }
    return { sessionId, serverNow: now };
  },
});

export const finish = internalMutation({
  args: { sessionId: v.id("sessions") },
  handler: async (ctx, { sessionId }) => {
    const s = await ctx.db.get(sessionId);
    if (s?.status !== "live") return;
    await ctx.db.patch(sessionId, { status: "finished", endedAt: Date.now(), activeArm: undefined });
  },
});

export const stop = mutation({
  args: { sessionId: v.id("sessions") },
  handler: async (ctx, { sessionId }) => {
    const userId = await requireUser(ctx);
    const s = await ctx.db.get(sessionId);
    if (!s || s.status !== "live") return;
    if (s.userId !== userId) throw new ConvexError("Only the player can stop this session.");
    await ctx.db.patch(sessionId, { status: "stopped", endedAt: Date.now(), activeArm: undefined });
  },
});

// Any signed-in user can hit E-STOP, whoever's session it is. Safety beats ownership.
export const estop = mutation({
  args: {},
  handler: async (ctx) => {
    await requireUser(ctx);
    const rig = await ensureRig(ctx);
    await ctx.db.patch(rig._id, { estop: true });
    const live = await rigSession(ctx);
    if (live) await ctx.db.patch(live._id, { status: "stopped", endedAt: Date.now(), activeArm: undefined });
  },
});

export const resetEstop = mutation({
  args: { pin: v.optional(v.string()) },
  handler: async (ctx, { pin }) => {
    await requireUser(ctx);
    checkPin(pin);
    const rig = await ensureRig(ctx);
    await ctx.db.patch(rig._id, { estop: false });
  },
});

export const get = query({
  args: { sessionId: v.id("sessions") },
  handler: async (ctx, { sessionId }) => {
    await requireUser(ctx);
    const session = await ctx.db.get(sessionId);
    if (!session) return null;
    const events = await ctx.db
      .query("events")
      .withIndex("by_session", (q) => q.eq("sessionId", sessionId))
      .collect();
    // Best finished score this player had in the same mode+difficulty *before* this session.
    let previousBest: number | null = null;
    const earlier = await ctx.db
      .query("sessions")
      .withIndex("by_user", (q) => q.eq("userId", session.userId).lt("createdAt", session.createdAt))
      .collect();
    for (const s of earlier) {
      if (
        s.status === "finished" &&
        s.mode === session.mode &&
        s.difficulty === session.difficulty &&
        s.simulated === session.simulated
      ) {
        previousBest = Math.max(previousBest ?? 0, s.score);
      }
    }
    return { session, events, previousBest, player: await displayName(ctx, session.userId) };
  },
});

export const history = query({
  args: {},
  handler: async (ctx) => {
    const userId = await getAuthUserId(ctx);
    if (!userId) return [];
    return await ctx.db
      .query("sessions")
      .withIndex("by_user", (q) => q.eq("userId", userId))
      .order("desc")
      .take(50);
  },
});

export const personalBests = query({
  args: {},
  handler: async (ctx) => {
    const userId = await getAuthUserId(ctx);
    if (!userId) return {};
    const bests: Record<string, Doc<"sessions">> = {};
    const all = await ctx.db
      .query("sessions")
      .withIndex("by_user", (q) => q.eq("userId", userId))
      .collect();
    for (const s of all) {
      if (s.status !== "finished") continue;
      const key = bestKey(s.simulated, s.mode, s.difficulty);
      if (!bests[key] || s.score > bests[key].score) bests[key] = s;
    }
    return bests;
  },
});

// Robot and simulated scores are separate boards: practice against the virtual opponent
// shouldn't outrank real punches.
export const leaderboard = query({
  args: { mode: modeV, difficulty: difficultyV, simulated: v.boolean() },
  handler: async (ctx, { mode, difficulty, simulated }) => {
    const top = await ctx.db
      .query("sessions")
      .withIndex("by_board", (q) =>
        q.eq("mode", mode).eq("difficulty", difficulty).eq("simulated", simulated).eq("status", "finished"),
      )
      .order("desc")
      .take(200);
    const seen = new Set<Id<"users">>();
    const rows = [];
    for (const s of top) {
      if (seen.has(s.userId)) continue;
      seen.add(s.userId);
      rows.push({ session: s, player: await displayName(ctx, s.userId) });
      if (rows.length === 10) break;
    }
    return rows;
  },
});
