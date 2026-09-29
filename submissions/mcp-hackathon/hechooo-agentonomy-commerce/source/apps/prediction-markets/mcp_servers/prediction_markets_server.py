from __future__ import annotations

import ipaddress
import json
import re
import sys
import urllib.parse
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from mcp.server.fastmcp import FastMCP

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from shared.config import AppConfig  # noqa: E402
from shared.core_http import core_request_headers  # noqa: E402
from shared.core_account_client import CoreAccountClient, CoreAccountClientError  # noqa: E402
from services.funding_adapter_service.schemas import (  # noqa: E402
    CreatePolymarketBridgeDepositRequest,
    CreatePolymarketBridgeQuoteRequest,
    CreatePolymarketFundingOperationRequest,
    PolymarketBridgeDeposit,
    PolymarketBridgeQuote,
    PolymarketBridgeStatus,
    PolymarketFundingOperationView,
    FUNDING_OPERATION_PENDING_STATUSES,
    FUNDING_OPERATION_STATUSES,
    funding_operation_next_action,
)
from services.deposit_wallet_service.schemas import (  # noqa: E402
    PolymarketDepositWalletReadiness,
    PolymarketDepositWalletState,
    PreparePolymarketDepositWalletRequest,
)
from services.account_binding_service.schemas import (  # noqa: E402
    CreatePolymarketBindingSessionRequest,
    PolymarketAccountBinding,
    PolymarketBindingSession,
    canonicalize_optional_evm_address,
)
from services.portfolio_service.schemas import PortfolioSnapshot  # noqa: E402
from shared.schemas import (  # noqa: E402
    AgentIdea,
    CompletePolymarketOrderSigningSessionRequest,
    CreatePolymarketOrderSigningSessionRequest,
    ExecutePredictionMarketOrderRequest,
    ExecutionReadiness,
    CreateOrderPreviewRequest,
    PredictionMarketContextRequest,
    PredictionMarketContextResult,
    PredictionMarketExecution,
    PredictionMarketOrderPreview,
    PolymarketOrderSigningSession,
    ScoreMarketsResult,
    SearchMarketsResult,
    StrategyRecord,
    UnifiedMarket,
)
from storage.trading_ledger import TradingLedger  # noqa: E402

CONFIG = AppConfig.from_env()
CORE_ACCOUNT_CLIENT = CoreAccountClient(
    CONFIG.clink_core_account_service_url,
    CONFIG.clink_core_internal_api_token,
)
MCP_SERVER = FastMCP(
    "Clink Prediction Markets MCP Server",
    instructions="Cross-platform prediction-market context, evidence, preview, and execution tools for Hermes. Clink does not decide trades; Hermes reads context and chooses whether to request previews or execution.",
    host=CONFIG.mcp_host,
    port=CONFIG.mcp_port,
    stateless_http=True,
    json_response=True,
)

_SUGGESTED_USDC_AMOUNT = re.compile(
    r"^(?:0|[1-9][0-9]*)(?:\.[0-9]{1,6})?$"
)
_BROWSER_NUMERIC_HOST_LABEL = re.compile(
    r"^(?:0[xX][0-9A-Fa-f]+|[0-9]+)$"
)
_UINT256_MAX = (1 << 256) - 1
_DIRECT_FUNDING_RESPONSE_ERROR = "Polymarket funding response is invalid"
_DIRECT_FUNDING_NEXT_ACTION = "fund_polymarket_from_spending_authorization"
_FUNDING_UI_URL_ERROR = "Polymarket funding UI URL is unavailable"
_TYPE3_BINDING_READINESS_ERROR = (
    "Polymarket Deposit Wallet is not ready for type-3 binding"
)
_DEPOSIT_WALLET_PREPARATION_READINESS_ERROR = (
    "Polymarket Deposit Wallet cannot be prepared for the current Core Account"
)
_DEPOSIT_WALLET_PREPARATION_ACTIONS = {
    "prepare_polymarket_deposit_wallet",
    "configure_builder_relayer",
    "install_builder_relayer_sdk",
    "inspect_builder_relayer_error",
    "deploy_polymarket_deposit_wallet",
    "inspect_builder_relayer_response",
    "poll_polymarket_relayer_transaction",
}
class _PredictionMarketsRequestError(RuntimeError):
    def __init__(self, status_code: int, response_body: str) -> None:
        self.status_code = status_code
        self.response_body = response_body
        super().__init__(
            f"prediction markets router request failed: "
            f"{status_code} {response_body}"
        )


def _request_json(base_url: str, path: str, payload: dict | None = None) -> dict:
    data = json.dumps(payload).encode("utf-8") if payload is not None else None
    headers = {"Content-Type": "application/json"} if payload is not None else {}
    if base_url.rstrip("/") == CONFIG.account_binding_url.rstrip("/"):
        headers.update(core_request_headers(CONFIG, json_content=payload is not None))
        if path.startswith("/polymarket/bindings/latest/"):
            path = path.replace("/polymarket/bindings/latest/", "/internal/polymarket/bindings/latest/", 1)
        elif path.startswith("/polymarket/bindings/"):
            path = path.replace("/polymarket/bindings/", "/internal/polymarket/binding/", 1)
    elif CONFIG.is_core_service_url(base_url):
        headers.update(core_request_headers(CONFIG, json_content=payload is not None))
    elif base_url.rstrip("/") == CONFIG.funding_adapter_url.rstrip("/"):
        token = CONFIG.prediction_markets_internal_api_token.strip()
        if not token:
            raise RuntimeError(
                "PREDICTION_MARKETS_INTERNAL_API_TOKEN is required for funding adapter requests"
            )
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(
        f"{base_url}{path}",
        data=data,
        headers=headers,
        method="POST" if payload is not None else "GET",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8")
        raise _PredictionMarketsRequestError(exc.code, detail) from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"prediction markets router request failed: {exc}") from exc


@MCP_SERVER.tool()
def create_prediction_market_strategy(
    user_id: str,
    topic: str,
    hypothesis: str,
    agent_reasoning: list[str] | None = None,
    agent_id: str = "external_prediction_agent",
    strategy_id: str | None = None,
    status: str = "active",
    metadata: dict | None = None,
) -> StrategyRecord:
    """Create a strategy/thesis record so later previews and venue fills can be attributed to agent performance."""
    now = datetime.utcnow().isoformat() + "Z"
    strategy = StrategyRecord(
        strategy_id=strategy_id or f"strat_{uuid4().hex[:12]}",
        user_id=user_id,
        agent_id=agent_id,
        topic=topic,
        hypothesis=hypothesis,
        agent_reasoning=agent_reasoning or [],
        status=status,
        metadata=metadata or {},
        created_at=now,
        updated_at=now,
    )
    TradingLedger(CONFIG.ledger_db_file).upsert_strategy(strategy)
    return strategy


@MCP_SERVER.tool()
def create_agent_idea(
    user_id: str,
    topic: str,
    agent_message: str,
    recommendation: str,
    agent_id: str = "external_prediction_agent",
    market: dict | None = None,
    confidence: float | None = None,
    suggested_trade: dict | None = None,
    risks: list[str] | None = None,
    strategy_id: str | None = None,
    preview_id: str | None = None,
    execution_id: str | None = None,
    status: str = "proposed",
    metadata: dict | None = None,
) -> AgentIdea:
    """Record Hermes' scanned market idea so the dashboard can show the recommendation before preview/execution."""
    now = datetime.utcnow().isoformat() + "Z"
    normalized_market = UnifiedMarket(**market).model_dump() if market is not None else None
    idea = AgentIdea(
        idea_id=f"idea_{uuid4().hex[:12]}",
        user_id=user_id,
        agent_id=agent_id,
        topic=topic,
        agent_message=agent_message,
        recommendation=recommendation,
        confidence=confidence,
        market=normalized_market,
        suggested_trade=suggested_trade or {},
        risks=risks or [],
        status=status,
        strategy_id=strategy_id,
        preview_id=preview_id,
        execution_id=execution_id,
        metadata=metadata or {},
        created_at=now,
        updated_at=now,
    )
    TradingLedger(CONFIG.ledger_db_file).upsert_agent_idea(idea)
    return idea


