# Unified Wallet Authorization Core Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the Core wallet identity, cross-product spending grant, per-chain asset allowance, account console, and authorization-resolution foundation required by Prediction Markets and Marketplace.

**Architecture:** Add an `account_service` inside Clink Core with dedicated PostgreSQL tables for wallet identities, account sessions, spending grants, and asset allowances. The account service and funding service share the same Core database; funding resolves and row-locks grants before creating reservations, while vertical adapters only receive immutable references. Existing single-venue spending authorizations remain read-only during migration and are never promoted to cross-product grants automatically.

**Tech Stack:** Python 3.11+, FastAPI, Pydantic v2, SQLAlchemy 2, PostgreSQL 17, eth-account, pytest, browser EIP-191/EVM JSON-RPC.

## Global Constraints

- Core never stores user private keys or reusable raw ownership signatures.
- Product scopes are explicit; an empty product scope is invalid and no implicit `all` scope exists.
- One `(wallet identity, network, token, spender)` tuple maps to one asset allowance.
- Polygon and Base allowances are independent even when one spending grant covers both products.
- Increasing limits, adding products/networks/assets, or extending expiry requires a fresh wallet confirmation.
- Hermes never connects to Core MCP and cannot create, expand, pause, resume, reduce, or revoke user permissions.
- Platform credentials remain in vertical adapters.
- Public account routes use short-lived one-time sessions; internal APIs require `CLINK_CORE_INTERNAL_API_TOKEN`.
- Every write is idempotent and every budget reservation is atomic.

---

## File Structure

- Create `services/account_service/schemas.py`: Core account domain API models.
- Create `services/account_service/repository.py`: PostgreSQL repository and row-locking operations.
- Create `services/account_service/service.py`: wallet proof, grants, allowances, and resolution rules.
- Create `services/account_service/app.py`: public account console/session endpoints and protected internal endpoints.
- Create `services/account_service/console.py`: isolated HTML renderer for the account page.
- Create `migrations/versions/20260715_0003_unified_wallet_authorization.py`: production schema.
- Modify `services/funding_service/ledger.py`: share SQLAlchemy metadata and bind reservations to grants.
- Modify `services/funding_service/schemas.py`: grant/allowance references on reservation requests.
- Modify `services/funding_service/service.py`: resolution verification, atomic grant reserve/release/finalize.
- Modify `services/funding_service/app.py`: resolution and account-aware funding APIs.
- Modify `shared/config.py`, `.env.example`, `run_demo.sh`, `run_demo_stop.sh`, and `run_demo_status.sh`: account runtime configuration.
- Create focused tests under `tests/test_wallet_identity.py`, `tests/test_spending_grants.py`, `tests/test_asset_allowances.py`, `tests/test_authorization_resolution.py`, and `tests/test_account_console.py`.

---

### Task 1: Persistent Core Account Domain

**Files:**
- Create: `services/account_service/__init__.py`
- Create: `services/account_service/schemas.py`
- Create: `services/account_service/repository.py`
- Create: `migrations/versions/20260715_0003_unified_wallet_authorization.py`
- Test: `tests/test_account_repository.py`

**Interfaces:**
- Produces `AccountRepository(database_url: str)`.
- Produces `WalletIdentity`, `AccountSession`, `SpendingGrant`, and `AssetAllowance` Pydantic models.
- Produces repository methods `save_wallet_identity`, `active_wallet_identities`, `save_spending_grant`, `active_spending_grants`, `save_asset_allowance`, and `asset_allowances`.

- [ ] **Step 1: Write failing repository tests**

```python
def test_wallet_identity_and_allowance_uniqueness(tmp_path):
    repo = AccountRepository(f"sqlite+pysqlite:///{tmp_path/'core.db'}")
    identity = wallet_identity(user_id="u", wallet="0x" + "1" * 40)
    repo.save_wallet_identity(identity)
    assert repo.active_wallet_identities("u") == [identity]
    repo.save_asset_allowance(asset_allowance(identity.wallet_identity_id))
    with pytest.raises(ValueError, match="asset allowance already exists"):
        repo.save_asset_allowance(asset_allowance(identity.wallet_identity_id, allowance_id="other"))
```

- [ ] **Step 2: Run the test and verify it fails**

Run: `PYTHONPATH=. .venv/bin/python -m pytest -q tests/test_account_repository.py`

Expected: FAIL because `services.account_service` does not exist.

- [ ] **Step 3: Add typed domain models**

