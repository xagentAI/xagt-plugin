"""Read-only C projections. Core is the authority for payment settlement."""

from typing import Any

from .adapters.http import DownstreamError
from .adapters.ownership import object_id
from .projections import build_account_summary


def owned_account(context: Any, user_id: str) -> dict:
    summary = build_account_summary(context.core, context.prediction_markets, user_id, strict_owner=True)
    try:
        hosted = context.core.hosted_wallet_readiness(user_id)
        if not isinstance(hosted, dict) or hosted.get("user_id") != user_id:
            raise DownstreamError("core", 404, "owned account not found")
        hosted = {key: hosted.get(key) for key in ("ready", "credential_routing", "reason_code")}
    except DownstreamError:
        hosted = {"ready": False, "reason_code": "HOSTED_STATUS_UNAVAILABLE"}
    summary["hosted_execution"] = hosted
    if hosted.get("ready") is not True:
        summary["status"] = "attention_required"
        for product in summary["products"].values():
            if product.get("ready") is True:
                product["next_action"] = "contact_service_operator"
            product["ready"] = False
        if summary["core"].get("ready") is True:
            summary["next_action"] = "contact_service_operator"
    return summary


def owned_payment(context: Any, user_id: str, kind: str, operation_id: str) -> dict:
    operation_id = object_id(operation_id)
    if kind == "marketplace":
        payment = context.marketplace.get_purchase(user_id=user_id, purchase_id=operation_id)
        state = payment.get("state", "unknown")
        delivered = state == "delivered"
    elif kind == "polymarket_funding":
        payment = context.prediction_markets.get_funding_payment(user_id=user_id, operation_id=operation_id)
        state = payment.get("status", "unknown")
        delivered = state == "finalized"
    else:
        raise ValueError("unsupported payment kind")

    result = {
        "kind": kind, "operation_id": operation_id, "status": state,
        "core_status": "not_started", "receipt_id": None, "tx_hash": None,
        "settled": False, "delivery_complete": False,
        "failure_reason_code": payment.get("failure_reason_code") or payment.get("reason_code"),
        "next_action": payment.get("next_action") or "read_payment_status",
    }
    reservation_id = payment.get("reservation_id")
    if not reservation_id:
        return result
    try:
        core = context.core.get_payment_reservation(
            user_id=user_id, reservation_id=reservation_id, purchase_id=operation_id,
        )
    except DownstreamError as exc:
        if exc.status_code in {401, 403, 404}:
            raise
        result.update(core_status="unknown", failure_reason_code="SETTLEMENT_VERIFICATION_UNAVAILABLE")
        return result
    settled = (
        core.get("state") in {"settled", "finalized"}
        and bool(core.get("receipt_id")) and bool(core.get("tx_hash"))
    )
    result.update(
        core_status=core.get("state", "unknown"),
        receipt_id=core.get("receipt_id"), tx_hash=core.get("tx_hash"),
        settled=settled, delivery_complete=settled and delivered,
    )
    return result
