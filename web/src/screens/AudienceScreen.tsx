import { useMutation, useQuery } from "convex/react";
import { useEffect, useState, type FormEvent } from "react";
import { api } from "../../convex/_generated/api";
import { AUDIENCE_EMOJIS as EMOJIS } from "../../convex/game";
import { Wordmark } from "../App";
import { buzz, useNow } from "../lib";

// waxonwaxoff.ink/audience: no account. Enter the crowd code shown in the headset, then every tap
// sends an emoji that floats up around the coach in the player's view.
const CODE_KEY = "wax.audienceCode";

function clientId(): string {
  try {
    let id = localStorage.getItem("wax.audienceClient");
    if (!id) {
      id = Math.random().toString(36).slice(2) + Date.now().toString(36);
      localStorage.setItem("wax.audienceClient", id);
    }
    return id;
  } catch {
    return Math.random().toString(36).slice(2);
  }
}

function savedCode(): string {
  const fromUrl = new URLSearchParams(location.search).get("c");
  if (fromUrl) return fromUrl.toUpperCase();
  try {
    return localStorage.getItem(CODE_KEY) ?? "";
  } catch {
    return "";
  }
}

export function AudienceScreen() {
  const [code, setCode] = useState(savedCode);
  const [draft, setDraft] = useState("");
  const ring = useQuery(api.audience.ring, code ? { code } : "skip");
  const react = useMutation(api.audience.react);
  const [client] = useState(clientId);
  const [sent, setSent] = useState<{ id: number; emoji: string; x: number }[]>([]);
  const [slow, setSlow] = useState(false);
  const now = useNow(500);

  useEffect(() => {
    try {
      if (ring) localStorage.setItem(CODE_KEY, code);
    } catch {
      /* private mode */
    }
  }, [ring, code]);

  function join(e: FormEvent) {
    e.preventDefault();
    setCode(draft);
  }

  async function send(emoji: string) {
    buzz(15);
    const id = Date.now() + Math.random();
    setSent((s) => [...s.slice(-12), { id, emoji, x: 10 + Math.random() * 80 }]);
    setTimeout(() => setSent((s) => s.filter((x) => x.id !== id)), 1400);
    try {
      const r = await react({ code, emoji, client });
      setSlow(!r.ok);
    } catch {
      setCode("");
    }
  }

  if (!code || ring === null) {
    return (
      <div className="audience">
        <Wordmark size="lg" />
        <form className="card stack" onSubmit={join}>
          <h2 className="card-title">Join the crowd</h2>
          <p className="hint">
            {ring === null ? "That code didn't match. " : ""}Enter the crowd code shown next to the ring. Your reactions pop up in the
            fighter's headset.
          </p>
          <input
            className="pin-input"
            autoCapitalize="characters"
            autoComplete="off"
            spellCheck={false}
            maxLength={6}
            placeholder="ABC123"
            value={draft}
            onChange={(e) => setDraft(e.target.value.toUpperCase().replace(/[^A-Z0-9]/g, ""))}
          />
          <button className="btn btn-primary btn-lg btn-block" disabled={draft.length < 6}>
            Join
          </button>
        </form>
      </div>
    );
  }

  const live = ring?.live;
  return (
    <div className="audience">
      <Wordmark />
      <section className="card audience-ring">
        <div className="audience-label">{live ? "IN THE RING" : "WAITING FOR A FIGHTER"}</div>
        <div className="audience-player">{ring?.player ?? "—"}</div>
        {live && (
          <div className="audience-stats">
            <span>{live.score} pts</span>
            <span>
              {live.hits} hits · {live.misses} misses
            </span>
            <span>{Math.max(0, Math.ceil((live.endsAt - now) / 1000))} s</span>
          </div>
        )}
      </section>
      <div className="audience-grid">
        {EMOJIS.map((e) => (
          <button key={e} className="audience-emoji" onClick={() => void send(e)}>
            {e}
          </button>
        ))}
      </div>
      <p className="hint audience-hint">{slow ? "Easy there, max 4 a second" : "Tap to react, the fighter sees it live"}</p>
      <div className="audience-float" aria-hidden>
        {sent.map((s) => (
          <span key={s.id} style={{ left: `${s.x}%` }}>
            {s.emoji}
          </span>
        ))}
      </div>
    </div>
  );
}
