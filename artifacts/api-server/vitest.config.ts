import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    environment: "node",
    globals: false,
    include: ["src/**/*.test.ts"],
    reporters: "default",
    // Silence pino/pino-http noise during test runs
    env: {
      LOG_LEVEL: "silent",
      NODE_ENV: "test",
    },
  },
});
