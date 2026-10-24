import { defineConfig, loadEnv } from "vite";
import react from "@vitejs/plugin-react";

export default defineConfig(({ mode }) => {
  const env = loadEnv(mode, process.cwd(), "");
  return {
    plugins: [react()],
    // GitHub Pages serves the app from /<repo>/; the Pages workflow sets BASE_PATH.
    base: env.BASE_PATH || "/",
    // With a local Convex backend (127.0.0.1), proxy it so a phone on the same Wi-Fi can reach it
    // through this dev server. See src/main.tsx.
    server: {
      proxy: { "/api": { target: env.VITE_CONVEX_URL, ws: true, changeOrigin: true } },
    },
  };
});