@MCP_SERVER.tool()
def update_agent_idea(
    idea_id: str,
    status: str | None = None,
    preview_id: str | None = None,
    execution_id: str | None = None,
    recommendation: str | None = None,
    agent_message: str | None = None,
    metadata: dict | None = None,
) -> AgentIdea:
    """Update an existing AgentIdea after preview creation, execution, dismissal, or failure."""
    ledger = TradingLedger(CONFIG.ledger_db_file)
    existing = ledger.get_agent_idea(idea_id)
    if existing is None:
        raise RuntimeError(f"agent idea not found: {idea_id}")
    merged_metadata = {**existing.metadata, **(metadata or {})}
    updated = existing.model_copy(
        update={
            "status": status or existing.status,
            "preview_id": preview_id if preview_id is not None else existing.preview_id,
            "execution_id": execution_id if execution_id is not None else existing.execution_id,
            "recommendation": recommendation or existing.recommendation,
            "agent_message": agent_message or existing.agent_message,
            "metadata": merged_metadata,
            "updated_at": datetime.utcnow().isoformat() + "Z",
        }
    )
    ledger.upsert_agent_idea(updated)
    return updated


def _canonical_evm_address_or_none(
    value: object,
    *,
    field_name: str,
) -> str | None:
    try:
        return canonicalize_optional_evm_address(
            value,
            field_name=field_name,
        )
    except ValueError:
        return None


def _same_address(left: str | None, right: str | None) -> bool:
    return bool(left and right) and str(left).lower() == str(right).lower()


def _binding_is_polymarket_deposit_type3(binding: dict) -> bool:
    metadata = binding.get("metadata") if isinstance(binding.get("metadata"), dict) else {}
    account_mode = binding.get("account_mode") or metadata.get("account_mode")
    signature_type = (
        binding.get("polymarket_signature_type")
        or metadata.get("resolved_signature_type")
    )
    wallet_address = _canonical_evm_address_or_none(
        binding.get("wallet_address"),
        field_name="binding wallet address",
    )
    deposit_wallet = _canonical_evm_address_or_none(
        binding.get("polymarket_deposit_wallet"),
        field_name="binding Polymarket deposit wallet",
    )
    funder_address = _canonical_evm_address_or_none(
        binding.get("funder_address"),
        field_name="binding funder address",
    )
    return bool(
        binding.get("status") == "active"
        and binding.get("has_api_credentials") is True
        and account_mode == "deposit_wallet"
        and str(signature_type or "") == "3"
        and wallet_address
        and deposit_wallet
        and funder_address
        and funder_address == deposit_wallet
    )


def _resolve_polymarket_funding_target_from_binding(
    binding: dict,
    requested_mode: str = "x402_funding",
    authoritative_deposit_readiness: dict | None = None,
) -> dict:
    metadata = binding.get("metadata") if isinstance(binding.get("metadata"), dict) else {}
    account_mode = binding.get("account_mode") or metadata.get("account_mode")
    wallet_address = binding.get("wallet_address")
    funder_address = binding.get("funder_address")
    deposit_wallet = binding.get("polymarket_deposit_wallet")
    signature_type = binding.get("polymarket_signature_type") or metadata.get("resolved_signature_type")
    binding_status = binding.get("status")
    has_api_credentials = bool(binding.get("has_api_credentials"))

    base = {
        "mode": requested_mode,
        "user_id": binding.get("user_id"),
        "binding_id": binding.get("binding_id"),
        "account_mode": account_mode or "unresolved",
        "signature_type": str(signature_type or ""),
        "payer_wallet": wallet_address,
        "funder_address": funder_address,
        "polymarket_deposit_wallet": deposit_wallet,
        "target_address": None,
        "target_source": None,
        "can_use_x402": False,
        "binding": binding,
    }

    if binding_status != "active" or not has_api_credentials:
        return {
            **base,
            "status": "blocked",
            "reason_code": "ACCOUNT_BINDING_NOT_ACTIVE",
            "reason": "Polymarket account binding is not active or CLOB credentials are unavailable.",
            "next_action": "create_polymarket_account_binding",
        }

    if not _binding_is_polymarket_deposit_type3(binding):
        deposit_readiness = (
            authoritative_deposit_readiness
            if isinstance(authoritative_deposit_readiness, dict)
            else _deposit_wallet_readiness_for_binding(binding)
        )
        return {
            **base,
            "status": "blocked",
            "reason_code": "POLYMARKET_TYPE3_BINDING_REQUIRED",
            "reason": "The ready Deposit Wallet must be bound with Polymarket signature type 3 before funding.",
            "next_action": "create_polymarket_account_binding_link",
            "deposit_wallet_readiness": deposit_readiness,
        }

    canonical_wallet = _canonical_evm_address_or_none(
        wallet_address,
        field_name="binding wallet address",
    )
    target_address = _canonical_evm_address_or_none(
        deposit_wallet,
        field_name="binding Polymarket deposit wallet",
    )
    target_source = "polymarket_deposit_wallet"

    if _same_address(target_address, canonical_wallet):
        return {
            **base,
            "status": "direct_only",
            "reason_code": "NO_DISTINCT_POLYMARKET_FUNDING_TARGET",
            "reason": "Polymarket funding target equals the payer wallet. Use direct wallet trading instead of x402 funding.",
            "next_action": "use_direct_wallet_trading",
            "target_address": None,
            "target_source": target_source,
        }

    return {
        **base,
        "status": "ready",
        "reason_code": "POLYMARKET_FUNDING_TARGET_READY",
        "reason": "A distinct Polymarket funding target was resolved for x402 funding.",
        "next_action": "fund_polymarket_from_spending_authorization",
        "target_address": target_address,
        "target_source": target_source,
        "can_use_x402": True,
    }


def _deposit_wallet_readiness_for_binding(binding: dict) -> dict:
    user_id = binding.get("user_id")
    owner_wallet = _canonical_evm_address_or_none(
        binding.get("wallet_address"),
        field_name="binding wallet address",
    )
    if not isinstance(user_id, str) or not user_id or not owner_wallet:
        return {
            "status": "blocked",
            "can_use_x402": False,
            "reason": "active binding does not include a user id and owner wallet",
            "next_action": "create_polymarket_account_binding",
        }
    query = urllib.parse.urlencode({"user_id": user_id, "owner_wallet": owner_wallet})
    try:
        response = _request_json(
            CONFIG.deposit_wallet_url,
            f"/polymarket/deposit-wallet/readiness?{query}",
        )
        if not isinstance(response, dict):
            raise ValueError("deposit wallet service returned an invalid response")
        return response
    except Exception:
        return {
            "status": "unavailable",
            "can_use_x402": False,
            "reason": "deposit wallet service unavailable",
            "next_action": "start_prediction_markets_deposit_wallet_service",
        }


def _pick_active_spending_authorization(funding_status: dict) -> dict | None:
    if not isinstance(funding_status, dict):
        return None
    spending_authorizations = funding_status.get("spending_authorizations") or []
    if not isinstance(spending_authorizations, list):
        return None
    for authorization in spending_authorizations:
        if (
            isinstance(authorization, dict)
            and authorization.get("status") == "active"
            and authorization.get("venue") == "polymarket"
        ):
            return authorization
    for authorization in spending_authorizations:
        if isinstance(authorization, dict) and authorization.get("status") == "active":
            return authorization
    return None


def _deposit_wallet_recovery_action(
    readiness: dict,
    *,
    identity_matches: bool,
) -> str:
    if readiness.get("status") == "unavailable":
        return "start_prediction_markets_deposit_wallet_service"
    next_action = readiness.get("next_action")
    if (
        identity_matches
        and isinstance(next_action, str)
        and next_action in _DEPOSIT_WALLET_PREPARATION_ACTIONS
    ):
        return next_action
    return "prepare_polymarket_deposit_wallet"


