# Public visitor demo implementation plan

Goal: visitors can click “开始演示”, receive a private browser session with their own 1.00 simulated-USDC budget, buy the CSV service, reload and replay without entering a deployment token. Preserve the existing private machine API and its original order/budget. Refreshing or reusing an existing session never creates a new spending grant.

Architecture: HttpOnly same-site cookie authenticates a random persisted visitor session. Each visitor has an isolated state directory containing the existing Core and Marketplace implementation. A single additional guest worker is reused for the current visitor, closed on tenant switch, and reopened from persisted state. One async operation lock bounds guest concurrency; the existing private review worker remains separate. Core continues to own spending authorization, budget and settlement. All demo settlement is simulated.

Global constraints:
- Source repo base: 79b657e7c63158fafc657cf6370048bcde384c57; branch codex/public-demo-sessions.
- Preserve /v1 Bearer authentication and original state; add /demo/session and /demo/v1 cookie routes.
- Cookie name agentonomy_demo; random 32-byte URL-safe secret, only SHA-256 stored. HttpOnly, SameSite=Strict, Path=/, no Domain; Secure for HTTPS deployment. Never return the credential in JSON, JS or logs.
- Session lifetime 7 days; maximum 128 stored sessions; at most 10 new sessions per rolling minute. Expired guest state can be removed only under the guest-operation lock and only inside the dedicated public-demo/sandboxes root. Never delete/reset a valid session, baseline state, original evidence, or grant to recover from errors.
- Mutating demo requests require Origin equal to configured demo_origin. Demo disabled unless AGENTONOMY_DEMO_ORIGIN is set to an exact allowed origin; plain HTTP only for localhost/127.0.0.1/::1 development.
- Per-session request cap settings.requests_per_minute (default 60); global guest cap 2x that (120). Session bootstrap cap 20 requests/minute, in addition to 10 new identities/minute. Authenticate before buffering API inputs, 256 KiB body limit, 10-second body timeout.
- Guest worker uses merchant port 0 (OS-assigned loopback); existing ReviewRuntime supports it. Only one additional Marketplace/Core/merchant composition at a time. Waiting for the guest lock is bounded to 2 seconds; operation timeout 50 seconds. Timeout/cancellation must close/terminate the owning guest process before unlocking; persistence remains intact.
- Public session ID is 32 lowercase hex, a noncredential for segregating browser saved order IDs. Server never accepts a session directory or tenant ID from body/query as authority.
- User-supplied identity/pricing/budget overrides remain forbidden. No real funds, production accounts, user private keys or email provider setup.

