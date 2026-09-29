import httpx
import pytest

from apps.node.clink_node.adapters.http import DownstreamError
from apps.node.clink_node.adapters.core import CoreHttpAdapter
from apps.node.clink_node.adapters.marketplace import MarketplaceHttpAdapter
from apps.node.clink_node.adapters.prediction_markets import PredictionMarketsHttpAdapter


@pytest.mark.parametrize("method,field,endpoint", [
    ("get_purchase_preview", "preview_id", "/purchases/previews/preview_a"),
    ("get_purchase", "purchase_id", "/purchases/purchase_a"),
    ("get_order_preview", "preview_id", "/order-previews/preview_a"),
    ("get_execution", "execution_id", "/execution/execution_a"),
])
def test_business_object_lookup_checks_owner_and_id_before_return(method, field, endpoint):
    object_id = endpoint.rsplit("/", 1)[1]
    payload = {field: object_id, "user_id": "c_alice", "agent_id": "hermes"}
    calls = []

    def request(req):
        calls.append(req)
        assert req.headers["authorization"] == "Bearer internal"
        assert req.method == "GET"
        assert req.url.path == endpoint
        return httpx.Response(200, json=payload)

    cls = MarketplaceHttpAdapter if method.startswith("get_purchase") else PredictionMarketsHttpAdapter
    adapter = cls(base_url="http://127.0.0.1:9999", internal_token="internal", transport=httpx.MockTransport(request))
    getter = getattr(adapter, method)
    assert getter(user_id="c_alice", **{field: object_id})[field] == object_id
    for changed in ({"user_id": "c_bob"}, {"user_id": None}, {field: "foreign"}):
        original = dict(payload)
        payload.update(changed)
        with pytest.raises(DownstreamError) as exc:
            getter(user_id="c_alice", **{field: object_id})
        assert "c_bob" not in str(exc.value)
        payload.clear()
        payload.update(original)
    if cls is PredictionMarketsHttpAdapter:
        payload["agent_id"] = None
        with pytest.raises(DownstreamError):
            getter(user_id="c_alice", **{field: object_id})
    assert all(req.method == "GET" for req in calls)


@pytest.mark.parametrize("unsafe_id", ["../other", "a/b", "a?user_id=b", "a#b", "", "a\nb"])
def test_object_identifiers_cannot_select_a_different_route(unsafe_id):
    def request(_):
        pytest.fail("invalid identifiers must be rejected before HTTP")
    adapter = MarketplaceHttpAdapter(base_url="http://127.0.0.1:9999", internal_token="internal", transport=httpx.MockTransport(request))
    with pytest.raises((ValueError, DownstreamError)):
        adapter.get_purchase_preview(user_id="c_alice", preview_id=unsafe_id)


def test_core_receipt_lookup_joins_owned_purchase_and_reservation():
    payload = {"reservation_id": "reserve_a", "user_id": "c_alice", "purchase_id": "purchase_a",
               "state": "finalized", "receipt_id": "receipt_a", "tx_hash": "0x" + "1" * 64,
               "payment_authorization": {"not_for_clients": True}}
    core = CoreHttpAdapter(**{k + "_url": "http://127.0.0.1:8018" for k in ("account", "action", "policy", "audit", "funding")},
                           internal_token="internal", transport=httpx.MockTransport(lambda _: httpx.Response(200, json=payload)))
    result = core.get_payment_reservation(user_id="c_alice", reservation_id="reserve_a", purchase_id="purchase_a")
    assert result["receipt_id"] == "receipt_a" and "payment_authorization" not in result
    with pytest.raises(DownstreamError):
        core.get_payment_reservation(user_id="c_alice", reservation_id="reserve_a", purchase_id="other")
    with pytest.raises(DownstreamError):
        core.get_payment_reservation(user_id="c_bob", reservation_id="reserve_a", purchase_id="purchase_a")
