"""Wax On Wax Off: the Devpost video, in ManimGL. One scene, one section per narration line.

    python3 video/make_video.py --voice <id>               # narration (ElevenLabs) + render + mux
    manimgl video/pitch.py Pitch -w --color "#121012"      # just the render

Styled like waxonwaxoff.ink: Anton display type (cream WAX ON, red WAX OFF), Inter body, dark
background, red target rings. Each section's length comes from its narration clip
(video/audio/durations.json, written by make_video.py); without audio it falls back to ~2.6 words/s.
A section's animations take about 75% of its time, then it holds until the voice has finished.
"""

import json
from pathlib import Path

from manimlib import *

HERE = Path(__file__).resolve().parent
NARRATION = json.loads((HERE / "narration.json").read_text())
DUR_FILE = HERE / "audio" / "durations.json"
DURATIONS = json.loads(DUR_FILE.read_text()) if DUR_FILE.exists() else {}
GAP_S = 0.8  # pause after each line; make_video.py pads the audio by the same

# waxonwaxoff.ink (web/src/styles.css)
BG = "#121012"
SURFACE = "#1c191b"
SURFACE_2 = "#272326"
LINE_C = "#3a3436"
INK = "#f2ead8"
MUTED = "#a39a8c"
RED = "#e8442e"
GOLD = "#e3b341"
GREEN = "#63c587"
BLUE = "#5aa9e6"
ORANGE = "#f08a3c"
METAL = "#d9d2c5"
METAL_DARK = "#3a3537"
DISPLAY = "Anton"
BODY = "Inter"


def dur(section: str) -> float:
    if section in DURATIONS:
        return DURATIONS[section] + GAP_S
    words = next(len(s["text"].split()) for s in NARRATION if s["id"] == section)
    return words / 2.6 + GAP_S


def display(text, size=72, color=INK):
    return Text(text, font=DISPLAY, font_size=size).set_color(color)   # Anton ignores color=; set it after


def body(text, size=28, color=INK):
    return Text(text, font=BODY, font_size=size).set_color(color)


def wordmark(size=96):
    return VGroup(display("WAX ON", size, INK), display("WAX OFF", size, RED)).arrange(DOWN, aligned_edge=LEFT, buff=0.05)


def rings(n=5, r=0.45, color=RED):
    """The site's target rings."""
    return VGroup(*[Circle(radius=r * (i + 1), stroke_color=color, stroke_width=2, stroke_opacity=0.35 - 0.05 * i) for i in range(n)])


def card(text, accent=LINE_C, w=2.8, h=1.0, size=22):
    r = RoundedRectangle(width=w, height=h, corner_radius=0.16, fill_color=SURFACE, fill_opacity=1,
                         stroke_color=accent, stroke_width=2.5)
    t = body(text, size)
    t.move_to(r)
    return VGroup(r, t)


def target_pad(r=0.3, color=RED):
    return VGroup(Circle(radius=r, fill_color=color, fill_opacity=1, stroke_color=INK, stroke_width=3),
                  Circle(radius=r * 0.55, stroke_color=INK, stroke_width=2, stroke_opacity=0.7),
                  Dot(radius=r * 0.12, color=INK))


def link(p, q, h):
    v = q - p
    seg = RoundedRectangle(width=max(np.linalg.norm(v), h), height=h, corner_radius=h / 2,
                           fill_color=METAL, fill_opacity=1, stroke_color="#8c857a", stroke_width=2)
    seg.rotate(np.arctan2(v[1], v[0]))
    seg.move_to((p + q) / 2)
    return seg


def joint(p, r=0.17):
    return VGroup(Circle(radius=r, fill_color=METAL_DARK, fill_opacity=1, stroke_color=INK, stroke_width=2).move_to(p),
                  Dot(p, radius=r * 0.35, color=RED))