```python
class WalletIdentity(BaseModel):
    wallet_identity_id: str
    user_id: str
    chain_family: Literal["eip155"] = "eip155"
    wallet_address: str
    status: Literal["pending", "active", "suspended", "revoked"]
    proof_scheme: Literal["eip191"] = "eip191"
    proof_hash: str
    verified_at: datetime | None = None
    created_at: datetime
    updated_at: datetime

class SpendingGrant(BaseModel):
    spending_grant_id: str
    wallet_identity_id: str
    user_id: str
    agent_id: str
    status: Literal["pending", "active", "paused", "exhausted", "expired", "revoked"]
    max_amount_usdc: Decimal
    per_transaction_limit_usdc: Decimal
    daily_limit_usdc: Decimal
    used_amount_usdc: Decimal = Decimal("0")
    reserved_amount_usdc: Decimal = Decimal("0")
    product_scopes: list[str]
    venue_scopes: list[str] = []
    merchant_scopes: list[str] = []
    network_scopes: list[str]
    asset_scopes: list[str]
    starts_at: datetime
    expires_at: datetime
    created_at: datetime
    updated_at: datetime
```

- [ ] **Step 4: Add dedicated SQLAlchemy tables and migration**

Create tables `wallet_identities`, `account_sessions`, `spending_grants`, `asset_allowances`, and `spending_grant_daily_usage`. Use unique constraints for wallet identity and asset allowance scopes, JSON columns for explicit scope arrays, `NUMERIC(38, 6)` for USDC policy amounts, timezone-aware timestamps, and indexes on `user_id`, `status`, and expiry.

- [ ] **Step 5: Implement repository conversions and guarded upserts**

Repository methods must canonicalize EVM addresses to lowercase and use `SELECT ... FOR UPDATE` for grant mutation on PostgreSQL. SQLite tests may use a process lock but must preserve identical behavior.

- [ ] **Step 6: Run repository tests**

Run: `PYTHONPATH=. .venv/bin/python -m pytest -q tests/test_account_repository.py tests/test_funding_tx_hash_migration.py`

Expected: PASS.

- [ ] **Step 7: Commit**

```bash
git add services/account_service migrations/versions/20260715_0003_unified_wallet_authorization.py tests/test_account_repository.py
git commit -m "Add Core account authorization schema"
```

---

### Task 2: Wallet Identity Challenge And Verification

**Files:**
- Create: `services/account_service/service.py`
- Test: `tests/test_wallet_identity.py`

**Interfaces:**
- Consumes `AccountRepository` from Task 1.
- Produces `AccountService.create_wallet_challenge(user_id, wallet_address, return_url=None)`.
- Produces `AccountService.verify_wallet_challenge(session_id, signed_message, signature)`.
- Produces `AccountService.revoke_wallet_identity(wallet_identity_id)`.

- [ ] **Step 1: Write failing proof tests**

Cover successful recovery, wrong signer, altered message, expired session, repeated verification, another user's wallet replay, and revocation.

```python
session = service.create_wallet_challenge("u", account.address)
signature = Account.sign_message(
    encode_defunct(text=session.message_to_sign), account.key
).signature.hex()
identity = service.verify_wallet_challenge(session.session_id, session.message_to_sign, signature)
assert identity.status == "active"
with pytest.raises(ValueError, match="already consumed"):
    service.verify_wallet_challenge(session.session_id, session.message_to_sign, signature)
```

- [ ] **Step 2: Verify tests fail**

Run: `PYTHONPATH=. .venv/bin/python -m pytest -q tests/test_wallet_identity.py`

Expected: FAIL because `AccountService` is missing.

- [ ] **Step 3: Implement a canonical ownership message**

The signed text must include the exact service domain, user id, wallet address, session id, nonce, issued-at time, expiry, and purpose `clink_wallet_identity`. Reject a configured domain mismatch and any message not byte-identical to the persisted challenge.

- [ ] **Step 4: Verify EIP-191 recovery and consume sessions atomically**

Use `encode_defunct(text=message)` and `Account.recover_message`. Persist only `keccak(signature)`/message proof hash on the identity; mark the account session consumed in the same transaction.

- [ ] **Step 5: Implement revocation cascade**

Revoking an identity changes all active grants owned by that identity to `paused` with reason `wallet_identity_revoked`. It does not delete historical receipts or platform bindings.

- [ ] **Step 6: Run tests and commit**

Run: `PYTHONPATH=. .venv/bin/python -m pytest -q tests/test_wallet_identity.py tests/test_account_repository.py`

```bash
git add services/account_service/service.py tests/test_wallet_identity.py
git commit -m "Add verified wallet identities"
```

---

### Task 3: Spending Grants And Per-Chain Asset Allowances

**Files:**
- Modify: `services/account_service/schemas.py`
- Modify: `services/account_service/service.py`
- Test: `tests/test_spending_grants.py`
- Test: `tests/test_asset_allowances.py`

