"""HTTP admission for the opt-in, shared C Agent ingress."""

import asyncio
import hmac
from typing import Any

from fastapi import APIRouter
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel, ConfigDict, Field
from starlette.responses import JSONResponse

from shared.opc_protocol import OpcProtocolError, canonical_opc_origin

from .opc_core_client import OpcCoreError


_OPC_POST_PATHS = frozenset(
    {
        "/v1/opc/pairings",
        "/v1/opc/token",
        "/v1/opc/status",
        "/v1/opc/revoke",
    }
)


class _OpcProofRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    proof: str = Field(
        min_length=1,
        max_length=16 * 1024,
        pattern=r"^[\x21-\x7e]+$",
    )


def bearer_token(scope: dict) -> str:
    values = [value for name, value in scope.get("headers", []) if name.lower() == b"authorization"]
    if len(values) != 1 or not values[0].startswith(b"Bearer ") or len(values[0]) > 2048:
        raise ValueError("unauthorized")
    try:
        value = values[0][7:].decode("ascii")
    except UnicodeDecodeError:
        raise ValueError("unauthorized") from None
    if not value or any(ord(ch) <= 32 or ord(ch) >= 127 for ch in value):
        raise ValueError("unauthorized")
    return value


async def _bounded_request(app, scope, receive, send):
    if scope.get("method") not in {"POST", "PUT", "PATCH", "DELETE"}:
        await app(scope, receive, send)
        return
    body = bytearray()
    try:
        async with asyncio.timeout(10):
            while True:
                message = await receive()
                if message["type"] == "http.disconnect":
                    return
                if message["type"] != "http.request":
                    continue
                body.extend(message.get("body", b""))
                if len(body) > 65536:
                    await JSONResponse({"error": "request_too_large"}, status_code=413)(scope, receive, send)
                    return
                if not message.get("more_body", False):
                    break
    except TimeoutError:
        await JSONResponse({"error": "request_timeout"}, status_code=408)(scope, receive, send)
        return
    consumed = False

    async def replay():
        nonlocal consumed
        if consumed:
            return await receive()
        consumed = True
        return {"type": "http.request", "body": bytes(body), "more_body": False}

    await app(scope, replay, send)


class RuntimeMcpAuthMiddleware:
    def __init__(self, app, *, access_service: Any):
        self.app, self.access_service = app, access_service

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        try:
            token = bearer_token(scope)
            await asyncio.to_thread(self.access_service.authenticate, token)
        except ValueError:
            await JSONResponse({"error": "unauthorized"}, status_code=401,
                               headers={"WWW-Authenticate": "Bearer", "Cache-Control": "no-store"})(scope, receive, send)
            return
        except Exception:
            # Database/credential infrastructure failure is not permission to proceed.
            await JSONResponse({"error": "authentication_unavailable"}, status_code=503)(scope, receive, send)
            return
        await _bounded_request(self.app, scope, receive, send)


class ControlIngressMiddleware:
    def __init__(self, app, *, control_token: str | None = None):
        self.app = app
        self.control_token = control_token

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return
        path = scope.get("path", "")
        control = path.startswith("/v1/c/")
        method = scope.get("method", "")
        opc = path in _OPC_POST_PATHS and method == "POST"
        marketplace_catalogue = (
            path == "/v1/marketplace/services" and method == "GET"
        )
        # The OPC surface is deliberately exact.  In particular, no GET,
        # trailing-slash or unknown OPC path may fall through to a legacy route.
        if path.startswith("/v1/opc/") and not opc:
            await JSONResponse(
                {"error": "route_not_available"}, status_code=404
            )(scope, receive, send)
            return
        # Existing wallet interaction handlers enforce their own session/signature
        # and CSRF checks. Other legacy Node data/companion routes are not public.
        public = path in {"/healthz", "/readyz", "/account"} or path.startswith((
            "/account/", "/polymarket/binding-console/", "/polymarket/binding-sessions/",
        )) or path == "/polymarket/clob-server-time"
        if not control and not public and not opc and not marketplace_catalogue:
            await JSONResponse({"error": "route_not_available"}, status_code=404)(scope, receive, send)
            return
        if control:
            try:
                authorized = (
                    isinstance(self.control_token, str)
                    and hmac.compare_digest(
                        bearer_token(scope), self.control_token
                    )
                )
            except (TypeError, ValueError):
                authorized = False
            if not authorized:
                await JSONResponse({"error": "unauthorized"}, status_code=401)(scope, receive, send)
                return

        async def no_store(message):
            if message["type"] == "http.response.start":
                message = dict(message)
                message["headers"] = [(name, value) for name, value in message.get("headers", []) if name.lower() != b"cache-control"]
                message["headers"].append((b"cache-control", b"no-store"))
            await send(message)

        await _bounded_request(self.app, scope, receive, no_store)