def _core_spending_projection(core_account: dict) -> dict:
    mandate = core_account.get("active_spending_mandate")
    account_url = core_account.get("account_url")
    return {
        "active_spending_mandate": mandate,
        "spending_budget": (
            {
                "limits_usdc": mandate.get("limits_usdc") or {},
                "remaining_usdc": mandate.get("remaining_usdc") or {},
                "notification_mode": mandate.get("notification_mode"),
                "expires_at": mandate.get("expires_at"),
            }
            if mandate
            else None
        ),
        "core_account_management": {
            "account_url": account_url,
            "next_action": (
                "open_core_account_url"
                if account_url
                else "create_core_account_setup_link"
            ),
        },
    }


def _normalize_suggested_usdc_amount(value: str) -> str:
    if not isinstance(value, str):
        raise ValueError("suggested_amount_usdc is invalid")
    normalized = value.strip()
    if len(normalized) > 85 or not _SUGGESTED_USDC_AMOUNT.fullmatch(normalized):
        raise ValueError("suggested_amount_usdc is invalid")
    whole, separator, fraction = normalized.partition(".")
    fraction = fraction.ljust(6, "0") if separator else "000000"
    atomic = int(whole) * 1_000_000 + int(fraction)
    if atomic <= 0 or atomic > _UINT256_MAX:
        raise ValueError("suggested_amount_usdc is invalid")
    return f"{int(whole)}.{fraction}"


def _core_authorization_is_required(error: Exception) -> bool:
    if (
        not isinstance(error, _PredictionMarketsRequestError)
        or error.status_code != 409
    ):
        return False
    try:
        payload = json.loads(error.response_body)
    except (TypeError, ValueError):
        return False
    return (
        isinstance(payload, dict)
        and set(payload) == {"detail"}
        and payload.get("detail") == "Core authorization is not ready"
    )


def _core_authorization_action(
    *,
    user_id: str,
    amount_usdc: str,
    confirmation_id: str,
    operation_id: str | None,
) -> dict:
    try:
        session = CORE_ACCOUNT_CLIENT.create_setup_link(user_id)
    except CoreAccountClientError as exc:
        raise RuntimeError(str(exc)) from exc
    account_url = session.get("account_url")
    if not isinstance(account_url, str) or not account_url.startswith(
        ("http://", "https://")
    ):
        raise RuntimeError("Core Account response did not include a valid public account URL")
    return {
        "status": "action_required",
        "operation_id": operation_id,
        "receipt_id": None,
        "tx_hash": None,
        "amount_usdc": amount_usdc,
        "confirmation_id": confirmation_id,
        "account_url": account_url,
        "action_label": "Open Clink spending account",
        "expires_at": session.get("expires_at"),
        "next_action": "open_core_account_url",
        "resume_action": _DIRECT_FUNDING_NEXT_ACTION,
        "requires_new_confirmation": False,
    }


def _validated_direct_funding_operation(
    response: dict,
    *,
    expected_user_id: str,
    expected_amount_usdc: str,
    expected_resource: str,
    expected_opc_installation_id: str | None = None,
    expected_operation_id: str | None = None,
) -> dict:
    try:
        if not isinstance(response, dict):
            raise ValueError
        operation = PolymarketFundingOperationView.model_validate_json(
            json.dumps(response, allow_nan=False)
        ).model_dump(mode="json")
        if any(
            response.get(field) != operation.get(field)
            for field in (
                "operation_id",
                "user_id",
                "status",
                "amount_usdc",
                "resource",
                "opc_installation_id",
                "reservation_id",
                "core_tx_hash",
                "next_action",
            )
        ):
            raise ValueError
        if (
            operation["user_id"] != expected_user_id
            or operation["amount_usdc"] != expected_amount_usdc
            or operation["resource"] != expected_resource
            or operation["opc_installation_id"]
            != expected_opc_installation_id
            or expected_operation_id is not None
            and operation["operation_id"] != expected_operation_id
            or funding_operation_next_action(operation["status"])
            != operation["next_action"]
        ):
            raise ValueError
    except (TypeError, ValueError):
        raise RuntimeError(_DIRECT_FUNDING_RESPONSE_ERROR) from None
    return operation


def _direct_funding_projection(operation: dict) -> dict:
    projection = {
        "status": operation["status"],
        "operation_id": operation["operation_id"],
        "receipt_id": None,
        "tx_hash": operation.get("core_tx_hash"),
        "amount_usdc": operation["amount_usdc"],
        "failure_reason_code": operation.get("failure_reason_code"),
        "core_state": operation.get("core_state"),
        "bridge_status": operation.get("bridge_status"),
        "venue_buying_power_before_atomic": operation.get(
            "venue_buying_power_before_atomic"
        ),
        "venue_buying_power_after_atomic": operation.get(
            "venue_buying_power_after_atomic"
        ),
        "signing_url": None,
        "next_action": (
            operation["next_action"]
            if operation["status"] in {"failed", "released"}
            else _DIRECT_FUNDING_NEXT_ACTION
        ),
    }
    return projection


def _settled_direct_funding_projection(operation: dict) -> dict:
    reservation_id = operation.get("reservation_id")
    operation_tx_hash = operation.get("core_tx_hash")
    if not isinstance(reservation_id, str) or not isinstance(
        operation_tx_hash, str
    ):
        raise RuntimeError(_DIRECT_FUNDING_RESPONSE_ERROR)
    reservation_path_id = urllib.parse.quote(reservation_id, safe="")
    reservation = _request_json(
        CONFIG.clink_core_funding_service_url,
        f"/funding/spending-reservations/{reservation_path_id}",
    )
    receipt_id = (
        reservation.get("receipt_id") if isinstance(reservation, dict) else None
    )
    tx_hash = (
        reservation.get("tx_hash") if isinstance(reservation, dict) else None
    )
    try:
        reservation_amount_usdc = _normalize_suggested_usdc_amount(
            reservation.get("amount_usdc")
            if isinstance(reservation, dict)
            else None
        )
    except ValueError:
        reservation_amount_usdc = None
    if (
        not isinstance(reservation, dict)
        or reservation.get("reservation_id") != reservation_id
        or reservation.get("purchase_id") != operation["operation_id"]
        or reservation.get("user_id") != operation["user_id"]
        or reservation_amount_usdc != operation["amount_usdc"]
        or reservation.get("resource") != operation["resource"]
        or reservation.get("state") != "finalized"
        or not isinstance(receipt_id, str)
        or not receipt_id
        or receipt_id != receipt_id.strip()
        or not isinstance(tx_hash, str)
        or tx_hash != operation_tx_hash
    ):
        raise RuntimeError(_DIRECT_FUNDING_RESPONSE_ERROR)
    return {
        "status": "settled",
        "operation_id": operation["operation_id"],
        "receipt_id": receipt_id,
        "tx_hash": tx_hash,
        "amount_usdc": operation["amount_usdc"],
        "signing_url": None,
        "next_action": "complete",
    }


def _funding_ui_hostname(hostname: str, *, bracketed: bool) -> str:
    normalized_hostname = hostname.rstrip(".").lower()
    if (
        normalized_hostname == "localhost"
        or normalized_hostname.endswith(".localhost")
    ):
        raise RuntimeError(_FUNDING_UI_URL_ERROR)
    try:
        address = ipaddress.ip_address(hostname)
    except ValueError:
        if bracketed:
            raise RuntimeError(_FUNDING_UI_URL_ERROR) from None
        labels = hostname.split(".")
        if labels and _BROWSER_NUMERIC_HOST_LABEL.fullmatch(labels[-1]):
            raise RuntimeError(_FUNDING_UI_URL_ERROR)
        if any(
            not label
            or len(label) > 63
            or re.fullmatch(
                r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?",
                label,
            )
            is None
            for label in labels
        ):
            raise RuntimeError(_FUNDING_UI_URL_ERROR) from None
        return hostname.lower()
    if (
        (bracketed and address.version != 6)
        or getattr(address, "scope_id", None) is not None
    ):
        raise RuntimeError(_FUNDING_UI_URL_ERROR)
    mapped_address = getattr(address, "ipv4_mapped", None)
    routability_address = mapped_address or address
    if (
        not routability_address.is_global
        or routability_address.is_multicast
        or routability_address.is_reserved
        or routability_address.is_unspecified
    ):
        raise RuntimeError(_FUNDING_UI_URL_ERROR)
    if address.version == 6:
        return f"[{address.compressed}]"
    return address.compressed