**Interfaces:**
- Produces `create_spending_grant(request)`, `pause_spending_grant`, `resume_spending_grant`, `reduce_spending_grant`, and `revoke_spending_grant`.
- Produces `verify_asset_allowance(wallet_identity_id, network, token_address, spender_address, allowance_tx_hash)`.
- Produces `refresh_asset_allowance(asset_allowance_id)`.

- [ ] **Step 1: Write failing scope and lifecycle tests**

Test explicit products, invalid empty scope, per-transaction/daily/total limits, expiry, pause/resume, reduce-only mutation, and rejection of any increase without a new wallet-confirmed account session.

- [ ] **Step 2: Write failing chain proof tests**

Use a fake RPC and assert receipt success, sender, token contract, `approve(address,uint256)` selector, spender, amount, and confirmation count. Confirm a Polygon allowance cannot satisfy a Base request.

- [ ] **Step 3: Implement grant validation**

```python
if not request.product_scopes:
    raise ValueError("at least one product scope is required")
if request.per_transaction_limit_usdc > request.max_amount_usdc:
    raise ValueError("per-transaction limit exceeds total grant")
if request.daily_limit_usdc > request.max_amount_usdc:
    raise ValueError("daily limit exceeds total grant")
```

Normalize and deduplicate every scope list. Only accept known product identifiers from configuration; initial values are `prediction_markets` and `marketplace`.

- [ ] **Step 4: Implement on-chain allowance verification**

Decode exact `approve(address,uint256)` calldata and persist a verified allowance only after required confirmations. Refresh with `eth_call allowance(owner,spender)` and mark an allowance `insufficient`, `revoked`, or `stale` when chain state changes.

- [ ] **Step 5: Run tests and commit**

Run: `PYTHONPATH=. .venv/bin/python -m pytest -q tests/test_spending_grants.py tests/test_asset_allowances.py`

```bash
git add services/account_service tests/test_spending_grants.py tests/test_asset_allowances.py
git commit -m "Add cross-product spending grants"
```

---

### Task 4: Authorization Resolution And Atomic Budget Reservation

**Files:**
- Modify: `services/account_service/schemas.py`
- Modify: `services/account_service/service.py`
- Modify: `services/funding_service/schemas.py`
- Modify: `services/funding_service/service.py`
- Modify: `services/funding_service/ledger.py`
- Test: `tests/test_authorization_resolution.py`
- Test: `tests/test_grant_reservations.py`

**Interfaces:**
- Produces `AuthorizationResolutionRequest` and `AuthorizationResolutionResult`.
- Produces `AccountService.resolve_authorization(request)`.
- Extends `CreateSpendingReservationRequest` with `wallet_identity_id`, `spending_grant_id`, `asset_allowance_id`, and `product`.

- [ ] **Step 1: Write failing resolution tests**

Assert exact matching for user, agent, product, venue, network, token, amount, date, identity status, grant status, and allowance status. Return structured reason codes such as `WALLET_IDENTITY_REQUIRED`, `SPENDING_GRANT_REQUIRED`, `ASSET_ALLOWANCE_REQUIRED`, `PRODUCT_SCOPE_MISMATCH`, and `BUDGET_EXCEEDED`.

- [ ] **Step 2: Write failing concurrent reservation tests**

Create a grant with 5 USDC remaining and run two 4 USDC reservations concurrently. Exactly one may succeed. Verify release restores reserved budget, settle moves reserved to used, and replay returns the original reservation.

- [ ] **Step 3: Implement resolution as readiness, not approval**

Resolution returns immutable references and remaining amounts but never returns `approved=true`. The next action must be `create_action_and_evaluate_policy` so policy/risk cannot be skipped.

- [ ] **Step 4: Bind action/policy/audit scope to grant references**

Add `product`, `wallet_identity_id`, `spending_grant_id`, and `asset_allowance_id` to the exact Marketplace/Prediction Market action, policy, audit, and reservation scopes. Reject reference changes on replay.

- [ ] **Step 5: Implement atomic grant accounting**

Within the Core database transaction, lock the grant, recompute total/daily/per-transaction availability, increment `reserved_amount_usdc`, and create the funding reservation. `settle` moves the amount from reserved to used; `release` removes reserved; terminal replay is idempotent.

- [ ] **Step 6: Run tests and commit**

Run: `PYTHONPATH=. .venv/bin/python -m pytest -q tests/test_authorization_resolution.py tests/test_grant_reservations.py tests/test_marketplace_reservations.py tests/test_marketplace_payment_reconciliation.py`

```bash
git add services/account_service services/funding_service tests/test_authorization_resolution.py tests/test_grant_reservations.py
git commit -m "Resolve and reserve unified spending grants"
```

