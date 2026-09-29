from __future__ import annotations

import re
import secrets
import hashlib
import sys
from pathlib import Path

import uvicorn
from fastapi import FastAPI, Header, HTTPException, Query
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, ConfigDict, Field

ROOT_DIR = Path(__file__).resolve().parents[2]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from services.account_binding_service.console import render_polymarket_console  # noqa: E402
from services.account_binding_service.schemas import (  # noqa: E402
    CompletePolymarketBindingSessionRequest,
    CreatePolymarketBindingSessionRequest,
    RevokePolymarketBindingSessionRequest,
)
from services.account_binding_service.service import PolymarketAccountBindingService, PolymarketClobAuthError  # noqa: E402
from shared.config import AppConfig  # noqa: E402
from shared.core_account_client import CoreAccountClient, CoreAccountClientError  # noqa: E402

CONFIG = AppConfig.from_env()
SERVICE = PolymarketAccountBindingService(CONFIG)
CORE_ACCOUNT_CLIENT = CoreAccountClient(
    CONFIG.clink_core_account_service_url,
    CONFIG.clink_core_internal_api_token,
)
APP = FastAPI(title="Clink Prediction Markets Account Binding")


class CoreAccountSetupRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    user_id: str = Field(min_length=1, max_length=96)


def _canonical_evm_address(value: str | None) -> str:
    normalized = str(value or "").strip().lower()
    if not re.fullmatch(r"0x[0-9a-f]{40}", normalized):
        raise HTTPException(status_code=502, detail="Core Account returned an invalid wallet address")
    return normalized


def _require_core_wallet(user_id: str, submitted_wallet: str | None = None) -> str:
    try:
        readiness = CORE_ACCOUNT_CLIENT.readiness(user_id)
    except CoreAccountClientError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    if not readiness.get("wallet_bound") or not readiness.get("wallet_address"):
        raise HTTPException(status_code=409, detail="Core Account wallet binding is required")
    core_wallet = _canonical_evm_address(readiness["wallet_address"])
    if submitted_wallet is not None and _canonical_evm_address(submitted_wallet) != core_wallet:
        raise HTTPException(status_code=409, detail="Selected wallet does not match the active Core wallet")
    return core_wallet


def _require_internal_token(authorization: str | None = Header(default=None)) -> None:
    expected = CONFIG.clink_core_internal_api_token.strip()
    supplied = str(authorization or "").removeprefix("Bearer ").strip()
    if not expected or not secrets.compare_digest(supplied, expected):
        raise HTTPException(status_code=401, detail="invalid internal bearer token")


def _require_console_token(session: object, supplied: str | None) -> None:
    metadata = getattr(session, "metadata", {}) or {}
    expected_hash = str(metadata.get("console_token_hash") or "")
    supplied_hash = hashlib.sha256(str(supplied or "").encode()).hexdigest()
    if not expected_hash or not secrets.compare_digest(supplied_hash, expected_hash):
        raise HTTPException(status_code=401, detail="binding console session unavailable")


def _public_session(session: object) -> dict:
    payload = session.model_dump()
    payload["metadata"] = {
        key: value
        for key, value in payload.get("metadata", {}).items()
        if key != "console_token_hash"
    }
    return payload


@APP.get("/healthz")
def healthz() -> dict:
    return {
        "service": "prediction_markets_account_binding_service",
        "status": "ok",
        "console_base_url": CONFIG.account_binding_console_base_url,
        "credential_store": SERVICE.credential_store.describe(),
    }


@APP.get("/clink/account/readiness")
def core_account_readiness(user_id: str) -> dict:
    try:
        readiness = CORE_ACCOUNT_CLIENT.readiness(user_id)
    except CoreAccountClientError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return {
        key: value
        for key, value in readiness.items()
        if key not in {"wallet_address", "wallet_identity_id"}
    }


@APP.post("/clink/account/setup-link", status_code=201)
def create_core_account_setup_link(request: CoreAccountSetupRequest) -> dict:
    try:
        return CORE_ACCOUNT_CLIENT.create_setup_link(request.user_id)
    except CoreAccountClientError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc


@APP.post("/internal/polymarket/binding-sessions")
def create_binding_session(
    request: CreatePolymarketBindingSessionRequest,
    authorization: str | None = Header(default=None),
) -> dict:
    _require_internal_token(authorization)
    core_wallet = _require_core_wallet(request.user_id, request.wallet_address)
    core_bound_request = request.model_copy(update={"wallet_address": core_wallet})
    return _public_session(SERVICE.create_binding_session(core_bound_request))


@APP.get("/internal/polymarket/binding-sessions/{session_id}")
def get_binding_session(
    session_id: str,
    authorization: str | None = Header(default=None),
) -> dict:
    _require_internal_token(authorization)
    session = SERVICE.get_binding_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="binding session not found")
    return session.model_dump()


