"""ORIN Capability Contract: the machine-evaluable link between evidence and executable capability.

A contract declares WHAT is proven, UNDER WHICH CONDITIONS, WHICH conditions are MATERIAL,
and WHAT scope is allowed. check() classifies drift by materiality: INVALIDATE -> STALE,
REVALIDATE -> recheck required, IGNORE -> non-material, execution continues. That is drift
classification, not blind invalidation.
"""
import time
from . import protocol as P
from .hashing import short

CONTRACTS = {}
SEQUENCE = [0]

ACTIONS = ("INVALIDATE", "REVALIDATE", "IGNORE")


def _next():
    SEQUENCE[0] += 1
    return SEQUENCE[0]


def active_for(agent_id, capability):
    """Latest admitted contract binding (agent, capability); a re-proven, re-admitted
    contract with a narrower scope supersedes the earlier one."""
    candidates = [con for con in CONTRACTS.values()
                  if con["agent_id"] == agent_id and con["capability"] == capability
                  and con["status"] == "ACTIVE"]
    if candidates:
        return max(candidates, key=lambda c: c.get("admitted_at", 0))
    return None


def create_contract(contract_id, agent_id, capability, scope=None, conditions=None,
                    materiality=None, evaluation_id=None):
    """scope: {'max_amount': 50, 'currency': 'USDC'}
    conditions: {'wallet': 'W1', 'chain': 'C1', 'tool_surface': 'T7', 'policy': 'P4'}
    materiality: {'wallet': 'INVALIDATE', 'tool_surface': 'REVALIDATE', 'logging': 'IGNORE'}
    Fields in conditions/scope default to INVALIDATE; unknown fields default to IGNORE."""
    cid = contract_id or ("C-%04d" % _next())
    for field, action in (materiality or {}).items():
        if action not in ACTIONS:
            raise ValueError(f"bad materiality action {action}")
    CONTRACTS[cid] = {"contract_id": cid, "agent_id": agent_id, "capability": capability,
                      "scope": dict(scope or {}), "conditions": dict(conditions or {}),
                      "materiality": dict(materiality or {}), "evaluation_id": evaluation_id,
                      "proof_id": None, "status": "UNBOUND", "created_at": time.time(),
                      "observations": []}
    return dict(CONTRACTS[cid])


def _materiality(contract, field):
    m = contract["materiality"]
    if field in m:
        return m[field]
    if field in contract["conditions"] or field in contract["scope"]:
        return "INVALIDATE"
    return "IGNORE"


def admit(contract_id):
    con = CONTRACTS.get(contract_id)
    if not con:
        return {"decision": "DENY", "reason": "NO_SUCH_CONTRACT", "contract_id": contract_id}
    st = P.check_status(con["agent_id"], con["capability"])
    if st.get("status") == "VERIFIED":
        p = P.get_proof(con["agent_id"], con["capability"])
        con["proof_id"] = p["proof_id"]
        con["status"] = "ACTIVE"
        con["admitted_at"] = time.time()
        con["valid_until"] = p["expires_at"]
        return {"decision": "ADMIT", "contract_id": contract_id, "proof_id": p["proof_id"],
                "scope": con["scope"]}
    return {"decision": "DENY", "reason": "UNPROVEN", "contract_id": contract_id,
            "proof": st.get("status")}


def observe(contract_id, changes):
    """Non-material changes are recorded, not fatal."""
    con = CONTRACTS.get(contract_id)
    if not con:
        return {"error": "NO_SUCH_CONTRACT"}
    con["observations"].extend([{"recorded_at": time.time(), **c} for c in changes])
    return {"recorded": len(changes), "observations": list(con["observations"])}


def _drift(contract, conditions):
    changed, recheck, observed = [], [], []
    cond = conditions or {}
    for field, expected in contract["conditions"].items():
        if field in cond and cond[field] != expected:
            entry = {"field": field, "expected": expected, "current": cond[field]}
            action = _materiality(contract, field)
            if action == "INVALIDATE":
                changed.append(entry)
            elif action == "REVALIDATE":
                recheck.append(entry)
            else:
                observed.append(entry)
    return changed, recheck, observed


def _scope_violations(contract, requested):
    out = []
    for field, allowed in contract["scope"].items():
        if field in (requested or {}):
            try:
                over = float(requested[field]) > float(allowed)
            except (TypeError, ValueError):
                over = requested[field] != allowed
            if over:
                out.append({"field": field, "requested": requested[field], "allowed": allowed})
    return out


def check(contract_id, conditions=None, requested=None):
    """The customer-facing call: agent runtime asks 'may this happen right now?'"""
    con = CONTRACTS.get(contract_id)
    if not con:
        return {"decision": "DENY", "reason": "NO_SUCH_CONTRACT", "contract_id": contract_id}
    if con["status"] != "ACTIVE" or not con["proof_id"]:
        return {"decision": "DENY", "reason": "NOT_ADMITTED", "contract_id": contract_id}
    st = P.check_status(con["agent_id"], con["capability"])
    if st.get("status") == "STALE":
        return {"decision": "DENY", "reason": "REVALIDATION_REQUIRED", "contract_id": contract_id,
                "changed": [{"field": "execution_surface", "reason": st.get("reason")}],
                "previous_admission": con["contract_id"]}
    if st.get("status") != "VERIFIED":
        return {"decision": "DENY", "reason": st.get("reason", "UNPROVEN"),
                "contract_id": contract_id, "previous_admission": con["contract_id"]}
    p = P.get_proof(con["agent_id"], con["capability"])
    if p["proof_id"] != con["proof_id"]:
        return {"decision": "DENY", "reason": "ADMISSION_SUPERSEDED", "contract_id": contract_id,
                "previous_proof": con["proof_id"], "current_proof": p["proof_id"]}
    changed, recheck, observed = _drift(con, conditions)
    if changed:
        return {"decision": "DENY", "reason": "MATERIAL_DRIFT", "contract_id": contract_id,
                "changed": changed, "observed_nonmaterial": observed,
                "previous_admission": con["contract_id"]}
    if recheck:
        return {"decision": "DENY", "reason": "REVALIDATION_REQUIRED", "contract_id": contract_id,
                "changed": recheck, "observed_nonmaterial": observed,
                "previous_admission": con["contract_id"]}
    violations = _scope_violations(con, requested)
    if violations:
        return {"decision": "DENY", "reason": "SCOPE_EXPANSION", "contract_id": contract_id,
                "violations": violations, "scope": con["scope"]}
    return {"decision": "ALLOW", "capability": con["capability"],
            "admission": f"OR-{con['contract_id']}", "scope": con["scope"],
            "proof": con["proof_id"], "valid_until": con.get("valid_until"),
            "revalidation": "required_on_material_change",
            "observed_nonmaterial": observed, "contract_id": contract_id}