def attach_opc_routes(
    app,
    core_client: Any,
    *,
    public_origin: str,
    account_public_origin: str | None = None,
    control_token: str | None = None,
    allow_loopback_http: bool = False,
    add_ingress: bool = True,
) -> None:
    """Attach the four public OPC proof endpoints to the Node API.

    The route body contains only the device proof.  Core is called through the
    already-authenticated ``core_client``; callers never receive its internal
    URL or bearer.  ``add_ingress`` is false when C routes already installed
    the shared admission middleware on the same FastAPI app.
    """

    if core_client is None:
        raise ValueError("OPC Core client is required")
    try:
        public = canonical_opc_origin(
            public_origin,
            allow_loopback_http=allow_loopback_http,
        )
        account = canonical_opc_origin(
            account_public_origin or public_origin,
            allow_loopback_http=allow_loopback_http,
        )
    except OpcProtocolError as exc:
        raise ValueError("OPC public origin is invalid") from exc

    if add_ingress:
        app.add_middleware(
            ControlIngressMiddleware,
            control_token=control_token,
        )

    @app.exception_handler(RequestValidationError)
    async def invalid_opc_request(_request, _exc):
        return JSONResponse({"error": "invalid_request"}, status_code=422)

    router = APIRouter(prefix="/v1/opc")

    def failure(exc: Exception) -> JSONResponse:
        if isinstance(exc, OpcCoreError):
            status_code = (
                exc.status_code
                if 400 <= exc.status_code < 500
                else 503
            )
        else:
            status_code = 503
        return JSONResponse(
            {
                "error": (
                    "opc_request_rejected"
                    if status_code < 500
                    else "opc_service_unavailable"
                )
            },
            status_code=status_code,
        )

    @router.post("/pairings", status_code=201)
    def create_pairing(request: _OpcProofRequest):
        try:
            return _public_pairing(core_client.create_pairing(request.proof), account)
        except Exception as exc:
            return failure(exc)

    @router.post("/token")
    def issue_token(request: _OpcProofRequest):
        try:
            return _public_token(core_client.issue_token(request.proof), public)
        except Exception as exc:
            return failure(exc)

    @router.post("/status")
    def status(request: _OpcProofRequest):
        try:
            return _public_status(core_client.status(request.proof))
        except Exception as exc:
            return failure(exc)

    @router.post("/revoke")
    def revoke(request: _OpcProofRequest):
        try:
            value = core_client.revoke(request.proof)
            if (
                type(value) is not dict
                or value.get("status") != "revoked"
            ):
                raise OpcCoreError(502, "OPC Core response is invalid")
            return {
                "installation_id": _public_installation_id(
                    value.get("installation_id")
                ),
                "status": "revoked",
            }
        except Exception as exc:
            return failure(exc)

    app.include_router(router)


