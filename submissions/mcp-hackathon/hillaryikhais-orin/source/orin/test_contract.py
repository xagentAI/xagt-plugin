"""ORIN Capability Contract tests: materiality, drift classification, scope, intersections, differential."""
from orin.engine import protocol as P
from orin.engine import governance as G
from orin.engine import contract as CT

CAP = "invoice.duplicate_detection"
BASE = {"version": "v1", "code": "det-v1", "model": "m1", "prompt": "p1",
        "tools": ["read"], "skills": ["dup"], "config": {}, "env": "prod"}

def setup_function(_):
    P.AGENTS.clear(); P.EVALS.clear(); P.PROOFS.clear(); P.HISTORY.clear()
    P.HANDLERS.clear(); P._seq = 0
    G.reset()
    CT.CONTRACTS.clear()

def verify_agent(agent_id, capability=CAP):
    ev = P.create_evaluation(agent_id, capability)
    P.run_evaluation(ev["eval_id"])
    ev = P.verify(ev["eval_id"])
    if ev["status"] == "VERIFIED":
        P.issue_proof(ev["eval_id"])
    return ev

def admitted_contract(agent_id, capability=CAP, scope=None, conditions=None, materiality=None):
    c = CT.create_contract(None, agent_id, capability, scope=scope, conditions=conditions,
                           materiality=materiality)
    assert CT.admit(c["contract_id"])["decision"] == "ADMIT"
    return c["contract_id"]

def test_contract_requires_proof_at_admit():
    P.declare_agent(dict(BASE, agent_id="Z"))
    c = CT.create_contract(None, "Z", CAP)
    assert CT.admit(c["contract_id"])["decision"] == "DENY"  # no proof -> not bound (I1/I6)

def test_check_allow_with_scope_and_conditions():
    P.declare_agent(dict(BASE, agent_id="A"))
    verify_agent("A")
    cid = admitted_contract("A", scope={"max_amount": 50},
                            conditions={"chain": "C1", "wallet": "W1"})
    r = CT.check(cid, conditions={"chain": "C1", "wallet": "W1"}, requested={"max_amount": 40})
    assert r["decision"] == "ALLOW", r
    assert r["scope"] == {"max_amount": 50} and r["proof"]

def test_material_drift_invalidates():
    P.declare_agent(dict(BASE, agent_id="A"))
    verify_agent("A")
    cid = admitted_contract("A", scope={"max_amount": 50},
                            conditions={"chain": "C1", "wallet": "W1"})
    r = CT.check(cid, conditions={"chain": "C1", "wallet": "W2"})
    assert r["decision"] == "DENY" and r["reason"] == "MATERIAL_DRIFT", r
    assert r["changed"][0]["field"] == "wallet"

def test_nonmaterial_drift_continues_with_observe():
    P.declare_agent(dict(BASE, agent_id="A"))
    verify_agent("A")
    cid = admitted_contract("A", conditions={"wallet": "W1"},
                            materiality={"wallet": "IGNORE", "logging": "IGNORE"})
    r = CT.check(cid, conditions={"wallet": "W9", "logging": "v2"})
    assert r["decision"] == "ALLOW", r  # non-material -> CONTINUE not STALE
    assert r["observed_nonmaterial"]
    CT.observe(cid, [{"field": "logging", "from": "v1", "to": "v2"}])
    assert len(CT.CONTRACTS[cid]["observations"]) == 1

def test_revalidate_tier_requires_reevaluation():
    P.declare_agent(dict(BASE, agent_id="A"))
    verify_agent("A")
    cid = admitted_contract("A", conditions={"tool_surface": "T7"},
                            materiality={"tool_surface": "REVALIDATE"})
    r = CT.check(cid, conditions={"tool_surface": "T8"})
    assert r["decision"] == "DENY" and r["reason"] == "REVALIDATION_REQUIRED", r

def test_scope_expansion_blocked_even_when_evidence_valid():
    P.declare_agent(dict(BASE, agent_id="A"))
    verify_agent("A")
    cid = admitted_contract("A", scope={"max_amount": 50})
    r = CT.check(cid, requested={"max_amount": 120})
    assert r["decision"] == "DENY" and r["reason"] == "SCOPE_EXPANSION", r

def test_material_change_to_proof_surface_stale():
    P.declare_agent(dict(BASE, agent_id="A"))
    verify_agent("A")
    cid = admitted_contract("A", scope={"max_amount": 50})
    P.declare_agent(dict(BASE, agent_id="A", model="m8"))  # fingerprint change
    r = CT.check(cid, requested={"max_amount": 10})
    assert r["decision"] == "DENY" and r["reason"] == "REVALIDATION_REQUIRED", r

def test_delegation_authority_never_exceeds_proven_scope():
    P.declare_agent(dict(BASE, agent_id="A", tools=["read"]))
    P.declare_agent(dict(BASE, agent_id="B", tools=["read"]))
    verify_agent("A"); verify_agent("B")
    CT.admit(CT.create_contract(None, "A", CAP, scope={"max_amount": 50})["contract_id"])
    CT.admit(CT.create_contract(None, "B", CAP, scope={"max_amount": 10})["contract_id"])
    d = G.delegate("A", "B", CAP, scope={"max_amount": 30})
    assert d["state"] == "ADMITTED", d
    assert d["effective_scope"] == {"max_amount": 10}  # min(A granted 50, B proven 10, del 30) = 10
    a = G.admission("B", CAP)
    assert a["state"] == "ADMITTED" and a["constraints"][0]["scope"] == {"max_amount": 10}
    # B requesting within ITS effective scope routes; beyond blocks
    inv = {"a": {"number": "INV-1"}, "b": {"number": "INV-1"}, "max_amount": 10}
    assert G.harness_invoke("B", CAP, inv)["verdict"] == "ALLOW"
    inv5 = {"a": {"number": "INV-1"}, "b": {"number": "INV-1"}, "max_amount": 25}
    r = G.harness_invoke("B", CAP, inv5)
    assert r["verdict"] == "RESTRICTED", r

