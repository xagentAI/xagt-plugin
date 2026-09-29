from __future__ import annotations

import hmac
from dataclasses import dataclass, field
from typing import Any, Protocol

from fastapi import (
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Query,
    Request,
    status,
)
from fastapi.responses import JSONResponse, Response

from .adapters.core import AccountProxyResponse
from .adapters.http import DownstreamError
from .agent_access import AgentAccessService
from .agent_access_api import attach_agent_access_routes

from .companion import attach_companion
from .config import NodeSettings
from .interactions import InteractionService
from .miniapp.routes import attach_miniapp_routes
from .miniapp.service import MiniAppChatService
from .projections import build_account_summary, build_activity_summary
from .schemas import (
    AccountSessionRequest,
    InteractionConsumeRequest,
    InteractionRequest,
)
from .storage.base import NodeRepository


_MAX_PUBLIC_PROXY_POST_BODY_BYTES = 64 * 1024


class CoreAdapter(Protocol):
    def health(self) -> dict[str, Any]: ...

    def account_readiness(self, user_id: str) -> dict[str, Any]: ...

    def wallet_balances(self, user_id: str) -> dict[str, Any]: ...

    def create_account_session(self, user_id: str) -> dict[str, Any]: ...

    def proxy_account_request(
        self,
        *,
        method: str,
        path: str,
        query: str,
        headers: list[tuple[str, str]],
        body: bytes,
    ) -> AccountProxyResponse: ...

    def audit_summary(
        self,
        user_id: str,
        limit: int,
    ) -> list[dict[str, Any]]: ...


class BusinessAdapter(Protocol):
    name: str

    def health(self) -> dict[str, Any]: ...

    def capabilities(self) -> list[dict[str, Any]]: ...

    def proxy_public_request(
        self,
        *,
        method: str,
        path: str,
        query: str,
        headers: list[tuple[str, str]],
        body: bytes,
    ) -> AccountProxyResponse: ...


class MarketplaceAdapter(BusinessAdapter, Protocol):
    def list_services(
        self,
        limit: int = 20,
    ) -> dict[str, Any]: ...


class PredictionMarketsAdapter(BusinessAdapter, Protocol):
    def account_status(self, user_id: str) -> dict[str, Any]: ...

    def account_balance(self, user_id: str) -> dict[str, Any]: ...


@dataclass(frozen=True)
class NodeApiContext:
    settings: NodeSettings
    repository: NodeRepository
    interaction_service: InteractionService
    session_token: str
    core: CoreAdapter
    marketplace: MarketplaceAdapter
    prediction_markets: PredictionMarketsAdapter
    miniapp_service: MiniAppChatService | None = None
    agent_access_service: AgentAccessService | None = None
    agent_control_token: str = field(default="", repr=False)