def _polymarket_funding_ui_url(canonical_amount_usdc: str | None) -> str:
    raw_base_url = str(CONFIG.account_binding_console_base_url).strip()
    if any(
        ord(character) <= 32 or ord(character) == 127
        for character in raw_base_url
    ):
        raise RuntimeError(_FUNDING_UI_URL_ERROR)
    try:
        parsed = urllib.parse.urlsplit(raw_base_url)
        port = parsed.port
    except ValueError:
        raise RuntimeError(_FUNDING_UI_URL_ERROR) from None
    if (
        parsed.scheme.lower() != "https"
        or not parsed.netloc
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.path not in {"", "/"}
        or parsed.query
        or parsed.fragment
        or port not in {None, 443}
    ):
        raise RuntimeError(_FUNDING_UI_URL_ERROR)
    hostname = _funding_ui_hostname(
        parsed.hostname,
        bracketed=parsed.netloc.startswith("["),
    )
    fragment = (
        "funding"
        if canonical_amount_usdc is None
        else f"funding={canonical_amount_usdc}"
    )
    return urllib.parse.urlunsplit(
        ("https", hostname, "/miniapp/", "", fragment)
    )


def _get_polymarket_funding_operation(
    *, user_id: str, operation_id: str
) -> dict:
    operation_path = urllib.parse.quote(str(operation_id), safe="")
    query = urllib.parse.urlencode({"user_id": user_id})
    return _request_json(
        CONFIG.funding_adapter_url,
        f"/polymarket/funding-operations/{operation_path}?{query}",
    )


def _funding_operation_is_ready(operation: dict | None) -> bool:
    if not isinstance(operation, dict):
        return False
    return bool(
        operation.get("status") == "finalized"
        and operation.get("core_state") == "finalized"
        and operation.get("bridge_status") == "COMPLETED"
        and operation.get("reservation_id")
        and operation.get("audit_event_id")
        and operation.get("core_tx_hash")
    )


def _public_funding_operation_summary(operation: dict | None) -> dict | None:
    if not isinstance(operation, dict):
        return None
    summary = {
        field: operation.get(field)
        for field in ("operation_id", "status", "reason", "next_action")
        if field in operation
    }
    if operation.get("status") in FUNDING_OPERATION_PENDING_STATUSES:
        summary["next_action"] = _DIRECT_FUNDING_NEXT_ACTION
    return summary


@MCP_SERVER.tool()
def create_core_account_setup_link(user_id: str) -> dict:
    """Create a short-lived Core Account page link for user-controlled wallet binding and spending-cap authorization."""
    try:
        session = CORE_ACCOUNT_CLIENT.create_setup_link(user_id)
    except CoreAccountClientError as exc:
        raise RuntimeError(str(exc)) from exc
    return {
        "user_id": user_id,
        "status": "pending_user_action",
        "account_url": session["account_url"],
        "expires_at": session.get("expires_at"),
        "next_action": "open_core_account_url",
    }


@MCP_SERVER.tool()
def resolve_polymarket_funding_target(
    user_id: str,
    requested_mode: str = "x402_funding",
) -> dict:
    """Resolve whether Polymarket funding should use direct EOA trading or a distinct x402 funding target."""
    binding = _request_json(CONFIG.account_binding_url, f"/polymarket/bindings/latest/{user_id}")
    return _resolve_polymarket_funding_target_from_binding(binding, requested_mode=requested_mode)


