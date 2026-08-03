import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

// https://vite.dev/config/
export default defineConfig({
  plugins: [react()],
  server: {
    port: 5173,
    // In dev the app talks to the Django API directly via VITE_API_BASE_URL
    // (http://localhost:8000/api/v1). No proxy needed because the backend
    // enables CORS for the dev origin; a proxy is only wired for prod where
    // Caddy serves both from one origin.
  },
  build: {
    outDir: "dist",
    sourcemap: false,
    rollupOptions: {
      input: {
        main: "index.html",
        // The service worker is a second, independent entry point rather
        // than a plugin-generated one (no vite-plugin-pwa): a hand-written
        // SW needs a stable, unhashed URL — the browser re-fetches exactly
        // "/sw.js" on every navigation to check for updates, so it can never
        // carry a content hash the way the app's own JS/CSS does.
        sw: "src/sw.ts",
      },
      output: {
        entryFileNames: (chunk) => (chunk.name === "sw" ? "sw.js" : "assets/[name]-[hash].js"),
      },
    },
  },
});
