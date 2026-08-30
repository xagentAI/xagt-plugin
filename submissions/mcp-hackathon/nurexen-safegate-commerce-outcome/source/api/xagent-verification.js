"use strict";
const { PROJECT_SLUG, COMMIT_RE, reviewedCommit } = require("../lib/meta");

module.exports = function handler(req, res) {
  const commit = reviewedCommit();
  if (!COMMIT_RE.test(commit)) {
    return res.status(503).json({ schemaVersion: 1, slug: PROJECT_SLUG, code: "REVIEW_COMMIT_NOT_SET" });
  }
  return res.status(200).json({ schemaVersion: 1, slug: PROJECT_SLUG, commit });
};
