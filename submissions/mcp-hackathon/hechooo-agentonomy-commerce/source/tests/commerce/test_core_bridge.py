"""Black-box tests for the process-isolated real Core composition."""

from decimal import Decimal
from pathlib import Path

import pytest

from examples.commerce.core_bridge import CoreBridge


USER_ID = "commerce-demo-user"
AGENT_ID = "hermes"
MERCHANT_ID = "commerce_analytics"
VENUE = "clink_marketplace"
TRUST_TIER = "clink_verified"


def _authorization(core: CoreBridge, amount: str = "0.30") -> dict:
    snapshot = core.snapshot()
    readiness = core.funding_readiness()
    return core.resolve_authorization(
        {
            "user_id": USER_ID,
            "agent_id": AGENT_ID,
            "authorization_rail": "native_allowance",
            "product": "marketplace",
            "venue": VENUE,
            "merchant": MERCHANT_ID,
            "merchant_trust_tier": TRUST_TIER,
            "network": snapshot["network"],
            "token_address": snapshot["token"],
            "asset": snapshot["token"],
            "spender_address": readiness["spender_address"],
            "amount_usdc": amount,
            "destination": snapshot["pay_to"],
            "resource": snapshot["resource"],
        }
    )


def _scope(core: CoreBridge, purchase_id: str, amount: str, authorization: dict) -> dict:
    snapshot = core.snapshot()
    atomic = str((Decimal(amount) * Decimal("1000000")).quantize(Decimal("1")))
    return {
        "purchase_id": purchase_id,
        "quote_hash": "0x" + purchase_id.encode().hex().ljust(64, "0"),
        "network": snapshot["network"],
        "asset": snapshot["token"],
        "amount_atomic": atomic,
        "destination": snapshot["pay_to"],
        "resource": snapshot["resource"],
        "authorization_rail": "native_allowance",
        "product": "marketplace",
        "merchant_trust_tier": TRUST_TIER,
        "wallet_identity_id": authorization["wallet_identity_id"],
        "spending_grant_id": authorization["spending_grant_id"],
        "asset_allowance_id": authorization["asset_allowance_id"],
    }


def _prepare_purchase(
    core: CoreBridge,
    *,
    purchase_id: str,
    amount: str,
    authorization: dict,
) -> tuple[dict, dict]:
    scope = _scope(core, purchase_id, amount, authorization)
    action = core.create_action(
        {
            "user_id": USER_ID,
            "agent_id": AGENT_ID,
            "action_type": "marketplace_purchase",
            "amount_usdc": amount,
            "merchant_id": MERCHANT_ID,
            "metadata": scope,
        }
    )
    policy = core.evaluate_policy(
        {
            "action_id": action["action_id"],
            "user_id": USER_ID,
            "agent_id": AGENT_ID,
            "action_type": "marketplace_purchase",
            "amount_usdc": amount,
            "merchant_id": MERCHANT_ID,
            "target_address": scope["destination"],
            "chain": scope["network"],
            "user_confirmed": True,
            "metadata": scope,
        }
    )
    assert policy["approved"] is True
    core.update_action(
        action["action_id"],
        {
            "state": "policy_approved",
            "policy_decision_id": policy["policy_decision_id"],
        },
    )
    core.audit(
        {
            "event_type": "marketplace_purchase_policy_evaluated",
            "source_service": "clink_marketplace",
            "action_id": action["action_id"],
            "user_id": USER_ID,
            "agent_id": AGENT_ID,
            "policy_decision_id": policy["policy_decision_id"],
            "payload": {
                **scope,
                "merchant_id": MERCHANT_ID,
                "venue": VENUE,
            },
        }
    )
    return scope, {"action": action, "policy": policy}


