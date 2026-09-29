"""ORIN attack-lab + invariant tests (I1-I10)."""
from fastapi.testclient import TestClient
from orin.api import app
from orin.engine import protocol as P
from orin.engine import contract as CT
from orin.agents.reference import flawed_agent

c = TestClient(app)
CAP = "invoice.duplicate_detection"
GOOD = {"agent_id": "agent-good", "version": "v1", "code": "det-v1", "model": "m1",
        "prompt": "p1", "tools": ["read"], "skills": ["dup"], "config": {}, "env": "prod"}
BAD = dict(GOOD, agent_id="agent-bad")

def setup_function(_):
    P.AGENTS.clear(); P.EVALS.clear(); P.PROOFS.clear(); P.HISTORY.clear()
    P.HANDLERS.clear(); P._seq = 0
    CT.CONTRACTS.clear()

def run_full(agent, handler=None):
    P.declare_agent(agent)
    if handler:
        P.register_handler(agent["agent_id"], handler)
    ev = P.create_evaluation(agent["agent_id"], CAP)
    P.run_evaluation(ev["eval_id"])
    return P.verify(ev["eval_id"])

def test_good_agent_verified_with_proof():
    ev = run_full(GOOD)
    assert ev["status"] == "VERIFIED", ev["summary"]
    assert ev["summary"] == {"total": 50, "passed": 50, "failed": 0, "adv_total": 10, "adv_passed": 10}
    proof = P.issue_proof(ev["eval_id"])
    assert proof["status"] == "VERIFIED" and P.verify_proof_signature(proof)
    st = P.check_status("agent-good", CAP)
    assert st["status"] == "VERIFIED"  # I1, I2, I8

def test_overclaim_rejected():
    ev = run_full(BAD, flawed_agent)
    assert ev["status"] == "FAILED"  # hidden + adversarial catch it
    try:
        P.issue_proof(ev["eval_id"])
        assert False, "I1: no proof without passing evaluation"
    except ValueError:
        pass

def test_version_substitution_stale():
    ev = run_full(GOOD)
    P.issue_proof(ev["eval_id"])
    P.declare_agent(dict(GOOD, tools=["read", "refund"]))  # material change
    st = P.check_status("agent-good", CAP)
    assert st["status"] == "STALE"  # I3, I4, I10

def test_capability_widening_not_verified():
    ev = run_full(GOOD)
    P.issue_proof(ev["eval_id"])
    st = P.check_status("agent-good", "invoice.refund")
    assert st["status"] == "NOT_VERIFIED"  # I5

def test_tampered_proof_invalid():
    ev = run_full(GOOD)
    proof = P.issue_proof(ev["eval_id"])
    proof["tests"]["passed"] = 999
    assert not P.verify_proof_signature(proof)  # I6

def test_hidden_never_exposed():
    r = c.post("/evaluations/create", json={"agent_id": "x"}) if False else None
    P.declare_agent(GOOD)
    ev = P.create_evaluation("agent-good", CAP)
    body = c.get(f"/evaluations/{ev['eval_id']}").json()
    assert not any(i.startswith("adv-") for i in body["public_challenges"])  # I7

def test_history_immutable_and_api_loop():
    P.declare_agent(GOOD)
    r = c.post("/evaluations/create", json={"agent_id": "agent-good", "capability": CAP}).json()
    r = c.post("/evaluations/run", json={"eval_id": r["eval_id"]}).json()
    assert r["status"] == "VERIFIED" and r["proof"]["proof_id"].startswith("OR-")
    assert len(P.HISTORY) == 1  # I9
    st = c.get(f"/capabilities/agent-good/{CAP}/status").json()
    assert st["status"] == "VERIFIED"
    m = c.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
               "params": {"name": "orin.verify_capability",
                          "arguments": {"agent_id": "agent-good", "capability": CAP}}}).json()
    assert m["result"]["structuredContent"]["verified"] is True
