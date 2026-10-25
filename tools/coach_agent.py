"""The coach agent: after each round it reads the player's stats from Convex, decides the next
round's drill with Nemotron (running on the GX10), and the headset applies it.

    observe: Convex /hub/coach (this round, per-hand reaction times and misses, history, rank)
    decide:  Nemotron 3.5 30B on the GX10 (llama-server, OpenAI-compatible) returns a JSON plan
    act:     the headset starts the next round at plan.difficulty, brings up more pads on
             plan.focus, and the coach speaks plan.say (ElevenLabs, tools/coach_voice.py)

tools/serve_xr.py serves it as POST /coach/plan -> {plan, source}. The model is reached through an
SSH tunnel to the GX10 (NEMOTRON_URL, default http://127.0.0.1:18346); when it's unreachable or
answers badly, a rule-based plan stands in and source says "rules".
"""

import json
import os
import re
import urllib.request

NEMOTRON_URL = os.environ.get("NEMOTRON_URL", "http://127.0.0.1:18346")
TIMEOUT_S = 12

SYSTEM = """You are the AI coach in a boxing reaction trainer. A player punches pads that light up on their
left or right; you get their stats as JSON. Plan the NEXT round to train their weakest point.

Reply with ONLY a JSON object, no other text:
{"difficulty": "easy" | "medium" | "hard",
 "focus": "left" | "right" | "both",
 "reason": "<one short sentence, the stat that drove the decision>",
 "say": "<one or two sentences spoken to the player: a cheeky, gruff old British boxing coach.
         Mention one real number from the stats. Under 30 words.>"}

Guidelines: focus the hand with more misses or the slower average reaction. Go harder after a
strong round (accuracy above 80% and good reactions), easier after a poor one (accuracy below 50%).
Reaction times are in milliseconds; lower is better."""


def rules_plan(c: dict) -> dict:
    """The stand-in when Nemotron is unavailable: the same guidelines, written out."""
    rd = c.get("round") or {}
    hits, misses = rd.get("hits", 0), rd.get("misses", 0)
    acc = hits / (hits + misses) if hits + misses else None
    lm, rm = rd.get("leftMisses", 0), rd.get("rightMisses", 0)
    la, ra = rd.get("leftAvgMs"), rd.get("rightAvgMs")
    focus = "both"
    if lm != rm:
        focus = "left" if lm > rm else "right"
    elif la and ra and abs(la - ra) > 40:
        focus = "left" if la > ra else "right"
    difficulty = "medium" if acc is None else "hard" if acc > 0.8 else "easy" if acc < 0.5 else "medium"
    side = f"your {focus} hand" if focus != "both" else "both hands"
    return {
        "difficulty": difficulty,
        "focus": focus,
        "reason": f"accuracy {acc:.0%}, misses left {lm} / right {rm}" if acc is not None else "no round stats yet",
        "say": f"Right. Next round we work on {side}. {difficulty.capitalize()} mode. Don't let me down.",
    }


def valid(plan: dict) -> bool:
    return (
        plan.get("difficulty") in ("easy", "medium", "hard")
        and plan.get("focus") in ("left", "right", "both")
        and isinstance(plan.get("say"), str)
        and 0 < len(plan["say"]) < 300
    )


def nemotron_plan(c: dict) -> dict:
    facts = {k: c.get(k) for k in ("player", "round", "history", "rank")}
    body = {
        "messages": [{"role": "system", "content": SYSTEM}, {"role": "user", "content": json.dumps(facts)}],
        "temperature": 0.7,
        "max_tokens": 400,
        "response_format": {"type": "json_object"},
    }
    req = urllib.request.Request(
        NEMOTRON_URL + "/v1/chat/completions",
        data=json.dumps(body).encode(),
        headers={"Content-Type": "application/json"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=TIMEOUT_S) as resp:
        text = json.loads(resp.read())["choices"][0]["message"]["content"]
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S)  # reasoning models may think first
    m = re.search(r"\{.*\}", text, re.S)
    plan = json.loads(m.group(0)) if m else {}
    if not valid(plan):
        raise ValueError(f"unusable plan: {text[:200]!r}")
    return {k: plan[k] for k in ("difficulty", "focus", "reason", "say") if k in plan}


def plan(c: dict) -> dict:
    """{plan, source}: Nemotron's plan, or the rules' when it can't be had."""
    try:
        return {"plan": nemotron_plan(c), "source": "nemotron"}
    except Exception as e:
        print(f"coach agent: nemotron unavailable ({e}); using rules")
        return {"plan": rules_plan(c), "source": "rules"}
