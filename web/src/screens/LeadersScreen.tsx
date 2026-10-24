import { useQuery } from "convex/react";
import { useState } from "react";
import type { Id } from "../../convex/_generated/dataModel";
import { api } from "../../convex/_generated/api";
import { DIFFICULTIES, MODES, type Difficulty, type Mode } from "../../convex/game";
import { avg } from "../lib";

export function LeadersScreen({ meId, onOpen }: { meId?: Id<"users">; onOpen: (id: Id<"sessions">) => void }) {
  const [mode, setMode] = useState<Mode>("standard");
  const [difficulty, setDifficulty] = useState<Difficulty>("medium");
  const [simulated, setSimulated] = useState(false);
  const rows = useQuery(api.sessions.leaderboard, { mode, difficulty, simulated });

  return (
    <div className="stack">
      <BoardToggle simulated={simulated} onChange={setSimulated} />
      <div className="seg seg-3">
        {(Object.keys(MODES) as Mode[]).map((m) => (
          <button key={m} className={mode === m ? "seg-on" : ""} onClick={() => setMode(m)}>
            {MODES[m].label}
          </button>
        ))}
      </div>
      <div className="seg seg-3 seg-sm">
        {(Object.keys(DIFFICULTIES) as Difficulty[]).map((d) => (
          <button key={d} className={difficulty === d ? "seg-on" : ""} onClick={() => setDifficulty(d)}>
            {DIFFICULTIES[d].label}
          </button>
        ))}
      </div>

      {rows === undefined ? (
        <div className="loading">Loading…</div>
      ) : rows.length === 0 ? (
        <div className="empty">
          {simulated ? "No practice runs yet." : "Nobody has fought the real arms yet. Take the top spot."}
        </div>
      ) : (
        <ol className="list board">
          {rows.map(({ session: s, player }, i) => (
            <li key={s._id}>
              <button className={`row ${s.userId === meId ? "row-me" : ""}`} onClick={() => onOpen(s._id)}>
                <span className={`rank rank-${i + 1}`}>{i + 1}</span>
                <span className="row-main">
                  <span className="row-title">
                    {player}
                    {s.userId === meId && <span className="tag">You</span>}
                  </span>
                  <span className="row-sub">
                    {s.hits} hits · {avg(s.reactionSumMs, s.hits) ?? "—"} ms avg · streak {s.bestStreak}
                  </span>
                </span>
                <span className="row-score">{s.score}</span>
              </button>
            </li>
          ))}
        </ol>
      )}
    </div>
  );
}

export function BoardToggle({ simulated, onChange }: { simulated: boolean; onChange: (sim: boolean) => void }) {
  return (
    <div className="seg seg-2 seg-sm">
      <button className={!simulated ? "seg-on" : ""} onClick={() => onChange(false)}>
        Robot
      </button>
      <button className={simulated ? "seg-on" : ""} onClick={() => onChange(true)}>
        Practice
      </button>
    </div>
  );
}
