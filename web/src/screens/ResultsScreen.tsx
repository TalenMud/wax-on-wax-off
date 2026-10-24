import { useMutation, useQuery } from "convex/react";
import type { Doc, Id } from "../../convex/_generated/dataModel";
import { api } from "../../convex/_generated/api";
import { DIFFICULTIES, MODES } from "../../convex/game";
import { useState } from "react";
import { avg, errorMessage, formatDate, learnServerTime, pct } from "../lib";

export function ResultsScreen({ sessionId, onBack }: { sessionId: Id<"sessions">; onBack: () => void }) {
  const data = useQuery(api.sessions.get, { sessionId });
  const me = useQuery(api.sessions.me);
  const start = useMutation(api.sessions.start);
  const [error, setError] = useState<string | null>(null);

  if (data === undefined) return <div className="loading">Loading…</div>;
  if (data === null) return <div className="empty">Session not found.</div>;

  const { session: s, events, previousBest, player } = data;
  const attempts = s.hits + s.misses;
  const hitTimes = events.filter((e) => e.kind === "hit").map((e) => e.reactionMs ?? 0);
  const fastest = hitTimes.length ? Math.min(...hitTimes) : null;
  const isPB = s.status === "finished" && s.hits > 0 && (previousBest === null || s.score > previousBest);
  const mine = me?._id === s.userId;

  async function again() {
    setError(null);
    try {
      const { serverNow } = await start({ mode: s.mode, difficulty: s.difficulty, simulate: s.simulated });
      learnServerTime(serverNow);
    } catch (err) {
      setError(errorMessage(err));
    }
  }

  return (
    <div className="stack">
      <button className="back" onClick={onBack}>
        ‹ Back
      </button>

      <section className="result-hero">
        <div className="eyebrow">
          {MODES[s.mode].label} · {DIFFICULTIES[s.difficulty].label} · {formatDate(s.createdAt)}
          {s.simulated && " · Practice"}
          {!mine && ` · ${player}`}
        </div>
        {isPB && <div className="pb-badge">New personal best</div>}
        {s.status === "stopped" && <div className="tag">Ended early · not ranked</div>}
        <div className="result-score">{s.score}</div>
        <div className="result-score-label">points</div>
        {previousBest !== null && !isPB && s.status === "finished" && (
          <div className="hint">Your best here is {previousBest}</div>
        )}
      </section>

      <div className="grid-3">
        <Tile label="Hits" value={s.hits} />
        <Tile label="Accuracy" value={pct(s.hits, attempts) ?? "—"} unit={attempts ? "%" : ""} />
        <Tile label="Best streak" value={s.bestStreak} />
        <Tile label="Avg reaction" value={avg(s.reactionSumMs, s.hits) ?? "—"} unit={s.hits ? "ms" : ""} />
        <Tile label="Fastest" value={fastest ?? "—"} unit={fastest ? "ms" : ""} />
        <Tile label="Misses" value={s.misses} />
      </div>

      <SideBreakdown s={s} />

      <section className="card">
        <h3 className="card-title">Every strike</h3>
        <Timeline events={events} windowMs={DIFFICULTIES[s.difficulty].windowMs} />
      </section>

      {error && <p className="form-error">{error}</p>}
      {mine && (
        <button className="btn btn-primary btn-block btn-lg" onClick={again}>
          Run it back
        </button>
      )}
    </div>
  );
}

function Tile({ label, value, unit }: { label: string; value: number | string; unit?: string }) {
  return (
    <div className="tile">
      <div className="tile-value">
        {value}
        {unit && <small>{unit}</small>}
      </div>
      <div className="tile-label">{label}</div>
    </div>
  );
}

function SideBreakdown({ s }: { s: Doc<"sessions"> }) {
  const sides = (["left", "right"] as const).map((side) => {
    const st = s[side];
    return { side, ...st, acc: pct(st.hits, st.hits + st.misses), avg: avg(st.reactionSumMs, st.hits) };
  });
  const [l, r] = sides;
  let callout: string | null = null;
  if (l.avg && r.avg && Math.abs(l.avg - r.avg) >= 40) {
    const slow = l.avg > r.avg ? l : r;
    callout = `${slow.side === "left" ? "Left" : "Right"} side is ${Math.abs(l.avg - r.avg)} ms slower. Drill it.`;
  } else if (l.acc !== null && r.acc !== null && Math.abs(l.acc - r.acc) >= 15) {
    const weak = l.acc < r.acc ? l : r;
    callout = `You miss more on the ${weak.side}.`;
  } else if (l.hits + r.hits > 0) {
    callout = "Balanced on both sides.";
  }
  const maxAvg = Math.max(l.avg ?? 0, r.avg ?? 0, 1);

  return (
    <section className="card">
      <h3 className="card-title">Left vs right</h3>
      <div className="sides">
        {sides.map((x) => (
          <div key={x.side} className={`side side-${x.side}`}>
            <div className="side-name">{x.side === "left" ? "Left arm" : "Right arm"}</div>
            <div className="side-big">
              {x.hits}
              <small> / {x.hits + x.misses}</small>
            </div>
            <div className="side-row">
              <span>Accuracy</span>
              <span>{x.acc === null ? "—" : `${x.acc}%`}</span>
            </div>
            <div className="side-row">
              <span>Avg</span>
              <span>{x.avg === null ? "—" : `${x.avg} ms`}</span>
            </div>
            <div className="side-bar">
              <div style={{ width: `${((x.avg ?? 0) / maxAvg) * 100}%` }} />
            </div>
          </div>
        ))}
      </div>
      {callout && <p className="callout">{callout}</p>}
    </section>
  );
}

function Timeline({ events, windowMs }: { events: Doc<"events">[]; windowMs: number }) {
  if (!events.length) return <p className="hint">No strikes recorded.</p>;
  const W = 320;
  const H = 120;
  const max = Math.max(windowMs, ...events.map((e) => e.reactionMs ?? 0));
  const bw = Math.max(2, Math.min(14, W / events.length - 2));
  const step = W / events.length;
  const y = (ms: number) => H - (ms / max) * H;
  return (
    <div className="timeline">
      <svg viewBox={`0 0 ${W} ${H + 4}`} preserveAspectRatio="none" role="img" aria-label="Reaction time per strike">
        {[400, 600].map((ms) => (
          <g key={ms}>
            <line x1="0" x2={W} y1={y(ms)} y2={y(ms)} className="tl-ref" />
          </g>
        ))}
        {events.map((e, i) => {
          const x = i * step + (step - bw) / 2;
          if (e.kind === "miss") return <rect key={e._id} x={x} y={H - 6} width={bw} height={6} rx="1" className="tl-miss" />;
          const top = y(e.reactionMs ?? 0);
          return <rect key={e._id} x={x} y={top} width={bw} height={H - top} rx="1.5" className={`tl-hit tl-${e.arm}`} />;
        })}
      </svg>
      <div className="tl-legend">
        <span>
          <i className="sw sw-left" /> Left
        </span>
        <span>
          <i className="sw sw-right" /> Right
        </span>
        <span>
          <i className="sw sw-miss" /> Miss
        </span>
        <span className="tl-scale">lines at 400 / 600 ms · taller = slower</span>
      </div>
    </div>
  );
}
