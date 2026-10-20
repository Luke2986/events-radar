import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import path from "path";

// Separate vitest config (not using vite.config.ts) because vite.config.ts
// pulls in Tailwind, Replit dev plugins, and other production-only concerns
// that are irrelevant (and slow) for unit tests.
export default defineConfig({
  plugins: [react()],
  resolve: {
    alias: {
      "@": path.resolve(import.meta.dirname, "src"),
    },
    dedupe: ["react", "react-dom"],
  },
  test: {
    environment: "jsdom",
    globals: false,
    setupFiles: ["./src/test/setup.ts"],
    include: ["src/**/*.test.ts", "src/**/*.test.tsx"],
    reporters: "default",
  },
});
