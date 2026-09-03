import json
import uuid
from fastapi import APIRouter, HTTPException
from sqlalchemy.orm import Session

from app.models.db import SessionRow, engine
from app.schemas.api import FailureRecord, ObservePage, ParseIn, SessionCreate, VerifyIn
from app.services.certificates import issue_certificate
from app.services.claim_parser import parse_claim
from app.services.scope import scope_hash
from app.services.verifier import verify

router = APIRouter()


def _db() -> Session:
    return Session(engine, expire_on_commit=False)


def _load(row: SessionRow) -> dict:
    return {"id": row.id, "resource_type": row.resource_type, "source": row.source,
            "scope": json.loads(row.scope_json or "{}"), "scope_hash": row.scope_hash,
            "pagination_type": row.pagination_type, "snapshot_strategy": row.snapshot_strategy,
            "status": row.status, "observations": json.loads(row.observations_json or "[]"),
            "failures": json.loads(row.failures_json or "[]")}


@router.post("/sessions")
async def create_session(body: SessionCreate):
    if body.pagination_type not in ("cursor", "offset", "page", "single"):
        raise HTTPException(400, "pagination_type must be cursor|offset|page|single")
    if body.snapshot_strategy not in ("STRICT", "BEST_EFFORT", "UNKNOWN"):
        raise HTTPException(400, "snapshot_strategy must be STRICT|BEST_EFFORT|UNKNOWN")
    sid = "sess_" + uuid.uuid4().hex[:12]
    db = _db()
    row = SessionRow(id=sid, resource_type=body.resource_type, source=body.source,
                     scope_json=json.dumps(body.scope), scope_hash=scope_hash(body.scope),
                     pagination_type=body.pagination_type, snapshot_strategy=body.snapshot_strategy)
    db.add(row)
    db.commit()
    db.close()
    return {"session_id": sid, "status": "collecting", "scope_hash": row.scope_hash}


@router.get("/sessions/{sid}")
async def get_session(sid: str):
    db = _db()
    row = db.get(SessionRow, sid)
    if not row:
        db.close()
        raise HTTPException(404, "session not found")
    out = _load(row)
    out["observation_count"] = len(out["observations"])
    out["failure_count"] = len(out["failures"])
    db.close()
    return out


@router.post("/sessions/{sid}/observe")
async def observe(sid: str, body: ObservePage):
    db = _db()
    row = db.get(SessionRow, sid)
    if not row:
        db.close()
        raise HTTPException(404, "session not found")
    obs = json.loads(row.observations_json or "[]")
    scope = body.scope if body.scope is not None else json.loads(row.scope_json or "{}")
    entry = {"page_number": body.page_number, "offset": body.offset, "cursor_in": body.cursor_in,
             "cursor_out": body.cursor_out, "has_more": body.has_more, "records_seen": body.records_seen,
             "items": body.items, "scope": scope, "scope_hash": scope_hash(scope),
             "snapshot_id": body.snapshot_id, "authoritative_total": body.authoritative_total}
    obs.append(entry)
    row.observations_json = json.dumps(obs)
    row.status = "complete" if not body.has_more else "collecting"
    db.add(row)
    db.commit()
    last = obs[-1]
    nxt = last.get("cursor_out") if last.get("has_more") else None
    db.close()
    return {"accepted": True, "coverage_status": "COMPLETE" if not body.has_more else "INCOMPLETE",
            "next_expected_cursor": nxt, "pages_seen": len(obs)}


@router.post("/sessions/{sid}/failure")
async def record_failure(sid: str, body: FailureRecord):
    db = _db()
    row = db.get(SessionRow, sid)
    if not row:
        db.close()
        raise HTTPException(404, "session not found")
    fails = json.loads(row.failures_json or "[]")
    fails.append({"page_number": body.page_number, "kind": body.kind, "message": body.message})
    row.failures_json = json.dumps(fails)
    row.status = "collecting"
    db.add(row)
    db.commit()
    db.close()
    return {"accepted": True, "unresolved_failures": len(fails)}


@router.get("/sessions/{sid}/observations")
async def list_observations(sid: str):
    db = _db()
    row = db.get(SessionRow, sid)
    if not row:
        db.close()
        raise HTTPException(404, "session not found")
    out = {"observations": json.loads(row.observations_json or "[]"),
           "failures": json.loads(row.failures_json or "[]")}
    db.close()
    return out


@router.post("/sessions/{sid}/verify")
async def verify_claim(sid: str, body: VerifyIn):
    db = _db()
    row = db.get(SessionRow, sid)
    if not row:
        db.close()
        raise HTTPException(404, "session not found")
    sess = _load(row)
    claim = body.claim.model_dump(exclude_none=False)
    result = verify(sess, claim)
    row.result_json = json.dumps(result)
    if result["verdict"] == "PROVEN":
        row.certificate_json = json.dumps(issue_certificate(sess, claim, result))
        row.status = "proven"
    else:
        row.certificate_json = "{}"
        row.status = "collecting"
    db.add(row)
    db.commit()
    cert = json.loads(row.certificate_json or "{}")
    db.close()
    result["certificate"] = cert or None
    return result


@router.get("/sessions/{sid}/certificate")
async def get_certificate(sid: str):
    db = _db()
    row = db.get(SessionRow, sid)
    if not row:
        db.close()
        raise HTTPException(404, "session not found")
    cert = json.loads(row.certificate_json or "{}")
    db.close()
    if not cert:
        raise HTTPException(404, "no certificate (claim not PROVEN yet)")
    return cert


@router.post("/claims/parse")
async def parse(body: ParseIn):
    return parse_claim(body.text)
