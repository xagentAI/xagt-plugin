import assert from "node:assert/strict";
import { createHash } from "node:crypto";
import test from "node:test";

import { deploymentConfig } from "../src/config.js";
import { fixtureEvidenceFetcher } from "../src/evidence/fixture.js";

test("local fixture configuration supplies reachable demo evidence", () => {
  const config = deploymentConfig({
    NODE_ENV: "development",
    DOCKET_AUTH_MODE: "off",
    DOCKET_AI_PROVIDER: "gemini",
    DOCKET_EVIDENCE_FIXTURE: "true",
  });

  assert.equal(config.evidenceFixture, true);
  assert.deepEqual(config.evidenceAllowHosts, ["evidence.example.test"]);
  assert.equal(typeof config.evidenceFetcher, "function");
  assert.equal(typeof config.evidenceResolver, "function");
});

test("production configuration never enables local fixture evidence", () => {
  const config = deploymentConfig({
    NODE_ENV: "production",
    DOCKET_AUTH_MODE: "required",
    DOCKET_AUTH_TOKENS: JSON.stringify({ "production-test-token": { tenantId: "tenant-a", subject: "agent-a", scopes: ["*"] } }),
    DOCKET_AI_PROVIDER: "gemini",
    DOCKET_EVIDENCE_FIXTURE: "true",
  });

  assert.equal(config.evidenceFixture, false);
  assert.deepEqual(config.evidenceAllowHosts, []);
  assert.equal(config.evidenceRequireAllowlist, true);
  assert.equal(config.evidenceFetcher, undefined);
  assert.equal(config.evidenceResolver, undefined);
});

test("explicit public demo auth mode overrides production defaults", () => {
  const config = deploymentConfig({
    NODE_ENV: "production",
    DOCKET_AUTH_MODE: "off",
    DOCKET_AI_PROVIDER: "fixture",
  });
  assert.equal(config.auth.required, false);
});

test("local fixture evidence matches the sample agreement digests", async () => {
  const fixtures = [
    ["https://evidence.example.test/ev-smoke.txt", "7a06fea670b648b816b370c13260b8ea0e43fbe40407f783b7b48be78d6b6188"],
    ["https://evidence.example.test/ev-docs.txt", "7fae5aa4fbdcda611ce6166302da0dddda7fe3628ccd702ed9b214e8b07af9b5"],
    ["https://evidence.example.test/ev-errors.txt", "825a550e10bc7cb366385f3932effcae419432e1f4c21fc860dc1a405f16c0da"],
  ];

  for (const [uri, expectedDigest] of fixtures) {
    const response = await fixtureEvidenceFetcher(new URL(uri));
    assert.equal(response.status, 200);
    const content = await response.text();
    assert.equal(createHash("sha256").update(content).digest("hex"), expectedDigest);
  }
});
