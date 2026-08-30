"use strict";
const { COMMIT_RE, reviewedCommit } = require("../lib/meta");

module.exports = function handler(req, res) {
  const commit = reviewedCommit();
  if (!COMMIT_RE.test(commit)) {
    return res.status(503).json({ status: "misconfigured", code: "REVIEW_COMMIT_NOT_SET" });
  }
  return res.status(200).json({ status: "ok", commit });
};
