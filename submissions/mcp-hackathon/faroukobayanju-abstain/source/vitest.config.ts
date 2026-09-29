import { defineConfig } from 'vitest/config';

/**
 * Explicit config so the suite is self-contained.
 *
 * Without this file vitest walks UP the directory tree looking for a config.
 * The submitted source is vendored into another repository
 * (submissions/mcp-hackathon/<slug>/source/), and that repository has its own
 * vitest config using `tests/**`. Inheriting it made `npm test` report
 * "No test files found, exiting with code 1" for a reviewer running the exact
 * command in verification/README.md, while passing here. Pin the root and the
 * include pattern so the result does not depend on where the directory sits.
 */
export default defineConfig({
  root: __dirname,
  test: {
    include: ['test/**/*.test.ts'],
    environment: 'node',
  },
});
