import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    environment: "jsdom",
    exclude: ["e2e/**", "node_modules/**"],
    coverage: { reporter: ["text", "lcov"], thresholds: { lines: 80 } }
  }
});
