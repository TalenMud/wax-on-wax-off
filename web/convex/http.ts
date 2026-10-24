import { httpRouter } from "convex/server";
import { internal } from "./_generated/api";
import type { Id } from "./_generated/dataModel";
import { httpAction } from "./_generated/server";
import { auth } from "./auth";

const http = httpRouter();
auth.addHttpRoutes(http);

function authorized(req: Request): Response | null {
  const secret = process.env.HUB_SECRET;
  if (!secret) return new Response("HUB_SECRET is not set on this deployment", { status: 500 });
  if (req.headers.get("Authorization") !== `Bearer ${secret}`) return new Response("Unauthorized", { status: 401 });
  return null;
}

http.route({
  path: "/hub/poll",
  method: "GET",
  handler: httpAction(async (ctx, req) => {
    const denied = authorized(req);
    if (denied) return denied;
    return Response.json(await ctx.runMutation(internal.hub.poll, {}));
  }),
});

http.route({
  path: "/hub/event",
  method: "POST",
  handler: httpAction(async (ctx, req) => {
    const denied = authorized(req);
    if (denied) return denied;
    const body = await req.json();
    const kind = body.kind;
    const arm = body.arm;
    if (!["present", "hit", "miss"].includes(kind) || !["left", "right"].includes(arm)) {
      return new Response("kind must be present|hit|miss and arm must be left|right", { status: 400 });
    }
    const result = await ctx.runMutation(internal.hub.event, {
      sessionId: body.sessionId as Id<"sessions">,
      kind,
      arm,
      reactionMs: typeof body.reactionMs === "number" ? body.reactionMs : undefined,
    });
    return Response.json(result);
  }),
});

export default http;
