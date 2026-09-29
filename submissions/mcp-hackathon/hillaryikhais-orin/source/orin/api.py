"""ORIN API — capability admission protocol."""
import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from orin.engine import protocol as P
from orin.engine import governance as G
from orin.engine import contract as CT

def current_revision():
    """Deployed commit for the automated online gate. Prefer the env binding set at
    deploy time (ORIN_COMMIT), then a REVISION file in the tree, else local."""
    env = os.environ.get("ORIN_COMMIT")
    if env:
        return env
    here = os.path.dirname(os.path.abspath(__file__))
    for cand in (os.path.join(here, "REVISION"), os.path.join(here, "..", "REVISION")):
        if os.path.exists(cand):
            with open(cand) as f:
                return f.read().strip()
    return "local-dev"

REVISION = current_revision()
SLUG = os.environ.get("ORIN_SLUG", "hillaryikhais-orin")

app = FastAPI(title="ORIN — capability admission backed by execution", version="3.0.0")
app.add_middleware(CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"])

@app.get("/health")
def health():
    return {"status": "ok", "commit": REVISION, "service": "orin", "version": "3.0.0"}

@app.get("/.well-known/xagent-verification.json")
def xagent_verification():
    return {"schemaVersion": 1, "slug": SLUG, "commit": REVISION}

@app.post("/capabilities/declare")
def declare_agent(body: dict):
    return P.declare_agent(body)

@app.post("/evaluations/create")
def eval_create(body: dict):
    return P.create_evaluation(body["agent_id"], body.get("capability", "invoice.duplicate_detection"))

@app.post("/evaluations/run")
def eval_run(body: dict):
    ev = P.run_evaluation(body["eval_id"])
    ev = P.verify(body["eval_id"])
    out = {"eval_id": ev["eval_id"], "status": ev["status"], "summary": ev["summary"]}
    if ev["status"] == "VERIFIED":
        out["proof"] = P.issue_proof(body["eval_id"])
    else:
        out["failures"] = [r["challenge_id"] for r in ev["results"] if not r["pass"]]
    # I7: never leak hidden inputs
    return out

@app.get("/evaluations/{eid}")
def eval_get(eid: str):
    ev = P.EVALS.get(eid, {})
    return {"eval_id": eid, "status": ev.get("status"), "summary": ev.get("summary"),
            "public_challenges": P.public_challenge_ids()}

@app.get("/capabilities/{agent_id}/{cap}/proof")
def get_proof(agent_id: str, cap: str):
    return P.get_proof(agent_id, cap) or {"status": "NOT_VERIFIED"}

@app.get("/capabilities/{agent_id}/{cap}/status")
def status(agent_id: str, cap: str):
    return P.check_status(agent_id, cap)

# ---- governance: admission / delegation / composition / execution gate ----
@app.get("/capabilities/{agent_id}/{cap}/admission")
def get_admission(agent_id: str, cap: str):
    return G.admission(agent_id, cap)

@app.post("/delegations")
def post_delegation(b: dict):
    return G.delegate(b["delegator"], b["delegatee"], b["capability"], b.get("delegation_id"))

@app.get("/delegations/{did}")
def get_delegation(did: str):
    return G.check_delegation(did)

@app.post("/compositions")
def post_composition(b: dict):
    comps = [(c["agent_id"], c["capability"]) for c in b.get("components", [])]
    return G.compose(b.get("workflow_id"), comps)

@app.get("/compositions/{wid}")
def get_composition(wid: str):
    return G.check_composition(wid)

@app.post("/execute")
def post_execute(b: dict):
    return G.execute_gate(b["agent_id"], b["capability"], b.get("execution_id"))

@app.post("/harness/invoke")
def post_harness(b: dict):
    return G.harness_invoke(b["agent_id"], b["capability"], b.get("skill_input"))

@app.get("/harness/audit")
def get_harness_audit():
    return {"audit": G.harness_audit()}

# ---- capability contracts: evidence -> contract -> admission -> CHECK ----
@app.post("/capabilities/contract")
def post_contract(b: dict):
    return CT.create_contract(b.get("contract_id"), b["agent_id"], b["capability"],
                              b.get("scope"), b.get("conditions"), b.get("materiality"),
                              b.get("evaluation_id"))

@app.post("/capabilities/{cid}/admit")
def post_admit(cid: str):
    return CT.admit(cid)

@app.post("/capabilities/{cid}/check")
def post_check(cid: str, b: dict):
    return CT.check(cid, b.get("conditions"), b.get("requested"))

@app.post("/capabilities/{cid}/observe")
def post_observe(cid: str, b: dict):
    return CT.observe(cid, b.get("changes", []))

@app.get("/capabilities/{cid}/status")
def contract_status(cid: str):
    con = CT.CONTRACTS.get(cid)
    return con or {"error": "NO_SUCH_CONTRACT"}

def _verify_capability(agent_id, capability):
    st = P.check_status(agent_id, capability)
    if st.get("status") == "VERIFIED":
        p = P.get_proof(agent_id, capability)
        return {"verified": True, "proof_id": p["proof_id"], "scope": capability,
                "tested": p["issued_at"], "expires": p["expires_at"]}
    return {"verified": False, **st}

TOOLS = [
    {"name": "orin.verify_capability",
     "description": "Check whether an agent holds a VERIFIED capability proof. Returns verified true/false with proof.",
     "inputSchema": {"type": "object", "properties": {"agent_id": {"type": "string"}, "capability": {"type": "string"}}, "required": ["agent_id", "capability"]}},
    {"name": "orin.get_proof",
     "description": "Fetch the signed capability proof for an agent.",
     "inputSchema": {"type": "object", "properties": {"agent_id": {"type": "string"}, "capability": {"type": "string"}}, "required": ["agent_id", "capability"]}},
    {"name": "orin.check_status",
     "description": "VERIFIED, STALE, NOT_VERIFIED or INVALID for an agent capability.",
     "inputSchema": {"type": "object", "properties": {"agent_id": {"type": "string"}, "capability": {"type": "string"}}, "required": ["agent_id", "capability"]}},
    {"name": "orin.request_evaluation",
     "description": "Create, run and verify a hidden-challenge evaluation for an agent capability.",
     "inputSchema": {"type": "object", "properties": {"agent_id": {"type": "string"}, "capability": {"type": "string"}}, "required": ["agent_id"]}},
    {"name": "orin.check_admission",
     "description": "Live admission state for an agent capability: ADMITTED only while the demonstrated evidence is still valid. Governs execution, delegation and composition.",
     "inputSchema": {"type": "object", "properties": {"agent_id": {"type": "string"}, "capability": {"type": "string"}}, "required": ["agent_id", "capability"]}},
    {"name": "orin.delegate_capability",
     "description": "Delegate a capability to another agent; admitted only if both sides currently hold valid evidence. Auto-invalidates when either execution surface changes.",
     "inputSchema": {"type": "object", "properties": {"delegator": {"type": "string"}, "delegatee": {"type": "string"}, "capability": {"type": "string"}}, "required": ["delegator", "delegatee", "capability"]}},
    {"name": "orin.compose_capabilities",
     "description": "Assemble a workflow from demonstrated capabilities; admitted only while every component is currently admitted.",
     "inputSchema": {"type": "object", "properties": {"components": {"type": "array", "items": {"type": "object"}}}, "required": ["components"]}},
    {"name": "orin.execute_gate",
     "description": "Decision boundary before executing a capability: ALLOW only on current admission, DENIED otherwise.",
     "inputSchema": {"type": "object", "properties": {"agent_id": {"type": "string"}, "capability": {"type": "string"}}, "required": ["agent_id", "capability"]}},
    {"name": "orin.harness_invoke",
     "description": "Harness decision path: consumes ORIN admission before the skill executes. ADMITTED routes the call, CONSTRAINED routes it restricted, STALE/UNPROVEN/REVOKED deny.",
     "inputSchema": {"type": "object", "properties": {"agent_id": {"type": "string"}, "capability": {"type": "string"}, "skill_input": {"type": "object"}}, "required": ["agent_id", "capability"]}},
    {"name": "orin.create_contract",
     "description": "Declare a Capability Contract: scope, required conditions, and materiality rules saying which changes INVALIDATE, which REVALIDATE, which are IGNORED.",
     "inputSchema": {"type": "object", "properties": {"contract_id": {"type": "string"}, "agent_id": {"type": "string"}, "capability": {"type": "string"}, "scope": {"type": "object"}, "conditions": {"type": "object"}, "materiality": {"type": "object"}}, "required": ["agent_id", "capability"]}},
    {"name": "orin.admit_contract",
     "description": "Bind an ACTIVE proof to a contract, issuing the capability lease (escrow). Requires a currently VERIFIED proof.",
     "inputSchema": {"type": "object", "properties": {"contract_id": {"type": "string"}}, "required": ["contract_id"]}},
    {"name": "orin.check_capability",
     "description": "The agent runtime CHECK: may this capability execute right now? Evaluates proof freshness, material condition drift (INVALIDATE/REVALIDATE/IGNORE), and scope. Returns ALLOW or DENY with reason.",
     "inputSchema": {"type": "object", "properties": {"contract_id": {"type": "string"}, "conditions": {"type": "object"}, "requested": {"type": "object"}}, "required": ["contract_id"]}},
]

@app.post("/mcp")
def mcp(body: dict):
    method, bid, p = body.get("method", ""), body.get("id"), body.get("params", {})
    if method == "initialize":
        return {"jsonrpc": "2.0", "id": bid, "result": {"protocolVersion": "2024-11-05",
                "capabilities": {"tools": {}}, "serverInfo": {"name": "orin", "version": "1.0.0"}}}
    if method == "tools/list":
        return {"jsonrpc": "2.0", "id": bid, "result": {"tools": TOOLS}}
    if method == "tools/call":
        args = p.get("arguments", {}) if "arguments" in p else p
        name = p.get("name", "")
        aid, cap = args.get("agent_id", ""), args.get("capability", "invoice.duplicate_detection")
        if name in ("orin.verify_capability", "orin.check_status"):
            r = _verify_capability(aid, cap) if "verify" in name else P.check_status(aid, cap)
        elif name == "orin.get_proof":
            r = P.get_proof(aid, cap) or {"status": "NOT_VERIFIED"}
        elif name == "orin.request_evaluation":
            ev = P.create_evaluation(aid, cap)
            ev = P.run_evaluation(ev["eval_id"])
            ev = P.verify(ev["eval_id"])
            r = {"eval_id": ev["eval_id"], "status": ev["status"], "summary": ev["summary"]}
            if ev["status"] == "VERIFIED":
                r["proof"] = P.issue_proof(ev["eval_id"])
        elif name == "orin.check_admission":
            r = G.admission(aid, cap)
        elif name == "orin.delegate_capability":
            r = G.delegate(args.get("delegator", ""), args.get("delegatee", ""), cap)
        elif name == "orin.compose_capabilities":
            comps = [(c.get("agent_id", ""), c.get("capability", "")) for c in args.get("components", [])]
            r = G.compose(None, comps)
        elif name == "orin.execute_gate":
            r = G.execute_gate(aid, cap)
        elif name == "orin.harness_invoke":
            r = G.harness_invoke(aid, cap, args.get("skill_input"))
        elif name == "orin.create_contract":
            r = CT.create_contract(args.get("contract_id"), aid, cap, args.get("scope"),
                                   args.get("conditions"), args.get("materiality"))
        elif name == "orin.admit_contract":
            r = CT.admit(args.get("contract_id", ""))
        elif name == "orin.check_capability":
            r = CT.check(args.get("contract_id", ""), args.get("conditions"), args.get("requested"))
        else:
            return {"jsonrpc": "2.0", "id": bid, "error": {"code": -32602, "message": "unknown tool"}}
        return {"jsonrpc": "2.0", "id": bid, "result": {"content": [{"type": "text", "text": str(r)}], "structuredContent": r}}
    return {"jsonrpc": "2.0", "id": bid, "error": {"code": -32601, "message": "unknown method"}}
