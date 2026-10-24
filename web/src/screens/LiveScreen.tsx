import { useMutation } from "convex/react";
import type { FunctionReturnType } from "convex/server";
import { useEffect, useRef, useState } from "react";
import { api } from "../../convex/_generated/api";
import { DIFFICULTIES, MODES, reactionRating, type Arm } from "../../convex/game";
import { avg, buzz, formatClock, useNow } from "../lib";

type Live = NonNullable<FunctionReturnType<typeof api.sessions.live>>;

const RING_R = 108;
const RING_C = 2 * Math.PI * RING_R;

export function LiveScreen({ live }: { live: Live }) {
  const { session: s, recent } = live;
  const now = useNow(50);
  const stop = useMutation(api.sessions.stop);
  const countdownMs = s.startsAt - now;
  const leftMs = s.endsAt - now;
  const progress = Math.min(1, Math.max(0, leftMs / (s.durationS * 1000)));
  const latest = recent[0];

  useEffect(() => window.scrollTo(0, 0), []);

  // Pop the counter and buzz the phone on each new hit; shake on a miss.
  const [flash, setFlash] = useState<"hit" | "miss" | null>(null);
  const seen = useRef(latest?._id);
  useEffect(() => {
    if (!latest || latest._id === seen.current) return;
    seen.current = latest._id;
    setFlash(latest.kind);
    buzz(latest.kind === "hit" ? 35 : [20, 30, 20]);
    const id = setTimeout(() => setFlash(null), 450);
    return () => clearTimeout(id);
  }, [latest]);

  // Beep-style buzz on each countdown second.
  const countdownSec = Math.ceil(countdownMs / 1000);
  useEffect(() => {
    if (countdownSec > 0 && countdownSec <= 3) buzz(25);
    if (countdownSec === 0) buzz(120);
  }, [countdownSec]);

  const lastRating = latest?.kind === "hit" && latest.reactionMs != null ? reactionRating(latest.reactionMs) : null;
  const urgent = leftMs <= 10_000 && countdownMs <= 0;

  return (
    <div className={`live ${flash ? `live-${flash}` : ""}`}>
      <header className="live-top">
        <div>
          <div className="eyebrow">
            {MODES[s.mode].label} · {DIFFICULTIES[s.difficulty].label}
            {s.simulated && " · Simulated"}
          </div>
          <div className={`live-clock ${urgent ? "live-clock-urgent" : ""}`}>
            {formatClock(countdownMs > 0 ? s.durationS * 1000 : leftMs)}
          </div>
        </div>
        <button className="btn btn-ghost" onClick={() => void stop({ sessionId: s._id })}>
          End early
        </button>
      </header>

      <div className="ring-wrap">
        <svg className="ring" viewBox="0 0 240 240" aria-hidden>
          <circle className="ring-track" cx="120" cy="120" r={RING_R} />
          <circle
            className="ring-fill"
            cx="120"
            cy="120"
            r={RING_R}
            strokeDasharray={RING_C}
            strokeDashoffset={RING_C * (1 - progress)}
            transform="rotate(-90 120 120)"
          />
        </svg>
        <div className="ring-center">
          <div key={s.hits} className="ring-hits">
            {s.hits}
          </div>
          <div className="ring-label">hits</div>
        </div>
      </div>

      <div className="pads">
        <Pad side="left" active={s.activeArm === "left"} stats={s.left} />
        <Pad side="right" active={s.activeArm === "right"} stats={s.right} />
      </div>

      <div className="live-stats">
        <Stat label="Score" value={s.score} />
        <Stat label="Streak" value={s.streak} accent={s.streak >= 5} />
        <Stat label="Avg" value={avg(s.reactionSumMs, s.hits) ?? "—"} unit={s.hits ? "ms" : ""} />
      </div>

      <div className="last-strike">
        {latest ? (
          latest.kind === "hit" ? (
            <>
              <span className={`tone tone-${lastRating!.tone}`}>{lastRating!.label}</span>
              <span className="last-ms">{latest.reactionMs} ms</span>
              <span className="last-pts">+{latest.points}</span>
            </>
          ) : (
            <span className="tone tone-miss">Missed {latest.arm}</span>
          )
        ) : (
          <span className="hint">Waiting for the first pad…</span>
        )}
      </div>

      {countdownMs > 0 && (
        <div className="countdown" role="status">
          <div key={countdownSec} className="countdown-num">
            {countdownSec}
          </div>
          <div className="countdown-sub">Hands up</div>
        </div>
      )}
    </div>
  );
}

function Pad({
  side,
  active,
  stats,
}: {
  side: Arm;
  active: boolean;
  stats: { hits: number; misses: number; reactionSumMs: number };
}) {
  return (
    <div className={`pad pad-${side} ${active ? "pad-on" : ""}`}>
      <div className="pad-glove" />
      <div className="pad-name">{side === "left" ? "Left arm" : "Right arm"}</div>
      <div className="pad-count">
        {stats.hits}
        <span> / {stats.hits + stats.misses}</span>
      </div>
    </div>
  );
}

function Stat({ label, value, unit, accent }: { label: string; value: number | string; unit?: string; accent?: boolean }) {
  return (
    <div className={`stat ${accent ? "stat-accent" : ""}`}>
      <div className="stat-value">
        {value}
        {unit && <small>{unit}</small>}
      </div>
      <div className="stat-label">{label}</div>
    </div>
  );
}
