"""HTTP application factory with explicit Cloudflare runtime bindings."""

import hashlib
import hmac
import inspect
import json
import re
import secrets
from typing import Any, Literal
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response
from pydantic import BaseModel, ConfigDict, Field, StrictBool

from app.adapters import demos
from app.adapters.nexus import SourceInsufficient, SourceUnavailable
from app.domain.engine import InputError, METHOD_VERSION, evaluate, normalize_curve, validate_pair
from app.evidence import build_evidence
from app.storage import IntegrityError, QuotaExceeded, StorageUnavailable, now

SLUG = "paratrix-strategy-increment"
COOKIE = "strategy_increment_session"
MAX_BODY = 2 * 1024 * 1024


def strict_json(body):
    def object_pairs(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate key")
            result[key] = value
        return result

    def reject_constant(_value):
        raise ValueError("non-finite JSON")

    return json.loads(body, parse_float=str, parse_constant=reject_constant, object_pairs_hook=object_pairs)


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class SnapshotInput(StrictModel):
    curve: dict[str, Any]


class PairInput(StrictModel):
    baseline_snapshot_id: str = Field(pattern=r"^s_[0-9a-f]{32}$")
    candidate_snapshot_id: str = Field(pattern=r"^s_[0-9a-f]{32}$")
    start: str | None = Field(default=None, max_length=40)
    end: str | None = Field(default=None, max_length=40)


class ExperimentInput(PairInput):
    criteria: dict[str, Any] | None = None
    mode: Literal["historical_exploration", "declared_holdout"] = "historical_exploration"
    data_seen: StrictBool = True
    parent_experiment_id: str | None = Field(default=None, pattern=r"^e_[0-9a-f]{32}$")


class NexusInput(StrictModel):
    strategy_ref: str = Field(min_length=1, max_length=120, pattern=r"^[a-zA-Z0-9_-]+$")


def error(status, code, message, issues=None):
    return JSONResponse(
        status_code=status, content={"error": {"code": code, "message": message, "issues": issues or []}}
    )


async def resolved(value):
    """Accept asynchronous runtime operations and synchronous test doubles."""
    return await value if inspect.isawaitable(value) else value


def create_app(*, store, nexus, settings, source_hash, assets):
    """Compose the Worker HTTP interface; runtime resources are always injected."""
    app = FastAPI(
        title="Strategy Increment",
        version="0.1.0",
        description="Reproducible research using complete simulated equity curves",
    )
    app.state.store = store
    app.state.nexus = nexus
    app.state.source_sha256 = source_hash
    commit = settings.get("REVIEW_COMMIT", "")
    app.state.commit = commit if re.fullmatch(r"[0-9a-f]{40}", commit) else None
    secure_cookie = settings.get("COOKIE_SECURE", "false").lower() == "true"

    @app.middleware("http")
    async def boundaries(request: Request, call_next):
        token = request.cookies.get(COOKIE, "")
        secret = app.state.store.secret.encode()
        nonce, _, sig = token.partition(".")
        expected = hmac.new(secret, nonce.encode(), hashlib.sha256).hexdigest()
        fresh = (
            not re.fullmatch(r"[0-9a-f]{64}", nonce)
            or not re.fullmatch(r"[0-9a-f]{64}", sig)
            or not hmac.compare_digest(sig, expected)
        )
        if fresh:
            nonce = secrets.token_hex(32)
            token = nonce + "." + hmac.new(secret, nonce.encode(), hashlib.sha256).hexdigest()
        request.state.owner = hashlib.sha256(nonce.encode()).hexdigest()
        response = None
        allowed_hosts = {"127.0.0.1", "localhost", "::1", "testserver"}
        configured_origin = settings.get("PUBLIC_ORIGIN", "")
        if configured_origin:
            allowed_hosts.add(urlsplit(configured_origin).hostname)
        if request.url.hostname not in allowed_hosts:
            return error(400, "host_rejected", "Request host is not configured.")
        if request.method in {"POST", "PUT", "PATCH", "DELETE"}:
            origin = request.headers.get("origin")
            allowed_origin = settings.get("PUBLIC_ORIGIN") or str(request.base_url).rstrip("/")
            if request.headers.get("sec-fetch-site") == "cross-site" or (origin and origin != allowed_origin):
                response = error(403, "origin_rejected", "Only same-origin browser requests are accepted.")
            elif request.headers.get("content-type", "").split(";")[0].lower() != "application/json":
                response = error(415, "json_required", "Content-Type must be application/json.")
            else:
                body = bytearray()
                async for chunk in request.stream():
                    body.extend(chunk)
                    if len(body) > MAX_BODY:
                        response = error(413, "payload_too_large", "Request body exceeds 2 MiB.")
                        break
                if response is None:
                    try:
                        # Preserve numeric JSON decimals as strings before model validation.
                        # The domain accepts exact decimal strings; ambiguous JSON is rejected.
                        request._body = json.dumps(
                            strict_json(bytes(body)), ensure_ascii=False, allow_nan=False
                        ).encode()
                    except (ValueError, UnicodeError, RecursionError):
                        response = error(
                            422, "invalid_json", "Invalid JSON, duplicate fields, or non-finite numbers."
                        )
        if response is None:
            try:
                response = await call_next(request)
            except Exception:
                # No raw upstream errors, user inputs, SQL or credentials in responses/logs.
                response = error(
                    500,
                    "internal_error",
                    "The request failed; check experiment history before retrying a save.",
                )
        if fresh:
            response.set_cookie(
                COOKIE,
                token,
                max_age=60 * 60 * 24 * 30,
                httponly=True,
                secure=secure_cookie,
                samesite="strict",
                path="/",
            )
        response.headers["X-Content-Type-Options"] = "nosniff"
        response.headers["Referrer-Policy"] = "no-referrer"
        response.headers["X-Frame-Options"] = "DENY"
        response.headers["Cache-Control"] = "no-store"
        if request.url.path == "/" or request.url.path.startswith("/static/"):
            response.headers["Content-Security-Policy"] = (
                "default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; "
                "connect-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'"
            )
        return response

    @app.exception_handler(RequestValidationError)
    async def request_invalid(_request, exc):
        issues = [
            {
                "code": "invalid_field",
                "path": ".".join(str(p) for p in item["loc"]),
                "message": "Field is missing, has an invalid type, or is unsupported.",
            }
            for item in exc.errors()[:20]
        ]
        return error(422, "invalid_input", "Check the request fields.", issues)

    @app.exception_handler(InputError)
    async def input_invalid(_request, exc):
        return error(422, "not_evaluable", "The inputs do not meet the comparison requirements.", exc.issues)

    @app.exception_handler(KeyError)
    async def not_found(_request, _exc):
        return error(404, "not_found", "The record was not found in the current session.")

    @app.exception_handler(QuotaExceeded)
    async def quota(_request, _exc):
        return error(
            429, "session_quota", "The session limit of 100 snapshots or 100 experiments has been reached."
        )

    @app.exception_handler(StorageUnavailable)
    async def storage_error(_request, _exc):
        return error(
            503,
            "storage_unavailable",
            "Storage is temporarily unavailable; check experiment history before retrying a save.",
        )

    @app.exception_handler(IntegrityError)
    async def integrity_error(_request, _exc):
        return error(
            503,
            "stored_data_mismatch",
            "Stored data integrity failed; calculation and export have been blocked.",
        )

    async def asset_response(name):
        media_types = {
            "index.html": "text/html",
            "app.js": "application/javascript",
            "styles.css": "text/css",
        }
        if name not in media_types:
            return error(404, "not_found", "File not found.")
        asset = await assets.fetch("https://assets.internal/" + name)
        return Response(bytes(await asset.bytes()), status_code=asset.status, media_type=media_types[name])

    @app.get("/", include_in_schema=False)
    async def index():
        return await asset_response("index.html")

    @app.get("/static/{name:path}", include_in_schema=False)
    async def static_asset(name: str):
        return await asset_response(name)

    @app.get("/health")
    async def health():
        if not await resolved(app.state.store.health()):
            raise StorageUnavailable()
        return {
            "status": "ok",
            "commit": app.state.commit,
            "source_sha256": app.state.source_sha256,
            "method_version": METHOD_VERSION,
            "release_bound": app.state.commit is not None,
        }

    @app.get("/.well-known/xagent-verification.json")
    async def proof():
        if app.state.commit is None:
            return error(503, "release_not_bound", "No actual release review commit has been bound.")
        return {"schemaVersion": 1, "slug": SLUG, "commit": app.state.commit}

    @app.get("/v1/demo-cases")
    async def cases():
        return {"cases": demos.list_cases()}

    @app.get("/v1/demo-cases/{case_id}")
    async def get_case(case_id: str):
        return demos.get_case(case_id)

    @app.get("/v1/source-status")
    async def sources():
        return {"local": {"available": True}, "nexus": app.state.nexus.status()}

    @app.post("/v1/nexus/import", status_code=201)
    async def import_nexus(body: NexusInput, request: Request):
        try:
            curve = await resolved(app.state.nexus.import_curve(body.strategy_ref))
            return await resolved(app.state.store.snapshot(request.state.owner, normalize_curve(curve)))
        except SourceUnavailable:
            return error(
                503,
                "source_unavailable",
                "The external Nexus connection is disabled in this deployment. Use a public example or import simulated equity JSON.",
            )
        except SourceInsufficient as exc:
            return error(
                422,
                "source_not_sufficient",
                "The Nexus response lacks the complete data required for analysis.",
                getattr(exc, "issues", []),
            )

    @app.post("/v1/data-snapshots", status_code=201)
    async def snapshot(body: SnapshotInput, request: Request):
        return await resolved(
            app.state.store.snapshot(request.state.owner, normalize_curve(body.curve), body.curve)
        )

    async def pair(body, owner):
        return (
            await resolved(app.state.store.get("snapshots", owner, body.baseline_snapshot_id)),
            await resolved(app.state.store.get("snapshots", owner, body.candidate_snapshot_id)),
        )

    @app.post("/v1/comparison-inputs/validate")
    async def validate(body: PairInput, request: Request):
        a, b = await pair(body, request.state.owner)
        return validate_pair(a["curve"], b["curve"], start=body.start, end=body.end)

    @app.post("/v1/experiments", status_code=201)
    async def experiment(body: ExperimentInput, request: Request):
        owner = request.state.owner
        a, b = await pair(body, owner)
        if body.parent_experiment_id:
            await resolved(app.state.store.get("experiments", owner, body.parent_experiment_id))
        result = evaluate(a["curve"], b["curve"], start=body.start, end=body.end, criteria=body.criteria)
        config = body.model_dump()
        config["start"], config["end"] = result["coverage"]["start"], result["coverage"]["end"]
        reasons = []
        if body.data_seen:
            reasons.append("The researcher declared that this interval has already been observed.")
        if body.mode == "historical_exploration":
            reasons.append("The researcher selected historical exploration.")
        if any(item["curve"].get("provenance", {}).get("observed_before") is True for item in (a, b)):
            reasons.append("The source is marked as previously observed demonstration or historical data.")
        if body.parent_experiment_id:
            reasons.append("Derived from an existing experiment; exploration history is retained.")
        provenance = {
            "requested_mode": body.mode,
            "data_seen": body.data_seen,
            "effective_mode": "historical_exploration" if reasons else "declared_holdout",
            "exploration_reasons": reasons,
            "holdout_note": "Holdout status is a user declaration, not independently certified; a new session cannot recover earlier session history.",
            "locked_at": now(),
            "application_version": "0.1.0",
            "source_sha256": app.state.source_sha256,
            "review_commit": app.state.commit,
        }
        for key, item in (("baseline", a), ("candidate", b)):
            provenance[key] = {
                field: item["curve"][field]
                for field in ("name", "strategy_id", "run_id", "source_kind", "cost_model", "currency")
            }
            provenance[key].update(
                {
                    "snapshot_id": item["snapshot_id"],
                    "content_hash": item["content_hash"],
                    "observed_before": item["curve"].get("provenance", {}).get("observed_before"),
                }
            )
        identifier = "e_" + secrets.token_hex(16)
        record = {
            "experiment_id": identifier,
            "created_at": now(),
            "config": config,
            "provenance": provenance,
            "result": result,
            "evidence_url": f"/v1/experiments/{identifier}/evidence",
        }

        return await resolved(app.state.store.save_experiment(owner, record))

    @app.get("/v1/experiments")
    async def history(request: Request):
        records = await resolved(app.state.store.experiments(request.state.owner))
        return {
            "experiments": [
                {
                    "experiment_id": record["experiment_id"],
                    "created_at": record["created_at"],
                    "status": record["result"]["status"],
                    "baseline_name": record["provenance"]["baseline"]["name"],
                    "candidate_name": record["provenance"]["candidate"]["name"],
                    "mode": record["provenance"]["effective_mode"],
                }
                for record in records
            ]
        }

    @app.get("/v1/experiments/{experiment_id}")
    async def detail(experiment_id: str, request: Request):
        return await resolved(app.state.store.get("experiments", request.state.owner, experiment_id))

    @app.get("/v1/experiments/{experiment_id}/evidence")
    async def evidence(experiment_id: str, request: Request):
        record = await resolved(app.state.store.get("experiments", request.state.owner, experiment_id))
        a, b = await pair(ExperimentInput(**record["config"]), request.state.owner)
        return JSONResponse(
            build_evidence(
                record,
                a["curve"],
                b["curve"],
                raw_curves={
                    "baseline": a.get("raw_curve", a["curve"]),
                    "candidate": b.get("raw_curve", b["curve"]),
                },
            ),
            headers={"Content-Disposition": f'attachment; filename="{record["experiment_id"]}.json"'},
        )

    return app
