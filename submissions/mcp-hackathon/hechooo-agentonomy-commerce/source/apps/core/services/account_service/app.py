from __future__ import annotations

import base64
import hashlib
import html as html_encoding
import json
import os
import secrets
from contextlib import asynccontextmanager
from dataclasses import asdict, is_dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from threading import RLock
from typing import Callable, Literal
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode, urlsplit
from urllib.request import Request as URLRequest, urlopen
from uuid import uuid4

import uvicorn
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse, Response
from services.account_service.authorization import (
    AuthorizationForm, allowance_advice, authorization_terms,
)
from pydantic import BaseModel, ConfigDict, Field, field_validator

from shared.canonical_assets import CanonicalAssetRegistry
from shared.config import AppConfig
from shared.evm_rpc import NetworkRpcTransport
from services.audit_service.schemas import AuditSummaryEvent

from .console import (
    ACCOUNT_CONSOLE_CSS,
    ACCOUNT_CONSOLE_HTML,
    ACCOUNT_CONSOLE_JS,
    ACCOUNT_SESSION_CONFIRM_HTML,
)
from .repository import AccountRepository
from .allowance_recovery import AllowanceRecoveryStore
from .allowance_reconciler import AllowanceReconciler
from .opc_service import OpcAccountService
from .schemas import (
    AssetAllowance,
    AuthorizationResolutionRequest,
    PublicAccountSession,
    OpcInstallationAuthorization,
    SpendingGrantRequest,
    canonicalize_evm_address,
    canonicalize_transaction_hash,
    reject_control_characters,
)
from .service import (
    AccountService,
    AllowanceAmountMismatch,
    AllowanceVerificationPending,
    configured_network_configs,
)


CSP = (
    "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; "
    "img-src 'self' data:; font-src 'self'; object-src 'none'; base-uri 'none'; "
    "frame-ancestors 'none'; form-action 'self'"
)
SECURITY_HEADERS = {
    "Content-Security-Policy": CSP,
    "X-Content-Type-Options": "nosniff",
    "Cache-Control": "no-store",
    "Referrer-Policy": "no-referrer",
}
SESSION_COOKIE = "clink_account_session"
CSRF_COOKIE = "clink_account_csrf"
CSRF_HEADER = "X-CSRF-Token"


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CreateAccountSessionRequest(StrictRequest):
    user_id: str = Field(min_length=1, max_length=96)

    _safe_user_id = field_validator("user_id")(reject_control_characters)


class EmptyRequest(StrictRequest):
    pass


class OpcProofRequest(StrictRequest):
    proof: str = Field(min_length=1, max_length=16 * 1024)


class OpcAuthenticateRequest(StrictRequest):
    access_token: str = Field(min_length=1, max_length=512)


class OpcInstallationChallengeRequest(StrictRequest):
    spending_grant_id: str = Field(min_length=1, max_length=96)


class OpcInstallationApproveRequest(StrictRequest):
    challenge_session_id: str = Field(min_length=1, max_length=128)
    signed_message: str = Field(min_length=1, max_length=16 * 1024)
    signature: str = Field(min_length=1, max_length=512)


class WalletChallengeRequest(StrictRequest):
    wallet_address: str


class WalletVerifyRequest(StrictRequest):
    challenge_session_id: str
    signed_message: str
    signature: str


class GrantRequest(StrictRequest):
    user_id: str | None = None
    wallet_identity_id: str
    agent_id: str
    max_amount_usdc: Decimal
    per_transaction_limit_usdc: Decimal
    hourly_limit_usdc: Decimal | None = None
    daily_limit_usdc: Decimal
    product_scopes: list[str]
    venue_scopes: list[str] = Field(default_factory=list)
    merchant_scopes: list[str] = Field(default_factory=list)
    merchant_trust_scopes: list[str] = Field(default_factory=lambda: ["clink_verified"])
    notification_mode: str = "notify_all"
    network_scopes: list[str]
    asset_scopes: list[str]
    starts_at: datetime
    expires_at: datetime
    amends_spending_grant_id: str | None = Field(default=None, max_length=96)
    opc_pairing_id: str | None = Field(default=None, max_length=96)
    challenge_session_id: str | None = None
    signed_message: str | None = None
    signature: str | None = None


class AllowanceVerifyRequest(StrictRequest):
    wallet_identity_id: str
    network: str
    token_address: str
    spender_address: str
    allowance_tx_hash: str


class AllowanceAttemptRequest(StrictRequest):
    wallet_identity_id: str = Field(min_length=1, max_length=96)
    network: str = Field(min_length=1, max_length=32)
    token_address: str
    spender_address: str
    amount_atomic: str = Field(pattern=r"^[1-9][0-9]{0,77}$")
    request_key: str = Field(pattern=r"^[0-9a-f]{64}$")


class AllowanceAttemptKeyRequest(StrictRequest):
    request_key: str = Field(pattern=r"^[0-9a-f]{64}$")


class AllowanceAttemptSubmittedRequest(AllowanceAttemptKeyRequest):
    allowance_tx_hash: str


class ReduceGrantRequest(StrictRequest):
    max_amount_usdc: Decimal | None = None
    per_transaction_limit_usdc: Decimal | None = None
    hourly_limit_usdc: Decimal | None = None
    daily_limit_usdc: Decimal | None = None


def _json(value):
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if is_dataclass(value):
        return asdict(value)
    return value


def _decimal_string(value: Decimal) -> str:
    rendered = format(value, "f").rstrip("0").rstrip(".")
    return rendered or "0"


def _public_network_configs(
    network_configs: dict[str, dict[str, object]],
) -> dict[str, dict[str, object]]:
    """Expose only the network facts needed by the account browser console."""

    return {
        network: {
            "chain_id": int(values["chain_id"]),
            "required_confirmations": int(values["required_confirmations"]),
            "token_symbol": str(values["token_symbol"]),
            "token_decimals": int(values["token_decimals"]),
        }
        for network, values in network_configs.items()
    }


def _remote_audit_summary_reader(
    config: AppConfig, internal_token: str
) -> Callable[[str, int], list[AuditSummaryEvent]]:
    def read(user_id: str, limit: int) -> list[AuditSummaryEvent]:
        if not internal_token:
            return []
        query = urlencode({"user_id": user_id, "limit": limit})
        request = URLRequest(
            f"{config.audit_service_url}/audit/summary?{query}",
            headers={"Authorization": f"Bearer {internal_token}"},
        )
        try:
            with urlopen(request, timeout=2.0) as response:
                payload = json.loads(response.read())
        except (HTTPError, URLError, OSError, ValueError, TypeError):
            return []
        if not isinstance(payload, list):
            return []
        try:
            return [AuditSummaryEvent.model_validate(item) for item in payload]
        except ValueError:
            return []

    return read


