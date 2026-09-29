import json
import sys
import tempfile
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from platforms.kalshi.executor import KalshiExecutor
from shared.config import AppConfig
from shared.schemas import PredictionMarketOrderPreview, UnifiedMarket


def _generate_test_key_pem() -> bytes:
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )


def _write_test_key() -> str:
    pem = _generate_test_key_pem()
    handle = tempfile.NamedTemporaryFile("wb", delete=False)
    handle.write(pem)
    handle.close()
    return handle.name


def _config(private_key_path: str | None = None) -> AppConfig:
    config = AppConfig.from_env()
    config.kalshi_api_base_url = "https://external-api.demo.kalshi.co/trade-api/v2"
    config.kalshi_api_key_id = "test-key-id"
    config.kalshi_private_key_path = private_key_path
    config.kalshi_private_key_pem = None
    config.kalshi_order_time_in_force = "good_till_canceled"
    config.kalshi_self_trade_prevention_type = "taker_at_cross"
    config.kalshi_post_only = False
    config.kalshi_cancel_order_on_pause = False
    config.kalshi_reduce_only = False
    config.kalshi_subaccount = 0
    config.kalshi_exchange_index = 0
    return config


def _preview(outcome: str = "Yes", side: str = "buy", price: float = 0.56) -> PredictionMarketOrderPreview:
    market = UnifiedMarket(
        platform="kalshi",
        market_id="HIGHNY-24JAN01-T60",
        event_id="HIGHNY-24JAN01",
        title="NYC high temperature above 60 on Jan 1?",
        yes_price=0.56,
        no_price=0.44,
        tradable=True,
        execution_ready=True,
        raw={"ticker": "HIGHNY-24JAN01-T60", "event_ticker": "HIGHNY-24JAN01"},
    )
    return PredictionMarketOrderPreview(
        preview_id="pm_preview_kalshi_test",
        user_id="demo-user",
        agent_id="hermes_agent",
        platform="kalshi",
        market_id=market.market_id,
        title=market.title,
        outcome=outcome,
        side=side,
        amount_usd="5.6",
        limit_price=price,
        estimated_contracts=10,
        max_slippage_bps=100,
        max_slippage_usd="0.056",
        worst_case_price=price,
        state="confirmation_required",
        next_action="request_user_confirmation",
        requires_user_confirmation=True,
        live_mode=True,
        core_action_id="act_kalshi",
        core_policy_decision_id="policy_kalshi",
        core_audit_event_ids=["audit_kalshi"],
        market=market,
        created_at="2026-07-02T00:00:00Z",
        expires_at="2099-01-01T00:00:00Z",
    )


def main() -> None:
    missing = KalshiExecutor(config=_config()).readiness()
    assert missing.ready is False
    assert "KALSHI_PRIVATE_KEY_PATH or KALSHI_PRIVATE_KEY_PEM" in missing.missing

    calls: list[dict] = []

    def fake_requester(method: str, path: str, headers: dict, body: dict) -> dict:
        assert method == "POST"
        assert path == "/portfolio/events/orders"
        assert headers["KALSHI-ACCESS-KEY"] == "test-key-id"
        assert headers["KALSHI-ACCESS-TIMESTAMP"].isdigit()
        assert headers["KALSHI-ACCESS-SIGNATURE"]
        assert body["ticker"] == "HIGHNY-24JAN01-T60"
        assert body["time_in_force"] == "good_till_canceled"
        assert body["self_trade_prevention_type"] == "taker_at_cross"
        assert body["client_order_id"].startswith("clink-pm_preview_kalshi_test")
        calls.append(body)
        return {
            "order_id": "kalshi_order_123",
            "client_order_id": body["client_order_id"],
            "fill_count": "0.00",
            "remaining_count": body["count"],
            "ts_ms": 1715793600123,
        }

    executor = KalshiExecutor(config=_config(_write_test_key()), requester=fake_requester)
    readiness = executor.readiness()
    assert readiness.ready is True
    assert readiness.status == "ready"
    assert readiness.metadata["KALSHI_API_BASE_URL"] == "https://external-api.demo.kalshi.co/trade-api/v2"

    pem_config = _config()
    pem_config.kalshi_private_key_path = None
    pem_config.kalshi_private_key_pem = _generate_test_key_pem().decode("utf-8").replace("\n", "\\n")
    assert KalshiExecutor(config=pem_config, requester=fake_requester).readiness().ready is True

    yes_buy = executor.submit_order(_preview(outcome="Yes", side="buy", price=0.56))
    assert yes_buy.submitted is True
    assert yes_buy.order_id == "kalshi_order_123"
    assert calls[-1]["side"] == "bid"
    assert calls[-1]["price"] == "0.5600"
    assert calls[-1]["count"] == "10.00"

    no_buy = executor.submit_order(_preview(outcome="No", side="buy", price=0.30))
    assert no_buy.submitted is True
    assert calls[-1]["side"] == "ask"
    assert calls[-1]["price"] == "0.7000"

    print(json.dumps({"status": "ok", "submitted_order_id": yes_buy.order_id, "checked_bodies": len(calls)}, indent=2))


if __name__ == "__main__":
    main()
