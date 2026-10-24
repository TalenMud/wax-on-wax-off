import { useMutation, useQuery } from "convex/react";
import type { FunctionReturnType } from "convex/server";
import { useEffect, useState } from "react";
import { api } from "../../convex/_generated/api";
import { bestKey, DIFFICULTIES, MODES, type Difficulty, type Mode } from "../../convex/game";
import { EstopButton } from "../components/EstopButton";
import { HeadsetLink } from "../components/HeadsetLink";
import { useRigStatus } from "../components/RigPill";
import { buzz, errorMessage, formatClock, learnServerTime, useNow } from "../lib";

type Live = FunctionReturnType<typeof api.sessions.live>;

export function PlayScreen({ live }: { live: Live }) {
  const [mode, setMode] = useState<Mode>("standard");
  const [difficulty, setDifficulty] = useState<Difficulty>("medium");
  const rig = useRigStatus();
  const [simulate, setSimulate] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const bests = useQuery(api.sessions.personalBests) ?? {};
  const start = useMutation(api.sessions.start);
  const resetEstop = useMutation(api.sessions.resetEstop);

  // No robot connected? Default to the built-in simulator so the app is always demoable.
  useEffect(() => {
    if (rig.loaded) setSimulate(!rig.online);
  }, [rig.loaded, rig.online]);

  const busyElsewhere = live && !live.mine;
  // Simulated sessions don't touch the arms, so they're allowed while the rig is busy or E-STOPped.
  const blocked = !simulate && (!!busyElsewhere || rig.estop);

  async function go() {
    setBusy(true);
    setError(null);
    try {
      const { serverNow } = await start({ mode, difficulty, simulate });
      learnServerTime(serverNow);
      buzz(40);
    } catch (err) {
      setError(errorMessage(err));
    }
    setBusy(false);
  }

  return (
    <div className="stack">
      {rig.estop && (
        <div className="banner banner-danger">
          <div>
            <strong>E-STOP is latched</strong>
            <p>Check the arms and the area are clear, then reset.</p>
          </div>
          <button className="btn btn-light" onClick={() => void resetEstop().catch((err) => setError(errorMessage(err)))}>
            Reset
          </button>
        </div>
      )}
      {busyElsewhere && <BusyBanner live={live} />}
      {rig.online && <HeadsetLink />}

      <section>
        <h2 className="section-title">Session</h2>
        <div className="mode-list" role="radiogroup">
          {(Object.keys(MODES) as Mode[]).map((m) => {
            const pb = bests[bestKey(simulate, m, difficulty)];
            return (
              <button
                key={m}
                role="radio"
                aria-checked={mode === m}
                className={`mode ${mode === m ? "mode-on" : ""}`}
                onClick={() => setMode(m)}
              >
                <span className="mode-time">{formatClock(MODES[m].durationS * 1000)}</span>
                <span className="mode-body">
                  <span className="mode-name">{MODES[m].label}</span>
                  <span className="mode-blurb">{MODES[m].blurb}</span>
                </span>
                <span className="mode-pb">
                  {pb ? (
                    <>
                      <span className="mode-pb-label">Best</span>
                      {pb.score}
                    </>
                  ) : (
                    <span className="mode-pb-label">No best yet</span>
                  )}
                </span>
              </button>
            );
          })}
        </div>
      </section>

      <section>
        <h2 className="section-title">Difficulty</h2>
        <div className="seg seg-3">
          {(Object.keys(DIFFICULTIES) as Difficulty[]).map((d) => (
            <button key={d} className={difficulty === d ? "seg-on" : ""} onClick={() => setDifficulty(d)}>
              {DIFFICULTIES[d].label}
            </button>
          ))}
        </div>
        <p className="hint">
          {DIFFICULTIES[difficulty].blurb} · pad stays up {(DIFFICULTIES[difficulty].windowMs / 1000).toFixed(1)} s · up
          to {DIFFICULTIES[difficulty].maxRun} in a row on one side
        </p>
      </section>

      <label className="toggle">
        <span>
          <strong>Simulated rig</strong>
          <span className="hint">
            {rig.online ? "The real arms are connected." : "No arms connected. A virtual opponent plays instead."}
          </span>
        </span>
        <input type="checkbox" checked={simulate} onChange={(e) => setSimulate(e.target.checked)} />
      </label>

      {error && <p className="form-error">{error}</p>}

      <button className="btn btn-primary btn-block btn-xl" disabled={busy || blocked} onClick={go}>
        {busy ? "Starting…" : "Start"}
      </button>
      <p className="hint center">
        {simulate
          ? "Practice run against the virtual opponent. Scores go on the practice board."
          : "Player puts the headset on. 3 s countdown, then the arms start."}
      </p>
    </div>
  );
}

function BusyBanner({ live }: { live: NonNullable<Live> }) {
  const now = useNow(250);
  const left = live.session.endsAt - now;
  return (
    <div className="banner">
      <div>
        <strong>{live.player} is sparring</strong>
        <p>
          {MODES[live.session.mode].label} · {live.session.hits} hits · {formatClock(left)} left
        </p>
      </div>
      <EstopButton compact />
    </div>
  );
}
