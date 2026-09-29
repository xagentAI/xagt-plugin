"""ORIN governance: live admission state governing execution, delegation, composition.
Admission is DERIVED from current evidence at every call — automatic revocation, no human button (I14).
"""
import threading, time
from . import protocol as P
from . import contract as CT

LOCK = threading.Lock()
DELEGATIONS = {}
COMPOSITIONS = {}
EXECUTIONS = []
HARNESS_AUDIT = []
_seq = 0

def _next(prefix):
    global _seq
    _seq += 1
    return f"{prefix}-{_seq:04d}"

def _intersect_grants(grants):
    """Capability constraint intersection: composite/delegated scope = min of component limits.
    Numeric fields -> min; non-numeric must match or the intersection conflicts (None)."""
    keys = set()
    for g in grants:
        if g:
            keys.update(g)
    out = {}
    for k in keys:
        vals = [g[k] for g in grants if g and k in g]
        if all(isinstance(v, (int, float)) for v in vals):
            out[k] = min(vals)
        else:
            if len({str(v) for v in vals}) == 1:
                out[k] = vals[0]
            else:
                return None
    return out

def _active_constraints(agent_id, capability):
    """Live constraints inherited from active delegations to this agent."""
    cons = []
    for rec in DELEGATIONS.values():
        if (rec.get("state") == "ADMITTED" and rec.get("delegatee") == agent_id
                and rec.get("capability") == capability and rec.get("effective_scope")):
            cons.append({"via": rec["delegation_id"], "scope": rec["effective_scope"]})
    return cons

def admission(agent_id, capability, requested=None):
    """Live admission state, live-derived from current evidence (I8).
    Runtime decision: ADMITTED / CONSTRAINED / STALE / UNPROVEN / REVOKED."""
    st = P.check_status(agent_id, capability)
    if st.get("status") == "NOT_VERIFIED":
        return {"state": "UNPROVEN", "agent_id": agent_id, "capability": capability,
                "reason": "NO_PROOF"}
    if st.get("status") == "STALE":
        return {"state": "STALE", "agent_id": agent_id, "capability": capability,
                "reason": st.get("reason", "EVIDENCE_CHANGED")}
    if st.get("status") == "INVALID":
        return {"state": "REVOKED", "agent_id": agent_id, "capability": capability,
                "reason": st.get("reason", "EVIDENCE_TAMPER")}
    p = P.get_proof(agent_id, capability)
    cons = _active_constraints(agent_id, capability)
    out = {"state": "ADMITTED", "agent_id": agent_id, "capability": capability,
           "proof_id": p["proof_id"], "fingerprint": p["agent_fingerprint"],
           "validity": {"expires_at": p["expires_at"]},
           "constraints": cons,
           "delegation_state": "ACTIVE" if cons else None}
    if requested:
        restrictions = []
        for c in cons:
            for k, lim in c["scope"].items():
                if k in requested:
                    try:
                        over = float(requested[k]) > float(lim)
                    except Exception:
                        over = requested[k] != lim
                    if over:
                        restrictions.append({"field": k, "requested": requested[k],
                                             "allowed": lim, "via": c["via"]})
        if restrictions:
            out["state"] = "CONSTRAINED"
            out["restrictions"] = restrictions
    return out

def _check_admitted(a, capability):
    """Re-derive at read time: automatic invalidation when material conditions changed."""
    cur = admission(a, capability)
    return cur

def delegate(delegator, delegatee, capability, delegation_id=None, scope=None):
    """Evidence-bound delegation with authority intersection:
    delegated scope = A's granted scope ∩ B's proven capability scope ∩ delegation constraints.
    B can never receive more authority than it has proven (non-expanding authority)."""
    delegation_id = delegation_id or _next("DEL")
    with LOCK:
        da = admission(delegator, capability)
        if da["state"] != "ADMITTED":
            rec = {"delegation_id": delegation_id, "delegator": delegator, "delegatee": delegatee,
                   "capability": capability, "scope": scope, "state": "DENIED",
                   "reason": "DELEGATOR_NOT_ADMITTED", "detail": da, "created_at": time.time()}
            DELEGATIONS[delegation_id] = rec
            return dict(rec)
        db = admission(delegatee, capability)
        if db["state"] != "ADMITTED":
            rec = {"delegation_id": delegation_id, "delegator": delegator, "delegatee": delegatee,
                   "capability": capability, "scope": scope, "state": "DENIED",
                   "reason": "DELEGATEE_NOT_ADMITTED", "detail": db, "created_at": time.time()}
            DELEGATIONS[delegation_id] = rec
            return dict(rec)
        granted = CT.active_for(delegator, capability)
        proven = CT.active_for(delegatee, capability)
        effective = _intersect_grants([granted.get("scope") if granted else None,
                                       proven.get("scope") if proven else None, scope])
        if effective is None:
            rec = {"delegation_id": delegation_id, "delegator": delegator, "delegatee": delegatee,
                   "capability": capability, "scope": scope, "state": "DENIED",
                   "reason": "SCOPE_CONFLICT", "created_at": time.time()}
            DELEGATIONS[delegation_id] = rec
            return dict(rec)
        rec = {"delegation_id": delegation_id, "delegator": delegator, "delegatee": delegatee,
               "capability": capability, "scope": scope, "effective_scope": effective,
               "state": "ADMITTED", "proof_id": db["proof_id"], "created_at": time.time()}
        DELEGATIONS[delegation_id] = rec
        return dict(rec)