---

### Task 5: Account Service API And User-Controlled Console

**Files:**
- Create: `services/account_service/app.py`
- Create: `services/account_service/console.py`
- Test: `tests/test_account_console.py`

**Interfaces:**
- Public one-time session routes serve wallet ownership and permission controls.
- Protected internal routes expose identity/readiness/resolution to vertical adapters.

- [ ] **Step 1: Write failing route security tests**

Assert public console sessions work only with one-time high-entropy tokens, internal APIs reject missing bearer tokens, session responses never expose internal tokens, and CSP forbids inline/external scripts.

- [ ] **Step 2: Add protected internal APIs**

```text
POST /internal/account-sessions
GET  /internal/wallet-identities?user_id=...
GET  /internal/spending-grants?user_id=...&status=active
POST /internal/authorization-resolution
GET  /internal/account-readiness?user_id=...
```

- [ ] **Step 3: Add public account APIs**

```text
GET  /account/{session_id}
POST /account/{session_id}/wallet-challenge
POST /account/{session_id}/wallet-verify
POST /account/{session_id}/grants
POST /account/{session_id}/allowances/verify
POST /account/{session_id}/grants/{id}/{pause|resume|reduce|revoke}
POST /account/{session_id}/wallet-identities/{id}/revoke
```

Every route verifies the session user and refuses cross-user object access.

- [ ] **Step 4: Build one focused account page**

The page displays Wallet, Permissions, Chain Allowances, and Recent Audit Summary. It uses one primary action per section, separates Polygon and Base approvals, clearly explains that platform bindings are managed by vertical products, and never accepts private keys or platform API secrets.

- [ ] **Step 5: Run tests and commit**

Run: `PYTHONPATH=. .venv/bin/python -m pytest -q tests/test_account_console.py tests/test_wallet_identity.py tests/test_spending_grants.py tests/test_asset_allowances.py`

```bash
git add services/account_service tests/test_account_console.py
git commit -m "Add Clink account permissions console"
```

---

### Task 6: Runtime, Configuration, Migration, And Core E2E

**Files:**
- Modify: `shared/config.py`
- Modify: `.env.example`
- Modify: `run_demo.sh`
- Modify: `run_demo_stop.sh`
- Modify: `run_demo_status.sh`
- Modify: `README.md`
- Create: `tests/test_unified_account_e2e.py`

**Interfaces:**
- Adds `ACCOUNT_SERVICE_HOST`, `ACCOUNT_SERVICE_PORT`, `CLINK_ACCOUNT_PUBLIC_BASE_URL`, `CLINK_ACCOUNT_SESSION_TTL_SECONDS`, and allowed product configuration.
- Produces a stable internal account URL consumed by vertical adapters.

- [ ] **Step 1: Write failing E2E test**

The test binds one wallet, creates a grant covering `prediction_markets` and `marketplace`, verifies Polygon and Base allowances, resolves both products, reserves and settles one request, revokes the grant, and confirms both products become unavailable.

- [ ] **Step 2: Add runtime configuration**

Start `account_service` with Core, include it in stop/status port cleanup, redact secrets from config descriptions, and document production HTTPS/base URL requirements.

- [ ] **Step 3: Preserve legacy data safely**

Expose legacy spending authorizations as read-only records with `legacy=true`. Do not use them during unified authorization resolution. Add an operator report listing users who must reauthorize; do not synthesize grants.

- [ ] **Step 4: Run migrations and complete Core regression**

Run:

```bash
PYTHONPATH=. .venv/bin/python -m alembic upgrade head
PYTHONPATH=. .venv/bin/python -m pytest -q -p no:cacheprovider
```

Expected: migration succeeds on a fresh and an existing database; all Core tests pass.

- [ ] **Step 5: Commit**

```bash
git add shared/config.py .env.example run_demo.sh run_demo_stop.sh run_demo_status.sh README.md tests/test_unified_account_e2e.py
git commit -m "Complete unified Core account foundation"
```

---

## Follow-On Plans

After this Core plan passes:

1. `clink-prediction-markets`: reference Core WalletIdentity, remove duplicate Clink binding signature, remove local spending-cap proxy/UI, auto-resolve grants for funding, and keep only Polymarket CLOB credentials in the adapter.
2. `clink-marketplace`: auto-resolve grants for Clink-native purchases, return Core account URL when no grant exists, retain external x402 checkout, and bind external payments to unified budget/audit references.
3. Cross-product production E2E: one wallet identity, one grant, two chain allowances, Polymarket funding, Marketplace Clink-native purchase, external x402 purchase, unified revocation, and dashboard/audit verification.
