from types import SimpleNamespace

import pytest

from apps.node.clink_node.adapters.http import DownstreamError
from apps.node.clink_node.agent_access_views import owned_payment


class Core:
    def __init__(self, state="payment_submitted"):
        self.state = state

    def get_payment_reservation(self, *, user_id, reservation_id, purchase_id):
        assert (user_id, reservation_id, purchase_id) == ("c_alice", "reserve_a", "operation_a")
        return {"state": self.state, "receipt_id": "receipt_a" if self.state == "finalized" else None,
                "tx_hash": "0x" + "1" * 64}


class Market:
    def get_purchase(self, *, user_id, purchase_id):
        if user_id != "c_alice":
            raise DownstreamError("marketplace", 404, "owned object not found")
        return {"purchase_id": purchase_id, "reservation_id": "reserve_a", "state": "payment_submitted"}


def test_submitted_never_means_settled_and_finalized_uses_core_receipt():
    context = SimpleNamespace(core=Core(), marketplace=Market())
    result = owned_payment(context, "c_alice", "marketplace", "operation_a")
    assert result["settled"] is False
    assert result["tx_hash"] == "0x" + "1" * 64
    context.core.state = "finalized"
    result = owned_payment(context, "c_alice", "marketplace", "operation_a")
    assert result["settled"] is True
    assert result["receipt_id"] == "receipt_a"
    assert result["delivery_complete"] is False


def test_foreign_payment_rejected_before_core_read():
    context = SimpleNamespace(core=None, marketplace=Market())
    with pytest.raises(DownstreamError):
        owned_payment(context, "c_bob", "marketplace", "operation_a")


def test_unavailable_core_returns_unknown_not_settled():
    class Unavailable:
        def get_payment_reservation(self, **_):
            raise DownstreamError("core", 503, "private details")
    result = owned_payment(SimpleNamespace(core=Unavailable(), marketplace=Market()), "c_alice", "marketplace", "operation_a")
    assert result["settled"] is False
    assert result["core_status"] == "unknown"
    assert result["failure_reason_code"] == "SETTLEMENT_VERIFICATION_UNAVAILABLE"
    assert "private details" not in str(result)
