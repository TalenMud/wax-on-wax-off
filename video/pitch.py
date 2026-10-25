"""Wax On Wax Off: the Devpost video, in ManimGL. One scene, one section per narration line.

    python video/make_video.py            # narration audio (ElevenLabs) + render + mux -> video/out/
    manimgl video/pitch.py Pitch -w --color "#121012"   # just the render

Each section's length comes from its narration clip (video/audio/<id>.mp3, measured into
video/audio/durations.json by make_video.py); without audio it falls back to ~2.6 words/s. The
animations in a section take about 75% of its time, then it holds until the voice has finished.
"""

import json
from pathlib import Path

from manimlib import *

HERE = Path(__file__).resolve().parent
NARRATION = json.loads((HERE / "narration.json").read_text())
DUR_FILE = HERE / "audio" / "durations.json"
DURATIONS = json.loads(DUR_FILE.read_text()) if DUR_FILE.exists() else {}

BG = "#121012"
INK = "#f2ead8"
MUTED = "#a39a8c"
RED = "#e8442e"
GOLD = "#e3b341"
BLUE = "#5aa9e6"
ORANGE = "#f08a3c"
GREEN = "#63c587"
FONT = "DejaVu Sans"


def dur(section: str) -> float:
    if section in DURATIONS:
        return DURATIONS[section] + 0.4  # a breath between lines
    words = next(len(s["text"].split()) for s in NARRATION if s["id"] == section)
    return words / 2.6 + 0.4


def label(text, size=28, color=INK, weight=NORMAL):
    return Text(text, font=FONT, font_size=size, color=color, weight=weight)


def box(text, color, w=2.6, h=1.0, size=24):
    r = RoundedRectangle(width=w, height=h, corner_radius=0.18, stroke_color=color, stroke_width=3,
                         fill_color=color, fill_opacity=0.12)
    t = label(text, size)
    t.move_to(r)
    return VGroup(r, t)


def pad(color=RED, r=0.28):
    return Circle(radius=r, stroke_color=WHITE, stroke_width=3, fill_color=color, fill_opacity=0.9)


def robot_arm(base, angles, lengths=(1.1, 0.9), color=GREY_B):
    """A two-link arm from base; returns (VGroup of links and joints, end point)."""
    pts = [np.array(base, dtype=float)]
    a = 0.0
    for ang, ln in zip(angles, lengths):
        a += ang
        pts.append(pts[-1] + ln * np.array([np.cos(a), np.sin(a), 0.0]))
    links = VGroup(*[Line(p, q, stroke_width=14, color=color) for p, q in zip(pts, pts[1:])])
    joints = VGroup(*[Dot(p, radius=0.09, color=WHITE) for p in pts[:-1]])
    plate = Rectangle(width=0.7, height=0.18, fill_color=GREY_D, fill_opacity=1, stroke_width=0).move_to(pts[0] + DOWN * 0.1)
    return VGroup(plate, links, joints), pts[-1]


