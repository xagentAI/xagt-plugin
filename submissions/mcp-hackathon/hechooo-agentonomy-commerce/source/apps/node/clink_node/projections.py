from __future__ import annotations

from typing import Any, Protocol

from .adapters.http import DownstreamError


def build_balance_summary(
    core: Any, prediction_markets: Any, user_id: str, *, strict_owner: bool = False,
) -> dict[str, Any]:
    """Keep money and spending permission separate across all Node entry points."""
    try:
        wallet_funds = core.wallet_balances(user_id)
        if strict_owner:
            _require_projection_owner(wallet_funds, user_id)
    except DownstreamError:
        wallet_funds = {"status": "unavailable"}
    try:
        readiness = core.account_readiness(user_id)
        if strict_owner:
            _require_projection_owner(readiness, user_id)
        mandate = readiness.get("active_spending_mandate")
        spending_authorization = {
            "status": "ready" if isinstance(mandate, dict) else "not_configured",
            "limits_usdc": mandate.get("limits_usdc") if isinstance(mandate, dict) else None,
            "remaining_usdc": mandate.get("remaining_usdc") if isinstance(mandate, dict) else None,
            "meaning": "authorization_budget_not_wallet_balance",
        }
    except DownstreamError:
        spending_authorization = {
            "status": "unavailable", "limits_usdc": None, "remaining_usdc": None,
            "meaning": "authorization_budget_not_wallet_balance",
        }
    try:
        polymarket_funds = prediction_markets.account_balance(user_id)
        if strict_owner:
            _require_projection_owner(polymarket_funds, user_id)
    except DownstreamError:
        polymarket_funds = {"status": "unavailable"}
    sections = (wallet_funds, spending_authorization, polymarket_funds)
    return {
        "status": "ready" if all(item.get("status") == "ready" for item in sections) else "partial",
        "user_id": user_id, "wallet_funds": wallet_funds,
        "agent_spending_authorization": spending_authorization,
        "polymarket_funds": polymarket_funds,
    }


class AccountCore(Protocol):
    def account_readiness(self, user_id: str) -> dict[str, Any]: ...

    def audit_summary(
        self,
        user_id: str,
        limit: int,
    ) -> list[dict[str, Any]]: ...


class PredictionAccount(Protocol):
    def account_status(self, user_id: str) -> dict[str, Any]: ...


def build_account_summary(
    core: AccountCore,
    prediction_markets: PredictionAccount,
    user_id: str,
    *,
    strict_owner: bool = False,
) -> dict[str, Any]:
    readiness = core.account_readiness(user_id)
    if strict_owner:
        _require_projection_owner(readiness, user_id)
    core_ready = bool(readiness.get("ready"))
    mandate = readiness.get("active_spending_mandate") or {}
    scopes = {
        str(item)
        for item in mandate.get("product_scopes", [])
        if item
    }

    marketplace_scope = "marketplace" in scopes
    marketplace_ready = core_ready and marketplace_scope
    marketplace_next_action = _product_next_action(
        core_ready=core_ready,
        scope_ready=marketplace_scope,
        ready=marketplace_ready,
    )

    binding_error: DownstreamError | None = None
    try:
        raw_binding = prediction_markets.account_status(user_id)
        if strict_owner:
            _require_projection_owner(raw_binding, user_id)
    except DownstreamError as exc:
        binding_error = exc
        raw_binding = {
            "status": "unavailable",
            "next_action": "retry_prediction_markets_status",
        }
    binding = _safe_polymarket_binding(raw_binding)

    core_wallet = str(readiness.get("wallet_address") or "").lower()
    binding_wallet = str(binding.get("wallet_address") or "").lower()
    wallet_matches_core = bool(
        core_wallet
        and binding_wallet
        and core_wallet == binding_wallet
    )
    prediction_scope = "prediction_markets" in scopes
    binding_ready = (
        binding.get("status") == "active"
        and bool(binding.get("has_api_credentials"))
        and wallet_matches_core
    )
    prediction_ready = core_ready and prediction_scope and binding_ready
    prediction_next_action = _prediction_next_action(
        core_ready=core_ready,
        scope_ready=prediction_scope,
        binding=binding,
        wallet_matches_core=wallet_matches_core,
        ready=prediction_ready,
    )

    prediction_product: dict[str, Any] = {
        "ready": prediction_ready,
        "wallet_matches_core": wallet_matches_core,
        "account": binding,
        "next_action": prediction_next_action,
    }
    if binding_error is not None and not strict_owner:
        prediction_product["downstream"] = binding_error.as_dict()

    all_ready = (
        core_ready
        and marketplace_ready
        and prediction_ready
    )
    return {
        "user_id": user_id,
        "status": "ready" if all_ready else "attention_required",
        "core": readiness,
        "products": {
            "marketplace": {
                "ready": marketplace_ready,
                "next_action": marketplace_next_action,
            },
            "prediction_markets": prediction_product,
        },
        "next_action": (
            "agent_can_act_within_mandate"
            if all_ready
            else _first_required_action(
                core_ready,
                marketplace_ready,
                prediction_next_action,
            )
        ),
    }


def _require_projection_owner(payload: dict, user_id: str) -> None:
    if not isinstance(payload, dict) or payload.get("user_id") != user_id:
        raise DownstreamError("account", 404, "owned account not found")


def build_activity_summary(
    core: AccountCore,
    user_id: str,
    limit: int,
) -> dict[str, Any]:
    events = core.audit_summary(user_id, limit)
    items = [
        {
            "event": str(event.get("event") or "Account activity"),
            "summary": str(event.get("summary") or "Recorded by Clink"),
            "at": event.get("at"),
            "module": "core",
            "amount": None,
            "status": "recorded",
        }
        for event in events
    ]
    return {
        "user_id": user_id,
        "count": len(items),
        "items": items,
    }


def _safe_polymarket_binding(binding: dict[str, Any]) -> dict[str, Any]:
    allowed = (
        "binding_id",
        "status",
        "wallet_address",
        "funder_address",
        "polymarket_deposit_wallet",
        "account_mode",
        "polymarket_signature_type",
        "has_api_credentials",
        "reason",
        "next_action",
    )
    return {
        key: binding.get(key)
        for key in allowed
        if key in binding
    }


def _product_next_action(
    *,
    core_ready: bool,
    scope_ready: bool,
    ready: bool,
) -> str:
    if ready:
        return "marketplace_ready"
    if not core_ready:
        return "complete_core_account_setup"
    if not scope_ready:
        return "extend_spending_mandate_scope"
    return "inspect_marketplace_readiness"


def _prediction_next_action(
    *,
    core_ready: bool,
    scope_ready: bool,
    binding: dict[str, Any],
    wallet_matches_core: bool,
    ready: bool,
) -> str:
    if ready:
        return "prediction_markets_ready"
    if not core_ready:
        return "complete_core_account_setup"
    if not scope_ready:
        return "extend_spending_mandate_scope"
    if binding.get("status") != "active":
        return str(
            binding.get("next_action")
            or "create_polymarket_account_binding"
        )
    if not wallet_matches_core:
        return "rebind_polymarket_with_core_wallet"
    if not binding.get("has_api_credentials"):
        return "refresh_polymarket_clob_authorization"
    return "inspect_prediction_markets_readiness"


def _first_required_action(
    core_ready: bool,
    marketplace_ready: bool,
    prediction_next_action: str,
) -> str:
    if not core_ready:
        return "complete_core_account_setup"
    if not marketplace_ready:
        return "extend_spending_mandate_scope"
    return prediction_next_action
