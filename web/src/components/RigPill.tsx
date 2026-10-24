import { useQuery } from "convex/react";
import { api } from "../../convex/_generated/api";
import { RIG_ONLINE_MS, useNow } from "../lib";

export function useRigStatus() {
  const rig = useQuery(api.sessions.rig);
  const now = useNow(1000);
  if (!rig) return { loaded: false, online: false, estop: false };
  return { loaded: true, online: now - rig.lastSeenAt < RIG_ONLINE_MS, estop: rig.estop };
}

export function RigPill() {
  const { loaded, online, estop } = useRigStatus();
  if (!loaded) return null;
  const [tone, label] = estop ? ["danger", "E-STOP"] : online ? ["ok", "Rig online"] : ["off", "Rig offline"];
  return (
    <span className={`pill pill-${tone}`}>
      <span className="pill-dot" />
      {label}
    </span>
  );
}
