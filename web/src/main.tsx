import { ConvexAuthProvider } from "@convex-dev/auth/react";
import { ConvexReactClient } from "convex/react";
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import { AudienceScreen } from "./screens/AudienceScreen";
import "./styles.css";

const envUrl = import.meta.env.VITE_CONVEX_URL as string;
// A local backend isn't reachable from a phone, so in dev go through the Vite proxy instead.
const isLocalBackend = /\/\/(127\.0\.0\.1|localhost)[:/]/.test(envUrl);
const convex = new ConvexReactClient(import.meta.env.DEV && isLocalBackend ? window.location.origin : envUrl);

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ConvexAuthProvider client={convex}>
      {location.pathname.startsWith("/audience") ? <AudienceScreen /> : <App />}
    </ConvexAuthProvider>
  </StrictMode>,
);
