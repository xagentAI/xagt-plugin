# Changelog

All notable changes to Abstain are documented here.

## [Unreleased]

### Added

- Explain the product pain, Nexus dependency, system architecture, trust boundaries, and judge-facing demo flow.

### Removed

- Remove tracked macOS metadata from the reviewable source tree.

## [0.1.0.0] - 2026-09-18

### Added

- Verify production deployments end to end with one command, including durable readiness, concurrent receipt writes, chain integrity, and source-commit binding.
- Reject malformed Nexus payloads before they can influence an execution decision.
- Document the complete first-run, API, deployment, and receipt-chain workflows.

### Changed

- Keep execution decisions bound to the exact receipt-chain head used during evaluation, retrying safely after compare-and-set contention.
- Accept both direct Upstash and Vercel KV credential names for durable production storage.
- Make ephemeral storage explicit through readiness warnings and production write refusal.

### Fixed

- Prevent concurrent evaluators from committing stale duplicate-check decisions.
- Prevent malformed or unresolved Nexus evidence from reaching a receipt.
