// What the trash-talking coach knows about the player, for the hub's /coach/say (tools/serve_xr.py):
// this round so far, their history and leaderboard rank, and what the audience is sending.
import type { Doc } from "./_generated/dataModel";
import { internalQuery } from "./_generated/server";
import { displayName, linkedPlayer } from "./record";

const CROWD_WINDOW_MS = 30_000;

const avg = (sumMs: number, n: number) => (n ? Math.round(sumMs / n) : null);

export const context = internalQuery({
  args: {},
  handler: async (ctx) => {
    const now = Date.now();
    const rig = await ctx.db.query("rigs").withIndex("by_name", (q) => q.eq("name", "main")).unique();
    const live = await ctx.db.query("sessions").withIndex("by_status", (q) => q.eq("status", "live")).collect();
    const s = live.find((x) => !x.simulated);
    const userId = s?.userId ?? (rig ? linkedPlayer(rig, now) : null);

    let history = null;
    let rank = null;
    if (userId) {
      const past = (await ctx.db.query("sessions").withIndex("by_user", (q) => q.eq("userId", userId)).order("desc").take(50))
        .filter((x: Doc<"sessions">) => x.status === "finished" && !x.simulated);
      const hits = past.reduce((a, x) => a + x.hits, 0);
      history = {
        rounds: past.length,
        bestScore: past.reduce((a, x) => Math.max(a, x.score), 0),
        avgReactionMs: avg(past.reduce((a, x) => a + x.reactionSumMs, 0), hits),
        accuracy: hits + past.reduce((a, x) => a + x.misses, 0) ? hits / (hits + past.reduce((a, x) => a + x.misses, 0)) : null,
      };
      if (s || past.length) {
        const mode = s?.mode ?? past[0].mode;
        const difficulty = s?.difficulty ?? past[0].difficulty;
        const board = await ctx.db
          .query("sessions")
          .withIndex("by_board", (q) => q.eq("mode", mode).eq("difficulty", difficulty).eq("simulated", false).eq("status", "finished"))
          .order("desc")
          .take(200);
        const order: string[] = [];
        for (const x of board) if (!order.includes(x.userId)) order.push(x.userId);
        const i = order.indexOf(userId);
        rank = { position: i >= 0 ? i + 1 : null, of: order.length };
      }
    }

    const crowd: Record<string, number> = {};
    for (const r of await ctx.db.query("reactions").withIndex("by_at", (q) => q.gt("at", now - CROWD_WINDOW_MS)).collect()) {
      crowd[r.emoji] = (crowd[r.emoji] ?? 0) + 1;
    }

    return {
      player: userId ? await displayName(ctx, userId) : null,
      round: s
        ? {
            score: s.score,
            hits: s.hits,
            misses: s.misses,
            streak: s.streak,
            bestStreak: s.bestStreak,
            leftAvgMs: avg(s.left.reactionSumMs, s.left.hits),
            rightAvgMs: avg(s.right.reactionSumMs, s.right.hits),
            leftMisses: s.left.misses,
            rightMisses: s.right.misses,
            secondsLeft: Math.max(0, Math.round((s.endsAt - now) / 1000)),
          }
        : null,
      history,
      rank,
      crowd,
    };
  },
});
