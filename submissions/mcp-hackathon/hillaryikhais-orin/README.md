# ORIN — capability admission backed by execution

> **ORIN turns demonstrated capability into a live admission state that governs execution, delegation, and composition.**
> **Change the execution conditions, and the admission — and everything that depended on it — dies automatically.**

Not certification, not a benchmark, not a rating, not agent security. One operational question:

> **Can this exact agent perform this exact capability under this exact execution surface, right now?**

```
DISCOVER → PROVE → CONTRACT → ADMIT (escrow) → DELEGATE → COMPOSE → EXECUTE → CHECK → INVALIDATE → RE-PROVE
```

An agent is not admitted because it claims a capability. It is admitted because **it demonstrated it** — 50 repeatable challenges + 10 hidden adversarial, no LLM judge — and ORIN issues a signed, scope-bound, fingerprint-bound proof. Admission is a **live state**, derived from current evidence at every call: mutate the tool surface and the proof goes STALE, the delegation REVOKES itself, the composition INVALIDATES, and the Harness DENIES the invocation — no human revoke button.

## Capability Contracts: what may run, under which conditions, and what happens when they change

Every admitted capability is governed by an explicit **contract** — the machine-evaluable link between evidence and executable capability:

```
{
  "scope":      {"max_amount": 100},                       # what is allowed
  "conditions": {"chain": "eth", "tool_surface": "read"},  # what the proof requires
  "materiality":{ "chain": "INVALIDATE",                   # why it was proven
                  "tool_surface": "REVALIDATE",
                  "logging": "IGNORE" }
}
```

- **Admission = escrow.** `POST /capabilities/:id/admit` renders a *bounded* executable capability lease: it binds the active proof, so the admitted scope is capped by what was actually demonstrated — never more.
- **CHECK is the money call.** The runtime asks *"may this happen right now?"* before executing:
  - `ALLOW` — proof fresh, conditions hold, request inside scope.
  - `DENY MATERIAL_DRIFT` — an `INVALIDATE` condition changed (e.g. new chain): capability does **not** run on the new surface.
  - `DENY REVALIDATION_REQUIRED` — a `REVALIDATE` condition changed (e.g. new tool surface): gate until re-proven.
  - `DENY SCOPE_EXPANSION` — the request exceeds the escrowed scope even though evidence is valid.
  - `DENY ADMISSION_SUPERSEDED / REVALIDATION_REQUIRED (stale)` — proof replaced or execution surface mutated.
- **Drift is classified, not blindly invalidated.** `IGNORE` changes are observed and recorded (`POST /capabilities/:id/observe`) while execution continues; only material drift blocks. If a batch contains both, the DENY response reports the material cause *and* the observed non-material changes.
- **Constraint intersection in composition.** A composition's authority is the **intersection** of its members' contracted scopes (`min` for numeric limits, exact match for labels; conflicting labels → ADMITTED members can't compose). When a member re-proves with a narrower scope, the composite scope narrows — it can never expand.
- **Delegation cannot mint authority.** Delegated scope = delegator's grant ∩ delegatee's *proven* scope ∩ delegation constraints. A delegatee is capped by what it has independently demonstrated; denying SCOPE_CONFLICT keeps cross-chain grants impossible.

## Differential proof: the same workflow, WITH and WITHOUT ORIN

`python3 demo/differential.py` runs one job twice. **Without ORIN** the skill just executes — scorecards live inside the agent, no gate, so a drifted chain is processed. **With ORIN** the same drift is classified at CHECK: `INVALIDATE` blocks the call, `IGNORE` is observed, `REVALIDATE` gates until re-proven — then revalidation restores admission and exactly the same call `ALLOW`s. One job, one difference: ORIN.

## The runtime decision path

**X-Agent Harness → ORIN admission → Skill execution.** The Harness consumes ORIN's admission state *before* the Skill executes:

```
ADMITTED    → route call
CONSTRAINED → route call, restricted
STALE       → deny
UNPROVEN    → deny
REVOKED     → deny
```

Every harness decision is audit-logged (`GET /harness/audit`). The 15-step final loop (`python3 demo/final_loop.py`): discover → evaluate → proof → contract → ADMITTED → harness executes → delegate → delegated execution → surface mutates → STALE → harness blocks → delegation REVOKED → re-evaluate → new proof → RE-ADMITTED → same invocation succeeds.

## What ORIN decides — and what it doesn't

**X-Agent (or any runtime) controls whether an agent may execute. ORIN provides the missing state: currently demonstrated, therefore eligible for this execution.**

X-Agent's runtime asks: *can this action execute?* ORIN answers: *has this capability been demonstrated, and is that evidence still valid?*

```
ORIN admission → runtime authorization → execution
```

Layers shipped: **Evaluation → Proof → Admission → Delegation → Composition → Execution gate → Continuous validity.** Delegation is conditional on demonstrated capability (not identity), compositions assemble from currently admitted components with propagation naming the cause, and every mutation auto-revokes downstream admissions.

## Run

```
pip install -r requirements.txt
uvicorn orin.api:app --port 8001
python3 -m pytest orin/ -q   # 31 tests: gate, governance loop, fuzz, overclaim, tamper, hidden, contract/drift, differential, API/MCP
python3 demo/differential.py http://localhost:8001   # one job, WITH vs WITHOUT ORIN
```

Public deployment check: `./verification/orin-smoke.sh https://<your-app>`

## API / MCP

- `POST /capabilities/declare`, `POST /evaluations/create`, `POST /evaluations/run`, `GET /evaluations/:id`, `GET /capabilities/:agent/:cap/proof|status|admission`
- `POST /capabilities/contract` (create contract: scope/conditions/materiality), `POST /capabilities/:id/admit` (escrow), `POST /capabilities/:id/check` (**may this run right now?**), `POST /capabilities/:id/observe` (record IGNORE drift), `GET /capabilities/:id/status`
- `POST /delegations`, `GET /delegations/:id`, `POST /compositions`, `GET /compositions/:id`, `POST /execute`
- MCP `POST /mcp`: `orin.verify_capability`, `orin.get_proof`, `orin.check_status`, `orin.request_evaluation`, `orin.check_admission`, `orin.delegate_capability`, `orin.compose_capabilities`, `orin.execute_gate`, `orin.harness_invoke`, `orin.create_contract`, `orin.admit_contract`, `orin.check_capability`

## Invariants I1–I15

No proof without a passing evaluation; failed required test blocks VERIFIED; proof bound to agent fingerprint; material change → STALE; capability A proof never authorizes B; tampered evidence never verifies; hidden challenges never exposed; repeatable re-run; history immutable; STALE never returns VERIFIED; delegation requires both sides currently ADMITTED and auto-revokes on surface change; composition requires all components ADMITTED with named propagation; execution gate ALLOW only on current admission; revocation is automatic — the proof invalidates itself because the thing it proved changed; delegated authority is the intersection of grant, provable scope, and delegation constraints (no authority minting) and composite scope is the intersection of member scopes (narrowing propagates).
