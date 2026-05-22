import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";
import { fileURLToPath, URL } from "node:url";

// Issue #36 bundle-size targets:
//   * main chunk        < 200 KB gzipped
//   * LCP               < 2.5 s on a slow Telegram WebView
//
// We hit them with three levers wired in this config:
//   1. ``React.lazy`` + ``Suspense`` per route (see ``src/router.tsx``)
//      so navigating to ``/balance`` does not pull ``/history``.
//   2. ``manualChunks`` carves the React runtime, the router and the
//      Telegram SDK out of the entry bundle. They are cacheable forever
//      between deploys, which makes the *second* visit essentially free.
//   3. ``chunkSizeWarningLimit`` is tightened to the issue's budget so a
//      regression shows up as a CI warning instead of silently shipping.
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": fileURLToPath(new URL("./src", import.meta.url)),
    },
  },
  server: {
    host: true,
    port: 5173,
  },
  build: {
    target: "es2022",
    sourcemap: true,
    outDir: "dist",
    // ``vite build`` reports per-chunk *uncompressed* size; the issue's
    // 200 KB gzipped budget maps to roughly 600 KB raw, but we keep the
    // ceiling at 400 KB to leave headroom for new features.
    chunkSizeWarningLimit: 400,
    cssCodeSplit: true,
    reportCompressedSize: true,
    rollupOptions: {
      output: {
        manualChunks(id) {
          // React + ReactDOM live forever in their own chunk — the
          // browser cache amortises them across releases that only
          // touch app code.
          if (id.includes("/node_modules/react/") || id.includes("/node_modules/react-dom/")) {
            return "vendor-react";
          }
          if (id.includes("/node_modules/react-router-dom/")) {
            return "vendor-router";
          }
          // ``@twa-dev/sdk`` is heavy and only used to wire Telegram
          // theme / haptics — splitting it keeps the entry script lean.
          if (id.includes("/node_modules/@twa-dev/sdk/")) {
            return "vendor-telegram";
          }
          if (id.includes("/node_modules/@sentry/react/")) {
            return "vendor-sentry";
          }
          if (id.includes("/node_modules/zustand/")) {
            return "vendor-state";
          }
          return undefined;
        },
      },
    },
  },
});
