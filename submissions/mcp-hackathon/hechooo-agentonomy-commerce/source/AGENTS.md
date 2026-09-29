# Agentonomy Commerce engineering guide

Read README.md and docs/architecture.md before changing behavior.

Agentonomy Commerce exports the Clink runtime. Preserve the `clink_node` MCP
protocol and existing internal module names. Core remains the sole authority
for wallet identity, signed spending mandates, policy/risk, budget reservations,
funding and audit. Marketplace owns discovery, quotes, purchase and delivery.
No user private keys, seed phrases or MPC shares may be persisted.

All money uses deterministic precision. Money actions must be idempotent and
independently verified. A paid purchase with failed delivery must never charge
again on retry. A conversation confirmation does not replace a valid signature.

The local Commerce demo must be explicitly labelled simulated settlement; never
fall back from a real payment failure into a simulated success. Keep simulation
composition outside production service code. Do not contact production systems
or execute real funds as part of tests.

Check git status before editing. Use failing tests for behavior changes. Run
GitNexus impact before modifying existing symbols and detect-changes before a
commit. Run `make test-commerce` and relevant imported regression targets.
Do not commit runtime state, credentials, private deployment data or a virtualenv.