def _public_pairing(value: Any, account_origin: str) -> dict[str, Any]:
    if type(value) is not dict or set(value) != {
        "installation_id",
        "pairing_id",
        "verification_uri",
        "expires_at",
        "status",
    }:
        raise OpcCoreError(502, "OPC Core response is invalid")
    installation_id = _public_installation_id(value.get("installation_id"))
    pairing_id = value.get("pairing_id")
    if (
        type(pairing_id) is not str
        or not pairing_id.startswith("opc_pair_")
        or len(pairing_id) != len("opc_pair_") + 40
        or any(character not in "0123456789abcdef" for character in pairing_id.removeprefix("opc_pair_"))
    ):
        raise OpcCoreError(502, "OPC Core response is invalid")
    expires_at = value.get("expires_at")
    status = value.get("status")
    if type(expires_at) is not int or expires_at < 0 or status not in {"pending", "active"}:
        raise OpcCoreError(502, "OPC Core response is invalid")
    path = _safe_account_path(value.get("verification_uri"))
    return {
        "installation_id": installation_id,
        "pairing_id": pairing_id,
        "verification_uri": account_origin + path,
        "expires_at": expires_at,
        "status": status,
    }


def _public_token(value: Any, public_origin: str) -> dict[str, Any]:
    if type(value) is not dict or set(value) != {
        "installation_id",
        "access_token",
        "token_type",
        "expires_at",
        "mcp_url",
    }:
        raise OpcCoreError(502, "OPC Core response is invalid")
    installation_id = _public_installation_id(value.get("installation_id"))
    token = value.get("access_token")
    if (
        type(token) is not str
        or not token.startswith("agentonomy_opc_v1_")
        or len(token) <= len("agentonomy_opc_v1_")
        or len(token) > 512
        or any(ord(character) < 0x21 or ord(character) > 0x7E for character in token)
        or value.get("token_type") != "Bearer"
    ):
        raise OpcCoreError(502, "OPC Core response is invalid")
    expires_at = value.get("expires_at")
    if type(expires_at) is not int or expires_at < 0:
        raise OpcCoreError(502, "OPC Core response is invalid")
    return {
        "installation_id": installation_id,
        "access_token": token,
        "token_type": "Bearer",
        "expires_at": expires_at,
        "mcp_url": public_origin + "/mcp",
    }


def _public_status(value: Any) -> dict[str, Any]:
    if type(value) is not dict:
        raise OpcCoreError(502, "OPC Core response is invalid")
    installation_id = _public_installation_id(value.get("installation_id"))
    status = value.get("status")
    if type(status) is not str or status not in {
        "pending",
        "active",
        "consent_required",
        "revoked",
        "unpaired",
    }:
        raise OpcCoreError(502, "OPC Core response is invalid")
    result = {"installation_id": installation_id, "status": status}
    for name in (
        "label",
        "scope",
        "consent_expires_at",
        "created_at",
        "updated_at",
    ):
        if name not in value:
            continue
        item = value[name]
        if name == "label" and (
            type(item) is not str or not 1 <= len(item) <= 80
        ):
            raise OpcCoreError(502, "OPC Core response is invalid")
        if name == "scope" and item != "payments":
            raise OpcCoreError(502, "OPC Core response is invalid")
        if name.endswith("_at") and item is not None and type(item) is not str:
            raise OpcCoreError(502, "OPC Core response is invalid")
        result[name] = item
    return result


def _public_installation_id(value: Any) -> str:
    if (
        type(value) is not str
        or len(value) != len("opc_") + 40
        or not value.startswith("opc_")
        or any(character not in "0123456789abcdef" for character in value.removeprefix("opc_"))
    ):
        raise OpcCoreError(502, "OPC Core response is invalid")
    return value


def _safe_account_path(value: Any) -> str:
    if type(value) is not str or len(value) > 2048:
        raise OpcCoreError(502, "OPC Core response is invalid")
    try:
        from urllib.parse import urlsplit

        parsed = urlsplit(value)
    except ValueError:
        raise OpcCoreError(502, "OPC Core response is invalid") from None
    suffix = parsed.path.removeprefix("/account/")
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.hostname is None
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
        or not parsed.path.startswith("/account/")
        or not suffix
        or any(part in {"", ".", ".."} for part in parsed.path.split("/")[2:])
        or any(ord(character) <= 32 for character in parsed.path)
    ):
        raise OpcCoreError(502, "OPC Core response is invalid")
    return parsed.path
