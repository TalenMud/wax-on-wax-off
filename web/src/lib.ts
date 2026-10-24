import { ConvexError } from "convex/values";
import { useEffect, useState } from "react";

// Difference between the Convex server clock and this phone's clock, learned from mutations
// that return serverNow. Countdown/timer math uses serverTime() so phones with a skewed clock
// still show the same remaining time as the robot.
let clockOffsetMs = 0;
export function learnServerTime(serverNow: number) {
  clockOffsetMs = serverNow - Date.now();
}
export function serverTime() {
  return Date.now() + clockOffsetMs;
}

export function useNow(intervalMs = 100, enabled = true) {
  const [now, setNow] = useState(serverTime);
  useEffect(() => {
    if (!enabled) return;
    const id = setInterval(() => setNow(serverTime()), intervalMs);
    return () => clearInterval(id);
  }, [intervalMs, enabled]);
  return now;
}

export const RIG_ONLINE_MS = 6000;

export function formatClock(ms: number) {
  const total = Math.max(0, Math.ceil(ms / 1000));
  return `${Math.floor(total / 60)}:${String(total % 60).padStart(2, "0")}`;
}

export function avg(sum: number, count: number) {
  return count ? Math.round(sum / count) : null;
}

export function pct(part: number, whole: number) {
  return whole ? Math.round((part / whole) * 100) : null;
}

export function formatDate(ms: number) {
  return new Date(ms).toLocaleString(undefined, { weekday: "short", hour: "numeric", minute: "2-digit" });
}

export function errorCode(err: unknown): string | null {
  return err instanceof ConvexError && typeof err.data === "object" ? (err.data.code ?? null) : null;
}

export function errorMessage(err: unknown) {
  if (err instanceof ConvexError) return typeof err.data === "object" ? String(err.data.message) : String(err.data);
  if (err instanceof Error && /InvalidSecret|InvalidAccountId/.test(err.message)) return "Wrong email or password.";
  if (err instanceof Error && /already exists/.test(err.message)) return "An account with that email already exists.";
  return "Something went wrong. Try again.";
}

export function buzz(pattern: number | number[]) {
  navigator.vibrate?.(pattern);
}
