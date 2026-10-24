import { useQuery } from "convex/react";
import type { Id } from "../../convex/_generated/dataModel";
import { api } from "../../convex/_generated/api";
import { useState } from "react";
import { bestKey, DIFFICULTIES, MODES, type Difficulty, type Mode } from "../../convex/game";
import { avg, formatDate } from "../lib";
import { BoardToggle } from "./LeadersScreen";

export function HistoryScreen({ onOpen }: { onOpen: (id: Id<"sessions">) => void }) {
  const sessions = useQuery(api.sessions.history);
  const bests = useQuery(api.sessions.personalBests);
  const [pick, setPick] = useState<boolean | null>(null);
  if (sessions === undefined || bests === undefined) return <div className="loading">Loading…</div>;
  // Default to the robot table once there are robot sessions, otherwise practice.
  const simulated = pick ?? !sessions.some((s) => !s.simulated);

  return (
    <div className="stack">
      <section>
        <h2 className="section-title">Personal bests</h2>
        <BoardToggle simulated={simulated} onChange={setPick} />
        <div className="card pb-table-wrap">
          <table className="pb-table">
            <thead>
              <tr>
                <th />
                {(Object.keys(DIFFICULTIES) as Difficulty[]).map((d) => (
                  <th key={d}>{DIFFICULTIES[d].label}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {(Object.keys(MODES) as Mode[]).map((m) => (
                <tr key={m}>
                  <th>{MODES[m].label}</th>
                  {(Object.keys(DIFFICULTIES) as Difficulty[]).map((d) => {
                    const pb = bests[bestKey(simulated, m, d)];
                    return (
                      <td key={d}>
                        {pb ? (
                          <button className="pb-cell" onClick={() => onOpen(pb._id)}>
                            {pb.score}
                            <small>{pb.hits} hits</small>
                          </button>
                        ) : (
                          <span className="pb-none">—</span>
                        )}
                      </td>
                    );
                  })}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </section>

      <section>
        <h2 className="section-title">Sessions</h2>
        {sessions.length === 0 ? (
          <div className="empty">No sessions yet. Your first one shows up here.</div>
        ) : (
          <ul className="list">
            {sessions.map((s) => (
              <li key={s._id}>
                <button className="row" onClick={() => onOpen(s._id)}>
                  <span className="row-main">
                    <span className="row-title">
                      {MODES[s.mode].label} · {DIFFICULTIES[s.difficulty].label}
                      {s.status === "stopped" && <span className="tag">Ended early</span>}
                      {s.simulated && <span className="tag">Practice</span>}
                    </span>
                    <span className="row-sub">
                      {formatDate(s.createdAt)} · {s.hits} hits
                      {s.hits > 0 && ` · ${avg(s.reactionSumMs, s.hits)} ms avg`}
                    </span>
                  </span>
                  <span className="row-score">{s.status === "live" ? "LIVE" : s.score}</span>
                </button>
              </li>
            ))}
          </ul>
        )}
      </section>
    </div>
  );
}
