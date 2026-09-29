from __future__ import annotations

import json
import uuid
from typing import Annotated, Any

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.core.config import MAX_ENDPOINTS, MAX_PROJECTS, MAX_UPLOAD_BYTES
from app.models.db import ProjectRow, engine
from app.schemas.api import (
    ExhaustiveClaimRequest,
    ProjectCreate,
    ProxyRequest,
    TestRequest,
)
from app.services import importer
from app.services.analyzer import analyze_endpoints
from app.services.contract import build_agent_contract
from app.services.exhaustiveness import prove_exhaustive_claim
from app.services.http_client import safe_request
from app.services.runtime import execute_operation
from app.services.scoring import compute_score
from app.services.tester import probe_endpoint
from app.services.tools import generate_tools

router = APIRouter()


def _db() -> Session:
    return Session(engine, expire_on_commit=False)


def _save(row: ProjectRow, db: Session) -> None:
    db.add(row)
    db.commit()


def _json(raw: str | None, default: Any) -> Any:
    try:
        return json.loads(raw or "")
    except (TypeError, json.JSONDecodeError):
        return default


def _repair_bundle(row: ProjectRow) -> dict[str, Any]:
    value = _json(row.repairs_json, {})
    return value if isinstance(value, dict) else {"changes": value if isinstance(value, list) else [], "contract": None}


