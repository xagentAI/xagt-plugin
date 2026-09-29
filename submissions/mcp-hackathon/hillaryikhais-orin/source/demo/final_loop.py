#!/usr/bin/env python3
"""ORIN final loop — the 15-step demo. Usage: python3 demo/final_loop.py [base_url]"""
import json, sys, urllib.request

BASE = (sys.argv[1] if len(sys.argv) > 1 else "http://localhost:8001").rstrip("/")
CAP = "invoice.duplicate_detection"

def post(p, b):
    r = urllib.request.Request(BASE + p, data=json.dumps(b).encode(),
                               headers={"Content-Type": "application/json"}, method="POST")
    return json.load(urllib.request.urlopen(r))

def get(p):
    return json.load(urllib.request.urlopen(BASE + p))

def step(n, label, val):
    print(f"{n:2}. {label}\n    -> {json.dumps(val)[:180]}")

AG = {"agent_id": "agent-X", "version": "v1", "code": "det-v1", "model": "m1",
      "prompt": "p1", "tools": ["read"], "skills": ["dup"], "config": {}, "env": "prod"}
AGB = dict(AG, agent_id="agent-B")
INV = {"a": {"number": "INV-1", "amount": 10.0}, "b": {"number": "INV-1", "amount": 10.0}}

step(1, "Agent discovers Skill", get("/health"))
step(2, "ORIN evaluates it", post("/capabilities/declare", AG))
ev = post("/evaluations/create", {"agent_id": "agent-X", "capability": CAP})
r = post("/evaluations/run", {"eval_id": ev["eval_id"]})
step(3, "ORIN produces proof", r["proof"]["proof_id"])
step(4, "Capability becomes ADMITTED", get(f"/capabilities/agent-X/{CAP}/admission"))
step(5, "Harness permits real execution", post("/harness/invoke", {"agent_id": "agent-X", "capability": CAP, "skill_input": INV}))
post("/capabilities/declare", AGB)
post("/evaluations/create", {"agent_id": "agent-B", "capability": CAP})
post("/evaluations/run", {"eval_id": post("/evaluations/create", {"agent_id": "agent-B", "capability": CAP})["eval_id"]})
d = post("/delegations", {"delegator": "agent-X", "delegatee": "agent-B", "capability": CAP})
step(6, "Agent delegates it", d)
step(7, "Delegated capability executes", post("/harness/invoke", {"agent_id": "agent-B", "capability": CAP, "skill_input": INV}))
post("/capabilities/declare", dict(AGB, model="m9"))
step(8, "Execution surface changes", {"agent_id": "agent-B", "model": "m9"})
step(9, "ORIN marks proof STALE", get(f"/capabilities/agent-B/{CAP}/status"))
step(10, "Harness blocks the next invocation", post("/harness/invoke", {"agent_id": "agent-B", "capability": CAP, "skill_input": INV}))
step(11, "Delegation becomes invalid", get(f"/delegations/{d['delegation_id']}"))
ev2 = post("/evaluations/create", {"agent_id": "agent-B", "capability": CAP})
r2 = post("/evaluations/run", {"eval_id": ev2["eval_id"]})
step(12, "Re-evaluation runs", r2["summary"])
step(13, "New proof issued", r2["proof"]["proof_id"])
step(14, "Capability becomes ADMITTED", get(f"/capabilities/agent-B/{CAP}/admission"))
step(15, "Same invocation succeeds", post("/harness/invoke", {"agent_id": "agent-B", "capability": CAP, "skill_input": INV}))
print("\nFINAL LOOP OK")