@MCP_SERVER.tool()
def get_prediction_market_user_readiness(
    user_id: str,
    funding_operation_id: str | None = None,
) -> dict:
    """Return Core Account, Polymarket binding, funding, and trading readiness without creating sessions."""
    try:
        core_account = CORE_ACCOUNT_CLIENT.readiness(user_id)
    except CoreAccountClientError as exc:
        core_account = {
            "user_id": user_id,
            "wallet_bound": False,
            "spending_grant_active": False,
            "ready": False,
            "reason": str(exc),
        }
    if not isinstance(core_account, dict):
        core_account = {
            "user_id": user_id,
            "wallet_bound": False,
            "spending_grant_active": False,
            "ready": False,
            "reason": "Core Account readiness is unavailable",
        }
    try:
        binding = _request_json(CONFIG.account_binding_url, f"/polymarket/bindings/latest/{user_id}")
    except Exception:
        binding = {
            "status": "unavailable",
            "reason": "Polymarket account binding is unavailable",
            "next_action": "create_polymarket_account_binding_link",
        }
    if not isinstance(binding, dict):
        binding = {
            "status": "unavailable",
            "reason": "Polymarket account binding is unavailable",
            "next_action": "create_polymarket_account_binding_link",
        }

    core_user_matches = core_account.get("user_id") == user_id
    core_wallet = _canonical_evm_address_or_none(
        core_account.get("wallet_address"),
        field_name="Core Account wallet address",
    )
    wallet_bound = bool(
        core_user_matches
        and core_account.get("wallet_bound") is True
        and core_wallet
    )
    spending_authorization_ready = bool(
        core_user_matches
        and core_account.get("spending_grant_active") is True
    )
    binding_wallet = _canonical_evm_address_or_none(
        binding.get("wallet_address"),
        field_name="binding wallet address",
    )
    binding_subject_matches = binding.get("user_id") == user_id
    binding_core_matches = bool(
        binding_subject_matches
        and core_wallet
        and binding_wallet == core_wallet
    )
    polymarket_bound = bool(
        binding.get("status") == "active"
        and binding.get("has_api_credentials") is True
        and binding_core_matches
    )
    core_spending = _core_spending_projection(core_account)

    if not wallet_bound or not spending_authorization_ready:
        return {
            **core_spending,
            "user_id": user_id,
            "status": "core_account_required",
            "wallet_bound": wallet_bound,
            "polymarket_bound": polymarket_bound,
            "deposit_wallet_ready": False,
            "deposit_binding_join_ready": False,
            "x402_funding_ready": False,
            "funding_target_ready": False,
            "funding_operation_ready": False,
            "spending_authorization_ready": spending_authorization_ready,
            "trading_ready": False,
            "next_action": "create_core_account_setup_link",
            "core_account": core_account,
            "binding": binding,
        }

    deposit_readiness = _deposit_wallet_readiness_for_binding(
        {
            "user_id": user_id,
            "wallet_address": core_wallet,
        }
    )
    funding_route = _resolve_polymarket_funding_target_from_binding(
        binding,
        requested_mode="x402_funding",
        authoritative_deposit_readiness=deposit_readiness,
    )
    binding_deposit_wallet = _canonical_evm_address_or_none(
        binding.get("polymarket_deposit_wallet"),
        field_name="binding Polymarket deposit wallet",
    )
    deposit_owner = _canonical_evm_address_or_none(
        deposit_readiness.get("owner_wallet"),
        field_name="Deposit Wallet readiness owner",
    )
    ready_deposit_wallet = _canonical_evm_address_or_none(
        deposit_readiness.get("deposit_wallet"),
        field_name="Deposit Wallet readiness address",
    )
    deposit_identity_matches = bool(
        deposit_readiness.get("user_id") == user_id
        and core_wallet
        and deposit_owner == core_wallet
    )
    authoritative_deposit_ready = bool(
        deposit_identity_matches
        and ready_deposit_wallet
        and deposit_readiness.get("ready") is True
        and deposit_readiness.get("can_use_x402") is True
    )
    deposit_binding_join_ready = bool(
        authoritative_deposit_ready
        and binding_core_matches
        and _binding_is_polymarket_deposit_type3(binding)
        and binding_deposit_wallet == ready_deposit_wallet
    )

    if not authoritative_deposit_ready:
        deposit_next_action = _deposit_wallet_recovery_action(
            deposit_readiness,
            identity_matches=deposit_identity_matches,
        )
        funding_route = {
            **funding_route,
            "status": "blocked",
            "reason_code": "POLYMARKET_DEPOSIT_WALLET_NOT_READY",
            "reason": "The authoritative Polymarket Deposit Wallet is not ready for funding.",
            "next_action": deposit_next_action,
            "target_address": None,
            "can_use_x402": False,
            "deposit_wallet_readiness": deposit_readiness,
        }
        return {
            **core_spending,
            "user_id": user_id,
            "status": "funding_not_ready",
            "wallet_bound": True,
            "polymarket_bound": polymarket_bound,
            "deposit_wallet_ready": False,
            "deposit_binding_join_ready": False,
            "x402_funding_ready": False,
            "funding_target_ready": False,
            "funding_operation_ready": False,
            "spending_authorization_ready": True,
            "trading_ready": False,
            "next_action": deposit_next_action,
            "core_account": core_account,
            "binding": binding,
            "deposit_wallet_readiness": deposit_readiness,
            "funding_route": funding_route,
        }

    if not deposit_binding_join_ready:
        funding_route = {
            **funding_route,
            "status": "blocked",
            "reason_code": "POLYMARKET_TYPE3_BINDING_REQUIRED",
            "reason": "The authoritative Deposit Wallet must be joined to an exact Polymarket type-3 binding before funding.",
            "next_action": "create_polymarket_account_binding_link",
            "target_address": None,
            "can_use_x402": False,
            "deposit_wallet_readiness": deposit_readiness,
        }
        return {
            **core_spending,
            "user_id": user_id,
            "status": "polymarket_account_required",
            "wallet_bound": True,
            "polymarket_bound": polymarket_bound,
            "deposit_wallet_ready": True,
            "deposit_binding_join_ready": False,
            "x402_funding_ready": False,
            "funding_target_ready": False,
            "funding_operation_ready": False,
            "spending_authorization_ready": True,
            "trading_ready": False,
            "next_action": "create_polymarket_account_binding_link",
            "core_account": core_account,
            "binding": binding,
            "deposit_wallet_readiness": deposit_readiness,
            "funding_route": funding_route,
        }

    try:
        execution_readiness = _request_json(CONFIG.execution_url, "/execution/readiness")
        if not isinstance(execution_readiness, dict):
            raise ValueError("execution service returned an invalid response")
    except Exception:
        execution_readiness = {
            "live_ready": False,
            "reason": "execution service unavailable",
            "next_action": "start_prediction_markets_execution_service",
        }
    try:
        funding_readiness = _request_json(CONFIG.clink_core_funding_service_url, "/funding/readiness")
        if not isinstance(funding_readiness, dict):
            raise ValueError("funding service returned an invalid response")
    except Exception:
        funding_readiness = {
            "status": "offline",
            "settlement_rail": "unknown",
            "native_facilitator_ready": False,
            "reason": "funding service unavailable",
            "next_action": "start_clink_core_funding_service",
        }
    try:
        funding_status = _request_json(
            CONFIG.clink_core_funding_service_url,
            f"/funding/status?{urllib.parse.urlencode({'user_id': user_id, 'venue': 'polymarket'})}",
        )
        if not isinstance(funding_status, dict):
            raise ValueError("funding status returned an invalid response")
    except Exception:
        funding_status = {
            "authorizations": [],
            "spending_authorizations": [],
            "reason": "funding status unavailable",
        }

    funding_operation = None
    if funding_operation_id:
        try:
            funding_operation = _get_polymarket_funding_operation(
                user_id=user_id,
                operation_id=funding_operation_id,
            )
        except Exception:
            funding_operation = {
                "operation_id": funding_operation_id,
                "status": "unavailable",
                "reason": "funding operation is unavailable",
                "next_action": _DIRECT_FUNDING_NEXT_ACTION,
            }

    deposit_wallet_ready = authoritative_deposit_ready
    funding_target_ready = bool(
        funding_route.get("status") == "ready"
        and funding_route.get("can_use_x402") is True
        and deposit_binding_join_ready
        and _same_address(
            funding_route.get("target_address"),
            ready_deposit_wallet,
        )
    )
    funding_operation_ready = _funding_operation_is_ready(funding_operation)
    x402_funding_ready = funding_target_ready and funding_operation_ready
    legacy_funding_authorization = _pick_active_spending_authorization(funding_status)
    trading_ready = bool(
        execution_readiness.get("live_ready")
        and polymarket_bound
        and funding_target_ready
        and funding_operation_ready
    )

    if not funding_target_ready:
        status = "funding_not_ready"
        next_action = funding_route.get("next_action") or "prepare_polymarket_deposit_wallet"
    elif not funding_operation_id:
        status = "funding_operation_required"
        next_action = "fund_polymarket_from_spending_authorization"
    elif (
        isinstance(funding_operation, dict)
        and funding_operation.get("status") in FUNDING_OPERATION_PENDING_STATUSES
    ):
        status = "funding_pending"
        next_action = _DIRECT_FUNDING_NEXT_ACTION
    elif not funding_operation_ready:
        status = "funding_not_ready"
        next_action = "fund_polymarket_from_spending_authorization"
    elif not trading_ready:
        status = "trading_not_ready"
        next_action = execution_readiness.get("next_action") or "configure_prediction_market_execution"
    else:
        status = "ready"
        next_action = "create_prediction_market_order_preview"

    return {
        **core_spending,
        "user_id": user_id,
        "status": status,
        "wallet_bound": wallet_bound,
        "polymarket_bound": polymarket_bound,
        "deposit_wallet_ready": deposit_wallet_ready,
        "deposit_binding_join_ready": deposit_binding_join_ready,
        "x402_funding_ready": x402_funding_ready,
        "funding_target_ready": funding_target_ready,
        "funding_operation_ready": funding_operation_ready,
        "spending_authorization_ready": spending_authorization_ready,
        "trading_ready": trading_ready,
        "next_action": next_action,
        "core_account": core_account,
        "binding": binding,
        "deposit_wallet_readiness": deposit_readiness,
        "funding_route": funding_route,
        "funding_readiness": funding_readiness,
        "funding_status": funding_status,
        "funding_operation": _public_funding_operation_summary(
            funding_operation
        ),
        "legacy_funding_authorization": legacy_funding_authorization,
        "settlement_rail": funding_readiness.get("settlement_rail", "unknown"),
        "execution_readiness": execution_readiness,
    }


def prepare_polymarket_funding_ui(
    suggested_amount_usdc: str | None = None,
) -> dict:
    """Call only after the user explicitly requests a positive USDC amount. The final user response must include the returned funding_url verbatim. Preparing this UI does not mean a funding operation was created, funds were transferred, or the operation is settled."""
    canonical_amount = (
        _normalize_suggested_usdc_amount(suggested_amount_usdc)
        if suggested_amount_usdc is not None
        else None
    )
    action_label = "Open Polymarket funding"
    if canonical_amount is not None:
        display_amount = canonical_amount.rstrip("0").rstrip(".")
        action_label = f"Fund {display_amount} USDC"
    return {
        "suggested_amount_usdc": canonical_amount,
        "next_action": "open_polymarket_funding_operation",
        "funding_url": _polymarket_funding_ui_url(canonical_amount),
        "action_label": action_label,
    }


@MCP_SERVER.tool()
def check_polymarket_deposit_wallet_readiness(
    user_id: str,
    owner_wallet: str | None = None,
) -> PolymarketDepositWalletReadiness:
    """Check whether Clink can resolve a Polymarket deposit wallet target for x402 funding."""
    if owner_wallet is None:
        binding = _request_json(CONFIG.account_binding_url, f"/polymarket/bindings/latest/{user_id}")
        owner_wallet = binding.get("wallet_address") or binding.get("funder_address")
    query = urllib.parse.urlencode({"user_id": user_id, "owner_wallet": owner_wallet or ""})
    response = _request_json(CONFIG.deposit_wallet_url, f"/polymarket/deposit-wallet/readiness?{query}")
    return PolymarketDepositWalletReadiness(**response)