Task 1: persistent session store and guest worker owner
Files: new agentonomy_commerce/demo_sessions.py; tests/commerce/test_demo_sessions.py only.
Interfaces:
  DemoError(code: str, status: int)
  DemoSession(session_id: str, expires_at: int) immutable dataclass
  DemoSessions(state_dir: Path, *, clock=time.time, ttl_seconds=604800, max_sessions=128, creations_per_minute=10)
  start() -> None; resolve(token: str|None) -> DemoSession|None; create() -> tuple[DemoSession,str]; expired() -> list[DemoSession]; discard_expired(session: DemoSession) -> None; directory(session: DemoSession) -> Path
  DemoRuntime(sessions: DemoSessions, bridge_factory, *, lock_timeout=2, call_timeout=50)
  async start_session(token: str|None) -> tuple[DemoSession,str|None] (existing valid cookie returns same identity and None; otherwise clean expired safely then create)
  async call(token: str, method: str, arguments: dict|None=None) -> dict (re-resolve after taking lock; initialize/reuse worker; no other tenant's state)
  async close() -> None
- Start sessions SQLite under state_dir/public-demo/, sandbox paths under public-demo/sandboxes/<validated hex ID>; row contains token digest, ID, creation and expiry only.
- SQLite file/directory permissions restricted; failed/corrupt ledger must fail closed. No recovering by deleting registry or auto-funding an existing session.
- Worker construction: bridge_factory(sessions.directory(session), worker_module='agentonomy_commerce.worker', worker_args=('0',)); initial request('snapshot') validates readiness, then request(method, arguments). On switch close old worker before constructing next; saved Core/Marketplace data reused.
- All operation results returned unchanged; API maps _error using existing codes. On worker exception/timeout, invalidate/close only guest worker, not baseline or persisted state. No worker operation on resolve/auth errors. Preserve cancellation lock discipline.
- Tests first: credential hashing/no plaintext, existing session reuse, tamper/expiry, creation/cap limits, restart lookup, safe expiry deletion scope, A->B->A state/worker closure, simultaneous serialization, timeout cleanup, failure no session budget reset. Mock bridge tests never contact network.

Task 2: API/settings integration (main agent)
Files: agentonomy_commerce/settings.py, api.py; new tests/commerce/test_demo_api.py; Makefile test-review includes new tests.
- Add Settings.demo_origin: str|None=None, strict origin normalization, env read.
- Instantiate DemoSessions/DemoRuntime in app lifespan only if enabled; close guest runtime on shutdown. Existing private worker lifecycle/health unchanged.
- GET /demo/session returns {enabled,authenticated} plus session_id/expires_at if valid, no credential. POST accepts empty object only, validates Origin and rate, creates/reuses session and sets cookie only for new session. Never returns private API token. GET is the refresh restore check.
- Add /demo/v1/services,/budget,/previews,/purchases,/purchases/{id} aliases to existing handlers, passing Request through shared call() to select guest runtime from cookie. Cookie grants no access to /v1 and Bearer token grants no implicit guest identity.
- Extend middleware with separate session/rate/Origin checks without weakening legacy auth/body limits.
- Tests first: anonymous status, no-token creation, secure cookie flags, no secret in body, blocked cross-origin/missing Origin, invalid/expired cookies, privileged API still 401, caller identity override rejected, guest source selection, rate/body limits.
- Real worker integration: two separate TestClient cookie jars share app; A buys sample, B cannot read A order/execute A preview and retains 1.00; A replay remains .30/1 settlement/1 delivery; restart app and A cookie reopens same state. Use synthetic CSV and simulated settlement only.

Task 3: browser UX (bounded UI worker)
Files: agentonomy_commerce/static/index.html, app.js, style.css only.
- Preserve visual style. Replace token input/connect form with '开始演示' button; explain own 1.00 simulated budget, no registration and no real money. Default synthetic CSV present so start->quote->purchase is immediately discoverable.
- Startup GET /demo/session, restore existing session automatically, otherwise show Start. POST {} /demo/session on explicit click; all capability fetches /demo/v1/* with credentials:'same-origin'. Browser supplies same-origin Origin on POST. No Authorization header or token input/state.
- Request 401 clears active UI session and asks to start; do not auto-create new session or purchase on retry. All actions have loading/error states and preserve current preview/idempotency key after uncertain purchase.
- Save only nonsecret session_id, preview_id, previewKey, purchase_id in sessionStorage; do not store CSV or credentials. On reload restore saved IDs only if session_id matches server; GET existing order and budget, never charge automatically. Same paid preview replay remains possible after reload.
- Show session expiry politely and clear capacity/429/unavailable errors. Disable start when demo not enabled. Budget panel is visitor-specific. Remove shared-budget/token instructions from visible copy.
- Run JS syntax check and report changed handlers for GitNexus impact before editing existing functions. Main performs real browser verification.

Task 4: verification, docs, deploy and PR update (main)
- Update README/deployment/walkthrough and current submission to public browser flow while retaining machine API instructions separately. Add public demo verification script/cookie-jar examples without secrets.
- Run test-review/test-commerce and relevant existing regression, browser test with two independent sessions, reload/replay, unauthorized and origin rejection; independent review for session isolation and resource/lock lifecycle.
- GitNexus impact before existing symbol edits and detect-changes before commit. Review generated-file changes out of scope.
- Commit/push tested source, complete CI, update only dedicated review VM startup/env with demo_origin. Preserve private baseline state and original first order. Verify anonymous public flow on fresh guest session and persistence across container restart; keep original admin replay acceptance.
- Re-export exact new commit, refresh source hashes/evidence/RIGHTS unchanged scope, run official offline+online validation, update existing PR #83 and restore it from draft. Never create duplicate submission PR, publish cookies/tokens, modify DEV/PROD, register SSH keys or rewrite prior source history.
