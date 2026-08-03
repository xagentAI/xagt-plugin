import { defineConfig } from "vitest/config";

// Submitted projects are review artifacts, not part of this package's trusted test suite.
// Restrict CI to the marketplace CLI tests so an untrusted submission cannot execute here.
export default defineConfig({
  test: {
    include: ["tests/**/*.test.{ts,mjs}"]
  }
});
