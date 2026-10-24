import { useState, type FormEvent } from "react";
import { errorCode, errorMessage, savePin, storedPin } from "../lib";

type Run = (pin: string | undefined) => Promise<unknown>;
type Pending = { run: Run; onError: (msg: string) => void; error?: string };

const isPinError = (err: unknown) => ["PIN_REQUIRED", "PIN_WRONG"].includes(errorCode(err) ?? "");

// Wraps actions that need the rig PIN: tries the remembered PIN first, and only shows the
// prompt if the server asks for one.
export function usePinGate() {
  const [pending, setPending] = useState<Pending | null>(null);

  async function withPin(run: Run, onError: (msg: string) => void) {
    try {
      await run(storedPin());
    } catch (err) {
      if (!isPinError(err)) return onError(errorMessage(err));
      if (errorCode(err) === "PIN_WRONG") savePin(undefined);
      setPending({ run, onError });
    }
  }

  async function submit(pin: string) {
    if (!pending) return;
    try {
      await pending.run(pin);
      savePin(pin);
      setPending(null);
    } catch (err) {
      if (isPinError(err)) return setPending({ ...pending, error: "Wrong PIN. Check the sign at the booth." });
      setPending(null);
      pending.onError(errorMessage(err));
    }
  }

  const sheet = pending && <PinSheet error={pending.error} onCancel={() => setPending(null)} onSubmit={submit} />;
  return { withPin, sheet };
}

function PinSheet({
  error,
  onCancel,
  onSubmit,
}: {
  error?: string;
  onCancel: () => void;
  onSubmit: (pin: string) => Promise<void>;
}) {
  const [pin, setPin] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent) {
    e.preventDefault();
    setBusy(true);
    await onSubmit(pin);
    setBusy(false);
  }

  return (
    <div className="sheet-backdrop" onClick={onCancel}>
      <form className="sheet" onClick={(e) => e.stopPropagation()} onSubmit={submit}>
        <h3>Rig PIN</h3>
        <p className="hint">The real arms only move for people at the booth. Enter the PIN shown on the rig.</p>
        <input
          className="pin-input"
          inputMode="numeric"
          autoComplete="one-time-code"
          autoFocus
          maxLength={8}
          value={pin}
          onChange={(e) => setPin(e.target.value.replace(/\D/g, ""))}
          aria-label="Rig PIN"
        />
        {error && <p className="form-error">{error}</p>}
        <div className="sheet-actions">
          <button type="button" className="btn btn-ghost" onClick={onCancel}>
            Cancel
          </button>
          <button className="btn btn-primary" disabled={!pin || busy}>
            {busy ? "Checking…" : "Unlock"}
          </button>
        </div>
      </form>
    </div>
  );
}