@MCP_SERVER.tool()
def prepare_polymarket_deposit_wallet(
    user_id: str,
    owner_wallet: str | None = None,
    mode: str = "derive",
    metadata: dict | None = None,
) -> dict:
    """Ask Clink to derive or deploy the user's Polymarket deposit wallet through the builder relayer path."""
    try:
        core_account = CORE_ACCOUNT_CLIENT.readiness(user_id)
        if not isinstance(core_account, dict):
            raise ValueError("Core Account readiness is invalid")
        if core_account.get("user_id") != user_id:
            raise ValueError("Core Account subject does not match caller")
        if core_account.get("wallet_bound") is not True:
            raise ValueError("Core Account wallet is not bound")
        core_wallet = canonicalize_optional_evm_address(
            core_account.get("wallet_address"),
            field_name="Core Account wallet address",
        )
        if core_wallet is None:
            raise ValueError("Core Account wallet is missing")
        if owner_wallet is not None:
            requested_owner = canonicalize_optional_evm_address(
                owner_wallet,
                field_name="owner wallet",
            )
            if requested_owner != core_wallet:
                raise ValueError("owner wallet does not match Core Account")
    except (CoreAccountClientError, ValueError, TypeError, AttributeError):
        raise RuntimeError(
            _DEPOSIT_WALLET_PREPARATION_READINESS_ERROR
        ) from None

    try:
        binding = _request_json(
            CONFIG.account_binding_url,
            f"/polymarket/bindings/latest/{user_id}",
        )
    except Exception:
        binding = {"status": "unavailable"}
    if not isinstance(binding, dict):
        binding = {"status": "unavailable"}

    request = PreparePolymarketDepositWalletRequest(
        user_id=user_id,
        owner_wallet=core_wallet,
        mode=mode,
        metadata={**(metadata or {}), "binding_id": binding.get("binding_id")},
    )
    state_response = _request_json(
        CONFIG.deposit_wallet_url,
        "/polymarket/deposit-wallet/prepare",
        request.model_dump(),
    )
    state = PolymarketDepositWalletState(**state_response)
    state_payload = state.model_dump()
    state_owner = _canonical_evm_address_or_none(
        state_response.get("owner_wallet"),
        field_name="prepared Deposit Wallet owner",
    )
    state_deposit_wallet = _canonical_evm_address_or_none(
        state_response.get("deposit_wallet"),
        field_name="prepared Deposit Wallet address",
    )
    state_identity_matches = bool(
        state_response.get("user_id") == user_id
        and state_owner == core_wallet
    )
    state_ready = bool(
        state_identity_matches
        and state_deposit_wallet
        and state_response.get("can_use_x402") is True
        and state_response.get("status") in {"deployed", "funded", "ready"}
    )
    binding_wallet = _canonical_evm_address_or_none(
        binding.get("wallet_address"),
        field_name="binding wallet address",
    )
    binding_deposit_wallet = _canonical_evm_address_or_none(
        binding.get("polymarket_deposit_wallet"),
        field_name="binding Polymarket deposit wallet",
    )
    binding_join_ready = bool(
        state_ready
        and binding.get("user_id") == user_id
        and binding_wallet == core_wallet
        and _binding_is_polymarket_deposit_type3(binding)
        and binding_deposit_wallet == state_deposit_wallet
    )
    route = _resolve_polymarket_funding_target_from_binding(
        binding,
        requested_mode="x402_funding",
        authoritative_deposit_readiness={
            **state_payload,
            "ready": state_ready,
        },
    )
    if state_ready and not binding_join_ready:
        route = {
            **route,
            "status": "blocked",
            "reason_code": "POLYMARKET_TYPE3_BINDING_REQUIRED",
            "reason": "The prepared Deposit Wallet must be joined to an exact Polymarket type-3 binding before funding.",
            "next_action": "create_polymarket_account_binding_link",
            "target_address": None,
            "can_use_x402": False,
        }
    elif not state_ready:
        recovery_action = _deposit_wallet_recovery_action(
            state_payload,
            identity_matches=state_identity_matches,
        )
        route = {
            **route,
            "status": "blocked",
            "reason_code": "POLYMARKET_DEPOSIT_WALLET_NOT_READY",
            "reason": "The authoritative Polymarket Deposit Wallet is not ready for funding.",
            "next_action": recovery_action,
            "target_address": None,
            "can_use_x402": False,
        }
    return {
        "state": state_payload,
        "funding_route": route,
        "next_action": route.get("next_action"),
    }


@MCP_SERVER.tool()
def fund_polymarket_from_spending_authorization(
    user_id: str,
    amount_usdc: str,
    confirmation_id: str,
    user_confirmed: bool = False,
    resource: str = "clink://polymarket/funding",
    metadata: dict | None = None,
    opc_installation_id: str | None = None,
) -> dict:
    """Fund after one explicit conversational confirmation.

    Any clear natural-language confirmation that states the exact amount and execution intent counts; never require a fixed phrase.
    For a pending result: Call fund_polymarket_from_spending_authorization again with the identical confirmation_id and user_confirmed=True without asking the user again.
    For action_required: show account_url as the single Clink spending-account action. After the user returns, reuse the identical confirmation_id with user_confirmed=True; do not ask for another confirmation or create a new id.
    """
    if user_confirmed is not True:
        raise RuntimeError("explicit user confirmation is required")

    canonical_amount = _normalize_suggested_usdc_amount(amount_usdc)
    try:
        request = CreatePolymarketFundingOperationRequest(
            user_id=user_id,
            amount_usdc=canonical_amount,
            idempotency_key=confirmation_id,
            resource=resource,
            opc_installation_id=opc_installation_id,
        )
    except (TypeError, ValueError):
        raise ValueError("Polymarket funding request is invalid") from None
    if (
        request.user_id != user_id
        or request.idempotency_key != confirmation_id
        or request.resource != resource
        or request.opc_installation_id != opc_installation_id
    ):
        raise ValueError("Polymarket funding request is invalid")
    del metadata

    operation_id: str | None = None
    try:
        operation = _validated_direct_funding_operation(
            _request_json(
                CONFIG.funding_adapter_url,
                "/polymarket/funding-operations",
                request.model_dump(mode="json", exclude_none=True),
            ),
            expected_user_id=request.user_id,
            expected_amount_usdc=request.amount_usdc,
            expected_resource=request.resource,
            expected_opc_installation_id=request.opc_installation_id,
        )
        operation_id = operation["operation_id"]
        operation_path_id = urllib.parse.quote(operation_id, safe="")
        if operation["status"] == "created":
            operation = _validated_direct_funding_operation(
                _request_json(
                    CONFIG.funding_adapter_url,
                    f"/polymarket/funding-operations/{operation_path_id}/confirm",
                    {
                        "user_id": request.user_id,
                        "confirmed": True,
                        **(
                            {
                                "opc_installation_id": request.opc_installation_id
                            }
                            if request.opc_installation_id is not None
                            else {}
                        ),
                    },
                ),
                expected_user_id=request.user_id,
                expected_amount_usdc=request.amount_usdc,
                expected_resource=request.resource,
                expected_opc_installation_id=request.opc_installation_id,
                expected_operation_id=operation_id,
            )
        else:
            operation = _validated_direct_funding_operation(
                _request_json(
                    CONFIG.funding_adapter_url,
                    f"/polymarket/funding-operations/{operation_path_id}/advance",
                    {
                        "user_id": request.user_id,
                        **(
                            {
                                "opc_installation_id": request.opc_installation_id
                            }
                            if request.opc_installation_id is not None
                            else {}
                        ),
                    },
                ),
                expected_user_id=request.user_id,
                expected_amount_usdc=request.amount_usdc,
                expected_resource=request.resource,
                expected_opc_installation_id=request.opc_installation_id,
                expected_operation_id=operation_id,
            )
    except _PredictionMarketsRequestError as exc:
        if not _core_authorization_is_required(exc):
            raise
        return _core_authorization_action(
            user_id=request.user_id,
            amount_usdc=request.amount_usdc,
            confirmation_id=request.idempotency_key,
            operation_id=operation_id,
        )

    if operation["status"] == "finalized":
        return _settled_direct_funding_projection(operation)
    return _direct_funding_projection(operation)


