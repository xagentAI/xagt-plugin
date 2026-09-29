# Polymarket Core Wallet Identity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the Polymarket binding flow reuse and enforce the wallet already bound in Clink Core, while matching the Core Account visual language and removing duplicate spending controls.

**Architecture:** Core exposes the canonical active wallet through its protected readiness contract. Prediction Markets consumes that contract server-side, rejects missing or mismatched identities, and renders a venue-only CLOB authorization page. Browser checks improve feedback, while backend checks remain authoritative.

**Tech Stack:** FastAPI, Pydantic, SQLAlchemy repository layer, server-rendered HTML/CSS/JavaScript, injected EIP-1193 wallet providers, pytest, Python smoke scripts.

## Global Constraints

- Core Account is the sole wallet identity and spending-grant authority.
- Polymarket authorization must use the active Core wallet.
- Prediction Markets must not create or revoke spending grants.
- No private keys, seed phrases, or API secrets enter browser responses or logs.
- Existing internal bearer-token protection remains mandatory.

---

### Task 1: Extend Core readiness identity contract

**Files:**
- Modify: `clink-core/services/account_service/app.py`
- Modify: `clink-core/tests/test_account_console.py`

**Interfaces:**
- Produces: `GET /internal/account-readiness` fields `wallet_address: str | null` and `wallet_identity_id: str | null`.

- [ ] Write API tests asserting an unbound user returns null identity fields and a verified user returns its canonical wallet address and identity ID.
- [ ] Run the focused tests and confirm they fail because the fields are absent.
- [ ] Add the two fields from the first active wallet identity without weakening internal-token authentication.
- [ ] Run the focused tests and confirm they pass.
- [ ] Commit the Core contract change.

### Task 2: Enforce Core wallet in Polymarket binding

**Files:**
- Modify: `clink-prediction-markets/shared/core_account_client.py`
- Modify: `clink-prediction-markets/services/account_binding_service/app.py`
- Modify: `clink-prediction-markets/scripts/polymarket_account_binding_api_smoke.py`

**Interfaces:**
- Consumes: Core readiness `wallet_bound` and `wallet_address`.
- Produces: server-side `require_core_wallet(user_id, submitted_wallet=None) -> dict` behavior with HTTP 409 for missing or mismatched identity.

- [ ] Add smoke cases for missing Core wallet, matching wallet, and mismatched wallet completion.
- [ ] Run the smoke test and confirm the new cases fail.
- [ ] Gate session creation and completion with Core readiness and canonical address comparison.
- [ ] Run the smoke test and confirm all cases pass.
- [ ] Commit the backend enforcement.

### Task 3: Rebuild the Polymarket authorization page

**Files:**
- Modify: `clink-prediction-markets/services/account_binding_service/app.py`
- Modify: `clink-prediction-markets/scripts/polymarket_account_binding_console_markup_smoke.py`

**Interfaces:**
- Consumes: expected Core wallet embedded by the backend.
- Produces: Core-style four-section page with provider selection, same-wallet validation, CLOB authorization, and Polymarket account controls.

- [ ] Update markup assertions for Core-style masthead, indexed sections, expected wallet, and venue-only actions; assert spending-cap controls are absent.
- [ ] Run the markup smoke and confirm it fails against the current page.
- [ ] Replace the gradient/card page with the Core Account visual tokens and ledger layout.
- [ ] Retain Browser Wallet, OKX, and MetaMask provider detection; disable CLOB authorization until the connected wallet matches Core.
- [ ] Remove spending authorization, funding readiness, allowance transaction, and spending-cap revocation JavaScript.
- [ ] Run markup and binding smoke tests and confirm they pass.
- [ ] Commit the page redesign.

### Task 4: Documentation and cross-project regression

**Files:**
- Modify: `clink-prediction-markets/README.md`
- Modify: `clink-prediction-markets/docs/hermes_operator_prompt.md`

**Interfaces:**
- Produces: one canonical explanation of Core wallet binding versus Polymarket CLOB authorization.

- [ ] Document that the user connects the same wallet on the Polymarket page but does not bind Core again.
- [ ] Update Hermes language to say `Connect Core wallet` and `Authorize Polymarket`.
- [ ] Run Core focused tests, Prediction binding/API/markup smokes, Python compile checks, and diff checks.
- [ ] Confirm no spending-cap controls remain in the Polymarket page and no internal token is exposed.
- [ ] Commit documentation and verification updates.