def _approval_targets(
    config: AppConfig,
    service: AccountService,
    configured: dict[str, dict[str, str]] | None,
) -> dict[str, dict[str, str]]:
    if configured is None:
        if config.clink_facilitator_mode == "hosted":
            # Hosted executor contracts are part of the signed, per-chain
            # Node projection.  Do not ask operators to duplicate those
            # addresses in the legacy account-service spender settings.
            if config.hosted_rehearsal_enabled:
                fallback_tokens = {
                    network: network_config.get("token_address", "")
                    for network, network_config in service.network_configs.items()
                }
            else:
                # Preserve the production Hosted compatibility behavior:
                # these legacy token settings remain explicitly configured.
                fallback_tokens = {
                    "eip155:137": config.clink_polygon_usdc_address,
                    "eip155:8453": config.clink_base_usdc_address,
                }
            candidates = {
                network: {
                    "token_address": (
                        network_config.get("token_address")
                        or fallback_tokens.get(network, "")
                    ),
                    "spender_address": (
                        config.clink_hosted_facilitator_chain_targets
                        .get(network, {})
                        .get("executor_contract", "")
                    ),
                }
                for network, network_config in service.network_configs.items()
                if network in service.network_configs
            }
        else:
            candidates = {
                "eip155:137": {
                    "token_address": config.clink_polygon_usdc_address,
                    "spender_address": config.clink_polygon_spender_address,
                },
                "eip155:8453": {
                    "token_address": config.clink_base_usdc_address,
                    "spender_address": config.clink_base_spender_address,
                },
            }
    else:
        candidates = configured
    result = {}
    missing = []
    for network, target in candidates.items():
        token_address = target.get("token_address", "")
        spender_address = target.get("spender_address", "")
        if not token_address or not spender_address:
            missing.append(
                {
                    "eip155:137": "Polygon",
                    "eip155:8453": "Base",
                    "eip155:80002": "Polygon Amoy",
                }.get(network, network)
            )
            continue
        if network not in service.network_configs:
            raise ValueError("unsupported approval target network")
        result[network] = {
            "token_address": canonicalize_evm_address(token_address),
            "spender_address": canonicalize_evm_address(spender_address),
        }
    if (
        configured is None
        and missing
        and config.requires_complete_account_approval_targets
    ):
        raise RuntimeError(
            f"{', '.join(missing)} account approval target is incomplete"
        )
    return result


