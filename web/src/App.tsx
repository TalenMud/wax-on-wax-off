import { useAuthActions } from "@convex-dev/auth/react";
import { Authenticated, AuthLoading, Unauthenticated, useQuery } from "convex/react";
import { useEffect, useRef, useState } from "react";
import { api } from "../convex/_generated/api";
import type { Id } from "../convex/_generated/dataModel";
import { RigPill } from "./components/RigPill";
import { AuthScreen } from "./screens/AuthScreen";
import { HistoryScreen } from "./screens/HistoryScreen";
import { LeadersScreen } from "./screens/LeadersScreen";
import { LiveScreen } from "./screens/LiveScreen";
import { PlayScreen } from "./screens/PlayScreen";
import { ResultsScreen } from "./screens/ResultsScreen";

export type Tab = "play" | "history" | "leaders";

export default function App() {
  return (
    <>
      <AuthLoading>
        <div className="splash">
          <Wordmark />
        </div>
      </AuthLoading>
      <Unauthenticated>
        <AuthScreen />
      </Unauthenticated>
      <Authenticated>
        <Shell />
      </Authenticated>
    </>
  );
}

export function Wordmark({ size = "md" }: { size?: "md" | "lg" }) {
  return (
    <div className={`wordmark wordmark-${size}`}>
      <span>Wax On</span>
      <span className="wordmark-off">Wax Off</span>
    </div>
  );
}

function Shell() {
  const [tab, setTab] = useState<Tab>("play");
  const [viewing, setViewing] = useState<Id<"sessions"> | null>(null);
  const live = useQuery(api.sessions.live);
  const me = useQuery(api.sessions.me);
  const { signOut } = useAuthActions();
  const [menuOpen, setMenuOpen] = useState(false);

  // When my live session ends (timer or Stop), jump straight to its results.
  const myLiveId = live?.mine ? live.session._id : null;
  const lastLive = useRef<Id<"sessions"> | null>(null);
  useEffect(() => {
    if (myLiveId) lastLive.current = myLiveId;
    else if (lastLive.current && live !== undefined) {
      setViewing(lastLive.current);
      lastLive.current = null;
    }
  }, [myLiveId, live]);

  if (live?.mine) return <LiveScreen live={live} />;

  return (
    <div className="shell">
      <header className="topbar">
        <Wordmark />
        <div className="topbar-right">
          <RigPill />
          <button className="avatar" onClick={() => setMenuOpen((o) => !o)} aria-label="Account">
            {(me?.name ?? "?").slice(0, 1).toUpperCase()}
          </button>
        </div>
        {menuOpen && (
          <div className="menu" onClick={() => setMenuOpen(false)}>
            <div className="menu-name">{me?.name}</div>
            <div className="menu-email">{me?.email}</div>
            <button className="btn btn-ghost btn-block" onClick={() => void signOut()}>
              Sign out
            </button>
          </div>
        )}
      </header>

      <main className="content">
        {viewing ? (
          <ResultsScreen sessionId={viewing} onBack={() => setViewing(null)} />
        ) : tab === "play" ? (
          <PlayScreen live={live ?? null} />
        ) : tab === "history" ? (
          <HistoryScreen onOpen={setViewing} />
        ) : (
          <LeadersScreen meId={me?._id} onOpen={setViewing} />
        )}
      </main>

      <nav className="tabbar">
        {(
          [
            ["play", "Train", IconTarget],
            ["history", "History", IconClock],
            ["leaders", "Leaders", IconTrophy],
          ] as const
        ).map(([id, label, Icon]) => (
          <button
            key={id}
            className={`tab ${tab === id && !viewing ? "tab-active" : ""}`}
            onClick={() => {
              setViewing(null);
              setTab(id);
            }}
          >
            <Icon />
            <span>{label}</span>
          </button>
        ))}
      </nav>
    </div>
  );
}

function IconTarget() {
  return (
    <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="2">
      <circle cx="12" cy="12" r="9" />
      <circle cx="12" cy="12" r="4.5" />
      <circle cx="12" cy="12" r="1" fill="currentColor" />
    </svg>
  );
}
function IconClock() {
  return (
    <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="2">
      <circle cx="12" cy="12" r="9" />
      <path d="M12 7v5l3 2" strokeLinecap="round" />
    </svg>
  );
}
function IconTrophy() {
  return (
    <svg viewBox="0 0 24 24" width="22" height="22" fill="none" stroke="currentColor" strokeWidth="2">
      <path d="M7 4h10v5a5 5 0 0 1-10 0V4Z" />
      <path d="M7 6H4a3 3 0 0 0 3 4M17 6h3a3 3 0 0 1-3 4M12 14v4M8 20h8" strokeLinecap="round" />
    </svg>
  );
}