def robot_arm(base, a1, a2, a3=0.0, scale=1.0, pad_color=RED):
    """A cartoon of our arms: base, turret, upper arm, forearm, wrist and a claw holding a round pad.
    Angles in radians: a1 from horizontal at the shoulder, a2 and a3 relative to the previous link.
    The same structure for any angles, so Transform between two calls animates a move."""
    s = scale
    b = np.array([base[0], base[1], 0.0])
    plate = RoundedRectangle(width=1.1 * s, height=0.22 * s, corner_radius=0.06, fill_color=METAL_DARK, fill_opacity=1,
                             stroke_width=0).move_to(b + UP * 0.11 * s)
    stripe = Rectangle(width=1.1 * s, height=0.05 * s, fill_color=RED, fill_opacity=1, stroke_width=0).move_to(b + UP * 0.2 * s)
    turret = RoundedRectangle(width=0.5 * s, height=0.45 * s, corner_radius=0.1, fill_color=METAL, fill_opacity=1,
                              stroke_color="#8c857a", stroke_width=2).move_to(b + UP * 0.45 * s)
    shoulder = b + UP * 0.7 * s
    elbow = shoulder + 1.15 * s * np.array([np.cos(a1), np.sin(a1), 0])
    wrist = elbow + 0.95 * s * np.array([np.cos(a1 + a2), np.sin(a1 + a2), 0])
    d = np.array([np.cos(a1 + a2 + a3), np.sin(a1 + a2 + a3), 0])
    n = np.array([-d[1], d[0], 0])
    claw_base = wrist + d * 0.22 * s
    pad_c = wrist + d * 0.55 * s
    fingers = VGroup(*[link(claw_base + n * k * 0.2 * s, pad_c + n * k * 0.24 * s + d * 0.05 * s, 0.07 * s) for k in (-1, 1)])
    return VGroup(plate, stripe, turret,
                  link(shoulder, elbow, 0.3 * s), link(elbow, wrist, 0.24 * s), link(wrist, claw_base, 0.2 * s),
                  joint(shoulder, 0.19 * s), joint(elbow, 0.16 * s), joint(wrist, 0.13 * s),
                  target_pad(0.27 * s, pad_color).move_to(pad_c), fingers)


def pad_of(arm):
    return arm[9]