def create_app(context: NodeApiContext) -> FastAPI:
    app = FastAPI(
        title="Clink Node",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
    )
    app.state.context = context
    if context.settings.agent_access.enabled:
        attach_agent_access_routes(app, context)
    if context.miniapp_service is not None:
        attach_miniapp_routes(app, context.miniapp_service)

    def require_session(
        authorization: str | None = Header(default=None),
    ) -> None:
        expected = f"Bearer {context.session_token}"
        if authorization is None or not hmac.compare_digest(
            authorization,
            expected,
        ):
            raise HTTPException(
                status.HTTP_401_UNAUTHORIZED,
                "invalid Clink Node session",
            )

    @app.get("/healthz")
    def health() -> dict[str, Any]:
        modules = _module_projection(context.repository)
        failed = any(
            item["status"] in {"failed", "stopped"}
            for item in modules.values()
        )
        return {
            "service": "clink_node",
            "status": "degraded" if failed else "ok",
            "profile": context.settings.profile.value,
            "modules": modules,
        }

    @app.get("/readyz")
    def ready() -> JSONResponse:
        modules = _module_projection(context.repository)
        not_ready = {
            name: item
            for name, item in modules.items()
            if item["status"] not in {"ready", "external", "disabled"}
        }
        payload = {
            "service": "clink_node",
            "status": "not_ready" if not_ready else "ready",
            "modules": modules,
        }
        return JSONResponse(payload, status_code=503 if not_ready else 200)

    @app.get("/v1/node")
    def node() -> dict[str, Any]:
        return context.settings.redacted()

    @app.get("/v1/modules")
    def modules() -> dict[str, Any]:
        projection = _module_projection(context.repository)
        return {"count": len(projection), "modules": projection}

    @app.get("/v1/capabilities")
    def capabilities() -> dict[str, Any]:
        items = [
            *context.marketplace.capabilities(),
            *context.prediction_markets.capabilities(),
        ]
        return {"count": len(items), "capabilities": items}

    @app.get("/v1/marketplace/services")
    def marketplace_services(
        limit: int = Query(default=20, ge=1, le=20),
    ) -> dict[str, Any]:
        try:
            return context.marketplace.list_services(limit)
        except DownstreamError as exc:
            raise HTTPException(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                "Marketplace service catalog unavailable",
            ) from exc

    @app.get("/v1/account/readiness")
    def account_readiness(user_id: str) -> dict[str, Any]:
        return context.core.account_readiness(user_id)

    @app.get("/v1/account/summary")
    def account_summary(user_id: str) -> dict[str, Any]:
        return build_account_summary(
            context.core,
            context.prediction_markets,
            user_id,
        )

    @app.get("/v1/activity")
    def activity(
        user_id: str,
        limit: int = Query(default=12, ge=1, le=50),
    ) -> dict[str, Any]:
        return build_activity_summary(context.core, user_id, limit)

    @app.post(
        "/v1/account/sessions",
        status_code=status.HTTP_201_CREATED,
        dependencies=[Depends(require_session)],
    )
    def create_account_session(
        request: AccountSessionRequest,
    ) -> dict[str, Any]:
        return context.core.create_account_session(request.user_id)

    @app.api_route(
        "/account",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        include_in_schema=False,
    )
    @app.api_route(
        "/account/{account_path:path}",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        include_in_schema=False,
    )
    async def core_account_proxy(
        request: Request,
        account_path: str = "",
    ) -> Response:
        path = "/account"
        if account_path:
            path = f"{path}/{account_path}"
        proxied = context.core.proxy_account_request(
            method=request.method,
            path=path,
            query=request.url.query,
            headers=list(request.headers.items()),
            body=await request.body(),
        )
        response = Response(
            content=proxied.content,
            status_code=proxied.status_code,
        )
        for name, value in proxied.headers:
            response.headers.append(name, value)
        return response

    async def proxy_business_request(
        adapter: BusinessAdapter,
        request: Request,
        path: str,
    ) -> Response:
        body = await _bounded_public_proxy_body(request)
        try:
            proxied = adapter.proxy_public_request(
                method=request.method,
                path=path,
                query=request.url.query,
                headers=list(request.headers.items()),
                body=body,
            )
        except ValueError as exc:
            raise HTTPException(404, "interaction route unavailable") from exc
        response = Response(
            content=proxied.content,
            status_code=proxied.status_code,
        )
        for name, value in proxied.headers:
            response.headers.append(name, value)
        return response

    @app.api_route(
        "/x402/checkout/{checkout_path:path}",
        methods=["GET", "POST"],
        include_in_schema=False,
    )
    async def marketplace_checkout_proxy(
        request: Request,
        checkout_path: str,
    ) -> Response:
        return await proxy_business_request(
            context.marketplace,
            request,
            f"/x402/checkout/{checkout_path}",
        )

    @app.api_route(
        "/assets/x402_checkout.css",
        methods=["GET"],
        include_in_schema=False,
    )
    @app.api_route(
        "/assets/x402_checkout.js",
        methods=["GET"],
        include_in_schema=False,
    )
    async def marketplace_checkout_asset_proxy(
        request: Request,
    ) -> Response:
        return await proxy_business_request(
            context.marketplace,
            request,
            request.url.path,
        )

    @app.api_route(
        "/polymarket/{console_path:path}",
        methods=["GET", "POST"],
        include_in_schema=False,
    )
    async def polymarket_binding_proxy(
        request: Request,
        console_path: str,
    ) -> Response:
        return await proxy_business_request(
            context.prediction_markets,
            request,
            f"/polymarket/{console_path}",
        )

    @app.api_route(
        "/execution/polymarket/{console_path:path}",
        methods=["GET", "POST"],
        include_in_schema=False,
    )
    async def polymarket_order_proxy(
        request: Request,
        console_path: str,
    ) -> Response:
        return await proxy_business_request(
            context.prediction_markets,
            request,
            f"/execution/polymarket/{console_path}",
        )

    @app.post(
        "/v1/interactions",
        status_code=status.HTTP_201_CREATED,
        dependencies=[Depends(require_session)],
    )
    def create_interaction(
        request: InteractionRequest,
    ) -> dict[str, Any]:
        link = context.interaction_service.create(
            request.kind,
            request.user_id,
            request.payload,
        )
        return {
            "session_id": link.session_id,
            "url": link.url,
            "expires_at": link.expires_at.isoformat(),
        }

    @app.get("/v1/interactions/{session_id}")
    def interaction(session_id: str) -> dict[str, Any]:
        item = context.interaction_service.inspect(session_id)
        if item is None:
            raise HTTPException(404, "interaction unavailable")
        return {
            "session_id": item.session_id,
            "kind": item.kind,
            "user_id": item.user_id,
            "status": item.status,
            "expires_at": item.expires_at.isoformat(),
        }

    @app.post("/v1/interactions/{session_id}/consume")
    def consume_interaction(
        session_id: str,
        request: InteractionConsumeRequest,
    ) -> dict[str, Any]:
        item = context.interaction_service.consume(
            session_id,
            request.token,
        )
        if item is None:
            raise HTTPException(404, "interaction unavailable")
        return {
            "session_id": item.session_id,
            "kind": item.kind,
            "user_id": item.user_id,
            "status": item.status,
            "payload": item.payload,
        }

    attach_companion(
        app,
        miniapp_enabled=context.settings.miniapp.enabled,
    )
    return app