class Pitch(Scene):
    def section(self, name, build):
        """Clear the last section, run build(t) (animations taking about t seconds), hold until dur(name)."""
        total = dur(name)
        start = self.time
        self.clear_all(0.4)   # the previous section stays up until this one starts
        build(total * 0.75)
        self.wait(max(0.1, total - (self.time - start)))

    def clear_all(self, t=0.5):
        if self.mobjects:
            self.play(*[FadeOut(m) for m in self.mobjects], run_time=t)

    def construct(self):
        for name in ["hook", "what", "system", "align", "learning", "reflex", "safety", "coach", "close"]:
            self.section(name, getattr(self, f"s_{name}"))

    # ---------------------------------------------------------------- sections
    def s_hook(self, t):
        line = label("Boxing needs a partner.", 52, weight=BOLD)
        self.play(Write(line), run_time=t * 0.25)
        needs = VGroup(*[label(s, 30, MUTED) for s in ["hold the pads", "call the combos", "push you when you fade"]])
        needs.arrange(DOWN, buff=0.35).next_to(line, DOWN, buff=0.7)
        self.play(LaggedStartMap(FadeIn, needs, shift=UP * 0.2, lag_ratio=0.5), run_time=t * 0.3)
        self.play(FadeOut(needs), line.animate.shift(UP * 1.2), run_time=t * 0.15)
        built = label("So we built one.", 44, RED, weight=BOLD).next_to(line, DOWN, buff=0.9)
        self.play(FadeIn(built, scale=1.3), run_time=t * 0.2)

    def s_what(self, t):
        title = label("WAX ON WAX OFF", 56, weight=BOLD).to_edge(UP)
        left, lp = robot_arm([-1.6, -2.2, 0], [1.2, -1.0])
        right, rp = robot_arm([1.6, -2.2, 0], [1.94, 1.0])
        lpad, rpad = pad().move_to(lp), pad().move_to(rp)
        self.play(FadeIn(title), run_time=t * 0.12)
        self.play(ShowCreation(left), ShowCreation(right), run_time=t * 0.2)
        self.play(GrowFromCenter(lpad), GrowFromCenter(rpad), run_time=t * 0.1)
        coach = VGroup(Circle(radius=0.45, color=BLUE, fill_opacity=0.25).shift(UP * 1.1),
                       RoundedRectangle(width=1.4, height=1.6, corner_radius=0.3, color=BLUE, fill_opacity=0.2).shift(DOWN * 0.3))
        coach.set_stroke(BLUE, 3).set_opacity(0.6)
        coach.scale(0.8).shift(UP * 0.9)   # stands behind the arms, not in them
        coach_l = label("virtual coach, lined up with the arms", 22, BLUE).next_to(coach, UP, buff=0.2)
        self.play(FadeIn(coach), FadeIn(coach_l), run_time=t * 0.18)
        headset = VGroup(RoundedRectangle(width=1.6, height=0.8, corner_radius=0.25, color=INK, fill_color=GREY_E, fill_opacity=1),
                         label("Quest", 22)).to_corner(DL, buff=0.8)
        gloves = VGroup(Circle(radius=0.22, color=BLUE, fill_opacity=0.9), Circle(radius=0.22, color=RED, fill_opacity=0.9)).arrange(RIGHT, buff=0.3)
        gloves.next_to(headset, UP, buff=0.3)
        self.play(FadeIn(headset), FadeIn(gloves), run_time=t * 0.12)
        self.play(gloves[1].animate.move_to(rpad), run_time=t * 0.12)
        self.play(Flash(rpad.get_center(), color=GOLD, line_length=0.3), run_time=t * 0.08)

    def s_system(self, t):
        quest = box("Quest\nhands + game", BLUE).move_to(LEFT * 5 + UP * 1.2)
        laptop = box("Laptop server", INK).move_to(LEFT * 1.2 + UP * 1.2)
        gx10 = box("ASUS GX10", GREEN).move_to(RIGHT * 2.8 + UP * 1.2)
        arms = box("2 robot arms", GREY_B).move_to(RIGHT * 2.8 + DOWN * 1.6)
        convex = box("Convex", GOLD).move_to(LEFT * 1.2 + DOWN * 1.6)
        phone = box("Phone\nstats + leaderboard", ORANGE, w=3.0).move_to(LEFT * 5 + DOWN * 1.6)
        boxes = [quest, laptop, gx10, arms, convex, phone]
        self.play(LaggedStartMap(FadeIn, VGroup(*boxes), lag_ratio=0.25), run_time=t * 0.35)
        links = [(quest, laptop, ""), (laptop, gx10, "cable"), (gx10, arms, "CAN bus"), (laptop, convex, ""), (convex, phone, "")]
        arrows = VGroup()
        for a, b, txt in links:
            ar = Arrow(a.get_center(), b.get_center(), buff=0.75, stroke_width=4, color=MUTED)
            arrows.add(ar)
            if txt:
                arrows.add(label(txt, 18, MUTED).next_to(ar, UP if a.get_y() == b.get_y() else RIGHT, buff=0.08))
        self.play(LaggedStartMap(GrowArrow, VGroup(*[a for a in arrows if isinstance(a, Arrow)]), lag_ratio=0.2),
                  FadeIn(VGroup(*[a for a in arrows if not isinstance(a, Arrow)])), run_time=t * 0.3)
        dot = Dot(color=GOLD, radius=0.12).move_to(quest)
        self.play(dot.animate.move_to(laptop), run_time=t * 0.08)
        self.play(dot.animate.move_to(convex), run_time=t * 0.08)
        self.play(dot.animate.move_to(phone), run_time=t * 0.08)

    def s_align(self, t):
        title = label("Two touches line up virtual and real", 36, weight=BOLD).to_edge(UP)
        lp, rp = pad().move_to(LEFT * 2.2), pad().move_to(RIGHT * 2.2)
        ghost_l = pad(BLUE).set_opacity(0.4).move_to(LEFT * 1.4 + UP * 1.0)
        ghost_r = pad(BLUE).set_opacity(0.4).move_to(RIGHT * 3.0 + UP * 0.6)
        self.play(FadeIn(title), FadeIn(lp), FadeIn(rp), FadeIn(ghost_l), FadeIn(ghost_r), run_time=t * 0.15)
        stream = label("GX10 → pad positions from joint angles · 30 Hz", 24, GREEN).to_edge(DOWN, buff=1.2)
        self.play(Write(stream), run_time=t * 0.2)
        gl = Circle(radius=0.2, color=BLUE, fill_opacity=0.9).move_to(LEFT * 5 + DOWN * 2)
        gr = Circle(radius=0.2, color=RED, fill_opacity=0.9).move_to(RIGHT * 5 + DOWN * 2)
        self.play(FadeIn(gl), FadeIn(gr), run_time=t * 0.08)
        self.play(gl.animate.move_to(lp), run_time=t * 0.12)
        self.play(gr.animate.move_to(rp), run_time=t * 0.12)
        self.play(ghost_l.animate.move_to(lp), ghost_r.animate.move_to(rp), run_time=t * 0.15)
        out = label("→ position · heading · spacing", 28, GOLD).next_to(stream, DOWN, buff=0.3)
        self.play(FadeIn(out), run_time=t * 0.1)

    def s_learning(self, t):
        title = label("Teaching the arms to dodge", 38, weight=BOLD).to_edge(UP)
        steps = VGroup(*[box(s, c, w=2.7, h=0.8, size=20) for s, c in
                         [("28 demonstrations", INK), ("ACT policy on GX10", GREEN), ("shadow + replay tests", GOLD)]])
        steps.arrange(RIGHT, buff=0.4).next_to(title, DOWN, buff=0.5)
        self.play(FadeIn(title), LaggedStartMap(FadeIn, steps, lag_ratio=0.3), run_time=t * 0.25)
        axis = Line(LEFT * 3 + DOWN * 2.6, RIGHT * 3 + DOWN * 2.6, color=MUTED)
        human = Rectangle(width=1.4, height=3.6 * 0.6, fill_color=INK, fill_opacity=0.85, stroke_width=0)
        model = Rectangle(width=1.4, height=1.0 * 0.6, fill_color=RED, fill_opacity=0.9, stroke_width=0)
        human.next_to(axis, UP, buff=0).shift(LEFT * 1.3)
        model.next_to(axis, UP, buff=0).shift(RIGHT * 1.3)
        hl = label("human dodge\n36°", 22).next_to(human, UP, buff=0.15)
        ml = label("policy\n10°", 22, RED).next_to(model, UP, buff=0.15)
        self.play(ShowCreation(axis), GrowFromEdge(human, DOWN), GrowFromEdge(model, DOWN), run_time=t * 0.25)
        self.play(FadeIn(hl), FadeIn(ml), run_time=t * 0.1)
        why = VGroup(label("one frame can't show a punch coming", 22, MUTED),
                     label("random directions average to a wobble", 22, MUTED)).arrange(DOWN, buff=0.15).to_edge(RIGHT, buff=0.5).shift(DOWN * 1.2)
        self.play(LaggedStartMap(FadeIn, why, lag_ratio=0.5), run_time=t * 0.25)

    def s_reflex(self, t):
        title = label("Perception decides when. Taught poses decide how.", 32, weight=BOLD).to_edge(UP)
        self.play(FadeIn(title), run_time=t * 0.12)
        guard, gp = robot_arm([1.5, -2.4, 0], [1.6, -0.9], color=GREY_B)
        p = pad().move_to(gp)
        self.play(FadeIn(guard), FadeIn(p), run_time=t * 0.1)
        fist = Circle(radius=0.22, color=RED, fill_opacity=0.95).move_to(LEFT * 5 + gp[1] * UP)
        fist.set_y(gp[1])
        trail = label("headset: fist closing fast", 22, BLUE).next_to(fist, UP, buff=0.3)
        self.play(FadeIn(fist), FadeIn(trail), run_time=t * 0.08)
        self.play(fist.animate.shift(RIGHT * 3.2), run_time=t * 0.18)
        dodge, dp = robot_arm([1.5, -2.4, 0], [2.4, -1.6], color=GREY_B)
        self.play(Transform(guard, dodge), p.animate.move_to(dp), fist.animate.shift(RIGHT * 1.2), run_time=t * 0.12)
        tag = label("taught dodge pose · hold · return", 24, GOLD).to_edge(DOWN, buff=0.8)
        self.play(FadeIn(tag), run_time=t * 0.1)
        back, bp = robot_arm([1.5, -2.4, 0], [1.6, -0.9], color=GREY_B)
        self.play(Transform(guard, back), p.animate.move_to(bp), FadeOut(fist), run_time=t * 0.15)

    def s_safety(self, t):
        title = label("Safety first", 44, weight=BOLD).to_edge(UP)
        items = ["every pose taught by a person", "kept above the table and off its own base",
                 "speed capped", "torque off: lost heartbeat, stall, or Ctrl+C"]
        rows = VGroup()
        for s in items:
            tick = label("✓", 30, GREEN)
            rows.add(VGroup(tick, label(s, 28)).arrange(RIGHT, buff=0.3))
        rows.arrange(DOWN, aligned_edge=LEFT, buff=0.45).next_to(title, DOWN, buff=0.7)
        self.play(FadeIn(title), run_time=t * 0.12)
        self.play(LaggedStartMap(FadeIn, rows, shift=RIGHT * 0.3, lag_ratio=0.6), run_time=t * 0.7)

    def s_coach(self, t):
        title = label("A coach agent that plans your next round", 36, weight=BOLD).to_edge(UP)
        steps = [("observe\nConvex stats", GOLD), ("decide\nNemotron on GX10", GREEN), ("act\nnext round", RED), ("speak\nElevenLabs", BLUE)]
        nodes = VGroup(*[box(s, c, w=2.6, h=1.1, size=20) for s, c in steps])
        for i, n in enumerate(nodes):
            n.move_to(2.2 * np.array([np.cos(PI / 2 - i * PI / 2), np.sin(PI / 2 - i * PI / 2) * 0.75, 0]) + DOWN * 0.4)
        self.play(FadeIn(title), run_time=t * 0.1)
        self.play(LaggedStartMap(FadeIn, nodes, lag_ratio=0.4), run_time=t * 0.3)
        arrows = VGroup(*[CurvedArrow(nodes[i].get_center(), nodes[(i + 1) % 4].get_center(), angle=-PI / 3, color=MUTED, stroke_width=3)
                          for i in range(4)])
        for a in arrows:
            a.scale(0.55)
        self.play(LaggedStartMap(ShowCreation, arrows, lag_ratio=0.3), run_time=t * 0.2)
        emojis = VGroup(*[label(e, 34) for e in ["clap", "fire", "clown", "lol"]])
        for i, e in enumerate(emojis):
            e.move_to(RIGHT * (5.2 + (i % 2) * 0.6) + DOWN * (2.4 - i * 0.2)).set_color([GOLD, RED, ORANGE, BLUE][i])
        crowd = label("live crowd reactions", 22, MUTED).next_to(emojis, UP, buff=0.3)
        self.play(FadeIn(crowd), LaggedStartMap(lambda m: FadeIn(m, shift=UP), emojis, lag_ratio=0.3), run_time=t * 0.2)
        self.play(*[e.animate.shift(UP * 1.5).set_opacity(0) for e in emojis], run_time=t * 0.1)

    def s_close(self, t):
        tiles = VGroup(*[box(s, c, w=3.0, h=1.3, size=24) for s, c in
                         [("reaction time\nper hand", BLUE), ("accuracy", GREEN), ("streaks", GOLD)]]).arrange(RIGHT, buff=0.4).shift(UP * 1.5)
        self.play(LaggedStartMap(FadeIn, tiles, lag_ratio=0.3), run_time=t * 0.25)
        web = label("in the browser · no app store", 28, MUTED).next_to(tiles, DOWN, buff=0.5)
        self.play(FadeIn(web), run_time=t * 0.12)
        mark = VGroup(label("WAX ON", 64, INK, weight=BOLD), label("WAX OFF", 64, RED, weight=BOLD)).arrange(RIGHT, buff=0.4)
        mark.next_to(web, DOWN, buff=0.7)
        self.play(FadeIn(mark, scale=1.2), run_time=t * 0.2)
        cta = label("Come and get punched at.", 32, GOLD).next_to(mark, DOWN, buff=0.45)
        self.play(Write(cta), run_time=t * 0.2)
