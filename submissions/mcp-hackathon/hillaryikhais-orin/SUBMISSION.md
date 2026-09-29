# ORIN — capability admission backed by execution

> ORIN proves a capability, binds that proof to explicit execution conditions, and continuously decides whether that capability is still admissible.

## Capability

- **One-line description:** An agent asks "may this exact capability execute right now?" and ORIN answers from evidence-based — provable capability admission with materiality-classified drift, constraint intersection for delegation/composition, and escrowed scope.
- **Who it helps:** Any agent runtime (X-Agent is the reference environment) and any downstream system that must know whether a capability is *currently demonstrated* before authorizing its execution.
- **Capability boundary:** What it does: evaluate an agent's capability against 50 public + 10 hidden fixed challenges with no LLM judge; issue a signed, fingerprint-bound, scope-bound proof; bind that proof to an explicit Capability Contract (conditions + materiality); answer `CHECK` calls that classify drift by materiality (`INVALIDATE` blocks, `REVALIDATE` re-gates, `IGNORE` is observed); intersect authority in delegation and composition so scope can never expand; expose an execution gate the Harness consumes.

  What it does **not** do: on-chain security or auditing, vulnerability detection, wallet/transaction risk scoring, phishing/scam/rug-pull detection, benchmarks, certification, or ratings. It is a capability-admission primitive, not a security scanner.

## Live API

- **API base URL:** https://orin-md60.onrender.com
- **Health-check URL:** https://orin-md60.onrender.com/health
- **Authentication:** none (public read + capability lifecycle is idempotent and evidence-bound)
- **Rate limits / known limits:** none configured; evaluation is CPU-only (repeatable)
- **API contract:** `docs/orin-api.md` in `source/`; interactive OpenAPI at `/docs` on the live origin.

## Source and reproducibility

- **Source repository:** https://github.com/HillaryIkhais/orin
- **Review commit:** `ad71aec987e38aea9ef98039aadbc69fc40d672c`
- **Source submitted in this PR:** `source/`
- **Run tests:** `python3 -m pytest orin/ -q` (31 tests: gate, governance, harness, capability contracts, drift classification, constaint intersections, differential, API/MCP)
- **Run locally:** `pip install -r requirements.txt && uvicorn orin.api:app --port 8001`
- **Deploy:** `docker build -f Dockerfile.orin --build-arg GIT_SHA=ad71aec987e38aea9ef98039aadbc69fc40d672c -t orin . && docker run -p 8000:8000 orin` (or Render blueprint via `render.yaml`)
- **Version binding:** the deployed service reports `ORIN_COMMIT` (baked via Docker `GIT_SHA` build arg or deployed env var) in `/health` and `/.well-known/xagent-verification.json`.

The API exposes:

```json
// GET <health-check URL>
{"status":"ok","commit":"ad71aec987e38aea9ef98039aadbc69fc40d672c","service":"orin","version":"3.0.0"}
```

```json
// GET /.well-known/xagent-verification.json on the same API origin
{"schemaVersion":1,"slug":"hillaryikhais-orin","commit":"ad71aec987e38aea9ef98039aadbc69fc40d672c"}
```

## Verification

The reproducible call instructions and redacted example responses are in `verification/README.md`.

- **Health-check result:** `{"status":"ok","commit":"ad71aec987e38aea9ef98039aadbc69fc40d672c",...}` — see `verification/orin-smoke.sh`
- **Capability call:** `POST /capabilities/declare` → `POST /evaluations/create` → `POST /evaluations/run` → `GET /capabilities/:agent/:cap/proof` (also `POST /capabilities/contract` → `POST /capabilities/:id/admit` → `POST /capabilities/:id/check`)
- **Expected error behavior:** unknown capability → `NO_SUCH_CAPABILITY`; admission without a current proof → `UNPROVEN`/fail-closed; material drift → `DENY MATERIAL_DRIFT`; scope overrun → `DENY SCOPE_EXPANSION`.

## Security and data handling

- **Data collected:** only the agent fingerprint (repeatable hash of declared execution surface: code, model, prompt, environment) and evaluation results. No raw invoices, no wallet data, no secrets.
- **Purpose and retention:** fingerprints are hashed evidence and are never stored raw; in-memory only, cleared on restart.
- **Third parties / outbound network calls:** none. Evaluation is fully offline and repeatable.
- **Secrets:** No secrets are committed. Review access is supplied only through an approved private channel when required.
- **Known risks / restrictions:** nothing about ORIN proves that an agent is *safe* — only that it *can* perform a capability it was evaluated on. Do not use it as a security boundary.

## Support

- **Team / builder:** Hillary Ikhais
- **Contact:** https://github.com/HillaryIkhais
- **License / rights:** MIT; see `RIGHTS.md` for ownership declaration and third-party terms.