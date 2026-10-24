import { useMutation } from "convex/react";
import { api } from "../../convex/_generated/api";
import { buzz } from "../lib";

// Single tap, no confirmation: an emergency stop has to be instant.
export function EstopButton({ compact = false }: { compact?: boolean }) {
  const estop = useMutation(api.sessions.estop);
  return (
    <button
      className={`estop ${compact ? "estop-compact" : ""}`}
      onClick={() => {
        buzz([80, 40, 80]);
        void estop();
      }}
    >
      <span className="estop-face">E-STOP</span>
      {!compact && <span className="estop-sub">Stops both arms now</span>}
    </button>
  );
}
