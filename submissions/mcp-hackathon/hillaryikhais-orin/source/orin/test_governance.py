"""ORIN governance tests: admission/delegation/composition/execution-gate + full loop + fuzz (I11-I14)."""
import random
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

def verify_agent(agent_id):
    ev = P.create_evaluation(agent_id, CAP)
    P.run_evaluation(ev["eval_id"])
    ev = P.verify(ev["eval_id"])
    if ev["status"] == "VERIFIED":
        P.issue_proof(ev["eval_id"])
    return ev["status"]

def test_full_loop_admit_execute_mutate_denied_readmit():
    P.declare_agent(dict(BASE, agent_id="A"))
    assert verify_agent("A") == "VERIFIED"
    assert G.admission("A", CAP)["state"] == "ADMITTED"
    ex = G.execute_gate("A", CAP)
    assert ex["allowed"] is True  # EXECUTED
    P.declare_agent(dict(BASE, agent_id="A", tools=["read", "refund"]))  # MUTATE
    assert P.check_status("A", CAP)["status"] == "STALE"
    assert G.admission("A", CAP)["state"] == "STALE"  # automatic revocation, I14
    assert G.execute_gate("A", CAP)["allowed"] is False  # DENIED, I13
    assert verify_agent("A") == "VERIFIED"  # RE-PROVE
    assert G.admission("A", CAP)["state"] == "ADMITTED"  # RE-ADMITTED
    assert G.execute_gate("A", CAP)["allowed"] is True  # EXECUTED again

def test_delegation_conditional_and_auto_revoked():
    P.declare_agent(dict(BASE, agent_id="A"))
    P.declare_agent(dict(BASE, agent_id="B"))
    verify_agent("B")
    d = G.delegate("A", "B", CAP)
    assert d["state"] == "DENIED" and d["reason"] == "DELEGATOR_NOT_ADMITTED"  # A not admitted
    verify_agent("A")
    d = G.delegate("A", "B", CAP)
    assert d["state"] == "ADMITTED", d
    did = d["delegation_id"]
    P.declare_agent(dict(BASE, agent_id="B", model="m2"))  # B's surface changes
    cd = G.check_delegation(did)
    assert cd["state"] == "REVOKED" and cd["reason"] == "ADMISSION_INVALIDATED"  # I11, I14

def test_delegation_widening_denied():
    P.declare_agent(dict(BASE, agent_id="A"))
    P.declare_agent(dict(BASE, agent_id="B"))
    verify_agent("A")
    verify_agent("B")
    d = G.delegate("A", "B", "invoice.refund")
    assert d["state"] == "DENIED"  # neither holds proof for that capability (I5 extended)

def test_composition_propagation():
    P.declare_agent(dict(BASE, agent_id="A"))
    P.declare_agent(dict(BASE, agent_id="B"))
    P.declare_agent(dict(BASE, agent_id="C"))
    for x in ("A", "B", "C"):
        verify_agent(x)
    wf = G.compose("process_invoice", [("A", CAP), ("B", CAP), ("C", CAP)])
    assert wf["state"] == "ADMITTED"
    P.declare_agent(dict(BASE, agent_id="B", tools=["read", "pay"]))  # one component mutates
    cw = G.check_composition("process_invoice")
    assert cw["state"] == "INVALIDATED" and cw["reason"] == "ADMISSION_INVALIDATED"
    assert cw["broken_by"][0]["agent_id"] == "B"  # propagation names the cause (I12)

def test_api_governance_and_mcp():
    from orin.api import app
    from fastapi.testclient import TestClient
    c = TestClient(app)
    c.post("/capabilities/declare", json=dict(BASE, agent_id="A"))
    r = c.post("/evaluations/create", json={"agent_id": "A", "capability": CAP}).json()
    r = c.post("/evaluations/run", json={"eval_id": r["eval_id"]}).json()
    assert r["status"] == "VERIFIED"
    assert c.get(f"/capabilities/A/{CAP}/admission").json()["state"] == "ADMITTED"
    assert c.post("/execute", json={"agent_id": "A", "capability": CAP}).json()["allowed"] is True
    m = c.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
               "params": {"name": "orin.execute_gate", "arguments": {"agent_id": "A", "capability": CAP}}}).json()
    assert m["result"]["structuredContent"]["allowed"] is True

def test_fuzz_no_gate_bypass():
    random.seed(11)
    for _ in range(200):
        P.AGENTS.clear(); P.PROOFS.clear()
        G.reset()
        mut = random.random() < 0.5
        ag = dict(BASE, agent_id="A", tools=random.choice([["read"], ["read", "x"], ["pay"]]))
        P.declare_agent(ag)
        if random.random() < 0.7:
            verify_agent("A")
        if mut:
            P.declare_agent(dict(ag, model="mutated"))
        if random.random() < 0.5:  # exercise via composition too
            wf = G.compose(None, [("A", CAP)])
            assert not (wf["state"] == "ADMITTED" and G.execute_gate("A", CAP)["allowed"] is False), (wf, "bypass")
        ex = G.execute_gate("A", CAP)
        if ex["allowed"]:
            assert G.admission("A", CAP)["state"] == "ADMITTED"  # I13 held every time

def test_unproven_state():
    P.declare_agent(dict(BASE, agent_id="Z"))
    a = G.admission("Z", CAP)
    assert a["state"] == "UNPROVEN" and a["reason"] == "NO_PROOF"  # I6 at admission layer
    assert G.execute_gate("Z", CAP)["verdict"] == "DENIED"

def test_admission_object_binds_everything():
    P.declare_agent(dict(BASE, agent_id="A"))
    verify_agent("A")
    d = G.delegate("A", "A", CAP, scope={"batch_size": 2})  # self-delegation carries constraints
    assert d["state"] == "ADMITTED"
    a = G.admission("A", CAP)
    assert a["state"] == "ADMITTED" and a["proof_id"] and a["fingerprint"]
    assert a["delegation_state"] == "ACTIVE" and a["constraints"][0]["scope"] == {"batch_size": 2}
    assert a["validity"]["expires_at"] > 0