class Pitch(Scene):
    def setup(self):
        super().setup()
        self.keep = []  # stays up across sections (background rings)

    def section(self, name, build):
        """Clear the last section, run build(t) (animations taking about t seconds), hold until dur(name)."""
        total = dur(name)
        start = self.time
        gone = [m for m in self.mobjects if m not in self.keep]
        if gone:
            self.play(*[FadeOut(m) for m in gone], run_time=0.4)
        build(total * 0.75)
        self.wait(max(0.1, total - (self.time - start)))

    def construct(self):
        bg = rings(6, 0.5).move_to(RIGHT * 5.2 + UP * 2.4)
        self.add(bg)
        self.keep.append(bg)
        for name in ["hook", "what", "system", "align", "learning", "reflex", "safety", "coach", "close"]:
            self.section(name, getattr(self, f"s_{name}"))

    # ---------------------------------------------------------------- sections
    def s_hook(self, t):
        line = display("BOXING NEEDS A PARTNER.", 80).shift(UP * 2.2)
        self.play(FadeIn(line, shift=UP * 0.3), run_time=t * 0.15)
        needs = VGroup(*[body(s, 32, MUTED) for s in ["someone to hold the pads", "call the combos", "push you when you fade"]])
        needs.arrange(DOWN, buff=0.3).next_to(line, DOWN, buff=0.5)
        self.play(LaggedStartMap(FadeIn, needs, shift=UP * 0.2, lag_ratio=0.5), run_time=t * 0.3)
        built = display("SO WE BUILT ONE.", 72, RED).move_to(needs)
        left = robot_arm([-3.0, -3.9], 1.1, -0.9, 0.0).shift(DOWN * 3)
        right = robot_arm([3.0, -3.9], PI - 1.1, 0.9, 0.0).shift(DOWN * 3)
        self.play(FadeOut(needs), FadeIn(built, scale=1.2), run_time=t * 0.2)
        self.play(left.animate.shift(UP * 3), right.animate.shift(UP * 3), run_time=t * 0.3)

    def s_what(self, t):
        mark = wordmark(84).to_corner(UL, buff=0.6)
        tag = body("Reaction sparring against two robot arms.", 28, MUTED).next_to(mark, DOWN, aligned_edge=LEFT, buff=0.3)
        self.play(FadeIn(mark, shift=RIGHT * 0.3), FadeIn(tag), run_time=t * 0.15)
        coach = VGroup(Circle(radius=0.38, fill_color=BLUE, fill_opacity=0.25, stroke_color=BLUE, stroke_width=3).shift(UP * 1.05),
                       RoundedRectangle(width=1.3, height=1.5, corner_radius=0.35, fill_color=BLUE, fill_opacity=0.18,
                                        stroke_color=BLUE, stroke_width=3).shift(DOWN * 0.15)).shift(RIGHT * 2.3 + UP * 0.4)
        coach_l = body("virtual coach, behind the real arms", 20, BLUE).next_to(coach, UP, buff=0.15)
        left = robot_arm([0.1, -3.4], 1.25, -1.15, 0.2, scale=0.9)
        right = robot_arm([4.5, -3.4], PI - 1.25, 1.15, -0.2, scale=0.9)
        self.play(FadeIn(coach), FadeIn(coach_l), run_time=t * 0.15)
        self.play(FadeIn(left, shift=UP * 0.3), FadeIn(right, shift=UP * 0.3), run_time=t * 0.15)
        quest = VGroup(RoundedRectangle(width=1.7, height=0.75, corner_radius=0.3, fill_color=SURFACE_2, fill_opacity=1,
                                        stroke_color=INK, stroke_width=2), body("Quest", 22)).move_to(LEFT * 4.6 + DOWN * 1.3)
        glove = Circle(radius=0.24, fill_color=RED, fill_opacity=1, stroke_color=INK, stroke_width=2).next_to(quest, UP, buff=0.25)
        self.play(FadeIn(quest), FadeIn(glove), run_time=t * 0.1)
        self.play(glove.animate.move_to(pad_of(left).get_center() + LEFT * 0.25), run_time=t * 0.12)
        self.play(Flash(pad_of(left).get_center(), color=GOLD, line_length=0.3), pad_of(left).animate.shift(RIGHT * 0.12),
                  run_time=t * 0.08)

    def s_system(self, t):
        title = display("UNDER THE HOOD", 56).to_corner(UL, buff=0.6)
        quest = card("Quest\nhands + game", BLUE).move_to(LEFT * 4.6 + UP * 0.9)
        laptop = card("Laptop server", INK).move_to(LEFT * 0.9 + UP * 0.9)
        gx10 = card("ASUS GX10", GREEN).move_to(RIGHT * 2.9 + UP * 0.9)
        convex = card("Convex", GOLD).move_to(LEFT * 0.9 + DOWN * 1.8)
        phone = card("Phone\nstats + leaderboard", ORANGE, w=3.1).move_to(LEFT * 4.6 + DOWN * 1.8)
        arm = robot_arm([2.9, -3.3], 1.2, -1.0, 0.2, scale=0.7)
        nodes = [quest, laptop, gx10, convex, phone]
        self.play(FadeIn(title), LaggedStartMap(FadeIn, VGroup(*nodes), lag_ratio=0.25), FadeIn(arm), run_time=t * 0.3)
        pairs = [(quest, laptop, None), (laptop, gx10, "cable"), (laptop, convex, None), (convex, phone, None)]
        arrows, notes = VGroup(), VGroup()
        for a, b, txt in pairs:
            ar = Arrow(a.get_center(), b.get_center(), buff=0.85, stroke_width=4, color=MUTED)
            arrows.add(ar)
            if txt:
                notes.add(body(txt, 18, MUTED).next_to(ar, UP, buff=0.05))
        can = Arrow(gx10.get_bottom(), arm[2].get_top() + UP * 0.05, buff=0.1, stroke_width=4, color=MUTED)
        notes.add(body("CAN bus", 18, MUTED).next_to(can, RIGHT, buff=0.1))
        arrows.add(can)
        self.play(LaggedStartMap(GrowArrow, arrows, lag_ratio=0.2), FadeIn(notes), run_time=t * 0.3)
        dot = Dot(color=RED, radius=0.12).move_to(quest)
        for target in (laptop, convex, phone):
            self.play(dot.animate.move_to(target), run_time=t * 0.08)

    def s_align(self, t):
        title = display("LINING UP VIRTUAL AND REAL", 56).to_corner(UL, buff=0.6)
        left = robot_arm([-2.6, -3.5], 1.15, -0.95, 0.1, scale=0.85)
        right = robot_arm([2.6, -3.5], PI - 1.15, 0.95, -0.1, scale=0.85)
        self.play(FadeIn(title), FadeIn(left), FadeIn(right), run_time=t * 0.15)
        ghosts = VGroup(target_pad(0.27, BLUE).set_opacity(0.45).move_to(pad_of(left).get_center() + UP * 1.1 + RIGHT * 0.8),
                        target_pad(0.27, BLUE).set_opacity(0.45).move_to(pad_of(right).get_center() + UP * 0.7 + RIGHT * 0.9))
        stream = body("GX10 streams both pad positions from the joint angles, 30 times a second", 24, GREEN).to_edge(DOWN, buff=0.4)
        self.play(FadeIn(ghosts), Write(stream), run_time=t * 0.2)
        gl = Circle(radius=0.22, fill_color=BLUE, fill_opacity=1, stroke_color=INK, stroke_width=2).move_to(LEFT * 6 + UP * 0.5)
        gr = Circle(radius=0.22, fill_color=RED, fill_opacity=1, stroke_color=INK, stroke_width=2).move_to(RIGHT * 6 + UP * 0.5)
        self.play(FadeIn(gl), FadeIn(gr), run_time=t * 0.08)
        self.play(gl.animate.move_to(pad_of(left)), run_time=t * 0.12)
        self.play(gr.animate.move_to(pad_of(right)), run_time=t * 0.12)
        self.play(ghosts[0].animate.move_to(pad_of(left)), ghosts[1].animate.move_to(pad_of(right)), run_time=t * 0.13)
        out = body("two touches → position · heading · spacing", 28, GOLD).next_to(title, DOWN, aligned_edge=LEFT, buff=0.3)
        self.play(FadeIn(out), run_time=t * 0.1)

    def s_learning(self, t):
        title = display("TEACHING THE ARMS TO DODGE", 56).to_corner(UL, buff=0.6)
        steps = VGroup(*[card(s, c, w=3.0, h=0.8, size=20) for s, c in
                         [("28 demonstrations", INK), ("ACT policy on the GX10", GREEN), ("shadow + replay tests", GOLD)]])
        steps.arrange(RIGHT, buff=0.35).next_to(title, DOWN, aligned_edge=LEFT, buff=0.45)
        self.play(FadeIn(title), LaggedStartMap(FadeIn, steps, lag_ratio=0.3), run_time=t * 0.25)
        axis = Line(LEFT * 5.6 + DOWN * 2.9, LEFT * 1.0 + DOWN * 2.9, color=MUTED)
        human = Rectangle(width=1.3, height=2.6, fill_color=INK, fill_opacity=0.9, stroke_width=0)
        model = Rectangle(width=1.3, height=2.6 * 10 / 36, fill_color=RED, fill_opacity=1, stroke_width=0)
        human.next_to(axis, UP, buff=0).shift(LEFT * 1.0)
        model.next_to(axis, UP, buff=0).shift(RIGHT * 1.0)
        hl = VGroup(display("36°", 44), body("human dodge", 20, MUTED)).arrange(DOWN, buff=0.05).next_to(human, UP, buff=0.12)
        ml = VGroup(display("10°", 44, RED), body("learned policy", 20, MUTED)).arrange(DOWN, buff=0.05).next_to(model, UP, buff=0.12)
        self.play(ShowCreation(axis), GrowFromEdge(human, DOWN), GrowFromEdge(model, DOWN), run_time=t * 0.2)
        self.play(FadeIn(hl), FadeIn(ml), run_time=t * 0.1)
        arm = robot_arm([3.6, -3.5], 1.25, -1.0, 0.1, scale=0.8)
        self.play(FadeIn(arm), run_time=t * 0.06)
        wobble = [robot_arm([3.6, -3.5], 1.25 + d, -1.0 - d, 0.1, scale=0.8) for d in (0.06, -0.05, 0.04, 0.0)]
        why = VGroup(body("one camera frame can't show a punch coming", 22, MUTED),
                     body("random dodge directions average to a wobble", 22, MUTED)).arrange(DOWN, aligned_edge=LEFT, buff=0.15)
        why.next_to(arm, UP, buff=0.4).shift(LEFT * 0.4)
        self.play(FadeIn(why), run_time=t * 0.1)
        for w in wobble:
            self.play(Transform(arm, w), run_time=t * 0.04)

    def s_reflex(self, t):
        title = display("PERCEPTION DECIDES WHEN.", 52).to_corner(UL, buff=0.6)
        sub = display("TAUGHT POSES DECIDE HOW.", 52, RED).next_to(title, DOWN, aligned_edge=LEFT, buff=0.1)
        self.play(FadeIn(title), FadeIn(sub), run_time=t * 0.12)
        arm = robot_arm([2.6, -3.5], PI - 1.15, 0.95, -0.1)
        self.play(FadeIn(arm), run_time=t * 0.08)
        fist = Circle(radius=0.26, fill_color=RED, fill_opacity=1, stroke_color=INK, stroke_width=2).move_to(LEFT * 5.5)
        fist.set_y(pad_of(arm).get_y())
        note = body("headset: fist closing fast", 22, BLUE).next_to(fist, UP, buff=0.25)
        self.play(FadeIn(fist), FadeIn(note), run_time=t * 0.08)
        self.play(fist.animate.shift(RIGHT * 4.6), note.animate.shift(RIGHT * 4.6), run_time=t * 0.16)
        dodge = robot_arm([2.6, -3.5], PI - 0.75, 1.55, 0.3)
        self.play(Transform(arm, dodge), fist.animate.shift(RIGHT * 1.6), run_time=t * 0.1)
        tag = body("taught dodge pose  ·  hold  ·  return", 26, GOLD).to_edge(DOWN, buff=0.5)
        self.play(FadeIn(tag), run_time=t * 0.1)
        self.wait(t * 0.08)
        back = robot_arm([2.6, -3.5], PI - 1.15, 0.95, -0.1)
        self.play(Transform(arm, back), FadeOut(fist), FadeOut(note), run_time=t * 0.14)

    def s_safety(self, t):
        title = display("SAFETY FIRST", 64).to_corner(UL, buff=0.6)
        items = ["every pose is taught by a person", "kept above the table and off its own base",
                 "speed capped", "torque off: lost heartbeat, stall or Ctrl+C"]
        rows = VGroup()
        for s in items:
            rows.add(VGroup(Circle(radius=0.16, fill_color=GREEN, fill_opacity=1, stroke_width=0), body(s, 30)).arrange(RIGHT, buff=0.35))
        rows.arrange(DOWN, aligned_edge=LEFT, buff=0.5).next_to(title, DOWN, aligned_edge=LEFT, buff=0.7)
        arm = robot_arm([4.3, -3.5], PI - 1.2, 1.0, 0.0, scale=0.85)
        self.play(FadeIn(title), FadeIn(arm), run_time=t * 0.12)
        self.play(LaggedStartMap(FadeIn, rows, shift=RIGHT * 0.3, lag_ratio=0.6), run_time=t * 0.7)

    def s_coach(self, t):
        title = display("A COACH AGENT", 64).to_corner(UL, buff=0.6)
        sub = body("plans your next round from your stats", 28, MUTED).next_to(title, DOWN, aligned_edge=LEFT, buff=0.15)
        steps = [("observe\nConvex stats", GOLD), ("decide\nNemotron on the GX10", GREEN), ("act\nnext round", RED), ("speak\nElevenLabs", BLUE)]
        nodes = VGroup(*[card(s, c, w=2.9, h=1.1, size=20) for s, c in steps])
        centre = DOWN * 0.9 + LEFT * 1.6
        for i, n in enumerate(nodes):
            ang = PI / 2 - i * PI / 2
            n.move_to(centre + np.array([2.6 * np.cos(ang), 1.55 * np.sin(ang), 0]))
        self.play(FadeIn(title), FadeIn(sub), run_time=t * 0.1)
        self.play(LaggedStartMap(FadeIn, nodes, lag_ratio=0.4), run_time=t * 0.3)
        ring = Circle(radius=1.1, stroke_color=MUTED, stroke_width=3).move_to(centre)
        self.play(ShowCreation(ring), run_time=t * 0.15)
        bubbles = VGroup(*[VGroup(RoundedRectangle(width=1.5, height=0.55, corner_radius=0.27, fill_color=c, fill_opacity=0.9,
                                                   stroke_width=0), body(w, 20, BG))
                           for w, c in [("boo!", RED), ("clap clap", GOLD), ("again!", ORANGE), ("lol", BLUE)]])
        for i, b in enumerate(bubbles):
            b[1].move_to(b[0])
            b.move_to(RIGHT * (4.6 + (i % 2) * 1.3) + DOWN * (1.4 + (i // 2) * 0.8))
        crowd = body("live crowd, from their phones", 22, MUTED).move_to(RIGHT * 5.0 + DOWN * 0.5)
        self.play(FadeIn(crowd), LaggedStartMap(lambda m: FadeIn(m, shift=UP * 0.3), bubbles, lag_ratio=0.3), run_time=t * 0.2)
        self.play(*[b.animate.shift(UP * 1.6).set_opacity(0) for b in bubbles], run_time=t * 0.15)

    def s_close(self, t):
        tiles = VGroup(*[card(s, c, w=3.1, h=1.2, size=24) for s, c in
                         [("reaction time\nper hand", BLUE), ("accuracy", GREEN), ("streaks", GOLD)]]).arrange(RIGHT, buff=0.35)
        tiles.to_edge(UP, buff=0.8)
        self.play(LaggedStartMap(FadeIn, tiles, lag_ratio=0.3), run_time=t * 0.2)
        web = body("in the browser  ·  no app store", 28, MUTED).next_to(tiles, DOWN, buff=0.4)
        self.play(FadeIn(web), run_time=t * 0.1)
        mark = wordmark(110).move_to(LEFT * 2.6 + DOWN * 1.6)
        left = robot_arm([1.7, -3.7], 1.2, -1.0, 0.15, scale=0.75)
        right = robot_arm([5.8, -3.7], PI - 1.2, 1.0, -0.15, scale=0.75)
        self.play(FadeIn(mark, shift=UP * 0.3), FadeIn(left), FadeIn(right), run_time=t * 0.25)
        cta = body("Come and throw a few punches.  waxonwaxoff.ink", 28, GOLD).next_to(mark, DOWN, aligned_edge=LEFT, buff=0.35)
        self.play(Write(cta), run_time=t * 0.2)
