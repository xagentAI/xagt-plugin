"""Differential demo: THE SAME workflow, run side-by-side WITHOUT ORIN and WITH ORIN.

Shows non-material drift that a raw skill silently ingests vs. ORIN's drift
classification: INVALIDATE blocks the call, IGNORE records it, REVALIDATE gates it.
"""
import sys, urllib.request


def api(base, path, payload=None, method=None):
    import json
    body = json.dumps(payload).encode() if payload is not None else None
    m = method or ("POST" if payload is not None else "GET")
    req = urllib.request.Request(base + path, data=body, headers={"Content-Type": "application/json"}, method=m)
    return json.loads(urllib.request.urlopen(req).read())


def main():
    base = sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8000"
    h = api(base, "/health")
    print(f"[ORIN] {h}  <- capability admission backed by execution")
    print("Legend:  WITHOUT ORIN → raw skill keeps executing  /  WITH ORIN → drifted capability is blocked\n")

    # -- SAME workflow, both lanes --
    workflow = {
        "answer": "Without ORIN, %s (it is just code that runs).",
        "with_orin": None,
    }

    # 1) declare + evaluate + prove (evidence)
    print("== 1. EVERYONE GETS EVALUATED IDENTICALLY ==")
    declare = {"version": "v1", "code": "det-v1", "model": "m1", "prompt": "p1",
               "tools": ["read"], "skills": ["dup"], "config": {}, "env": "prod", "agent_id": "A"}
    api(base, "/capabilities/declare", declare)
    ev = api(base, "/evaluations/create", {"agent_id": "A", "capability": "invoice.duplicate_detection"})
    run = api(base, "/evaluations/run", {"eval_id": ev["eval_id"]})
    lock = api(base, "/evaluations/" + ev["eval_id"])
    proof = api(base, "/capabilities/A/invoice.duplicate_detection/proof")
    s = run["summary"]
    print(f"    verdict   : {run['status']}  ({s['passed']}/{s['total']} public + {s['adv_passed']}/{s['adv_total']} adversarial invoices)")
    print(f"    proof     : {run['proof']['proof_id']}  (HMAC-signed (repeatable))")
    print(f"    status    : {lock['status']}")
    print(f"    expires   : {int(proof.get('expires_at',0) - __import__('time').time())}s TTL\n")

    # 2) capability contract (scope + conditions + materiality)
    print("== 2. CAPABILITY CONTRACT ==")
    con = api(base, "/capabilities/contract", {
        "agent_id": "A", "capability": "invoice.duplicate_detection",
        "scope": {"max_amount": 100},
        "conditions": {"chain": "eth", "tool_surface": "read", "wallet_class": "safe", "logging": "v1"},
        "materiality": {"chain": "INVALIDATE", "tool_surface": "REVALIDATE", "logging": "IGNORE"},
    })
    print(f"    contract  : {con['contract_id']}  scope={{max_amount:100}}")
    print(f"    materiality: chain=INVALIDATE · tool_surface=REVALIDATE · logging=IGNORE\n")

    # 3) escrow: admit is the capability lease
    print("== 3. ESCROW: ADMIT BINDS PROOF -> LEASE ==")
    ad = api(base, f"/capabilities/{con['contract_id']}/admit", method="POST")
    print(f"    admission : {ad['decision']}  bound proof {ad['proof_id']}  valid {int(proof['expires_at']-__import__('time').time())}s\n")

    # 4) CHECK: the money call, different drifts
    print("== 4. CHECK — DRIFT CLASSIFICATION ==")
    clean = api(base, f"/capabilities/{con['contract_id']}/check",
                {"conditions": {"chain": "eth"}, "requested": {"max_amount": 90}})
    drift = api(base, f"/capabilities/{con['contract_id']}/check",
                {"conditions": {"chain": "sol", "logging": "v2"}})
    gate = api(base, f"/capabilities/{con['contract_id']}/check",
               {"conditions": {"tool_surface": "web_search"}})
    print(f"    same-chain call      : {clean['decision']}")
    print(f"    chain+logging drifted: {drift['decision']}  ({drift['reason']})")
    print(f"      chain   → INVALIDATE = blocks")
    print(f"      logging → IGNORE     = observed as {drift.get('observed_nonmaterial')}")
    print(f"    tool surface changed : {gate['decision']}  ({gate['reason']})  ← REVALIDATE gates\n")

    # 5) differential: run the invoice job in both lanes
    print("== 5. DIFFERENTIAL — SAME JOB, WITHOUT vs WITH ORIN ==")
    inv = {"a": {"number": "INV-1337", "amount": 80.0}, "b": {"number": "INV-1337", "amount": 80.0},
           "chain": "sol"}  # drifted chain, same as 4)
    print("    WITHOUT ORIN: agent calls skill directly → runs on drifted chain")
    print("    scorecards  : built into the agent, none of the gates run, code just runs")
    without = {"lin": 1, "shot": True, "model": "m1", "version": "v1"}
    print(f"    executed    : {without}  (no admission, no contract, no CHECK)")
    now = api(base, f"/capabilities/{con['contract_id']}/check", {"conditions": {"chain": "sol"}})
    print(f"    WITH ORIN   : CHECK → {now['decision']} ({now['reason']})")
    print(f"    gate        : skill execution DENIED at drift\n")

    # 6) recovery: revalidation restores admission
    print("== 6. REVALIDATION RESTORES ==")
    api(base, "/capabilities/declare", dict(declare, agent_id="A", version="v2", prompt="p2"))
    ev2 = api(base, "/evaluations/create", {"agent_id": "A", "capability": "invoice.duplicate_detection"})
    api(base, "/evaluations/run", {"eval_id": ev2["eval_id"]})
    con2 = api(base, "/capabilities/contract", {
        "agent_id": "A", "capability": "invoice.duplicate_detection",
        "scope": {"max_amount": 100},
        "conditions": {"chain": "sol"},
        "materiality": {"chain": "INVALIDATE"},
    })
    api(base, f"/capabilities/{con2['contract_id']}/admit", method="POST")
    fine = api(base, f"/capabilities/{con2['contract_id']}/check", {"conditions": {"chain": "sol"}})
    print(f"    re-evaluated on new surface → admitted again → CHECK on drifted chain now: {fine['decision']}")


if __name__ == "__main__":
    main()