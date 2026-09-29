from types import SimpleNamespace

import pytest

from apps.node.clink_node.adapters.http import DownstreamError
from apps.node.clink_node.agent_access_views import owned_account
from apps.node.clink_node.projections import build_balance_summary
from apps.node.tests.test_mcp_gateway import NativeCore, NativePrediction


class ScopedCore(NativeCore):
    def hosted_wallet_readiness(self, user_id):
        return {"user_id": user_id, "credential_routing": "per_wallet", "ready": False,
                "reason_code": "HOSTED_ENROLLMENT_REQUIRED"}


def test_account_reports_operator_enrollment_separately_from_user_wallet_setup():
    context = SimpleNamespace(core=ScopedCore(), prediction_markets=NativePrediction("prediction-markets"))
    result = owned_account(context, "user_1")
    assert result["core"]["ready"] is True
    assert result["hosted_execution"]["ready"] is False
    assert result["status"] == "attention_required"
    assert result["next_action"] == "contact_service_operator"
    assert result["products"]["marketplace"]["ready"] is False
    assert result["products"]["marketplace"]["next_action"] == "contact_service_operator"


def test_foreign_or_missing_core_owner_is_not_exposed():
    class Foreign(ScopedCore):
        def account_readiness(self, user_id):
            return super().account_readiness("other_user")
    context = SimpleNamespace(core=Foreign(), prediction_markets=NativePrediction("prediction-markets"))
    with pytest.raises(DownstreamError):
        owned_account(context, "user_1")


def test_foreign_binding_and_wallet_balances_are_hidden_not_assumed_zero():
    class ForeignCore(ScopedCore):
        def wallet_balances(self, user_id):
            return super().wallet_balances("other_user")
    class ForeignPrediction(NativePrediction):
        def account_status(self, user_id):
            return super().account_status("other_user")
    context = SimpleNamespace(core=ForeignCore(), prediction_markets=ForeignPrediction("prediction-markets"))
    result = owned_account(context, "user_1")
    assert result["products"]["prediction_markets"]["account"] == {
        "status": "unavailable", "next_action": "retry_prediction_markets_status",
    }
    assert "other_user" not in str(result)
    balances = build_balance_summary(context.core, context.prediction_markets, "user_1", strict_owner=True)
    assert balances["wallet_funds"] == {"status": "unavailable"}
    assert "amount_usdc" not in balances["wallet_funds"]


def test_hosted_readiness_failure_does_not_echo_internal_service_error():
    class Unavailable(ScopedCore):
        def hosted_wallet_readiness(self, user_id):
            raise DownstreamError("core", 503, "private-credential-token")
    result = owned_account(SimpleNamespace(core=Unavailable(), prediction_markets=NativePrediction("prediction-markets")), "user_1")
    assert result["hosted_execution"]["ready"] is False
    assert "private-credential-token" not in str(result)
