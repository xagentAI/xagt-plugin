# Core Account Entry Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Expose the existing Clink Core Account wallet and spending-cap setup through a safe Prediction Markets backend endpoint, MCP link relay, and dashboard action.

**Architecture:** Add a focused shared Core Account HTTP client that owns bearer-token authentication. The Prediction Markets account-binding service exposes browser-safe proxy routes, while the MCP server uses the same client and keeps readiness read-only. Core remains the system of record; Polymarket account binding remains independent.

**Tech Stack:** Python 3.11, urllib, FastAPI, FastMCP, React/Vite, script-based smoke tests.

## Global Constraints

- Never expose `CLINK_CORE_INTERNAL_API_TOKEN` to browsers, MCP responses, logs, or errors.
- Creating a Core Account session must require an explicit POST/tool action.
- Readiness must read Core wallet/grant state and must not create account sessions.
- Polymarket binding state must not be used as Core wallet-binding state.

---

### Task 1: Shared Core Account Client And Configuration

**Files:**
- Create: `shared/core_account_client.py`
- Modify: `shared/config.py`
- Modify: `.env.example`
- Test: `scripts/core_account_client_unit_smoke.py`

**Interfaces:**
- Produces: `CoreAccountClient(base_url: str, internal_token: str)` with `readiness(user_id: str) -> dict` and `create_setup_link(user_id: str) -> dict`.
- Produces: `AppConfig.clink_core_account_service_url` and `AppConfig.clink_core_internal_api_token`.

- [ ] **Step 1: Write a failing client smoke test** that runs a local HTTP server, asserts `POST /internal/account-sessions`, verifies the bearer token and exact `{"user_id": ...}` body, and verifies GET readiness query encoding.
- [ ] **Step 2: Run `python3 scripts/core_account_client_unit_smoke.py`** and confirm it fails because `shared.core_account_client` does not exist.
- [ ] **Step 3: Implement the minimal authenticated client and configuration fields**. Reject missing URL/token before issuing a request, preserve Core 4xx status in sanitized errors, and validate that session responses contain an HTTP(S) `account_url`.
- [ ] **Step 4: Run the client smoke test** and confirm it passes.
- [ ] **Step 5: Commit the client/configuration slice**.

### Task 2: MCP Tool And Correct Product Readiness

**Files:**
- Modify: `mcp_servers/prediction_markets_server.py`
- Create: `scripts/core_account_entry_mcp_unit_smoke.py`
- Modify: `scripts/user_readiness_mcp_unit_smoke.py`

**Interfaces:**
- Consumes: `CoreAccountClient.readiness()` and `CoreAccountClient.create_setup_link()`.
- Produces: MCP tool `create_core_account_setup_link(user_id: str) -> dict`.
- Produces: readiness fields `core_account`, `wallet_bound`, `spending_authorization_ready`, and ordered `next_action`.

- [ ] **Step 1: Write failing MCP tests** proving the setup tool returns `pending_user_action`, `account_url`, `expires_at`, and `next_action=open_core_account_url`; prove readiness returns `create_core_account_setup_link` when Core wallet/grant state is missing, even if Polymarket is also unbound.
- [ ] **Step 2: Run both MCP smoke tests** and confirm failure for the missing tool and current Polymarket-derived wallet state.
- [ ] **Step 3: Implement the MCP tool and query Core readiness independently**. Determine next action in this order: Core wallet/grant, Polymarket binding, deposit wallet, execution readiness.
- [ ] **Step 4: Run both MCP smoke tests** and confirm they pass.
- [ ] **Step 5: Commit the MCP/readiness slice**.

### Task 3: Browser-Safe Account Routes And Dashboard Entry

**Files:**
- Modify: `services/account_binding_service/app.py`
- Modify: `dashboard_frontend/src/App.jsx`
- Modify: `dashboard_frontend/src/styles.css`
- Create: `scripts/core_account_dashboard_smoke.py`

**Interfaces:**
- Produces: `GET /clink/account/readiness?user_id=...`.
- Produces: `POST /clink/account/setup-link` with body `{"user_id": "..."}`.
- Dashboard consumes both through `/account-api` and redirects only after a successful explicit button click.

- [ ] **Step 1: Write a failing dashboard/service smoke test** proving both routes delegate to the shared client and that the frontend contains separate `Core Account` and `Polymarket Account` sections plus the `Open Core Account` action.
- [ ] **Step 2: Run `python3 scripts/core_account_dashboard_smoke.py`** and confirm it fails because the routes and UI action are missing.
- [ ] **Step 3: Implement the proxy routes and dashboard state/action**. Keep Core wallet/grant cards separate from Polymarket CLOB binding; open the returned URL in the same browser tab.
- [ ] **Step 4: Run the dashboard smoke test and `npm run build`** and confirm both pass.
- [ ] **Step 5: Commit the dashboard slice**.

### Task 4: Operator Documentation And Regression Verification

**Files:**
- Modify: `docs/hermes_operator_prompt.md`
- Modify: `README.md`

**Interfaces:**
- Documents: Hermes may call `create_core_account_setup_link` only to relay the user-controlled page; it may never use shell/Python or conflate Core Account with Polymarket CLOB binding.

- [ ] **Step 1: Update operator and deployment documentation** with the two independent binding flows and required `CLINK_CORE_ACCOUNT_SERVICE_URL` / `CLINK_CORE_INTERNAL_API_TOKEN` configuration.
- [ ] **Step 2: Run all new smoke tests plus existing account-binding, readiness, MCP-surface, and dashboard design smokes**.
- [ ] **Step 3: Run `git diff --check` and inspect the final diff for token leakage or unrelated changes**.
- [ ] **Step 4: Commit the documentation and verification slice**.