def create_app(
    *,
    service: AccountService | None = None,
    internal_token: str | None = None,
    clock: Callable[[], datetime] | None = None,
    session_ttl: timedelta | None = None,
    audit_summary_reader: Callable[[str, int], list] | None = None,
    approval_targets: dict[str, dict[str, str]] | None = None,
    opc_service: OpcAccountService | None = None,
) -> FastAPI:
    config = AppConfig.from_env()
    current_clock = clock or (lambda: datetime.now(UTC))
    start_recovery_worker = service is None
    if service is None:
        repository = AccountRepository(config.funding_database_url)
        asset_registry = CanonicalAssetRegistry.from_config(config)
        network_configs = configured_network_configs(config)
        configured_tokens = {
            network: asset_registry.token_address(network)
            for network in network_configs
        }
        service = AccountService(
            repository,
            domain=os.getenv("CLINK_ACCOUNT_DOMAIN", "account.clink.local"),
            clock=current_clock,
            rpc_transport=NetworkRpcTransport(config.configured_rpc_urls),
            network_configs={
                network: {**values, "token_address": configured_tokens[network]}
                for network, values in network_configs.items()
            },
            allowed_products=set(config.account_allowed_products),
        )
    if opc_service is not None and opc_service.account is not service:
        raise ValueError("OPC service must share the account service instance")
    if opc_service is None:
        opc_origin = os.getenv("CLINK_OPC_PUBLIC_ORIGIN", "").strip()
        encoded_key = os.getenv("CLINK_OPC_TOKEN_SIGNING_KEY_B64", "").strip()
        if bool(opc_origin) != bool(encoded_key):
            raise RuntimeError(
                "CLINK_OPC_PUBLIC_ORIGIN and CLINK_OPC_TOKEN_SIGNING_KEY_B64 "
                "must be configured together"
            )
        if opc_origin:
            try:
                if "=" in encoded_key:
                    raise ValueError
                token_signing_key = base64.b64decode(
                    encoded_key + "=" * (-len(encoded_key) % 4),
                    altchars=b"-_",
                    validate=True,
                )
            except (TypeError, ValueError) as exc:
                raise RuntimeError("OPC token signing key is invalid") from exc
            account_url = urlsplit(config.account_public_base_url)
            account_origin = f"{account_url.scheme}://{account_url.netloc}"
            allow_loopback = os.getenv("CLINK_OPC_ALLOW_LOOPBACK_HTTP", "") == "1"
            opc_service = OpcAccountService(
                service,
                origin=opc_origin,
                account_origin=account_origin,
                token_signing_key=token_signing_key,
                clock=current_clock,
                allow_loopback_http=allow_loopback,
            )
    token = config.clink_internal_api_token if internal_token is None else internal_token
    read_audit_summary = audit_summary_reader or _remote_audit_summary_reader(
        config, token
    )
    supported_approval_targets = _approval_targets(config, service, approval_targets)
    if session_ttl is None:
        session_ttl = timedelta(seconds=config.account_session_ttl_seconds)
    if session_ttl <= timedelta(0):
        raise ValueError("account session TTL must be positive")
    public_base_path = urlsplit(config.account_public_base_url).path.rstrip("/")
    public_account_path = f"{public_base_path}/account"
    public_network_configs = _public_network_configs(service.network_configs)
    account_console_html = ACCOUNT_CONSOLE_HTML.replace(
        "__CLINK_ACCOUNT_BASE_PATH__", public_account_path
    )
    account_session_confirm_html = ACCOUNT_SESSION_CONFIRM_HTML.replace(
        "__CLINK_ACCOUNT_BASE_PATH__", public_account_path
    )

    recovery_store = AllowanceRecoveryStore(service.repository)
    recovery_worker = AllowanceReconciler(service, recovery_store, clock=current_clock)

    @asynccontextmanager
    async def lifespan(_app):
        if start_recovery_worker:
            recovery_worker.start()
        try:
            yield
        finally:
            if start_recovery_worker:
                recovery_worker.stop()

    app = FastAPI(
        title="Clink Account",
        version="0.1.0",
        description="User-controlled wallet identity and Hermes permission controls.",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )

    @app.middleware("http")
    async def security_boundary(request: Request, call_next):
        if request.url.path.startswith("/internal/"):
            if not token:
                response = JSONResponse(
                    content={"detail": "service unavailable"}, status_code=503
                )
            else:
                authorization = request.headers.get("authorization", "")
                supplied = authorization[7:] if authorization.startswith("Bearer ") else ""
                if not secrets.compare_digest(supplied, token):
                    response = JSONResponse(
                        content={"detail": "unauthorized"}, status_code=401
                    )
                else:
                    response = await call_next(request)
        else:
            response = await call_next(request)
        response.headers.update(SECURITY_HEADERS)
        return response

    @app.exception_handler(RequestValidationError)
    async def invalid_request(_request: Request, _exc: RequestValidationError):
        return JSONResponse(
            content={"detail": "invalid request"},
            status_code=422,
            headers=SECURITY_HEADERS,
        )

    def now() -> datetime:
        value = current_clock()
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("clock must return a timezone-aware datetime")
        return value.astimezone(UTC)

    def current_mandate_projection(
        *, user_id: str, wallet_identity_id: str | None, at: datetime
    ) -> dict | None:
        if not wallet_identity_id:
            return None
        supported_products = {"marketplace", "prediction_markets", "transfers"}
        candidates = [
            item
            for item in service.repository.spending_grants(user_id)
            if item.wallet_identity_id == wallet_identity_id
            and item.agent_id == "hermes"
            and supported_products.intersection(item.product_scopes)
            and item.status in {"active", "paused"}
            and item.starts_at <= at < item.expires_at
        ]
        if len(candidates) != 1:
            return None
        grant = candidates[0]
        hourly_used, hourly_reserved = (
            service.repository.spending_grant_rolling_hour_usage(
                grant.spending_grant_id, at
            )
        )
        daily_used, daily_reserved = service.repository.spending_grant_daily_usage(
            grant.spending_grant_id, at.date()
        )
        total_used = grant.used_amount_usdc
        total_reserved = grant.reserved_amount_usdc
        return {
            **_json(grant),
            "limits_usdc": {
                "per_transaction": _decimal_string(
                    grant.per_transaction_limit_usdc
                ),
                "rolling_hour": _decimal_string(grant.hourly_limit_usdc),
                "daily": _decimal_string(grant.daily_limit_usdc),
                "total": _decimal_string(grant.max_amount_usdc),
            },
            "used_usdc": {
                "rolling_hour": _decimal_string(hourly_used),
                "daily": _decimal_string(daily_used),
                "total": _decimal_string(total_used),
            },
            "reserved_usdc": {
                "rolling_hour": _decimal_string(hourly_reserved),
                "daily": _decimal_string(daily_reserved),
                "total": _decimal_string(total_reserved),
            },
            "remaining_usdc": {
                "rolling_hour": _decimal_string(
                    max(
                        Decimal("0"),
                        grant.hourly_limit_usdc - hourly_used - hourly_reserved,
                    )
                ),
                "daily": _decimal_string(
                    max(
                        Decimal("0"),
                        grant.daily_limit_usdc - daily_used - daily_reserved,
                    )
                ),
                "total": _decimal_string(
                    max(
                        Decimal("0"),
                        grant.max_amount_usdc - total_used - total_reserved,
                    )
                ),
            },
        }

    def allowance_readiness_for_mandate(
        mandate: dict | None, allowances: list[AssetAllowance]
    ) -> dict[str, bool]:
        readiness = {network: False for network in service.network_configs}
        if not mandate or mandate["status"] != "active":
            return readiness
        for network in readiness:
            target = supported_approval_targets.get(network)
            config_for_network = service.network_configs.get(network)
            if (
                not target or not config_for_network
                or network not in mandate["network_scopes"]
                or target["token_address"] not in mandate["asset_scopes"]
            ):
                continue
            token_decimals = int(config_for_network["token_decimals"])
            readiness[network] = any(
                item.network == network
                and item.wallet_identity_id == mandate["wallet_identity_id"]
                and item.status == "active"
                and item.token_address == target["token_address"]
                and item.spender_address == target["spender_address"]
                and item.token_decimals == token_decimals
                and item.observed_allowance_atomic > 0
                for item in allowances
            )
        return readiness

    @app.get("/healthz")
    def healthz() -> dict[str, str]:
        return {"service": "account_service", "status": "ok"}

    def browser_session_for(
        request: Request,
        *,
        require_csrf: bool = False,
        require_wallet_auth: bool = False,
        allow_wallet_disconnect: bool = False,
    ) -> PublicAccountSession:
        browser_session = request.cookies.get(SESSION_COOKIE, "")
        if not browser_session:
            raise HTTPException(401, "account session unavailable")
        session = service.repository.access_public_account_browser_session(
            hashlib.sha256(browser_session.encode()).hexdigest(), now()
        )
        if session is None or session.purpose != "clink_account_console":
            raise HTTPException(401, "account session unavailable")
        if session.status == "expired":
            raise HTTPException(410, "account session unavailable")
        if session.status != "active":
            raise HTTPException(401, "account session unavailable")
        if require_wallet_auth:
            identity = (
                service.repository.wallet_identity(
                    session.authenticated_wallet_identity_id
                )
                if session.authenticated_wallet_identity_id is not None
                else None
            )
            if (
                session.authenticated_at is None
                or identity is None
                or (
                    identity.status != "active"
                    and not (
                        allow_wallet_disconnect
                        and identity.status == "suspended"
                    )
                )
                or identity.user_id != session.user_id
            ):
                raise HTTPException(401, "wallet authentication required")
        if require_csrf:
            csrf_cookie = request.cookies.get(CSRF_COOKIE, "")
            csrf_header = request.headers.get(CSRF_HEADER, "")
            if (
                not csrf_cookie
                or not csrf_header
                or not secrets.compare_digest(csrf_cookie, csrf_header)
                or session.csrf_token_digest is None
                or not secrets.compare_digest(
                    hashlib.sha256(csrf_header.encode()).hexdigest(),
                    session.csrf_token_digest,
                )
            ):
                raise HTTPException(403, "csrf validation failed")
        return session

    def owned_identity(session: PublicAccountSession, wallet_identity_id: str):
        item = service.repository.wallet_identity(wallet_identity_id)
        if item is None or item.user_id != session.user_id:
            raise HTTPException(404, "account object unavailable")
        return item

    def owned_grant(session: PublicAccountSession, spending_grant_id: str):
        item = service.repository.spending_grant(spending_grant_id)
        if item is None or item.user_id != session.user_id:
            raise HTTPException(404, "account object unavailable")
        owned_identity(session, item.wallet_identity_id)
        return item

    def owned_allowance(session: PublicAccountSession, asset_allowance_id: str):
        item = service.repository.asset_allowance(asset_allowance_id)
        if item is None:
            raise HTTPException(404, "account object unavailable")
        owned_identity(session, item.wallet_identity_id)
        return item

    def cleanup_identity(
        session: PublicAccountSession, wallet_identity_id: str
    ):
        item = owned_identity(session, wallet_identity_id)
        current_session = (
            service.repository.public_account_session_by_id(
                session.public_account_session_id
            )
        )
        if (
            current_session is None
            or current_session.status != "active"
            or current_session.expires_at <= now()
            or current_session.authenticated_wallet_identity_id is None
        ):
            raise HTTPException(401, "wallet authentication required")
        authenticated_identity_id = (
            current_session.authenticated_wallet_identity_id
        )
        authenticated_identity = (
            service.repository.wallet_identity(authenticated_identity_id)
            if authenticated_identity_id is not None
            else None
        )
        if (
            authenticated_identity is not None
            and authenticated_identity.status == "suspended"
            and authenticated_identity.wallet_identity_id
            != item.wallet_identity_id
        ):
            raise HTTPException(404, "account object unavailable")
        return item

    def cleanup_allowance(
        session: PublicAccountSession, asset_allowance_id: str
    ):
        item = owned_allowance(session, asset_allowance_id)
        cleanup_identity(session, item.wallet_identity_id)
        return item

    def reject_disconnect_cleanup_session(
        session: PublicAccountSession,
    ) -> None:
        authenticated_identity_id = session.authenticated_wallet_identity_id
        identity = (
            service.repository.wallet_identity(authenticated_identity_id)
            if authenticated_identity_id is not None
            else None
        )
        if identity is not None and identity.status == "suspended":
            raise HTTPException(409, "wallet disconnect is in progress")

    def account_state(session: PublicAccountSession) -> dict:
        state_at = now()
        identities = service.repository.active_wallet_identities(session.user_id)
        selected_identity = next(
            (
                item
                for item in identities
                if item.wallet_identity_id
                == session.authenticated_wallet_identity_id
            ),
            None,
        )
        selected_identity_id = (
            selected_identity.wallet_identity_id if selected_identity else None
        )
        grants = [
            item
            for item in service.repository.spending_grants(session.user_id)
            if item.wallet_identity_id == selected_identity_id
        ]
        allowances = [
            item
            for item in (
                service.repository.asset_allowances(selected_identity_id)
                if selected_identity_id
                else []
            )
        ]
        current_mandate = current_mandate_projection(
            user_id=session.user_id,
            wallet_identity_id=selected_identity_id,
            at=state_at,
        )
        active_grant = bool(
            current_mandate and current_mandate["status"] == "active"
        )
        network_readiness = allowance_readiness_for_mandate(
            current_mandate, allowances
        )
        audit = [
            AuditSummaryEvent.model_validate(item).model_dump()
            for item in read_audit_summary(session.user_id, 8)
        ]
        readiness = {
            "wallet_bound": selected_identity is not None,
            "spending_grant_active": active_grant,
            "chain_allowances": network_readiness,
            "ready": (
                selected_identity is not None
                and active_grant
                and any(network_readiness.values())
            ),
        }
        return {
            "user_id": session.user_id,
            "wallet_identities": [
                _json(item)
                for item in sorted(
                    identities,
                    key=lambda item: item.wallet_identity_id
                    != selected_identity_id,
                )
            ],
            "spending_grants": [_json(item) for item in grants],
            "current_spending_mandate": current_mandate,
            "asset_allowances": [_json(item) for item in allowances],
            "allowance_recovery": (
                recovery_store.records(user_id=session.user_id,
                                       wallet_identity_id=selected_identity_id)
                if selected_identity_id else []
            ),
            "approval_targets": supported_approval_targets,
            "network_configs": public_network_configs,
            "readiness": readiness,
            "recent_audit_summary": audit,
        }

    @app.get("/account/static/account.css", include_in_schema=False)
    def account_css() -> Response:
        return Response(ACCOUNT_CONSOLE_CSS, media_type="text/css")

    @app.get("/account/static/account.js", include_in_schema=False)
    def account_js() -> Response:
        return Response(ACCOUNT_CONSOLE_JS, media_type="text/javascript")

    @app.post("/internal/account-sessions", status_code=201)
    def create_account_session(request: CreateAccountSessionRequest) -> dict:
        created_at = now()
        service.repository.cleanup_expired_public_account_sessions(created_at)
        session_id = secrets.token_urlsafe(32)
        session = PublicAccountSession(
            public_account_session_id=f"public_account_session_{uuid4().hex}",
            token_digest=hashlib.sha256(session_id.encode()).hexdigest(),
            user_id=request.user_id,
            expires_at=created_at + session_ttl,
            created_at=created_at,
            updated_at=created_at,
        )
        service.repository.create_public_account_session(session)
        account_path = f"/account/{session_id}"
        return {
            "session_id": session_id,
            "account_url": (
                f"{config.account_public_base_url}{account_path}"
                if config.account_public_base_url
                else account_path
            ),
            "expires_at": session.expires_at.isoformat(),
        }

    @app.get("/internal/wallet-identities")
    def wallet_identities(user_id: str = Query(min_length=1, max_length=96)) -> list[dict]:
        return [_json(item) for item in service.repository.active_wallet_identities(user_id)]

    @app.get("/internal/spending-grants")
    def spending_grants(
        user_id: str = Query(min_length=1, max_length=96),
        status: Literal["active"] = "active",
    ) -> list[dict]:
        del status
        return [
            _json(item)
            for item in service.repository.active_spending_grants(
                user_id, at=current_clock()
            )
        ]

    @app.post("/internal/authorization-resolution")
    def authorization_resolution(request: AuthorizationResolutionRequest) -> dict:
        opc_authorization = None
        if request.opc_installation_id is not None and opc_service is not None:
            try:
                opc_authorization = opc_service.authorization_scope(
                    request.opc_installation_id,
                    user_id=request.user_id,
                    agent_id=request.agent_id,
                )
            except ValueError:
                pass
        if request.opc_installation_id is None:
            result = _json(service.resolve_authorization(request))
        else:
            result = _json(
                service.resolve_authorization(
                    request,
                    opc_authorization=opc_authorization,
                )
            )
        if request.opc_installation_id is None:
            result.pop("opc_installation_id", None)
        return result

    @app.post("/internal/opc/pairings", status_code=201)
    def create_opc_pairing(request: OpcProofRequest) -> dict:
        if opc_service is None:
            raise HTTPException(503, "OPC service unavailable")
        try:
            return opc_service.create_pairing(request.proof)
        except ValueError as exc:
            raise HTTPException(400, "request could not be completed") from exc

    @app.post("/internal/opc/token")
    def issue_opc_token(request: OpcProofRequest) -> dict:
        if opc_service is None:
            raise HTTPException(503, "OPC service unavailable")
        try:
            return opc_service.issue_token(request.proof)
        except ValueError as exc:
            raise HTTPException(400, "request could not be completed") from exc

    @app.post("/internal/opc/status")
    def opc_status(request: OpcProofRequest) -> dict:
        if opc_service is None:
            raise HTTPException(503, "OPC service unavailable")
        try:
            return opc_service.status(request.proof)
        except ValueError as exc:
            raise HTTPException(400, "request could not be completed") from exc

    @app.post("/internal/opc/revoke")
    def revoke_opc_installation(request: OpcProofRequest) -> dict:
        if opc_service is None:
            raise HTTPException(503, "OPC service unavailable")
        try:
            return opc_service.revoke(request.proof)
        except ValueError as exc:
            raise HTTPException(400, "request could not be completed") from exc

    @app.post("/internal/opc/authenticate")
    def authenticate_opc_token(request: OpcAuthenticateRequest) -> dict:
        if opc_service is None:
            raise HTTPException(503, "OPC service unavailable")
        try:
            return opc_service.authenticate_access_token(request.access_token)
        except ValueError as exc:
            raise HTTPException(401, "OPC credential unavailable") from exc

    @app.get("/internal/account-readiness")
    def account_readiness(user_id: str = Query(min_length=1, max_length=96)) -> dict:
        readiness_at = now()
        identities = service.repository.active_wallet_identities(user_id)
        grants = service.repository.active_spending_grants(user_id, at=readiness_at)
        identities_by_id = {item.wallet_identity_id: item for item in identities}
        grant_wallet_ids = {
            item.wallet_identity_id
            for item in grants
            if item.wallet_identity_id in identities_by_id
        }
        if len(grant_wallet_ids) == 1:
            primary_identity = identities_by_id[next(iter(grant_wallet_ids))]
        elif len(identities) == 1:
            primary_identity = identities[0]
        else:
            primary_identity = None
        selected_identity_id = (
            primary_identity.wallet_identity_id if primary_identity else None
        )
        current_mandate = current_mandate_projection(
            user_id=user_id,
            wallet_identity_id=selected_identity_id,
            at=readiness_at,
        )
        spending_grant_active = bool(
            current_mandate and current_mandate["status"] == "active"
        )
        allowances = [
            item
            for item in (
                service.repository.asset_allowances(selected_identity_id)
                if selected_identity_id
                else []
            )
        ]
        networks = allowance_readiness_for_mandate(current_mandate, allowances)
        active_mandate = None
        if spending_grant_active:
            active_mandate = {
                "spending_grant_id": current_mandate["spending_grant_id"],
                "agent_id": current_mandate["agent_id"],
                "limits_usdc": current_mandate["limits_usdc"],
                "remaining_usdc": current_mandate["remaining_usdc"],
                "product_scopes": current_mandate["product_scopes"],
                "venue_scopes": current_mandate["venue_scopes"],
                "merchant_scopes": current_mandate["merchant_scopes"],
                "merchant_trust_scopes": current_mandate[
                    "merchant_trust_scopes"
                ],
                "network_scopes": current_mandate["network_scopes"],
                "asset_scopes": current_mandate["asset_scopes"],
                "notification_mode": current_mandate["notification_mode"],
                "expires_at": current_mandate["expires_at"],
            }
        result = {
            "user_id": user_id,
            "wallet_bound": bool(identities),
            "wallet_address": primary_identity.wallet_address if primary_identity else None,
            "wallet_identity_id": primary_identity.wallet_identity_id if primary_identity else None,
            "spending_grant_active": spending_grant_active,
            "active_spending_mandate": active_mandate,
            "chain_allowances": networks,
        }
        result["ready"] = (
            result["wallet_bound"]
            and result["spending_grant_active"]
            and any(networks.values())
        )
        return result

    @app.get("/internal/account-balances")
    def account_balances(user_id: str = Query(min_length=1, max_length=96)) -> dict:
        readiness = account_readiness(user_id)
        wallet_address = readiness["wallet_address"]
        if wallet_address is None:
            return {
                "user_id": user_id,
                "status": "not_bound",
                "wallet_bound": False,
                "wallet_address": None,
                "balances": {},
            }

        balances = {}
        for network, config in service.network_configs.items():
            token_address = config["token_address"]
            if token_address is None:
                continue
            balance = {
                "status": "unavailable",
                "network": network,
                "asset": config["token_symbol"],
                "token_address": token_address,
                "amount_atomic": None,
                "amount_usdc": None,
            }
            try:
                amount_atomic = service.observe_wallet_balance(
                    network=network,
                    wallet_address=wallet_address,
                )
            except (RuntimeError, ValueError, OSError):
                pass
            else:
                decimals = config["token_decimals"]
                amount = Decimal(amount_atomic).scaleb(-decimals)
                balance.update(
                    {
                        "status": "ready",
                        "amount_atomic": str(amount_atomic),
                        "amount_usdc": format(amount, f".{decimals}f"),
                    }
                )
            balances[network] = balance

        statuses = {item["status"] for item in balances.values()}
        status = "ready" if statuses == {"ready"} else "partial"
        if not balances or statuses == {"unavailable"}:
            status = "unavailable"
        return {
            "user_id": user_id,
            "status": status,
            "wallet_bound": True,
            "wallet_address": wallet_address,
            "balances": balances,
        }

    @app.post("/account/authorization-plan")
    def plan_authorization(http_request: Request, request: AuthorizationForm) -> dict:
        session = browser_session_for(
            http_request, require_csrf=True, require_wallet_auth=True
        )
        owner = owned_identity(session, request.wallet_identity_id)
        if session.authenticated_wallet_identity_id != request.wallet_identity_id:
            raise HTTPException(404, "account object unavailable")
        target = supported_approval_targets.get(request.network)
        if target is None or request.network not in service.network_configs:
            raise HTTPException(400, "unsupported approval target")
        at = now()
        candidates = [item for item in service.repository.spending_grants(session.user_id)
            if item.wallet_identity_id == request.wallet_identity_id
            and item.agent_id == "hermes"
            and item.status in {"active", "paused", "pending"}
            and at < item.expires_at]
        # Never create a replacement budget merely because a prior or future
        # authorization was omitted from the submitted form.
        if len(candidates) > 1 or (candidates and
                request.spending_grant_id != candidates[0].spending_grant_id):
            raise HTTPException(409, "refresh current authorization before editing")
        current = candidates[0] if candidates else None
        if request.spending_grant_id and current is None:
            raise HTTPException(409, "current authorization is unavailable")
        try:
            plan = authorization_terms(
                request, identity=owner, current=current,
                token_address=target["token_address"], at=at,
            )
        except ValueError as exc:
            raise HTTPException(400, "authorization conditions are invalid") from exc
        observation = None
        try:
            observation = service.inspect_asset_allowance(
                request.wallet_identity_id, request.network,
                target["token_address"], target["spender_address"],
            )
        except Exception:
            # Unknown RPC/persistence outcomes must not become a zero allowance
            # and must never initiate a replacement approve.
            pass
        observed = (
            observation.observed_allowance_atomic
            if observation is not None and observation.status != "stale" else None
        )
        terms = plan["terms"]
        advice = allowance_advice(
            total=Decimal(terms["max_amount_usdc"]),
            used=current.used_amount_usdc if current else Decimal("0"),
            per_transaction=Decimal(terms["per_transaction_limit_usdc"]),
            observed_atomic=observed,
        )
        return {
            **plan,
            "allowance": {
                **advice, "network": request.network, **target,
                "wallet_address": owner.wallet_address,
                "asset_allowance_id": observation.asset_allowance_id if observation else None,
                "observed_at": (
                    observation.last_chain_check_at.isoformat()
                    if observed is not None and observation.last_chain_check_at else None
                ),
            },
        }

    def account_destination(request: Request) -> str:
        return public_account_path + (
            "?view=authorization"
            if request.query_params.get("view") == "authorization" else ""
        )

    @app.get("/account")
    def account(request: Request):
        if "application/json" in request.headers.get("accept", ""):
            authenticated = browser_session_for(request, require_wallet_auth=True)
            return account_state(authenticated)
        browser_session = browser_session_for(request)
        html = account_console_html
        try:
            pairing = (
                opc_service.browser_pairing(browser_session.public_account_session_id)
                if opc_service is not None else None
            )
        except ValueError as exc:
            raise HTTPException(409, "OPC account setup is unavailable") from exc
        if pairing is not None:
            # Before wallet proof, expose only this browser session's device display
            # metadata and public network facts, never the user's account projection.
            bootstrap = {
                "pairing": {key: pairing[key] for key in (
                    "pairing_id", "installation_id", "label", "public_jwk_thumbprint",
                    "scope", "agent_id", "status", "expires_at",
                )},
                "network_configs": public_network_configs,
                "approval_targets": supported_approval_targets,
                "defaults": {"total_usdc": "20", "hourly_usdc": "5", "duration_days": 7},
            }
            encoded = html_encoding.escape(json.dumps(bootstrap), quote=True)
            html = html.replace('<body>', f'<body data-account-view="authorization" data-opc-setup="{encoded}">')
        elif request.query_params.get("view") == "authorization":
            html = html.replace('<body>', '<body data-account-view="authorization">')
        return HTMLResponse(html)

    @app.get("/account/{session_token}")
    def preview_account_session(request: Request, session_token: str):
        session = service.repository.access_public_account_session(
            hashlib.sha256(session_token.encode()).hexdigest(), now()
        )
        if session is None:
            raise HTTPException(404, "account session unavailable")
        if session.status == "expired":
            raise HTTPException(410, "account session unavailable")
        if session.status != "active":
            raise HTTPException(401, "account session unavailable")
        if session.exchanged_at is not None:
            browser_session = request.cookies.get(SESSION_COOKIE, "")
            bound_session = (
                service.repository.access_public_account_browser_session(
                    hashlib.sha256(browser_session.encode()).hexdigest(), now()
                )
                if browser_session
                else None
            )
            if (
                bound_session is None
                or bound_session.public_account_session_id
                != session.public_account_session_id
            ):
                raise HTTPException(404, "account session unavailable")
            return RedirectResponse(account_destination(request), status_code=303)
        return HTMLResponse(account_session_confirm_html)

    @app.post("/account/wallet-challenge")
    def wallet_challenge(
        http_request: Request, request: WalletChallengeRequest
    ) -> dict:
        session = browser_session_for(http_request, require_csrf=True)
        reject_disconnect_cleanup_session(session)
        try:
            return _json(
                service.create_wallet_challenge(
                    session.user_id,
                    request.wallet_address,
                    authorizing_wallet_identity_id=(
                        session.authenticated_wallet_identity_id
                    ),
                    created_by_public_account_session_id=(
                        session.public_account_session_id
                    ),
                )
            )
        except ValueError as exc:
            raise HTTPException(400, "request could not be completed") from exc

    @app.post("/account/wallet-verify")
    def wallet_verify(http_request: Request, request: WalletVerifyRequest) -> dict:
        session = browser_session_for(http_request, require_csrf=True)
        reject_disconnect_cleanup_session(session)
        challenge = service.repository.account_session(request.challenge_session_id)
        if (
            challenge is None
            or challenge.user_id != session.user_id
            or challenge.created_by_public_account_session_id
            != session.public_account_session_id
        ):
            raise HTTPException(404, "account object unavailable")
        try:
            identity = service.verify_wallet_challenge(
                request.challenge_session_id, request.signed_message, request.signature
            )
            return _json(identity)
        except ValueError as exc:
            raise HTTPException(400, "request could not be completed") from exc

    @app.post(
        "/account/wallet-challenges/{challenge_session_id}/cancel"
    )
    def cancel_wallet_challenge(
        challenge_session_id: str,
        http_request: Request,
        request: EmptyRequest | None = None,
    ) -> dict:
        del request
        session = browser_session_for(
            http_request,
            require_csrf=True,
        )
        if not service.cancel_wallet_challenge(
            challenge_session_id,
            user_id=session.user_id,
            public_account_session_id=(
                session.public_account_session_id
            ),
        ):
            raise HTTPException(404, "account object unavailable")
        return {"cancelled": True}

    @app.post("/account/grants")
    def create_grant(http_request: Request, request: GrantRequest):
        session = browser_session_for(
            http_request, require_csrf=True, require_wallet_auth=True
        )
        owned_identity(session, request.wallet_identity_id)
        challenge = None
        if request.challenge_session_id is not None:
            challenge = service.repository.account_session(request.challenge_session_id)
            if challenge is None or challenge.user_id != session.user_id:
                raise HTTPException(404, "account object unavailable")
        try:
            opc_installation = None
            creating_public_session_id = session.public_account_session_id
            if challenge is not None:
                creating_public_session_id = (
                    challenge.created_by_public_account_session_id
                    or session.public_account_session_id
                )
                clause_value = ((challenge.payload or {}).get("terms") or {}).get(
                    "opc_installation"
                )
                if clause_value is not None:
                    opc_installation = OpcInstallationAuthorization.model_validate(
                        clause_value
                    )
                    if (
                        challenge.created_by_public_account_session_id
                        != session.public_account_session_id
                        or (
                            request.opc_pairing_id is not None
                            and request.opc_pairing_id != opc_installation.pairing_id
                        )
                    ):
                        raise ValueError("OPC pairing account session mismatch")
            elif request.opc_pairing_id is not None:
                if opc_service is None:
                    raise HTTPException(503, "OPC service unavailable")
                opc_installation = opc_service.grant_installation_clause(
                    request.opc_pairing_id,
                    user_id=session.user_id,
                    public_account_session_id=session.public_account_session_id,
                    grant_expires_at=request.expires_at,
                )
            grant_request = SpendingGrantRequest(
                user_id=session.user_id,
                wallet_identity_id=request.wallet_identity_id,
                agent_id=request.agent_id,
                max_amount_usdc=request.max_amount_usdc,
                per_transaction_limit_usdc=request.per_transaction_limit_usdc,
                hourly_limit_usdc=request.hourly_limit_usdc,
                daily_limit_usdc=request.daily_limit_usdc,
                product_scopes=request.product_scopes,
                venue_scopes=request.venue_scopes,
                merchant_scopes=request.merchant_scopes,
                merchant_trust_scopes=request.merchant_trust_scopes,
                notification_mode=request.notification_mode,
                network_scopes=request.network_scopes,
                asset_scopes=request.asset_scopes,
                starts_at=request.starts_at,
                expires_at=request.expires_at,
                amends_spending_grant_id=request.amends_spending_grant_id,
                opc_installation=opc_installation,
                created_by_public_account_session_id=creating_public_session_id,
                session_id=request.challenge_session_id,
                signed_message=request.signed_message,
                signature=request.signature,
            )
            if request.challenge_session_id is None:
                return _json(service.create_spending_grant_challenge(grant_request))
            result = service.create_spending_grant(grant_request)
            return JSONResponse(content=_json(result), status_code=201)
        except ValueError as exc:
            raise HTTPException(400, "request could not be completed") from exc

    @app.get("/account/opc/pairing")
    def browser_opc_pairing(http_request: Request) -> dict:
        session = browser_session_for(http_request, require_wallet_auth=True)
        try:
            return {"pairing": (
                opc_service.browser_pairing(session.public_account_session_id)
                if opc_service is not None else None
            )}
        except ValueError as exc:
            raise HTTPException(409, "OPC device context unavailable") from exc

    @app.post("/account/opc/pairings/{pairing_id}/claim")
    def claim_opc_pairing(
        pairing_id: str,
        http_request: Request,
        request: EmptyRequest | None = None,
    ) -> dict:
        del request
        if opc_service is None:
            raise HTTPException(503, "OPC service unavailable")
        session = browser_session_for(
            http_request, require_csrf=True, require_wallet_auth=True
        )
        try:
            return opc_service.claim_pairing(
                pairing_id,
                user_id=session.user_id,
                public_account_session_id=session.public_account_session_id,
            )
        except ValueError as exc:
            raise HTTPException(400, "request could not be completed") from exc

    @app.post("/account/opc/pairings/{pairing_id}/challenge")
    def create_opc_installation_challenge(
        pairing_id: str,
        http_request: Request,
        request: OpcInstallationChallengeRequest,
    ) -> dict:
        if opc_service is None:
            raise HTTPException(503, "OPC service unavailable")
        session = browser_session_for(
            http_request, require_csrf=True, require_wallet_auth=True
        )
        owned_grant(session, request.spending_grant_id)
        try:
            return _json(
                opc_service.create_installation_challenge(
                    pairing_id,
                    user_id=session.user_id,
                    public_account_session_id=session.public_account_session_id,
                    spending_grant_id=request.spending_grant_id,
                )
            )
        except ValueError as exc:
            raise HTTPException(400, "request could not be completed") from exc

    @app.post("/account/opc/installations/approve")
    def approve_opc_installation(
        http_request: Request, request: OpcInstallationApproveRequest
    ) -> dict:
        if opc_service is None:
            raise HTTPException(503, "OPC service unavailable")
        session = browser_session_for(
            http_request, require_csrf=True, require_wallet_auth=True
        )
        challenge = service.repository.account_session(request.challenge_session_id)
        if (
            challenge is None
            or challenge.user_id != session.user_id
            or challenge.created_by_public_account_session_id
            != session.public_account_session_id
        ):
            raise HTTPException(404, "account object unavailable")
        try:
            return opc_service.approve_installation(
                request.challenge_session_id,
                request.signed_message,
                request.signature,
            )
        except ValueError as exc:
            raise HTTPException(400, "request could not be completed") from exc

    def recovery_scope(session, wallet_identity_id, network, token_address, spender_address):
        owned_identity(session, wallet_identity_id)
        if session.authenticated_wallet_identity_id != wallet_identity_id:
            raise HTTPException(404, "account object unavailable")
        try:
            target = supported_approval_targets.get(network)
            if (network not in service.network_configs or target is None
                or canonicalize_evm_address(token_address) != target["token_address"]
                or canonicalize_evm_address(spender_address) != target["spender_address"]):
                raise ValueError("unconfigured target")
        except ValueError as exc:
            raise HTTPException(400, "unsupported approval target") from exc

    def recovery_attempt(session, attempt_id):
        try:
            record = recovery_store.get(user_id=session.user_id, attempt_id=attempt_id)
        except ValueError as exc:
            raise HTTPException(404, "account object unavailable") from exc
        if record is None:
            raise HTTPException(404, "account object unavailable")
        recovery_scope(session, **{field: record[field] for field in (
            "wallet_identity_id", "network", "token_address", "spender_address",
        )})
        return record

    @app.post("/account/allowances/attempts")
    def begin_allowance_attempt(http_request: Request, request: AllowanceAttemptRequest):
        session = browser_session_for(http_request, require_csrf=True, require_wallet_auth=True)
        recovery_scope(session, request.wallet_identity_id, request.network,
                       request.token_address, request.spender_address)
        try:
            return recovery_store.begin(user_id=session.user_id, now=now(), **request.model_dump())
        except ValueError as exc:
            raise HTTPException(409, "An allowance attempt already requires reconciliation or its context changed; no transaction may be resent.") from exc

    @app.post("/account/allowances/attempts/{attempt_id}/submitted")
    def record_allowance_submission(attempt_id: str, http_request: Request,
                                   request: AllowanceAttemptSubmittedRequest):
        session = browser_session_for(http_request, require_csrf=True, require_wallet_auth=True)
        recovery_attempt(session, attempt_id)
        try:
            return recovery_store.submitted(user_id=session.user_id, attempt_id=attempt_id,
                                            now=now(), **request.model_dump())
        except ValueError as exc:
            raise HTTPException(409, "Allowance attempt context does not match; retained evidence was not replaced.") from exc

    @app.post("/account/allowances/attempts/{attempt_id}/rejected")
    def record_allowance_rejection(attempt_id: str, http_request: Request,
                                  request: AllowanceAttemptKeyRequest):
        session = browser_session_for(http_request, require_csrf=True, require_wallet_auth=True)
        recovery_attempt(session, attempt_id)
        try:
            return recovery_store.rejected(user_id=session.user_id, attempt_id=attempt_id,
                                          request_key=request.request_key, now=now())
        except ValueError as exc:
            raise HTTPException(409, "Allowance attempt cannot be cleared; reconcile the original submission.") from exc

    @app.post("/account/allowances/verify")
    def verify_allowance(
        http_request: Request, request: AllowanceVerifyRequest
    ) -> dict:
        session = browser_session_for(
            http_request, require_csrf=True, require_wallet_auth=True
        )
        recovery_scope(session, request.wallet_identity_id, request.network,
                       request.token_address, request.spender_address)
        try:
            canonicalize_transaction_hash(request.allowance_tx_hash)
        except ValueError as exc:
            raise HTTPException(400, "request could not be completed") from exc
        try:
            record = recovery_store.register_proof(user_id=session.user_id, now=now(),
                                                   **request.model_dump())
        except ValueError as exc:
            raise HTTPException(409, "An allowance attempt already requires reconciliation; retained evidence was not replaced.") from exc
        try:
            return _json(recovery_worker.verify(record))
        except AllowanceVerificationPending as exc:
            raise HTTPException(
                503,
                "Allowance verification is waiting for chain evidence. Verification "
                "can resume using the same transaction hash; do not resend the transaction.",
                headers={"Retry-After": "3"},
            ) from exc
        except AllowanceAmountMismatch as exc:
            return JSONResponse(
                status_code=409,
                content={
                    "detail": (
                        "The allowance transaction is confirmed with a different "
                        "amount. No transaction was resent."
                    ),
                    "code": "allowance_amount_mismatch",
                    "recovery": exc.recovery_record,
                },
            )
        except ValueError as exc:
            raise HTTPException(400, "request could not be completed") from exc
        except RuntimeError as exc:
            # A provider outage is not evidence that the wallet transaction
            # failed. The browser retains its proof and may only retry this
            # read/verification endpoint, never the wallet submission.
            raise HTTPException(
                503,
                "Allowance verification is temporarily unavailable. Your transaction "
                "has not been retried; verification can resume using the same "
                "transaction hash.",
                headers={"Retry-After": "3"},
            ) from exc

    @app.post("/account/allowances/{asset_allowance_id}/refresh")
    def refresh_allowance(
        asset_allowance_id: str,
        http_request: Request,
        request: EmptyRequest | None = None,
    ) -> dict:
        del request
        session = browser_session_for(
            http_request,
            require_csrf=True,
            require_wallet_auth=True,
            allow_wallet_disconnect=True,
        )
        cleanup_allowance(session, asset_allowance_id)
        try:
            result = service.refresh_asset_allowance(asset_allowance_id)
            cleanup_allowance(session, asset_allowance_id)
            return _json(result)
        except ValueError as exc:
            raise HTTPException(400, "request could not be completed") from exc

    @app.post("/account/grants/{spending_grant_id}/{action}")
    def mutate_grant(
        spending_grant_id: str,
        action: Literal["pause", "resume", "reduce", "revoke"],
        http_request: Request,
        request: ReduceGrantRequest | None = None,
    ) -> dict:
        session = browser_session_for(
            http_request, require_csrf=True, require_wallet_auth=True
        )
        owned_grant(session, spending_grant_id)
        try:
            if action == "pause":
                result = service.pause_spending_grant(spending_grant_id)
            elif action == "resume":
                result = service.resume_spending_grant(spending_grant_id)
            elif action == "revoke":
                result = service.revoke_spending_grant(spending_grant_id)
            else:
                values = request or ReduceGrantRequest()
                result = service.reduce_spending_grant(
                    spending_grant_id, **values.model_dump()
                )
            return _json(result)
        except ValueError as exc:
            raise HTTPException(400, "request could not be completed") from exc

    @app.post("/account/wallet-identities/{wallet_identity_id}/revoke")
    def revoke_identity(
        wallet_identity_id: str,
        http_request: Request,
        request: EmptyRequest | None = None,
    ) -> dict:
        del request
        session = browser_session_for(
            http_request, require_csrf=True, require_wallet_auth=True
        )
        owned_identity(session, wallet_identity_id)
        try:
            return _json(service.revoke_wallet_identity(wallet_identity_id))
        except ValueError as exc:
            raise HTTPException(400, "request could not be completed") from exc

    @app.post(
        "/account/wallet-identities/{wallet_identity_id}/prepare-disconnect"
    )
    def prepare_disconnect_identity(
        wallet_identity_id: str,
        http_request: Request,
        request: EmptyRequest | None = None,
    ) -> dict:
        del request
        session = browser_session_for(
            http_request,
            require_csrf=True,
            require_wallet_auth=True,
            allow_wallet_disconnect=True,
        )
        cleanup_identity(session, wallet_identity_id)
        try:
            return _json(
                service.prepare_wallet_identity_disconnect(
                    wallet_identity_id,
                    session.public_account_session_id,
                )
            )
        except ValueError as exc:
            raise HTTPException(400, "request could not be completed") from exc

    @app.get(
        "/account/wallet-identities/{wallet_identity_id}/disconnect-state"
    )
    def wallet_disconnect_state(
        wallet_identity_id: str,
        http_request: Request,
    ) -> dict:
        session = browser_session_for(http_request)
        identity = owned_identity(session, wallet_identity_id)
        return {
            "wallet_identity": _json(identity),
            "disconnect_complete": (
                service.repository.wallet_identity_disconnect_complete(
                    wallet_identity_id
                )
            ),
            "asset_allowances": [
                _json(item)
                for item in service.repository.asset_allowances(
                    wallet_identity_id
                )
            ],
            "approval_targets": {
                network: dict(target)
                for network, target in supported_approval_targets.items()
            },
            "network_configs": public_network_configs,
        }

    @app.post("/account/wallet-identities/{wallet_identity_id}/disconnect")
    def disconnect_identity(
        wallet_identity_id: str,
        http_request: Request,
        request: EmptyRequest | None = None,
    ) -> dict:
        del request
        session = browser_session_for(
            http_request,
            require_csrf=True,
            require_wallet_auth=True,
            allow_wallet_disconnect=True,
        )
        cleanup_identity(session, wallet_identity_id)
        try:
            return _json(
                service.disconnect_wallet_identity(
                    wallet_identity_id,
                    session.public_account_session_id,
                )
            )
        except ValueError as exc:
            raise HTTPException(400, "request could not be completed") from exc

    # Keep this wildcard route after every concrete /account POST endpoint.
    @app.post("/account/{session_token}")
    def exchange_account_session(request: Request, session_token: str):
        existing_browser_token = request.cookies.get(SESSION_COOKIE, "")
        existing_browser_session_digest = (
            hashlib.sha256(existing_browser_token.encode()).hexdigest()
            if existing_browser_token
            else None
        )
        browser_session = secrets.token_urlsafe(32)
        csrf_token = secrets.token_urlsafe(32)
        exchanged_at = now()
        browser_session_digest = hashlib.sha256(
            browser_session.encode()
        ).hexdigest()
        session = service.repository.exchange_public_account_session(
            hashlib.sha256(session_token.encode()).hexdigest(),
            browser_session_digest,
            hashlib.sha256(csrf_token.encode()).hexdigest(),
            exchanged_at,
            existing_browser_session_digest,
        )
        if session is None:
            raise HTTPException(404, "account session unavailable")
        if session.status == "expired":
            raise HTTPException(410, "account session unavailable")
        cookie_max_age = max(
            1, int((session.expires_at - exchanged_at).total_seconds())
        )
        response = RedirectResponse(account_destination(request), status_code=303)
        response.set_cookie(
            SESSION_COOKIE,
            browser_session,
            secure=True,
            httponly=True,
            samesite="strict",
            path=public_account_path,
            expires=session.expires_at,
            max_age=cookie_max_age,
        )
        response.set_cookie(
            CSRF_COOKIE,
            csrf_token,
            secure=True,
            httponly=False,
            samesite="strict",
            path=public_account_path,
            expires=session.expires_at,
            max_age=cookie_max_age,
        )
        return response

    return app


class LazyConfiguredApp:
    """Avoid database writes at import while preserving the conventional ASGI export."""

    def __init__(self) -> None:
        self._app: FastAPI | None = None
        self._lock = RLock()

    async def __call__(self, scope, receive, send) -> None:
        if self._app is None:
            with self._lock:
                if self._app is None:
                    self._app = create_app()
        await self._app(scope, receive, send)


app = LazyConfiguredApp()


def main() -> None:
    config = AppConfig.from_env()
    if not config.account_public_base_url:
        raise RuntimeError("CLINK_ACCOUNT_PUBLIC_BASE_URL is required")
    uvicorn.run(
        create_app(),
        host=config.account_service_host,
        port=config.account_service_port,
        # Account URLs contain one-time bearer secrets; business audit is separate.
        access_log=False,
    )


if __name__ == "__main__":
    main()