@MCP_SERVER.tool()
def create_polymarket_account_binding_link(
    user_id: str,
    agent_id: str = "hermes",
    expires_in_minutes: int = 30,
    return_url: str | None = None,
    metadata: dict | None = None,
) -> PolymarketBindingSession:
    """Create a browser wallet signing link that binds a user-controlled Polymarket account to Clink."""
    try:
        core_account = CORE_ACCOUNT_CLIENT.readiness(user_id)
        if not isinstance(core_account, dict):
            raise ValueError("Core Account readiness is invalid")
        if core_account.get("user_id") != user_id:
            raise ValueError("Core Account subject does not match caller")
        if core_account.get("wallet_bound") is not True:
            raise ValueError("Core Account wallet is not bound")
        core_wallet = canonicalize_optional_evm_address(
            core_account.get("wallet_address"),
            field_name="Core Account wallet address",
        )
        if core_wallet is None:
            raise ValueError("Core Account wallet is missing")
        deposit_readiness = _deposit_wallet_readiness_for_binding(
            {
                "user_id": user_id,
                "wallet_address": core_wallet,
            }
        )
        if (
            not isinstance(deposit_readiness, dict)
            or deposit_readiness.get("ready") is not True
            or deposit_readiness.get("can_use_x402") is not True
        ):
            raise ValueError("deposit wallet is not ready")
        deposit = PolymarketDepositWalletReadiness(**deposit_readiness)
        if deposit.user_id != user_id:
            raise ValueError("deposit readiness subject does not match caller")
        deposit_owner = canonicalize_optional_evm_address(
            deposit.owner_wallet,
            field_name="deposit readiness owner wallet",
        )
        if deposit_owner != core_wallet:
            raise ValueError("deposit readiness owner does not match Core Account")
        deposit_wallet = canonicalize_optional_evm_address(
            deposit.deposit_wallet,
            field_name="Polymarket deposit wallet",
        )
        if (
            deposit.ready is not True
            or deposit.can_use_x402 is not True
            or deposit_wallet is None
        ):
            raise ValueError("deposit wallet is not ready")
        request = CreatePolymarketBindingSessionRequest(
            user_id=user_id,
            agent_id=agent_id,
            wallet_address=core_wallet,
            polymarket_deposit_wallet=deposit_wallet,
            expires_in_minutes=expires_in_minutes,
            return_url=return_url,
            metadata=metadata or {},
        )
    except (CoreAccountClientError, ValueError, TypeError, AttributeError):
        raise RuntimeError(_TYPE3_BINDING_READINESS_ERROR) from None
    response = _request_json(
        CONFIG.account_binding_url,
        "/internal/polymarket/binding-sessions",
        request.model_dump(),
    )
    return PolymarketBindingSession(**response)


@MCP_SERVER.tool()
def get_polymarket_account_binding_status(
    user_id: str | None = None,
    binding_id: str | None = None,
) -> dict:
    """Fetch a Polymarket account binding by id, or the latest active binding for a user."""
    if binding_id:
        response = _request_json(CONFIG.account_binding_url, f"/polymarket/bindings/{binding_id}")
        return PolymarketAccountBinding(**response).model_dump()
    if not user_id:
        raise RuntimeError("user_id is required when binding_id is not provided")
    return _request_json(CONFIG.account_binding_url, f"/polymarket/bindings/latest/{user_id}")


@MCP_SERVER.tool()
def revoke_polymarket_account_binding(
    binding_id: str,
    reason: str = "user_requested_unbind",
    metadata: dict | None = None,
) -> dict:
    """Revoke a Clink-side Polymarket account binding and delete saved CLOB credentials."""
    response = _request_json(
        CONFIG.account_binding_url,
        f"/polymarket/bindings/{binding_id}/revoke",
        {"reason": reason, "metadata": metadata or {}},
    )
    return PolymarketAccountBinding(**response).model_dump()


@MCP_SERVER.tool()
def search_prediction_markets(
    query: str | None = None,
    platforms: list[str] | None = None,
    limit: int = 20,
    tradable_only: bool = True,
) -> SearchMarketsResult:
    """Search prediction markets across Polymarket and Kalshi. Read-only."""
    response = _request_json(
        CONFIG.router_url,
        "/markets/search",
        {"query": query, "platforms": platforms or ["polymarket", "kalshi"], "limit": limit, "tradable_only": tradable_only},
    )
    return SearchMarketsResult(**response)


@MCP_SERVER.tool()
def score_prediction_market_opportunities(
    query: str | None = None,
    markets: list[dict] | None = None,
    max_results: int = 5,
) -> ScoreMarketsResult:
    """Score already-discovered prediction markets by topic fit, tradability, liquidity, and spread."""
    normalized = [UnifiedMarket(**item).model_dump() for item in (markets or [])]
    response = _request_json(CONFIG.router_url, "/markets/score", {"query": query, "markets": normalized, "max_results": max_results})
    return ScoreMarketsResult(**response)


@MCP_SERVER.tool()
def create_prediction_market_order_preview(
    user_id: str,
    market: dict,
    amount_usd: str,
    agent_id: str = "external_prediction_agent",
    outcome: str = "Yes",
    side: str = "buy",
    limit_price: float | None = None,
    max_slippage_bps: int = 100,
    live_mode: bool = False,
    metadata: dict | None = None,
) -> PredictionMarketOrderPreview:
    """Create a Clink Core-gated, non-executing single-platform prediction market order preview."""
    request = CreateOrderPreviewRequest(
        user_id=user_id,
        agent_id=agent_id,
        market=UnifiedMarket(**market),
        outcome=outcome,
        side=side,
        amount_usd=amount_usd,
        limit_price=limit_price,
        max_slippage_bps=max_slippage_bps,
        live_mode=live_mode,
        metadata=metadata or {},
    )
    response = _request_json(CONFIG.preview_url, "/order-previews", request.model_dump())
    return PredictionMarketOrderPreview(**response)


@MCP_SERVER.tool()
def get_prediction_market_order_preview(preview_id: str) -> PredictionMarketOrderPreview:
    """Fetch a stored prediction market order preview by id."""
    response = _request_json(CONFIG.preview_url, f"/order-previews/{preview_id}")
    return PredictionMarketOrderPreview(**response)


@MCP_SERVER.tool()
def build_prediction_market_context(
    topic: str,
    goal: str | None = None,
    platforms: list[str] | None = None,
    markets: list[dict] | None = None,
    max_results: int = 8,
    tradable_only: bool = True,
    metadata: dict | None = None,
) -> PredictionMarketContextResult:
    """Build a neutral cross-platform market context package. Hermes owns the final trading judgment."""
    request = PredictionMarketContextRequest(
        topic=topic,
        goal=goal,
        platforms=platforms or ["polymarket", "kalshi"],
        markets=[UnifiedMarket(**market) for market in markets] if markets is not None else None,
        max_results=max_results,
        tradable_only=tradable_only,
        metadata=metadata or {},
    )
    response = _request_json(CONFIG.decision_url, "/context/build", request.model_dump())
    return PredictionMarketContextResult(**response)


@MCP_SERVER.tool()
def check_prediction_market_execution_readiness() -> ExecutionReadiness:
    """Check whether prediction market live execution is configured and which platforms are ready."""
    response = _request_json(CONFIG.execution_url, "/execution/readiness")
    return ExecutionReadiness(**response)


@MCP_SERVER.tool()
def execute_prediction_market_order_preview(
    preview_id: str,
    user_confirmed: bool = False,
    live_submission_confirmed: bool = False,
    confirmation_message: str | None = None,
    metadata: dict | None = None,
) -> PredictionMarketExecution:
    """Execute a single-platform order preview after explicit user and live-submission confirmation."""
    request = ExecutePredictionMarketOrderRequest(
        preview_id=preview_id,
        user_confirmed=user_confirmed,
        live_submission_confirmed=live_submission_confirmed,
        confirmation_message=confirmation_message,
        metadata=metadata or {},
    )
    response = _request_json(CONFIG.execution_url, "/execution/order-preview", request.model_dump())
    return PredictionMarketExecution(**response)