def test_delegation_scope_conflict_denied():
    P.declare_agent(dict(BASE, agent_id="A")); P.declare_agent(dict(BASE, agent_id="B"))
    verify_agent("A"); verify_agent("B")
    CT.admit(CT.create_contract(None, "A", CAP, scope={"currency": "USDC"})["contract_id"])
    CT.admit(CT.create_contract(None, "B", CAP, scope={"currency": "USDT"})["contract_id"])
    d = G.delegate("A", "B", CAP)
    assert d["state"] == "DENIED" and d["reason"] == "SCOPE_CONFLICT"

def test_composition_constraint_intersection_and_narrowing():
    P.declare_agent(dict(BASE, agent_id="A")); P.declare_agent(dict(BASE, agent_id="B"))
    P.declare_agent(dict(BASE, agent_id="C"))
    verify_agent("A"); verify_agent("B"); verify_agent("C")
    CT.admit(CT.create_contract(None, "A", CAP, scope={"max_amount": 1000})["contract_id"])
    CT.admit(CT.create_contract(None, "B", CAP, scope={"max_amount": 50})["contract_id"])
    CT.admit(CT.create_contract(None, "C", CAP, scope={"max_amount": 10})["contract_id"])
    wf = G.compose("process_invoice", [("A", CAP), ("B", CAP), ("C", CAP)])
    assert wf["state"] == "ADMITTED"
    assert wf["composite_scope"] == {"max_amount": 10}  # intersection = min
    # B goes stale -> composite invalidated
    P.declare_agent(dict(BASE, agent_id="B", model="m9"))
    cw = G.check_composition("process_invoice")
    assert cw["state"] == "INVALIDATED" and cw["broken_by"][0]["agent_id"] == "B"
    # B re-proven with narrower scope -> composite narrows
    verify_agent("B")
    CT.admit(CT.create_contract(None, "B", CAP, scope={"max_amount": 7})["contract_id"])
    cw = G.check_composition("process_invoice")
    assert cw["state"] == "ADMITTED" and cw["composite_scope"] == {"max_amount": 7}

def test_differential_before_after():
    """WITHOUT ORIN the capability keeps executing after conditions change;
    WITH ORIN the same workflow is blocked at drift and resumes only after revalidation."""
    P.declare_agent(dict(BASE, agent_id="A"))
    inv = {"a": {"number": "INV-1", "amount": 10.0}, "b": {"number": "INV-1", "amount": 10.0}}
    before = P._run_agent("A", inv)  # raw skill, no ORIN
    assert before == {"duplicate": True}
    verify_agent("A")
    cid = admitted_contract("A", scope={"max_amount": 50}, conditions={"wallet": "W1"})
    assert CT.check(cid, conditions={"wallet": "W1"})["decision"] == "ALLOW"
    CT.observe(cid, [{"field": "wallet", "delta": "none"}])
    # WITHOUT ORIN:  wallet changes, skill keeps executing
    no_orin = P._run_agent("A", dict(inv, wallet="W2"))
    assert no_orin == {"duplicate": True}  # continues
    # WITH ORIN: same change -> blocked
    r = CT.check(cid, conditions={"wallet": "W2"})
    assert r["decision"] == "DENY" and r["reason"] == "MATERIAL_DRIFT"
    # revalidation restores
    P.declare_agent(dict(BASE, agent_id="A"))
    verify_agent("A")
    cid2 = admitted_contract("A", scope={"max_amount": 50}, conditions={"wallet": "W2"})
    assert CT.check(cid2, conditions={"wallet": "W2"})["decision"] == "ALLOW"

def test_contract_via_mcp_and_api():
    from orin.api import app
    from fastapi.testclient import TestClient
    c = TestClient(app)
    P.declare_agent(dict(BASE, agent_id="A"))
    verify_agent("A")
    cid = c.post("/capabilities/contract", json={"agent_id": "A", "capability": CAP,
                "scope": {"max_amount": 50}, "conditions": {"chain": "C1"}}).json()["contract_id"]
    assert c.post(f"/capabilities/{cid}/admit").json()["decision"] == "ADMIT"
    assert c.post(f"/capabilities/{cid}/check", json={"conditions": {"chain": "C2"}}).json()["reason"] == "MATERIAL_DRIFT"
    aok = c.post(f"/capabilities/{cid}/check", json={"conditions": {"chain": "C1"}, "requested": {"max_amount": 10}}).json()
    assert aok["decision"] == "ALLOW"
    m = c.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
               "params": {"name": "orin.check_capability", "arguments": {"contract_id": cid,
                          "conditions": {"chain": "C1"}, "requested": {"max_amount": 10}}}}).json()
    assert m["result"]["structuredContent"]["decision"] == "ALLOW"