def check_delegation(delegation_id):
    with LOCK:
        rec = dict(DELEGATIONS.get(delegation_id, {}))
    if not rec:
        return {"delegation_id": delegation_id, "state": "UNKNOWN", "reason": "NO_SUCH_DELEGATION"}
    if rec.get("state") == "ADMITTED":
        cur_d = admission(rec["delegatee"], rec["capability"])
        cur_a = admission(rec["delegator"], rec["capability"])
        if cur_d["state"] != "ADMITTED" or cur_a["state"] != "ADMITTED":
            rec["state"] = "REVOKED"
            rec["reason"] = "ADMISSION_INVALIDATED"
            rec["invalidated_side"] = "delegatee" if cur_d["state"] != "ADMITTED" else "delegator"
            with LOCK:
                DELEGATIONS[delegation_id] = rec
    return rec

def compose(workflow_id, components):
    """components: (agent_id, capability) or {agent_id, capability, scope}.
    ADMITTED only if ALL currently admitted (I12). Composite scope = intersection
    of component contracts' scopes (capability constraint intersection)."""
    workflow_id = workflow_id or _next("WF")
    with LOCK:
        states = []
        grants = []
        for comp in components:
            if isinstance(comp, (tuple, list)):
                a, c = comp[0], comp[1]
            else:
                a, c = comp["agent_id"], comp["capability"]
            s = admission(a, c)
            if s["state"] == "ADMITTED":
                con = CT.active_for(a, c)
                grants.append(con.get("scope") if con else None)
            states.append({"agent_id": a, "capability": c, "state": s["state"],
                           "reason": s.get("reason"), "proof_id": s.get("proof_id")})
        broken = [s for s in states if s["state"] != "ADMITTED"]
        composite = _intersect_grants(grants) if not broken else None
        rec = {"workflow_id": workflow_id, "components": states,
               "state": "ADMITTED" if not broken else "DENIED",
               "composite_scope": composite,
               "broken_by": [{"agent_id": s["agent_id"], "capability": s["capability"],
                              "state": s["state"], "reason": s.get("reason")} for s in broken],
               "created_at": time.time()}
        COMPOSITIONS[workflow_id] = rec
        return dict(rec)

def check_composition(workflow_id):
    with LOCK:
        rec = dict(COMPOSITIONS.get(workflow_id, {}))
    if not rec:
        return {"workflow_id": workflow_id, "state": "UNKNOWN", "reason": "NO_SUCH_COMPOSITION"}
    if rec.get("state") == "ADMITTED":
        cur = compose(workflow_id + ":recheck", [(s["agent_id"], s["capability"]) for s in rec["components"]])
        if cur["state"] != "ADMITTED":
            rec["state"] = "INVALIDATED"
            rec["reason"] = "ADMISSION_INVALIDATED"
            rec["broken_by"] = cur["broken_by"]
        else:
            rec["composite_scope"] = cur["composite_scope"]  # narrowing propagates
    return rec

def execute_gate(agent_id, capability, execution_id=None):
    """The X-Agent decision boundary: ALLOW only on current ADMITTED state (I13). Execution becomes evidence."""
    execution_id = execution_id or _next("EX")
    a = admission(agent_id, capability)
    with LOCK:
        EXECUTIONS.append({"execution_id": execution_id, "agent_id": agent_id,
                           "capability": capability, "state": a["state"], "at": time.time()})
        if a["state"] != "ADMITTED":
            return {"allowed": False, "verdict": "DENIED", "reason": "NOT_ADMITTED",
                    "detail": a, "execution_id": execution_id}
        return {"allowed": True, "verdict": "ALLOW", "proof_id": a["proof_id"],
                "execution_id": execution_id}

def harness_invoke(agent_id, capability, skill_input=None):
    """The Harness consumes ORIN admission BEFORE the Skill executes (I15):
    ADMITTED -> route call, CONSTRAINED -> restrict, STALE/UNPROVEN/REVOKED -> deny."""
    a = admission(agent_id, capability, requested=skill_input)
    entry = {"agent_id": agent_id, "capability": capability, "admission_state": a["state"],
             "at": time.time()}
    if a["state"] in ("ADMITTED", "CONSTRAINED"):
        used = dict(skill_input or {})
        if a["state"] == "CONSTRAINED":
            for r in a["restrictions"]:
                used[r["field"]] = r["allowed"]
        result = P._run_agent(agent_id, used) if skill_input else None
        entry["verdict"] = "RESTRICTED" if a["state"] == "CONSTRAINED" else "ALLOW"
        rec = {"routed": True, "verdict": entry["verdict"],
               "restrictions": a.get("restrictions", []), "result": result,
               "admission": a, "audit_id": len(HARNESS_AUDIT)}
    else:
        entry["verdict"] = "DENY"
        rec = {"routed": False, "verdict": "DENY", "reason": a["state"],
               "detail": a, "audit_id": len(HARNESS_AUDIT)}
    with LOCK:
        HARNESS_AUDIT.append(entry)
    return rec

def harness_audit():
    with LOCK:
        return list(HARNESS_AUDIT)

def reset():
    with LOCK:
        DELEGATIONS.clear(); COMPOSITIONS.clear(); EXECUTIONS.clear(); HARNESS_AUDIT.clear()
