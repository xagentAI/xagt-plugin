"""ORIN harness tests: runtime decision path + the 15-step final loop (I15)."""
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

def test_harness_denies_stale_and_unproven():
    P.declare_agent(dict(BASE, agent_id="Z"))
    r = G.harness_invoke("Z", CAP, {"a": {"number": "INV-1"}, "b": {"number": "INV-1"}})
    assert r["routed"] is False and r["verdict"] == "DENY" and r["reason"] == "UNPROVEN"
    P.declare_agent(dict(BASE, agent_id="A"))
    verify_agent("A")
    P.declare_agent(dict(BASE, agent_id="A", model="m2"))  # surface change
    r = G.harness_invoke("A", CAP, {"a": {"number": "INV-1"}, "b": {"number": "INV-1"}})
    assert r["routed"] is False and r["verdict"] == "DENY" and r["reason"] == "STALE"

def test_harness_restricts_constrained_invocation():
    P.declare_agent(dict(BASE, agent_id="A"))
    verify_agent("A")
    d = G.delegate("A", "A", CAP, scope={"batch_size": 2})
    assert d["state"] == "ADMITTED"
    inv = {"a": {"number": "INV-1", "amount": 10.0}, "b": {"number": "INV-1", "amount": 10.0},
           "batch_size": 5}
    r = G.harness_invoke("A", CAP, inv)
    assert r["routed"] is True and r["verdict"] == "RESTRICTED", r
    assert r["restrictions"][0]["field"] == "batch_size" and r["restrictions"][0]["allowed"] == 2
    # within-limit invocation routes clean
    r2 = G.harness_invoke("A", CAP, dict(inv, batch_size=2))
    assert r2["routed"] is True and r2["verdict"] == "ALLOW"

def test_fifteen_step_final_loop():
    # 1. Agent discovers Skill (via MCP tools/list in API test); here: registers
    P.declare_agent(dict(BASE, agent_id="A"))
    P.declare_agent(dict(BASE, agent_id="B"))
    # 2-3. ORIN evaluates it, produces proof
    assert verify_agent("A") == "VERIFIED"
    # 4. Capability becomes ADMITTED
    assert G.admission("A", CAP)["state"] == "ADMITTED"
    # 5. Harness permits real execution
    inv = {"a": {"number": "INV-1", "amount": 10.0}, "b": {"number": "INV-1", "amount": 10.0}}
    r = G.harness_invoke("A", CAP, inv)
    assert r["routed"] is True and r["verdict"] == "ALLOW" and r["result"] == {"duplicate": True}
    # 6. Agent delegates it (B verified for delegation to be admitted)
    assert verify_agent("B") == "VERIFIED"
    d = G.delegate("A", "B", CAP)
    assert d["state"] == "ADMITTED"
    did = d["delegation_id"]
    # 7. Delegated capability executes
    r = G.harness_invoke("B", CAP, inv)
    assert r["routed"] is True and r["verdict"] == "ALLOW"
    # 8. Execution surface changes
    P.declare_agent(dict(BASE, agent_id="B", model="m9"))
    # 9. ORIN marks proof STALE
    assert P.check_status("B", CAP)["status"] == "STALE"
    # 10. Harness blocks the next invocation
    r = G.harness_invoke("B", CAP, inv)
    assert r["routed"] is False and r["verdict"] == "DENY" and r["reason"] == "STALE"
    # 11. Delegation becomes invalid
    assert G.check_delegation(did)["state"] == "REVOKED"
    # 12-13. Re-evaluation runs, new proof issued
    assert verify_agent("B") == "VERIFIED"
    # 14. Capability becomes ADMITTED
    assert G.admission("B", CAP)["state"] == "ADMITTED"
    # 15. Same invocation succeeds
    r = G.harness_invoke("B", CAP, inv)
    assert r["routed"] is True and r["verdict"] == "ALLOW"
    # Harness audit log recorded every decision
    audit = G.harness_audit()
    assert len(audit) == 4 and all("verdict" in e for e in audit)

def test_harness_via_mcp():
    from orin.api import app
    from fastapi.testclient import TestClient
    c = TestClient(app)
    P.declare_agent(dict(BASE, agent_id="A"))
    verify_agent("A")
    m = c.post("/mcp", json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
               "params": {"name": "orin.harness_invoke",
                          "arguments": {"agent_id": "A", "capability": CAP,
                                        "skill_input": {"a": {"number": "INV-1"}, "b": {"number": "INV-1"}}}}}).json()
    sc = m["result"]["structuredContent"]
    assert sc["routed"] is True and sc["verdict"] == "ALLOW"