async def _bounded_public_proxy_body(request: Request) -> bytes:
    if request.method != "POST":
        return b""
    raw_values = [
        value
        for name, value in request.scope.get("headers", ())
        if name.lower() == b"content-length"
    ]
    if len(raw_values) != 1:
        raise HTTPException(400, "proxy request is invalid")
    try:
        declared_text = raw_values[0].decode("ascii")
    except UnicodeError:
        raise HTTPException(400, "proxy request is invalid") from None
    if (
        not declared_text
        or not declared_text.isdigit()
        or len(declared_text) > 1
        and declared_text.startswith("0")
    ):
        raise HTTPException(400, "proxy request is invalid")
    maximum_text = str(_MAX_PUBLIC_PROXY_POST_BODY_BYTES)
    if (
        len(declared_text) > len(maximum_text)
        or len(declared_text) == len(maximum_text)
        and declared_text > maximum_text
    ):
        raise HTTPException(413, "proxy request is too large")
    declared = int(declared_text)
    content = bytearray()
    async for chunk in request.stream():
        if len(chunk) > _MAX_PUBLIC_PROXY_POST_BODY_BYTES - len(content):
            raise HTTPException(413, "proxy request is too large")
        content.extend(chunk)
    if len(content) != declared:
        raise HTTPException(400, "proxy request is invalid")
    return bytes(content)


def _module_projection(
    repository: NodeRepository,
) -> dict[str, dict[str, Any]]:
    return {
        record.name: {
            "mode": record.mode,
            "status": record.status,
            "pid": record.pid,
            "endpoint": record.endpoint,
            "mcp_url": record.mcp_url,
            "detail": record.detail,
            "updated_at": record.updated_at.isoformat(),
        }
        for record in repository.list_modules()
    }
