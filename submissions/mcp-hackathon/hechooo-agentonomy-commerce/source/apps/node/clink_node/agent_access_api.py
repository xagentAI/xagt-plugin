"""Trusted wallet-business control API, not an Agent administration surface."""

from dataclasses import asdict
from typing import Literal

from fastapi import APIRouter, HTTPException
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from pydantic import BaseModel, ConfigDict, Field

from .adapters.http import DownstreamError
from .agent_access import AgentAccessError
from .agent_access_http import ControlIngressMiddleware
from .agent_access_views import owned_account, owned_payment
from .projections import build_balance_summary


class _Request(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


class RegisterAgentRequest(_Request):
    subject_id: str = Field(min_length=1, max_length=256)
    external_agent_id: str = Field(min_length=1, max_length=256)


class RuntimeCredentialRequest(_Request):
    runtime_id: str = Field(min_length=1, max_length=256)
    request_id: str = Field(min_length=1, max_length=256)
    scope: Literal["read", "payments"] = "payments"
    ttl_seconds: int = Field(default=300, ge=60, le=900)
    replaces_credential_id: str | None = Field(default=None, min_length=1, max_length=256)


class AccountLinkRequest(_Request):
    kind: Literal["core", "polymarket"]


def attach_agent_access_routes(app, context) -> None:
    service = context.agent_access_service
    token = context.agent_control_token
    if service is None or not isinstance(token, str) or len(token) < 32 or not token.isascii():
        raise ValueError("agent access credentials are not configured")
    if any(ord(ch) <= 32 or ord(ch) >= 127 for ch in token):
        raise ValueError("agent access credentials are invalid")
    app.add_middleware(ControlIngressMiddleware, control_token=token)
    router = APIRouter(prefix="/v1/c")

    @app.exception_handler(AgentAccessError)
    async def access_error(_request, exc):
        return JSONResponse({"error": exc.code}, status_code={"unauthorized": 401, "not_found": 404, "conflict": 409}.get(exc.code, 400))

    @app.exception_handler(RequestValidationError)
    async def invalid_request(_request, _exc):
        return JSONResponse({"error": "invalid_request"}, status_code=422)

    @app.exception_handler(DownstreamError)
    async def downstream_error(_request, exc):
        code = 404 if exc.status_code in {403, 404} else 503
        return JSONResponse({"error": "owned_object_not_found" if code == 404 else "service_unavailable", "retry_safe": False}, status_code=code)

    @router.post("/agents", status_code=201)
    def register_agent(request: RegisterAgentRequest):
        return asdict(service.register(**request.model_dump()))

    @router.get("/agents/{agent_id}")
    def get_agent(agent_id: str):
        return asdict(service.get_agent(agent_id))

    @router.get("/agents/{agent_id}/runtime")
    def get_runtime(agent_id: str):
        return service.get_runtime_status(agent_id)

    @router.post("/agents/{agent_id}/runtime-credentials", status_code=201)
    def issue_credential(agent_id: str, request: RuntimeCredentialRequest):
        credential = service.issue_credential(agent_id=agent_id, **request.model_dump())
        return {**asdict(credential), "token_type": "Bearer", "mcp_url": context.settings.agent_access.mcp_public_url}

    @router.post("/agents/{agent_id}/runtimes/{runtime_id}/revoke")
    def revoke_runtime(agent_id: str, runtime_id: str):
        service.revoke_runtime(agent_id=agent_id, runtime_id=runtime_id)
        return {"agent_id": agent_id, "runtime_id": runtime_id, "status": "revoked", "payments_cancelled": False}

    @router.get("/agents/{agent_id}/account")
    def account(agent_id: str):
        binding = service.get_agent(agent_id)
        summary = owned_account(context, binding.user_id)
        return {"agent_id": agent_id, "account": summary,
                "balances": build_balance_summary(context.core, context.prediction_markets, binding.user_id, strict_owner=True),
                "permissions_editable_by_agent": False}

    @router.post("/agents/{agent_id}/account-links", status_code=201)
    def account_link(agent_id: str, request: AccountLinkRequest):
        binding = service.get_agent(agent_id)
        if request.kind == "core":
            session = context.core.create_account_session(binding.user_id)
            return {"kind": "core", "url": session["account_url"], "expires_at": session.get("expires_at")}
        readiness = context.core.account_readiness(binding.user_id)
        if (readiness.get("user_id") != binding.user_id or readiness.get("wallet_bound") is not True
                or not readiness.get("wallet_address")):
            raise HTTPException(409, "wallet_binding_required")
        return context.prediction_markets.create_agent_binding_session(
            user_id=binding.user_id, wallet_address=readiness["wallet_address"],
        )

    @router.get("/agents/{agent_id}/payments/{kind}/{operation_id}")
    def payment(agent_id: str, kind: Literal["marketplace", "polymarket_funding"], operation_id: str):
        binding = service.get_agent(agent_id)
        return owned_payment(context, binding.user_id, kind, operation_id)

    app.include_router(router)
