// Robot hub <-> Convex bridge. The hub (Python, robot laptop) polls /hub/poll and posts
// strikes to /hub/event; see brain/convex_bridge.py. Both routes need HUB_SECRET.
import { v } from "convex/values";
import { internalMutation } from "./_generated/server";
import { DIFFICULTIES } from "./game";
import { createSession, displayName, LINK_CODE_TTL_MS, linkedPlayer, newLinkCode, recordStrike, setPresented } from "./record";
import { armV, difficultyV, modeV } from "./schema";

const HEARTBEAT_WRITE_MS = 2000;
const AUDIENCE_CODE_TTL_MS = 12 * 60 * 60_000;
const REACTIONS_WINDOW_MS = 5000;

export const poll = internalMutation({
  args: {},
  handler: async (ctx) => {
    const now = Date.now();
    let rig = await ctx.db.query("rigs").withIndex("by_name", (q) => q.eq("name", "main")).unique();
    if (!rig) {
      const id = await ctx.db.insert("rigs", { name: "main", lastSeenAt: now, estop: false });
      rig = (await ctx.db.get(id))!;
    } else if (now - rig.lastSeenAt > HEARTBEAT_WRITE_MS) {
      await ctx.db.patch(rig._id, { lastSeenAt: now });
    }
    if (!rig.linkCode || now - (rig.linkCodeAt ?? 0) > LINK_CODE_TTL_MS) {
      const linkCode = newLinkCode();
      await ctx.db.patch(rig._id, { linkCode, linkCodeAt: now });
      rig = { ...rig, linkCode, linkCodeAt: now };
    }
    if (!rig.audienceCode || now - (rig.audienceCodeAt ?? 0) > AUDIENCE_CODE_TTL_MS) {
      const audienceCode = newLinkCode();
      await ctx.db.patch(rig._id, { audienceCode, audienceCodeAt: now });
      rig = { ...rig, audienceCode, audienceCodeAt: now };
    }
    const playerId = linkedPlayer(rig, now);

    // The last few seconds of audience emoji (the hub de-duplicates by id); older ones are dropped.
    const reactions = await ctx.db.query("reactions").withIndex("by_at", (q) => q.gt("at", now - REACTIONS_WINDOW_MS)).take(60);
    for (const old of await ctx.db.query("reactions").withIndex("by_at", (q) => q.lt("at", now - 60_000)).take(25)) {
      await ctx.db.delete(old._id);
    }

    const live = await ctx.db.query("sessions").withIndex("by_status", (q) => q.eq("status", "live")).collect();
    const s = live.find((x) => !x.simulated);
    const session =
      s
        ? {
            id: s._id,
            mode: s.mode,
            difficulty: s.difficulty,
            durationS: s.durationS,
            startsAt: s.startsAt,
            endsAt: s.endsAt,
            ...DIFFICULTIES[s.difficulty],
          }
        : null;
    return {
      serverNow: now,
      estop: false, // no phone E-STOP any more; kept for brain/convex_bridge.py
      session,
      linkCode: rig.linkCode,
      player: playerId ? await displayName(ctx, playerId) : null,
      audienceCode: rig.audienceCode,
      reactions: reactions.map((r) => ({ id: r._id, emoji: r.emoji, at: r.at })),
    };
  },
});

export const event = internalMutation({
  args: {
    sessionId: v.id("sessions"),
    kind: v.union(v.literal("present"), v.literal("hit"), v.literal("miss")),
    arm: armV,
    reactionMs: v.optional(v.number()),
  },
  handler: async (ctx, { sessionId, kind, arm, reactionMs }) => {
    const s = await ctx.db.get(sessionId);
    if (!s || s.simulated) return { accepted: false };
    if (kind === "present") {
      if (s.status !== "live") return { accepted: false };
      await setPresented(ctx, s, arm);
      return { accepted: true };
    }
    return { accepted: await recordStrike(ctx, s, { kind, arm, reactionMs }) };
  },
});

// The headset starts a round for whoever linked it from their phone.
export const start = internalMutation({
  args: { mode: modeV, difficulty: difficultyV },
  handler: async (ctx, { mode, difficulty }) => {
    const now = Date.now();
    const rig = await ctx.db.query("rigs").withIndex("by_name", (q) => q.eq("name", "main")).unique();
    if (!rig) return { ok: false, error: "rig not set up" };
    const userId = linkedPlayer(rig, now);
    if (!userId) return { ok: false, error: "no player linked" };
    const live = await ctx.db.query("sessions").withIndex("by_status", (q) => q.eq("status", "live")).collect();
    for (const s of live) {
      if (s.simulated) continue;
      if (s.endsAt + 2000 >= now) return { ok: false, error: "the rig is busy" };
      await ctx.db.patch(s._id, { status: "finished", endedAt: s.endsAt, activeArm: undefined });
    }
    await ctx.db.patch(rig._id, { playerAt: now });
    const { sessionId } = await createSession(ctx, { userId, mode, difficulty, simulate: false });
    return { ok: true, sessionId };
  },
});
