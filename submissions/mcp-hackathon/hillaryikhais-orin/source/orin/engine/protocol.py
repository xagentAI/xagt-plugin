"""Core protocol: declare -> run (real agent) -> observe -> verify -> proof -> consume -> retest."""
import time, hmac, hashlib
from . import challenges as CH
from .evaluator import evaluate
from .fingerprint import fingerprint
from .hashing import h, short, SECRET

AGENTS = {}       # agent_id -> agent record (incl. endpoint or handler name)
EVALS = {}        # eval_id -> evaluation
PROOFS = {}       # (agent_id, capability) -> current proof
HISTORY = []      # immutable proof history
HANDLERS = {}     # agent_id -> callable(input) -> output (in-process real agent)
_seq = 0

def _sign(payload: str) -> str:
    return hmac.new(SECRET.encode(), payload.encode(), hashlib.sha256).hexdigest()[:32]

def declare_agent(agent: dict):
    agent = dict(agent)
    agent["fingerprint"] = fingerprint(agent)
    agent["registered_at"] = time.time()
    AGENTS[agent["agent_id"]] = agent
    return agent

def register_handler(agent_id, fn):
    HANDLERS[agent_id] = fn

def _run_agent(agent_id, inp):
    if agent_id in HANDLERS:
        return HANDLERS[agent_id](dict(inp))
    # reference built-in: correct normalizer-based detector (used by demo good agent)
    from ..agents.reference import detect_duplicate
    return detect_duplicate(inp["a"], inp["b"])

def create_evaluation(agent_id, capability=CH.CAPABILITY):
    global _seq
    _seq += 1
    eid = f"EV-{_seq:04d}"
    agent = AGENTS.get(agent_id)
    if not agent:
        raise KeyError("unknown agent")
    EVALS[eid] = {"eval_id": eid, "agent_id": agent_id, "capability": capability,
                  "suite": CH.SUITE, "fingerprint": agent["fingerprint"],
                  "status": "CREATED", "results": []}
    return EVALS[eid]

def run_evaluation(eval_id):
    ev = EVALS[eval_id]
    agent_id = ev["agent_id"]
    results = []
    for ch in CH.PUBLIC + CH.HIDDEN:
        out = _run_agent(agent_id, ch["input"])
        ok = evaluate(ch, out)
        results.append({"challenge_id": ch["id"], "adversarial": ch["adversarial"],
                        "pass": ok, "input_hash": h(ch["input"]), "output_hash": h(out)})
    ev["results"] = results
    ev["status"] = "RAN"
    ev["ran_at"] = time.time()
    return ev

def verify(eval_id):
    ev = EVALS[eval_id]
    assert ev["status"] == "RAN", "must run before verify"
    pub = [r for r in ev["results"] if not r["adversarial"]]
    adv = [r for r in ev["results"] if r["adversarial"]]
    passed = sum(1 for r in pub if r["pass"])
    adv_passed = sum(1 for r in adv if r["pass"])
    ok = (passed == len(pub) and adv_passed == len(adv))
    ev["status"] = "VERIFIED" if ok else "FAILED"
    ev["summary"] = {"total": len(pub), "passed": passed, "failed": len(pub) - passed,
                     "adv_total": len(adv), "adv_passed": adv_passed}
    return ev

def issue_proof(eval_id):
    ev = EVALS[eval_id]
    if ev["status"] != "VERIFIED":
        raise ValueError("cannot issue proof for non-VERIFIED evaluation")
    agent = AGENTS[ev["agent_id"]]
    pid = "OR-" + short([ev["eval_id"], agent["agent_id"], agent["fingerprint"]])
    proof = {"proof_id": pid, "agent_id": agent["agent_id"],
             "agent_version": agent.get("version", "v1"),
             "agent_fingerprint": agent["fingerprint"],
             "capability": ev["capability"], "evaluation_suite": ev["suite"],
             "tests": {"total": ev["summary"]["total"], "passed": ev["summary"]["passed"],
                       "failed": ev["summary"]["failed"]},
             "adversarial": {"total": ev["summary"]["adv_total"], "passed": ev["summary"]["adv_passed"]},
             "issued_at": time.time(), "expires_at": time.time() + 90 * 86400,
             "status": "VERIFIED"}
    proof["signature"] = _sign(h([pid, proof["agent_fingerprint"], proof["capability"],
                                  proof["tests"], proof["adversarial"]]))
    PROOFS[(agent["agent_id"], ev["capability"])] = proof
    HISTORY.append(dict(proof))
    return proof

def check_status(agent_id, capability):
    key = (agent_id, capability)
    proof = PROOFS.get(key)
    agent = AGENTS.get(agent_id)
    if not proof:
        return {"status": "NOT_VERIFIED", "agent_id": agent_id, "capability": capability}
    if not agent:
        return {"status": "NOT_VERIFIED"}
    if agent["fingerprint"] != proof["agent_fingerprint"]:
        return {"status": "STALE", "reason": "execution_fingerprint_changed",
                "previous_proof": proof["proof_id"]}
    if time.time() > proof["expires_at"]:
        return {"status": "STALE", "reason": "proof_expired", "previous_proof": proof["proof_id"]}
    # tamper check
    expect = _sign(h([proof["proof_id"], proof["agent_fingerprint"], proof["capability"],
                      proof["tests"], proof["adversarial"]]))
    if expect != proof.get("signature"):
        return {"status": "INVALID", "reason": "evidence_tamper", "previous_proof": proof["proof_id"]}
    return {"status": "VERIFIED", "proof_id": proof["proof_id"], "agent_id": agent_id,
            "capability": capability}

def get_proof(agent_id, capability):
    return PROOFS.get((agent_id, capability))

def verify_proof_signature(proof: dict) -> bool:
    expect = _sign(h([proof["proof_id"], proof["agent_fingerprint"], proof["capability"],
                      proof["tests"], proof["adversarial"]]))
    return expect == proof.get("signature")

def public_challenge_ids():
    return [c["id"] for c in CH.PUBLIC]  # I7: hidden never exposed