def _public_signing_session_summary(session: dict) -> dict:
    validated = PolymarketOrderSigningSession(**session).model_dump()
    summary = {
        field: validated.get(field)
        for field in ("session_id", "status", "reason", "next_action")
    }
    if validated.get("execution_id") is not None:
        summary["execution_id"] = validated["execution_id"]
    return summary


@MCP_SERVER.tool()
def create_polymarket_order_signing_session(
    preview_id: str,
    user_confirmed: bool = False,
    live_submission_confirmed: bool = False,
    confirmation_message: str | None = None,
    expires_in_minutes: int = 10,
    metadata: dict | None = None,
) -> dict:
    """Create a Polymarket browser-signing session after Clink policy, funding, and confirmation gates."""
    request = CreatePolymarketOrderSigningSessionRequest(
        preview_id=preview_id,
        user_confirmed=user_confirmed,
        live_submission_confirmed=live_submission_confirmed,
        confirmation_message=confirmation_message,
        expires_in_minutes=expires_in_minutes,
        metadata=metadata or {},
    )
    response = _request_json(CONFIG.execution_url, "/execution/polymarket/order-signing-sessions", request.model_dump())
    summary = _public_signing_session_summary(response)
    if summary["status"] == "pending_browser_signature":
        summary["next_action"] = "open_polymarket_order_signing"
    return summary


@MCP_SERVER.tool()
def complete_polymarket_order_signing_session(
    session_id: str,
    signed_order: dict,
    wallet_address: str | None = None,
    order_type: str | None = None,
    metadata: dict | None = None,
) -> dict:
    """Submit a browser-signed Polymarket order and return its public status summary."""
    request = CompletePolymarketOrderSigningSessionRequest(
        signed_order=signed_order,
        wallet_address=wallet_address,
        order_type=order_type,
        metadata=metadata or {},
    )
    response = _request_json(CONFIG.execution_url, f"/execution/polymarket/order-signing-sessions/{session_id}/complete", request.model_dump())
    return _public_signing_session_summary(response)


@MCP_SERVER.tool()
def get_prediction_market_execution(execution_id: str) -> PredictionMarketExecution:
    """Fetch a stored prediction market execution by id."""
    response = _request_json(CONFIG.execution_url, f"/execution/{execution_id}")
    return PredictionMarketExecution(**response)


@MCP_SERVER.tool()
def get_prediction_market_portfolio_snapshot() -> PortfolioSnapshot:
    """Fetch read-only Agent Money Console portfolio, PnL, pending actions, and audit timeline."""
    response = _request_json(
        CONFIG.portfolio_url,
        "/portfolio/snapshot",
    )
    return PortfolioSnapshot(**response)


@MCP_SERVER.tool()
def sync_prediction_market_portfolio() -> dict:
    """Force one portfolio ledger reconciliation run before reading positions or PnL."""
    return _request_json(CONFIG.sync_url, "/sync/run", {})


@MCP_SERVER.tool()
def create_polymarket_bridge_deposit_address(
    user_id: str,
    polymarket_deposit_wallet_address: str | None = None,
    metadata: dict | None = None,
) -> PolymarketBridgeDeposit:
    """Create or fetch a Polymarket bridge deposit address for the configured user deposit wallet."""
    request = CreatePolymarketBridgeDepositRequest(
        user_id=user_id,
        polymarket_deposit_wallet_address=polymarket_deposit_wallet_address,
        metadata=metadata or {},
    )
    response = _request_json(CONFIG.funding_adapter_url, "/polymarket/deposit-address", request.model_dump())
    return PolymarketBridgeDeposit(**response)


@MCP_SERVER.tool()
def create_polymarket_bridge_quote(
    user_id: str,
    from_amount_usdc: str,
    recipient_address: str | None = None,
    metadata: dict | None = None,
) -> PolymarketBridgeQuote:
    """Create a Polymarket bridge quote. Recipient must match the configured Polymarket deposit wallet."""
    request = CreatePolymarketBridgeQuoteRequest(
        user_id=user_id,
        from_amount_usdc=from_amount_usdc,
        recipient_address=recipient_address,
        metadata=metadata or {},
    )
    response = _request_json(CONFIG.funding_adapter_url, "/polymarket/bridge-quote", request.model_dump())
    return PolymarketBridgeQuote(**response)


@MCP_SERVER.tool()
def get_polymarket_bridge_status(address: str) -> PolymarketBridgeStatus:
    """Read Polymarket bridge status for a known bridge deposit address."""
    response = _request_json(CONFIG.funding_adapter_url, f"/polymarket/bridge-status/{address}")
    return PolymarketBridgeStatus(**response)


@MCP_SERVER.tool()
def get_latest_polymarket_bridge_status() -> dict:
    """Read the latest cached Polymarket bridge funding status for dashboard/execution readiness."""
    return _request_json(CONFIG.funding_adapter_url, "/polymarket/latest-bridge-status")


@MCP_SERVER.tool()
def prediction_markets_router_health() -> dict:
    """Check router service health and configured public MCP URL."""
    try:
        with urllib.request.urlopen(f"{CONFIG.router_url}/healthz", timeout=5) as response:
            router = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        router = {"service": "prediction_markets_router_service", "status": "error", "error": f"{type(exc).__name__}: {exc}"}

    try:
        with urllib.request.urlopen(f"{CONFIG.preview_url}/healthz", timeout=5) as response:
            preview = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        preview = {"service": "prediction_markets_preview_service", "status": "error", "error": f"{type(exc).__name__}: {exc}"}

    try:
        with urllib.request.urlopen(f"{CONFIG.execution_url}/healthz", timeout=5) as response:
            execution = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        execution = {"service": "prediction_markets_execution_service", "status": "error", "error": f"{type(exc).__name__}: {exc}"}

    try:
        with urllib.request.urlopen(f"{CONFIG.decision_url}/healthz", timeout=5) as response:
            context = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        context = {"service": "prediction_markets_context_service", "status": "error", "error": f"{type(exc).__name__}: {exc}"}

    try:
        with urllib.request.urlopen(f"{CONFIG.sync_url}/healthz", timeout=5) as response:
            sync = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        sync = {"service": "prediction_markets_sync_service", "status": "error", "error": f"{type(exc).__name__}: {exc}"}

    try:
        with urllib.request.urlopen(f"{CONFIG.portfolio_url}/healthz", timeout=5) as response:
            portfolio = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        portfolio = {"service": "prediction_markets_portfolio_service", "status": "error", "error": f"{type(exc).__name__}: {exc}"}

    try:
        with urllib.request.urlopen(f"{CONFIG.funding_adapter_url}/healthz", timeout=5) as response:
            funding_adapter = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        funding_adapter = {"service": "prediction_markets_funding_adapter_service", "status": "error", "error": f"{type(exc).__name__}: {exc}"}

    try:
        with urllib.request.urlopen(f"{CONFIG.deposit_wallet_url}/healthz", timeout=5) as response:
            deposit_wallet = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        deposit_wallet = {"service": "prediction_markets_deposit_wallet_service", "status": "error", "error": f"{type(exc).__name__}: {exc}"}

    try:
        with urllib.request.urlopen(f"{CONFIG.account_binding_url}/healthz", timeout=5) as response:
            account_binding = json.loads(response.read().decode("utf-8"))
    except Exception as exc:
        account_binding = {"service": "prediction_markets_account_binding_service", "status": "error", "error": f"{type(exc).__name__}: {exc}"}

    return {
        "service": "prediction_markets_mcp_server",
        "status": "ok",
        "router": router,
        "preview": preview,
        "execution": execution,
        "context": context,
        "sync": sync,
        "portfolio": portfolio,
        "funding_adapter": funding_adapter,
        "deposit_wallet": deposit_wallet,
        "account_binding": account_binding,
        "mcp_url": CONFIG.mcp_url,
    }


if __name__ == "__main__":
    MCP_SERVER.run(transport="streamable-http")
