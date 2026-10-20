import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    environment: "node",
    include: ["src/**/*.test.ts"],
    restoreMocks: true,
    // The first run downloads a MongoDB binary for mongodb-memory-server (cached afterwards).
    hookTimeout: 120_000,
  },
});
