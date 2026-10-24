import { getAuthUserId } from "@convex-dev/auth/server";
import { ConvexError, v } from "convex/values";
import type { Doc, Id } from "./_generated/dataModel";
import { internalMutation, mutation, query, type MutationCtx, type QueryCtx } from "./_generated/server";
import { bestKey } from "./game";
import { createSession, displayName, linkedPlayer, newLinkCode } from "./record";
import { difficultyV, modeV } from "./schema";

const RIG = "main";

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

// Anyone can sign up on the public URL, so the real arms are only for the player linked to the
// headset: the link code is only visible to someone at the booth.
function requireLinked(rig: Doc<"rigs">, userId: Id<"users">, action: string) {
  if (linkedPlayer(rig, Date.now()) !== userId) {
    throw new ConvexError({ code: "NOT_LINKED", message: `Link the headset first to ${action}: enter the code shown in it.` });
  }
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
    const userId = await getAuthUserId(ctx);
    const rig = await ctx.db.query("rigs").withIndex("by_name", (q) => q.eq("name", RIG)).unique();
    // The phone checks linkedAt against LINK_TTL_MS itself so this query doesn't depend on the clock.
    const playerId = rig?.playerId ?? null;
    return {
      lastSeenAt: rig?.lastSeenAt ?? 0,
      linkedToMe: !!userId && playerId === userId,
      linkedAt: rig?.playerAt ?? 0,
    };
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
  args: { mode: modeV, difficulty: difficultyV, simulate: v.boolean() },
  handler: async (ctx, { mode, difficulty, simulate }) => {
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
      const rig = await ensureRig(ctx);
      requireLinked(rig, userId, "use the real rig");
      await ctx.db.patch(rig._id, { playerAt: now });
    }

    return await createSession(ctx, { userId, mode, difficulty, simulate });
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

// The phone enters the code shown in the headset. No rig PIN: only someone wearing the headset
// at the booth can see the code, which is the same proof of presence.
export const linkHeadset = mutation({
  args: { code: v.string() },
  handler: async (ctx, { code }) => {
    const userId = await requireUser(ctx);
    const rig = await ensureRig(ctx);
    const clean = code.toUpperCase().replace(/[^A-Z0-9]/g, "");
    if (!rig.linkCode || clean !== rig.linkCode) {
      throw new ConvexError({ code: "BAD_CODE", message: "That code doesn't match the headset. Check it and try again." });
    }
    const now = Date.now();
    await ctx.db.patch(rig._id, { playerId: userId, playerAt: now, linkCode: newLinkCode(), linkCodeAt: now });
  },
});

export const unlinkHeadset = mutation({
  args: {},
  handler: async (ctx) => {
    const userId = await requireUser(ctx);
    const rig = await ensureRig(ctx);
    if (rig.playerId === userId) await ctx.db.patch(rig._id, { playerId: undefined, playerAt: undefined });
  },
});