@APP.post("/polymarket/binding-sessions/{session_id}/complete")
def complete_binding_session(
    session_id: str,
    request: CompletePolymarketBindingSessionRequest,
    x_clink_console_token: str | None = Header(default=None),
) -> dict:
    session = SERVICE.get_binding_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="binding session not found")
    _require_console_token(session, x_clink_console_token)
    _require_core_wallet(session.user_id, request.wallet_address)
    try:
        return _public_session(SERVICE.complete_binding_session(session_id, request))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except PolymarketClobAuthError as exc:
        raise HTTPException(
            status_code=502,
            detail={
                "status": "clob_auth_failed",
                "reason": exc.detail,
                "status_code": exc.status_code,
                "next_action": "retry_polymarket_clob_auth_or_use_fallback",
            },
        ) from exc


@APP.get("/polymarket/clob-server-time")
def clob_server_time() -> dict:
    try:
        return {"timestamp": SERVICE.clob_auth_client.get_server_time()}
    except PolymarketClobAuthError as exc:
        raise HTTPException(status_code=502, detail={"status": "clob_time_failed", "reason": exc.detail}) from exc


@APP.get("/internal/polymarket/binding/{binding_id}")
def get_binding(binding_id: str, authorization: str | None = Header(default=None)) -> dict:
    _require_internal_token(authorization)
    binding = SERVICE.get_binding(binding_id)
    if binding is None:
        raise HTTPException(status_code=404, detail="binding not found")
    return binding.model_dump()


@APP.post("/internal/polymarket/binding/{binding_id}/revoke")
def revoke_binding(
    binding_id: str,
    request: dict | None = None,
    authorization: str | None = Header(default=None),
) -> dict:
    _require_internal_token(authorization)
    payload = request or {}
    try:
        return SERVICE.revoke_binding(
            binding_id,
            reason=str(payload.get("reason") or "user_requested_unbind"),
            metadata=payload.get("metadata") or {},
        ).model_dump()
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@APP.get("/internal/polymarket/bindings/latest/{user_id}")
def internal_latest_binding(user_id: str, authorization: str | None = Header(default=None)) -> dict:
    _require_internal_token(authorization)
    binding = SERVICE.latest_binding(user_id)
    return binding.model_dump() if binding else {
        "status": "unavailable",
        "next_action": "create_polymarket_account_binding",
    }


@APP.get("/polymarket/bindings/latest/{user_id}")
def public_latest_binding(user_id: str) -> dict:
    binding = SERVICE.latest_binding(user_id)
    return {
        "status": "active" if binding else "unavailable",
        "next_action": "account_binding_active" if binding else "create_polymarket_account_binding",
    }


@APP.post("/polymarket/binding-sessions/{session_id}/revoke")
def revoke_binding_session(
    session_id: str,
    request: RevokePolymarketBindingSessionRequest,
    x_clink_console_token: str | None = Header(default=None),
) -> dict:
    session = SERVICE.get_binding_session(session_id)
    if session is None or not session.binding_id:
        raise HTTPException(status_code=404, detail="active binding is not available for this session")
    _require_console_token(session, x_clink_console_token)
    if SERVICE._is_expired(session.expires_at):
        raise HTTPException(status_code=410, detail="binding console session expired")
    core_wallet = _require_core_wallet(session.user_id, request.wallet_address)
    expected_message = (
        "Revoke Clink Polymarket Binding\n"
        f"session_id={session.session_id}\n"
        f"binding_id={session.binding_id}\n"
        f"user_id={session.user_id}\n"
        f"wallet_address={core_wallet}"
    )
    if request.signed_message != expected_message or not SERVICE._signature_matches_wallet(
        core_wallet, request.signed_message, request.signature
    ):
        raise HTTPException(status_code=401, detail="wallet authorization is required to unbind Polymarket")
    try:
        return SERVICE.revoke_binding(
            session.binding_id,
            reason=request.reason,
            metadata=request.metadata,
        ).model_dump()
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@APP.get("/polymarket/binding-console/{session_id}", response_class=HTMLResponse)
def binding_console(
    session_id: str,
    access_token: str | None = Query(default=None, max_length=128),
) -> HTMLResponse:
    session = SERVICE.get_binding_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail="binding session not found")
    _require_console_token(session, access_token)
    nonce = secrets.token_urlsafe(24)
    return HTMLResponse(
        render_polymarket_console(
            session.model_dump(), nonce=nonce, console_token=access_token
        ),
        headers={
            "Content-Security-Policy": (
                "default-src 'none'; "
                f"script-src 'nonce-{nonce}'; style-src 'nonce-{nonce}'; "
                "connect-src 'self'; img-src 'self'; font-src 'self'; "
                "object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'"
            ),
            "X-Frame-Options": "DENY",
            "X-Content-Type-Options": "nosniff",
            "Cache-Control": "no-store",
            "Referrer-Policy": "no-referrer",
        },
    )


def main() -> None:
    uvicorn.run(APP, host=CONFIG.account_binding_host, port=CONFIG.account_binding_port)


if __name__ == "__main__":
    main()
