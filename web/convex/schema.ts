import { authTables } from "@convex-dev/auth/server";
import { defineSchema, defineTable } from "convex/server";
import { v } from "convex/values";

export const modeV = v.union(v.literal("sprint"), v.literal("standard"), v.literal("round"));
export const difficultyV = v.union(v.literal("easy"), v.literal("medium"), v.literal("hard"));
export const armV = v.union(v.literal("left"), v.literal("right"));

const sideStats = v.object({ hits: v.number(), misses: v.number(), reactionSumMs: v.number() });

export default defineSchema({
  ...authTables,

  sessions: defineTable({
    userId: v.id("users"),
    mode: modeV,
    difficulty: difficultyV,
    durationS: v.number(),
    // live: countdown or running (derive which from startsAt). stopped: ended early, not ranked.
    status: v.union(v.literal("live"), v.literal("finished"), v.literal("stopped")),
    simulated: v.boolean(),
    createdAt: v.number(),
    startsAt: v.number(),
    endsAt: v.number(),
    endedAt: v.optional(v.number()),
    hits: v.number(),
    misses: v.number(),
    score: v.number(),
    streak: v.number(),
    bestStreak: v.number(),
    reactionSumMs: v.number(),
    left: sideStats,
    right: sideStats,
    activeArm: v.optional(armV),
    activeSince: v.optional(v.number()),
  })
    .index("by_user", ["userId", "createdAt"])
    .index("by_status", ["status"])
    .index("by_board", ["mode", "difficulty", "simulated", "status", "score"]),

  events: defineTable({
    sessionId: v.id("sessions"),
    kind: v.union(v.literal("hit"), v.literal("miss")),
    arm: armV,
    reactionMs: v.optional(v.number()),
    points: v.number(),
    t: v.number(),
  }).index("by_session", ["sessionId", "t"]),

  // One row per physical robot setup. Only "main" is used today.
  rigs: defineTable({
    name: v.string(),
    lastSeenAt: v.number(),
    estop: v.boolean(),
    // The headset shows linkCode; a signed-in phone enters it to become the headset's player,
    // so rounds started from the headset are saved to that account.
    linkCode: v.optional(v.string()),
    linkCodeAt: v.optional(v.number()),
    playerId: v.optional(v.id("users")),
    playerAt: v.optional(v.number()),
    // The crowd's code for waxonwaxoff.ink/audience: stable for hours, unlike linkCode, which
    // changes whenever a player links.
    audienceCode: v.optional(v.string()),
    audienceCodeAt: v.optional(v.number()),
  }).index("by_name", ["name"]),

  // Emoji the audience sends; the hub relays the last few seconds of them to the headset.
  reactions: defineTable({
    emoji: v.string(),
    client: v.string(),
    at: v.number(),
  })
    .index("by_at", ["at"])
    .index("by_client", ["client", "at"]),
});