def _reserve_payload(core: CoreBridge, scope: dict, records: dict) -> dict:
    snapshot = core.snapshot()
    return {
        "purchase_id": scope["purchase_id"],
        "idempotency_key": scope["purchase_id"],
        "spending_authorization_id": None,
        "authorization_rail": scope["authorization_rail"],
        "wallet_identity_id": scope["wallet_identity_id"],
        "spending_grant_id": scope["spending_grant_id"],
        "asset_allowance_id": scope["asset_allowance_id"],
        "product": scope["product"],
        "action_id": records["action"]["action_id"],
        "policy_decision_id": records["policy"]["policy_decision_id"],
        "merchant_id": MERCHANT_ID,
        "merchant_trust_tier": TRUST_TIER,
        "quote_hash": scope["quote_hash"],
        "amount_usdc": str(Decimal(scope["amount_atomic"]) / Decimal("1000000")),
        "amount_atomic": scope["amount_atomic"],
        "network": scope["network"],
        "asset": scope["asset"],
        "destination": scope["destination"],
        "resource": scope["resource"],
        "venue": VENUE,
        "_snapshot_token": snapshot["token"],
    }


def _execute_purchase(core: CoreBridge, purchase_id: str, amount: str) -> dict:
    authorization = _authorization(core, amount)
    scope, records = _prepare_purchase(
        core,
        purchase_id=purchase_id,
        amount=amount,
        authorization=authorization,
    )
    payload = _reserve_payload(core, scope, records)
    payload.pop("_snapshot_token")
    reservation = core.reserve(payload)
    return core.settle(
        reservation["reservation_id"],
        {
            "payment_authorization": {
                "scheme": "exact",
                "network": scope["network"],
                "asset": "USDC",
                "amount_atomic": scope["amount_atomic"],
                "pay_to": scope["destination"],
            }
        },
    )


def test_signed_authorization_is_ready_inside_a_simulated_core(tmp_path: Path):
    with CoreBridge(tmp_path) as core:
        health = core.health()
        assert health["status"] == "ready"
        assert health["simulation"] is True
        authorization = _authorization(core)
        assert authorization["ready"] is True
        assert authorization["authorization_rail"] == "native_allowance"
        assert authorization["wallet_identity_id"]
        assert authorization["spending_grant_id"]
        assert authorization["asset_allowance_id"]

        snapshot = core.snapshot()
        assert snapshot["user_id"] == USER_ID
        assert Decimal(snapshot["budget_usdc"]) == Decimal("1.00")
        assert snapshot["receipt_signing_key"]


def test_real_core_reserves_and_settles_three_tenths_with_verified_receipt(
    tmp_path: Path,
):
    with CoreBridge(tmp_path) as core:
        settlement = _execute_purchase(core, "purchase_030", "0.30")
        assert settlement["state"] == "settled"
        assert settlement["receipt_id"]
        assert settlement["tx_hash"]
        assert settlement["settlement_receipt_verified"] is True

        snapshot = core.snapshot()
        assert Decimal(snapshot["used_amount_usdc"]) == Decimal("0.30")
        assert Decimal(snapshot["reserved_amount_usdc"]) == Decimal("0")
        assert snapshot["settlement_submissions"] == 1


def test_one_usdc_grant_rejects_eight_tenths_after_three_tenths_spend(
    tmp_path: Path,
):
    with CoreBridge(tmp_path) as core:
        _execute_purchase(core, "purchase_030", "0.30")
        with pytest.raises(RuntimeError, match="(?i)(budget|limit|spending)"):
            _execute_purchase(core, "purchase_080", "0.80")

        snapshot = core.snapshot()
        assert Decimal(snapshot["used_amount_usdc"]) == Decimal("0.30")
        assert Decimal(snapshot["reserved_amount_usdc"]) == Decimal("0")
        assert snapshot["settlement_submissions"] == 1


def test_revoke_makes_the_signed_grant_unavailable(tmp_path: Path):
    with CoreBridge(tmp_path) as core:
        _authorization(core)
        revoked = core.revoke()
        assert revoked["status"] == "revoked"
        authorization = _authorization(core)
        assert authorization["ready"] is False
        assert authorization["reason_code"] in {
            "SPENDING_GRANT_REQUIRED",
            "WALLET_IDENTITY_REQUIRED",
        }
