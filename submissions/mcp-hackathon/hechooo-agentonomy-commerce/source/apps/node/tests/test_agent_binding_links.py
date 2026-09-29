import json
from datetime import UTC, datetime, timedelta

import httpx
import pytest

from apps.node.clink_node.adapters.http import DownstreamError
from apps.node.clink_node.adapters.prediction_markets import PredictionMarketsHttpAdapter
from apps.node.tests.test_polymarket_live_operations import _funding_view


OWNER = "0x" + "11" * 20
DEPOSIT = "0x" + "22" * 20


def binding_fixture():
    return {"session_id": "pm_bind_sess_abcdef123456", "user_id": "user_a", "agent_id": "hermes",
            "wallet_address": OWNER, "polymarket_deposit_wallet": DEPOSIT, "status": "pending",
            "expires_at": (datetime.now(UTC) + timedelta(minutes=15)).isoformat(),
            "signing_url": "http://127.0.0.1:8047/polymarket/binding-console/pm_bind_sess_abcdef123456?access_token=" + "x" * 43}


def adapter_for(response):
    def request(req):
        if req.method == "GET":
            assert req.url.params["user_id"] == "user_a"
            return httpx.Response(200, json={"user_id": "user_a", "owner_wallet": OWNER,
                "deposit_wallet": DEPOSIT, "ready": True, "can_use_x402": True})
        payload = json.loads(req.content)
        assert payload["user_id"] == "user_a" and payload["agent_id"] == "hermes"
        assert "return_url" not in payload and "confirmed" not in payload
        return httpx.Response(200, json=response)
    return PredictionMarketsHttpAdapter(base_url="http://127.0.0.1:8040",
        account_binding_url="http://127.0.0.1:8047", public_base_url="https://agents.example",
        internal_token="test-token", transport=httpx.MockTransport(request))


def test_binding_link_is_for_exact_wallet_user_and_returned_session():
    adapter = adapter_for(binding_fixture())
    result = adapter.create_agent_binding_session(user_id="user_a", wallet_address=OWNER)
    assert result["url"].startswith("https://agents.example/polymarket/binding-console/pm_bind_sess_abcdef123456?")
    assert result["kind"] == "polymarket" and result["expires_at"]


@pytest.mark.parametrize("field,value", [
    ("user_id", "user_b"), ("agent_id", "agent_b"), ("wallet_address", DEPOSIT),
    ("polymarket_deposit_wallet", OWNER), ("session_id", "another_session"),
    ("expires_at", None), ("expires_at", "2020-01-01T00:00:00Z"), ("expires_at", "invalid"),
    ("status", "revoked"),
])
def test_binding_response_identity_session_expiry_mismatch_fails_closed(field, value):
    response = {**binding_fixture(), field: value}
    with pytest.raises(DownstreamError):
        adapter_for(response).create_agent_binding_session(user_id="user_a", wallet_address=OWNER)


def test_binding_response_missing_owner_fails_closed():
    response = binding_fixture()
    del response["user_id"]
    with pytest.raises(DownstreamError):
        adapter_for(response).create_agent_binding_session(user_id="user_a", wallet_address=OWNER)


def test_funding_payment_view_is_owned_and_read_only():
    payload = _funding_view(user_id="user_a", operation_id="pm_funding_a", status="submitted")
    payload["reservation_id"] = "reserve_a"
    def request(req):
        assert req.method == "GET"
        assert req.url.path == "/polymarket/funding-history/pm_funding_a"
        assert req.url.params["user_id"] == "user_a"
        return httpx.Response(200, json=payload)
    adapter = PredictionMarketsHttpAdapter(base_url="http://127.0.0.1:8040",
        internal_token="test-token", transport=httpx.MockTransport(request))
    result = adapter.get_funding_payment(user_id="user_a", operation_id="pm_funding_a")
    assert result["reservation_id"] == "reserve_a"
    assert set(result) == {"operation_id", "status", "reservation_id", "failure_reason_code", "next_action"}
    payload["user_id"] = "user_b"
    with pytest.raises(DownstreamError):
        adapter.get_funding_payment(user_id="user_a", operation_id="pm_funding_a")
