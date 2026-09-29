"use strict";

const PROJECT_SLUG = "nurexen-safegate-commerce-outcome";
const COMMIT_RE = /^[a-f0-9]{40}$/i;

function reviewedCommit() {
  return String(process.env.XAGENT_REVIEW_COMMIT || "").trim().toLowerCase();
}

module.exports = { PROJECT_SLUG, COMMIT_RE, reviewedCommit };
