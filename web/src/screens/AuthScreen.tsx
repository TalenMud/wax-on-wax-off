import { useAuthActions } from "@convex-dev/auth/react";
import { useState, type FormEvent } from "react";
import { Wordmark } from "../App";
import { errorMessage } from "../lib";

export function AuthScreen() {
  const { signIn } = useAuthActions();
  const [flow, setFlow] = useState<"signIn" | "signUp">("signIn");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  async function submit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    form.set("flow", flow);
    if (flow === "signUp" && String(form.get("password")).length < 8) {
      setError("Use at least 8 characters for your password.");
      return;
    }
    setBusy(true);
    setError(null);
    try {
      await signIn("password", form);
    } catch (err) {
      setError(errorMessage(err));
      setBusy(false);
    }
  }

  return (
    <div className="auth">
      <div className="auth-hero">
        <div className="auth-rings" aria-hidden />
        <Wordmark size="lg" />
        <p className="auth-tag">Reaction sparring against two robot arms. Train, time it, beat your best.</p>
      </div>

      <form className="card auth-card" onSubmit={submit}>
        <div className="seg seg-2">
          <button type="button" className={flow === "signIn" ? "seg-on" : ""} onClick={() => setFlow("signIn")}>
            Sign in
          </button>
          <button type="button" className={flow === "signUp" ? "seg-on" : ""} onClick={() => setFlow("signUp")}>
            Create account
          </button>
        </div>

        {flow === "signUp" && (
          <label className="field">
            <span>Name</span>
            <input name="name" autoComplete="nickname" placeholder="What should the board call you?" required />
          </label>
        )}
        <label className="field">
          <span>Email</span>
          <input name="email" type="email" autoComplete="email" inputMode="email" placeholder="you@school.edu" required />
        </label>
        <label className="field">
          <span>Password</span>
          <input
            name="password"
            type="password"
            autoComplete={flow === "signIn" ? "current-password" : "new-password"}
            placeholder={flow === "signUp" ? "At least 8 characters" : ""}
            required
          />
        </label>

        {error && <p className="form-error">{error}</p>}

        <button className="btn btn-primary btn-block btn-lg" disabled={busy}>
          {busy ? "One sec…" : flow === "signIn" ? "Sign in" : "Create account"}
        </button>
      </form>
    </div>
  );
}
