import { useMutation, useQuery } from "convex/react";
import { useState, type FormEvent } from "react";
import { api } from "../../convex/_generated/api";
import { LINK_TTL_MS } from "../../convex/game";
import { buzz, useNow } from "../lib";

type WithPin = (run: (pin: string | undefined) => Promise<unknown>, onError: (msg: string) => void) => Promise<unknown>;

// Link the VR headset to this account with the 6-character code it shows, so rounds started
// from the headset (right-hand pinch) are saved here.
export function HeadsetLink({ withPin }: { withPin: WithPin }) {
  const rig = useQuery(api.sessions.rig);
  const link = useMutation(api.sessions.linkHeadset);
  const unlink = useMutation(api.sessions.unlinkHeadset);
  const now = useNow(5000);
  const [code, setCode] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  // Hidden until the backend with headset linking is deployed (older ones don't send linkedAt).
  if (!rig || !("linkedAt" in rig)) return null;
  const linked = rig.linkedToMe && now - rig.linkedAt < LINK_TTL_MS;

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    setError(null);
    await withPin(async (pin) => {
      await link({ code, pin });
      setCode("");
      buzz(40);
    }, setError);
    setBusy(false);
  }

  if (linked) {
    return (
      <section className="card">
        <h2 className="card-title">Headset linked to you</h2>
        <p className="hint">Pinch your right hand in the headset to start a round. Your scores save here.</p>
        <button className="btn btn-ghost btn-block" onClick={() => void unlink()}>
          Unlink
        </button>
      </section>
    );
  }

  return (
    <form className="card stack" onSubmit={submit}>
      <h2 className="card-title">Playing in the headset?</h2>
      <p className="hint">Enter the code shown in the headset to save your rounds to this account.</p>
      <input
        className="pin-input"
        autoCapitalize="characters"
        autoComplete="off"
        spellCheck={false}
        maxLength={6}
        placeholder="ABC123"
        value={code}
        onChange={(e) => setCode(e.target.value.toUpperCase().replace(/[^A-Z0-9]/g, ""))}
        aria-label="Headset code"
      />
      {error && <p className="form-error">{error}</p>}
      <button className="btn btn-primary btn-block" disabled={code.length !== 6 || busy}>
        {busy ? "Linking…" : "Link headset"}
      </button>
    </form>
  );
}
