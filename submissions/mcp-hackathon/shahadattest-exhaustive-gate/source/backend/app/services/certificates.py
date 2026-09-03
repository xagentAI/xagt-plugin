"""Deterministic proof certificates (SHA-256 digests, no blockchain)."""
import hashlib
import json
from datetime import datetime, timezone
from typing import Any


def evidence_digest(session: dict[str, Any]) -> str:
    norm = json.dumps({"scope_hash": session.get("scope_hash"),
                       "observations": session.get("observations", []),
                       "failures": session.get("failures", [])},
                      sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(norm.encode()).hexdigest()


def issue_certificate(session: dict, claim: dict, verdict: dict) -> dict[str, Any]:
    digest = evidence_digest(session)
    cid = "proof_" + hashlib.sha256((digest + json.dumps(claim, sort_keys=True)).encode()).hexdigest()[:12]
    return {"certificate_id": cid, "claim_type": verdict.get("claim_type"),
            "claim": claim, "verdict": verdict.get("verdict"),
            "resource": session.get("resource_type"), "scope_hash": session.get("scope_hash"),
            "evidence_hash": digest, "records_examined": verdict.get("records_examined", 0),
            "pages_examined": verdict.get("pages_examined", 0),
            "snapshot_status": verdict.get("evidence_summary", {}).get("snapshot_status", "UNKNOWN"),
            "issued_at": datetime.now(timezone.utc).isoformat()}
