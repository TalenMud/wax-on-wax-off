// waxonwaxoff.ink/audience: anyone with the crowd code shown in the headset can send emoji, which
// float up around the coach (hub.poll relays them). No account needed, so it's rate limited.
import { ConvexError, v } from "convex/values";
import type { Doc } from "./_generated/dataModel";
import { mutation, query, type QueryCtx } from "./_generated/server";
import { AUDIENCE_EMOJIS } from "./game";
import { displayName, linkedPlayer } from "./record";

const MAX_PER_SECOND = 4; // per audience phone

async function rigForCode(ctx: QueryCtx, code: string): Promise<Doc<"rigs"> | null> {
  const rig = await ctx.db.query("rigs").withIndex("by_name", (q) => q.eq("name", "main")).unique();
  const clean = code.toUpperCase().replace(/[^A-Z0-9]/g, "");
  return rig && rig.audienceCode && clean === rig.audienceCode ? rig : null;
}

// What the audience page shows: who's in the ring and how they're doing. null = wrong code.
export const ring = query({
  args: { code: v.string() },
  handler: async (ctx, { code }) => {
    const rig = await rigForCode(ctx, code);
    if (!rig) return null;
    const live = await ctx.db.query("sessions").withIndex("by_status", (q) => q.eq("status", "live")).collect();
    const s = live.find((x) => !x.simulated);
    const playerId = s?.userId ?? linkedPlayer(rig, Date.now());
    return {
      player: playerId ? await displayName(ctx, playerId) : null,
      live: s ? { score: s.score, hits: s.hits, misses: s.misses, streak: s.streak, endsAt: s.endsAt } : null,
    };
  },
});

export const react = mutation({
  args: { code: v.string(), emoji: v.string(), client: v.string() },
  handler: async (ctx, { code, emoji, client }) => {
    if (!(await rigForCode(ctx, code))) {
      throw new ConvexError({ code: "BAD_CODE", message: "That code doesn't match the ring." });
    }
    if (!AUDIENCE_EMOJIS.includes(emoji) || client.length > 64) throw new ConvexError({ code: "BAD_INPUT", message: "Unknown reaction." });
    const now = Date.now();
    const recent = await ctx.db
      .query("reactions")
      .withIndex("by_client", (q) => q.eq("client", client).gt("at", now - 1000))
      .take(MAX_PER_SECOND);
    if (recent.length >= MAX_PER_SECOND) return { ok: false };
    await ctx.db.insert("reactions", { emoji, client, at: now });
    return { ok: true };
  },
});
