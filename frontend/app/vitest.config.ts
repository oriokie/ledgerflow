import { defineConfig } from "vitest/config";

// Pin the timezone before anything constructs a Date.
//
// `periodRange` deliberately takes local-time month/day boundaries and then
// serialises them to UTC — which is the correct behaviour for a user in
// Nairobi asking for "this month". The tests assert against fixed ISO strings,
// so they only hold in one reference frame: run them from UTC+3 and five of
// them fail on a correct implementation. Pinning makes the suite deterministic
// everywhere instead of green only in Greenwich.
//
// The trade-off is explicit: this fixes the *tests*, and leaves the
// timezone-correctness of `periodRange` itself unasserted. A test that varies
// TZ on purpose would be the thing that covers it.
process.env.TZ = "UTC";

// Test-only config, auto-loaded by Vitest and kept out of every tsconfig so the
// production build never compiles it. Tests don't need the React plugin's Fast
// Refresh — esbuild's automatic JSX runtime is enough and avoids a classic
// "React is not defined" transform.
export default defineConfig({
  esbuild: { jsx: "automatic", jsxImportSource: "react" },
  test: {
    globals: true,
    environment: "jsdom",
    setupFiles: ["./src/test/setup.ts"],
    css: false,
    include: ["src/**/*.test.{ts,tsx}"],
    coverage: {
      provider: "v8",
      reportsDirectory: "./coverage",
      include: ["src/**/*.{ts,tsx}"],
      exclude: ["src/**/*.test.{ts,tsx}", "src/test/**", "src/main.tsx", "src/**/*.d.ts"],
    },
  },
});