def _live_findings(test_results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    findings: list[dict[str, Any]] = []
    for result in test_results:
        common = {"endpoint": result.get("endpoint"), "operation_id": result.get("operation_id")}
        if result.get("shape_drift"):
            findings.append({**common, "severity": "high", "code": "OBSERVED_SHAPE_DRIFT", "message": "Successful observations returned different JSON shapes.", "suggested_repair": "Expose an evidence-bound union schema and a stable adapter envelope."})
        if result.get("schema_failures"):
            findings.append({**common, "severity": "high", "code": "OBSERVED_SCHEMA_MISMATCH", "message": f"{result['schema_failures']} observation(s) violated the declared success schema.", "suggested_repair": "Correct the upstream contract or response implementation."})
        if result.get("status") == "failed":
            findings.append({**common, "severity": "high", "code": "LIVE_PROBE_FAILED", "message": result.get("reason") or "No live observation passed.", "suggested_repair": "Provide valid test arguments, authentication, or restore the upstream endpoint."})
        elif result.get("status") == "skipped":
            findings.append({**common, "severity": "medium", "code": "LIVE_PROBE_SKIPPED", "message": result.get("reason") or "No live evidence was collected.", "suggested_repair": "Supply bounded test arguments or keep manual execution only."})
    return findings


def _evaluate(spec: dict[str, Any], tests: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    endpoints = importer.extract_endpoints(spec)
    analyses, issues = analyze_endpoints(endpoints)
    issues.extend(_live_findings(tests or []))
    return {"endpoints": endpoints, "analyses": analyses, "issues": issues, "score": compute_score(analyses, issues, tests)}


def _validate_scope(spec: dict[str, Any]) -> list[dict[str, Any]]:
    endpoints = importer.extract_endpoints(spec)
    if not endpoints:
        raise HTTPException(400, "The specification contains no supported operations")
    if len(endpoints) > MAX_ENDPOINTS:
        raise HTTPException(400, f"The specification exceeds the {MAX_ENDPOINTS}-operation limit")
    return endpoints


async def _fetch_spec(url: str) -> dict[str, Any]:
    try:
        response = await safe_request("GET", url)
    except HTTPException:
        raise
    except Exception as exc:
        raise HTTPException(400, f"Failed to fetch OpenAPI: {str(exc)[:300]}") from exc
    if not 200 <= response.status_code < 300:
        raise HTTPException(400, f"OpenAPI URL returned HTTP {response.status_code}")
    try:
        return importer.parse_spec_content(response.content.decode("utf-8", errors="strict"))
    except (TypeError, UnicodeDecodeError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc


def _create_row(name: str, spec: dict[str, Any], openapi_url: str = "") -> dict[str, Any]:
    endpoints = _validate_scope(spec)
    db = _db()
    if db.query(ProjectRow).count() >= MAX_PROJECTS:
        db.close()
        raise HTTPException(429, "Project capacity reached; delete an older project and retry")
    row = ProjectRow(id=uuid.uuid4().hex[:12], name=name, openapi_url=openapi_url, spec_json=json.dumps(spec))
    evaluation = _evaluate(spec)
    row.analysis_json = json.dumps(evaluation["analyses"])
    row.issues_json = json.dumps(evaluation["issues"])
    row.score_json = json.dumps(evaluation["score"])
    row.tools_json = "[]"
    _save(row, db)
    db.close()
    return {"id": row.id, "name": row.name, "endpoints": len(endpoints), "score": evaluation["score"], "issues": evaluation["issues"]}


@router.post("/projects")
async def create_project(body: ProjectCreate):
    if body.openapi_json is not None:
        try:
            spec = importer.parse_spec_content(body.openapi_json)
        except (TypeError, ValueError) as exc:
            raise HTTPException(400, str(exc)) from exc
    elif body.openapi_url:
        spec = await _fetch_spec(body.openapi_url)
    else:
        raise HTTPException(400, "Provide openapi_url or openapi_json")
    return _create_row(body.name, spec, body.openapi_url or "")


@router.post("/projects/upload")
async def upload_project(name: Annotated[str, Form()], file: Annotated[UploadFile, File()]):
    raw = await file.read(MAX_UPLOAD_BYTES + 1)
    if len(raw) > MAX_UPLOAD_BYTES:
        raise HTTPException(400, f"File exceeds the {MAX_UPLOAD_BYTES}-byte limit")
    try:
        spec = importer.parse_spec_content(raw.decode("utf-8", errors="strict"))
    except (TypeError, UnicodeDecodeError, ValueError) as exc:
        raise HTTPException(400, str(exc)) from exc
    return _create_row(name, spec)


@router.get("/projects")
async def list_projects():
    db = _db()
    rows = db.query(ProjectRow).limit(MAX_PROJECTS).all()
    result = [{"id": row.id, "name": row.name, "score": _json(row.score_json, {}).get("overall")} for row in rows]
    db.close()
    return result


@router.get("/projects/{pid}")
async def get_project(pid: str):
    db = _db()
    row = db.get(ProjectRow, pid)
    if not row:
        db.close()
        raise HTTPException(404, "Project not found")
    source_spec = _json(row.spec_json, {})
    result = {
        "id": row.id,
        "name": row.name,
        "openapi_url": row.openapi_url,
        "endpoints": importer.extract_endpoints(source_spec),
        "score": _json(row.score_json, {}),
        "issues": _json(row.issues_json, []),
        "comparison": _json(row.retest_json, {}),
        "proof": _json(row.proof_json, {}),
        "has_agent_contract": bool(_repair_bundle(row).get("contract")),
    }
    db.close()
    return result


@router.delete("/projects/{pid}", status_code=204)
async def delete_project(pid: str):
    db = _db()
    row = db.get(ProjectRow, pid)
    if not row:
        db.close()
        raise HTTPException(404, "Project not found")
    db.delete(row)
    db.commit()
    db.close()


@router.post("/projects/{pid}/analyze")
async def analyze(pid: str):
    db = _db()
    row = db.get(ProjectRow, pid)
    if not row:
        db.close()
        raise HTTPException(404, "Project not found")
    evaluation = _evaluate(_json(row.spec_json, {}), _json(row.tests_json, []))
    row.analysis_json = json.dumps(evaluation["analyses"])
    row.issues_json = json.dumps(evaluation["issues"])
    row.score_json = json.dumps(evaluation["score"])
    _save(row, db)
    db.close()
    return {"project_id": pid, "endpoints": len(evaluation["endpoints"]), "score": evaluation["score"], "issues": evaluation["issues"]}


@router.get("/projects/{pid}/analysis")
async def get_analysis(pid: str):
    db = _db()
    row = db.get(ProjectRow, pid)
    if not row:
        db.close()
        raise HTTPException(404, "Project not found")
    result = {"analyses": _json(row.analysis_json, []), "score": _json(row.score_json, {})}
    db.close()
    return result


@router.post("/projects/{pid}/test")
async def run_tests(pid: str, body: TestRequest | None = None):
    db = _db()
    row = db.get(ProjectRow, pid)
    if not row:
        db.close()
        raise HTTPException(404, "Project not found")
    body = body or TestRequest()
    spec = _json(row.spec_json, {})
    endpoints = importer.extract_endpoints(spec)
    results = [
        await probe_endpoint(endpoint, body.arguments.get(endpoint["operation_id"], {}), body.samples_per_endpoint)
        for endpoint in endpoints
    ]
    evaluation = _evaluate(spec, results)
    row.tests_json = json.dumps(results)
    row.analysis_json = json.dumps(evaluation["analyses"])
    row.issues_json = json.dumps(evaluation["issues"])
    row.score_json = json.dumps(evaluation["score"])
    _save(row, db)
    db.close()
    return {"project_id": pid, "tests": results, "score": evaluation["score"]}


@router.get("/projects/{pid}/tests")
async def get_tests(pid: str):
    db = _db()
    row = db.get(ProjectRow, pid)
    if not row:
        db.close()
        raise HTTPException(404, "Project not found")
    result = _json(row.tests_json, [])
    db.close()
    return result


@router.get("/projects/{pid}/issues")
async def get_issues(pid: str):
    db = _db()
    row = db.get(ProjectRow, pid)
    if not row:
        db.close()
        raise HTTPException(404, "Project not found")
    result = _json(row.issues_json, [])
    db.close()
    return result


@router.get("/projects/{pid}/score")
async def get_score(pid: str):
    db = _db()
    row = db.get(ProjectRow, pid)
    if not row:
        db.close()
        raise HTTPException(404, "Project not found")
    result = _json(row.score_json, {})
    db.close()
    return result


@router.post("/projects/{pid}/contract")
@router.post("/projects/{pid}/repair", deprecated=True)
async def build_contract(pid: str):
    db = _db()
    row = db.get(ProjectRow, pid)
    if not row:
        db.close()
        raise HTTPException(404, "Project not found")
    source_spec = _json(row.spec_json, {})
    tests = _json(row.tests_json, [])
    before_evaluation = _evaluate(source_spec, tests)
    contract, changes = build_agent_contract(source_spec, tests)
    contract_evaluation = _evaluate(contract, tests)
    comparison = {
        "before_score": before_evaluation["score"]["overall"],
        "after_score": contract_evaluation["score"]["overall"],
        "improvement": contract_evaluation["score"]["overall"] - before_evaluation["score"]["overall"],
        "source_findings": len(before_evaluation["issues"]),
        "contract_findings": len(contract_evaluation["issues"]),
        "changes_applied": len(changes),
        "basis": "re-analysis of the generated contract; no simulated score",
    }
    row.repairs_json = json.dumps({"changes": changes, "contract": contract})
    row.retest_json = json.dumps(comparison)
    row.tools_json = json.dumps(generate_tools(contract_evaluation["endpoints"]))
    _save(row, db)
    db.close()
    return {"changes": changes, "comparison": comparison, "contract": contract}


@router.get("/projects/{pid}/repairs")
async def get_repairs(pid: str):
    db = _db()
    row = db.get(ProjectRow, pid)
    if not row:
        db.close()
        raise HTTPException(404, "Project not found")
    result = _repair_bundle(row)
    db.close()
    return result


@router.get("/projects/{pid}/comparison")
async def get_comparison(pid: str):
    db = _db()
    row = db.get(ProjectRow, pid)
    if not row:
        db.close()
        raise HTTPException(404, "Project not found")
    result = _json(row.retest_json, {})
    db.close()
    return result


@router.get("/projects/{pid}/contract")
async def get_contract(pid: str):
    db = _db()
    row = db.get(ProjectRow, pid)
    if not row:
        db.close()
        raise HTTPException(404, "Project not found")
    contract = _repair_bundle(row).get("contract")
    db.close()
    if not contract:
        raise HTTPException(409, "Generate the agent contract first")
    return contract


@router.get("/projects/{pid}/tools")
async def get_tools(pid: str):
    db = _db()
    row = db.get(ProjectRow, pid)
    if not row:
        db.close()
        raise HTTPException(404, "Project not found")
    result = _json(row.tools_json, [])
    db.close()
    return result


@router.post("/projects/{pid}/proxy/{operation_id}")
async def proxy(pid: str, operation_id: str, body: ProxyRequest):
    db = _db()
    row = db.get(ProjectRow, pid)
    if not row:
        db.close()
        raise HTTPException(404, "Project not found")
    source_spec = _json(row.spec_json, {})
    contract = _repair_bundle(row).get("contract") or source_spec
    endpoint = next((item for item in importer.extract_endpoints(contract) if item["operation_id"] == operation_id), None)
    db.close()
    if not endpoint:
        raise HTTPException(404, "Operation not found")
    return await execute_operation(endpoint, body.arguments)


@router.post("/projects/{pid}/prove")
async def prove_claim(pid: str, body: ExhaustiveClaimRequest):
    db = _db()
    row = db.get(ProjectRow, pid)
    if not row:
        db.close()
        raise HTTPException(404, "Project not found")
    source_spec = _json(row.spec_json, {})
    endpoint = next((item for item in importer.extract_endpoints(source_spec) if item["operation_id"] == body.operation_id), None)
    if not endpoint:
        db.close()
        raise HTTPException(404, "Operation not found")
    db.close()
    result = await prove_exhaustive_claim(endpoint, body.model_dump())
    db = _db()
    row = db.get(ProjectRow, pid)
    if row:
        row.proof_json = json.dumps(result)
        _save(row, db)
    db.close()
    return result


@router.get("/projects/{pid}/export")
async def export(pid: str):
    db = _db()
    row = db.get(ProjectRow, pid)
    if not row:
        db.close()
        raise HTTPException(404, "Project not found")
    repairs = _repair_bundle(row)
    result = {
        "format": "apivouch-agent-pack-v1",
        "project": {"id": row.id, "name": row.name},
        "source_readiness": _json(row.score_json, {}),
        "live_evidence": _json(row.tests_json, []),
        "findings": _json(row.issues_json, []),
        "contract_changes": repairs.get("changes", []),
        "agent_contract": repairs.get("contract"),
        "mcp_tools": _json(row.tools_json, []),
        "comparison": _json(row.retest_json, {}),
        "exhaustiveness_proof": _json(row.proof_json, {}),
        "mcp_endpoint": f"/mcp/{row.id}",
    }
    db.close()
    return result
