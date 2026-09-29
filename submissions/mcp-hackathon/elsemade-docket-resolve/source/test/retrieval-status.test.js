import assert from "node:assert/strict";
import test from "node:test";

import { retrievalMessage, retrievalTone } from "../public/retrieval-status.js";

test("retrieval status distinguishes complete, partial, and total failure", () => {
  assert.equal(retrievalMessage({ items: [{ id: "e1" }], errors: [] }), "Evidence retrieved and digest-verified.");
  assert.equal(retrievalTone({ items: [{ id: "e1" }], errors: [] }), "");
  assert.equal(retrievalMessage({ items: [{ id: "e1" }], errors: [{ evidenceId: "e2" }] }), "Evidence was partially retrieved. Review the failures.");
  assert.equal(retrievalMessage({ items: [], errors: [{ evidenceId: "e1" }] }), "No evidence was retrieved. Review the failures.");
  assert.equal(retrievalTone({ items: [], errors: [{ evidenceId: "e1" }] }), "error");
});
