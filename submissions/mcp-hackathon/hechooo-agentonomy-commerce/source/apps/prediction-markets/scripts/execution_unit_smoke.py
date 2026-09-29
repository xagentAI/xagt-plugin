import json
import sys
from dataclasses import dataclass
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from platforms.base import ExecutionAdapter, PlatformExecutionResult
from platforms.polymarket.executor import PolymarketExecutor
from services.execution_service.service import ExecutionService
from shared.config import AppConfig
from shared.schemas import ExecutePredictionMarketOrderRequest, PredictionMarketOrderPreview, UnifiedMarket


class FakeOrderType:
    FAK = "FAK"
    GTC = "GTC"


@dataclass
class FakeMarketOrderArgs:
    token_id: str
    amount: float
    side: str
    price: float
    order_type: str


@dataclass
class FakeOrderArgs:
    price: float
    size: float
    side: str
    token_id: str


class FakePreviewStore:
    def __init__(self, preview: PredictionMarketOrderPreview | None) -> None:
        self.preview = preview

    def get_order_preview(self, preview_id: str) -> PredictionMarketOrderPreview | None:
        return self.preview if self.preview and self.preview.preview_id == preview_id else None


class FakePolymarketExecutor(ExecutionAdapter):
    platform = "polymarket"

    def readiness(self) -> PlatformExecutionResult:
        return PlatformExecutionResult(platform="polymarket", ready=True, missing=[], warnings=[], metadata={"fake": True})

    def submit_order(self, preview: PredictionMarketOrderPreview) -> PlatformExecutionResult:
        assert preview.platform == "polymarket"
        return PlatformExecutionResult(
            platform="polymarket",
            ready=True,
            submitted=True,
            order_id="0xfake_order",
            tx_hash="0xfake_tx",
            status="matched",
            raw_response={"status": "matched", "orderID": "0xfake_order", "transactionsHashes": ["0xfake_tx"]},
        )


class FakeKalshiExecutor(ExecutionAdapter):
    platform = "kalshi"

    def readiness(self) -> PlatformExecutionResult:
        return PlatformExecutionResult(platform="kalshi", ready=False, missing=["fake Kalshi adapter is not ready"], warnings=[])

    def submit_order(self, preview: PredictionMarketOrderPreview) -> PlatformExecutionResult:
        return PlatformExecutionResult(platform="kalshi", ready=False, submitted=False, status="not_supported", reason="fake Kalshi adapter is disabled")


class FakeCoreGateway:
    def create_action_intent(self, payload: dict) -> dict:
        assert payload["action_type"] == "prediction_market_order_execute"
        assert payload["metadata"]["preview_id"] == "pm_preview_fake"
        return {"action_id": "act_execute_fake", **payload}

    def evaluate_policy(self, payload: dict) -> dict:
        assert payload["action_type"] == "prediction_market_order_execute"
        approved = payload["metadata"]["execution_ready"] is True
        return {
            "policy_decision_id": "policy_execute_fake",
            "approved": approved,
            "decision": "approved" if approved else "blocked",
            "reason_code": "APPROVED" if approved else "EXECUTION_NOT_READY",
            "required_action": None if approved else "check_execution_readiness",
            **payload,
        }

    def write_audit_event(self, payload: dict) -> dict:
        assert payload["event_type"] in {
            "prediction_market_execution_requested",
            "prediction_market_execution_policy_evaluated",
        }
        return {"event_id": f"audit_{payload['event_type']}", **payload}


class FakeFundingGateway:
    def __init__(self, status: str, pusd_buying_power_usdc: str = "0") -> None:
        self.status = status
        self.pusd_buying_power_usdc = pusd_buying_power_usdc

    def get_funding_readiness(
        self,
        user_id: str,
        platform: str,
        amount_usd: str,
        *,
        funding_operation_id: str | None = None,
        binding_id: str | None = None,
        venue_wallet_address: str | None = None,
    ) -> dict:
        assert funding_operation_id == "funding-unit-smoke"
        assert binding_id == "binding-unit-smoke"
        assert venue_wallet_address == "0x" + "11" * 20
        result = {
            "status": self.status,
            "platform": platform,
            "pusd_buying_power_usdc": self.pusd_buying_power_usdc,
            "amount_usd": amount_usd,
            "ready": self.status == "ready",
            "next_action": (
                "execute_prediction_market_order_preview"
                if self.status == "ready"
                else "complete_funding_before_execution"
            ),
        }
        if result["ready"]:
            result["funding_proof"] = {
                "operation_id": funding_operation_id,
                "user_id": user_id,
                "binding_id": binding_id,
                "venue_wallet_address": venue_wallet_address,
                "bridge_address": "0x" + "44" * 20,
                "status": "finalized",
                "amount_usdc": "1.000000",
                "resource": "polygon:usdc",
                "core_state": "finalized",
                "bridge_status": "COMPLETED",
                "venue_buying_power_before_atomic": "0",
                "venue_buying_power_after_atomic": "1000000",
                "reservation_id": "reservation-unit-smoke",
                "audit_event_id": "audit-unit-smoke",
                "core_tx_hash": "0x" + "44" * 32,
            }
        return result


class FakeAccountBindingGateway:
    def latest_polymarket_binding(self, user_id: str) -> dict:
        assert user_id == "demo-user"
        return {
            "binding_id": "binding-unit-smoke",
            "user_id": user_id,
            "status": "active",
            "wallet_address": "0x" + "22" * 20,
            "funder_address": "0x" + "11" * 20,
            "polymarket_deposit_wallet": "0x" + "11" * 20,
            "account_mode": "deposit_wallet",
            "polymarket_signature_type": "3",
        }


class FakeAccountIdentityGateway:
    def active_wallet(self, user_id: str) -> str:
        assert user_id == "demo-user"
        return "0x" + "22" * 20


class FakePolymarketClient:
    def __init__(self, response: dict | None = None) -> None:
        self.response = response or {"status": "matched", "orderID": "0xfake_order", "transactionsHashes": ["0xfake_tx"]}
        self.market_order_args = None
        self.limit_order_args = None
        self.posted_order_type = None

    def create_market_order(self, order_args):
        self.market_order_args = order_args
        return {"signed": "market"}

    def create_order(self, order_args):
        self.limit_order_args = order_args
        return {"signed": "limit"}

    def post_order(self, signed_order, order_type):
        self.posted_order_type = order_type
        return self.response


def _preview(platform: str = "polymarket", amount: str = "1") -> PredictionMarketOrderPreview:
    market = UnifiedMarket(
        platform=platform,
        market_id="market_1",
        title="Kraken IPO by December 31, 2026?",
        yes_price=0.37,
        no_price=0.63,
        tradable=True,
        execution_ready=True,
        raw={"clobTokenIds": ["123456789", "987654321"]},
    )
    return PredictionMarketOrderPreview(
        preview_id="pm_preview_fake",
        user_id="demo-user",
        agent_id="hermes_agent",
        platform=platform,
        market_id="market_1",
        title=market.title,
        outcome="Yes",
        side="buy",
        amount_usd=amount,
        limit_price=0.37,
        estimated_contracts=2.7,
        max_slippage_bps=100,
        max_slippage_usd="0.01",
        worst_case_price=0.3737,
        state="confirmation_required",
        next_action="request_user_confirmation",
        requires_user_confirmation=True,
        live_mode=True,
        core_action_id="act_fake",
        core_policy_decision_id="policy_fake",
        core_audit_event_ids=["audit_fake"],
        market=market,
        metadata={"funding_operation_id": "funding-unit-smoke"},
        created_at="2026-07-02T00:00:00Z",
        expires_at="2099-01-01T00:00:00Z",
    )


def _preview_with_raw(raw: dict) -> PredictionMarketOrderPreview:
    preview = _preview()
    return preview.model_copy(update={"market": preview.market.model_copy(update={"raw": raw})})


def _config(live_mode: bool) -> AppConfig:
    config = AppConfig.from_env()
    config.execution_file = "/tmp/clink_prediction_execution_test.jsonl"
    config.live_mode = live_mode
    config.require_user_confirmation = True
    config.require_funding_before_execution = False
    return config


def main() -> None:
    storage = Path("/tmp/clink_prediction_execution_test.jsonl")
    storage.unlink(missing_ok=True)
    preview = _preview()
    api_string_preview = _preview_with_raw(
        {
            "outcomes": '["Yes", "No"]',
            "clobTokenIds": '["1111111111111111111111111111111111111111111111111111111111111111", "2222222222222222222222222222222222222222222222222222222222222222"]',
        }
    )
    assert PolymarketExecutor._resolve_token_id(api_string_preview) == "1111111111111111111111111111111111111111111111111111111111111111"
    no_preview = api_string_preview.model_copy(update={"outcome": "No"})
    assert PolymarketExecutor._resolve_token_id(no_preview) == "2222222222222222222222222222222222222222222222222222222222222222"

    buy_client = FakePolymarketClient()
    fake_order_types = (FakeMarketOrderArgs, FakeOrderArgs, FakeOrderType)
    PolymarketExecutor._submit_order_with_client(
        buy_client,
        api_string_preview,
        "1111111111111111111111111111111111111111111111111111111111111111",
        fake_order_types,
    )
    assert buy_client.market_order_args is not None
    assert buy_client.market_order_args.amount == 1.0
    assert buy_client.market_order_args.price == api_string_preview.worst_case_price
    assert buy_client.posted_order_type == "FAK"
    assert buy_client.limit_order_args is None

    sell_client = FakePolymarketClient()
    sell_preview = api_string_preview.model_copy(update={"side": "sell"})
    PolymarketExecutor._submit_order_with_client(
        sell_client,
        sell_preview,
        "1111111111111111111111111111111111111111111111111111111111111111",
        fake_order_types,
    )
    assert sell_client.limit_order_args is not None
    assert sell_client.limit_order_args.size == sell_preview.estimated_contracts
    assert sell_client.posted_order_type == "GTC"

    executors = {"polymarket": FakePolymarketExecutor(), "kalshi": FakeKalshiExecutor()}
    core_gateway = FakeCoreGateway()

    dry_service = ExecutionService(
        config=_config(live_mode=False),
        preview_store=FakePreviewStore(preview),
        executors=executors,
        core_gateway=core_gateway,
        account_binding_gateway=FakeAccountBindingGateway(),
        account_identity_gateway=FakeAccountIdentityGateway(),
    )
    blocked = dry_service.execute_order_preview(ExecutePredictionMarketOrderRequest(preview_id=preview.preview_id))
    assert blocked.state == "blocked"
    assert blocked.next_action == "request_user_confirmation"
    assert blocked.submitted is False

    simulated = dry_service.execute_order_preview(
        ExecutePredictionMarketOrderRequest(preview_id=preview.preview_id, user_confirmed=True, live_submission_confirmed=True)
    )
    assert simulated.state == "simulated_live_execution"
    assert simulated.execution_mode == "dry_run"
    assert simulated.submitted is False
    assert simulated.next_action == "enable_live_mode_for_real_execution"

    live_service = ExecutionService(
        config=_config(live_mode=True),
        preview_store=FakePreviewStore(preview),
        executors=executors,
        core_gateway=core_gateway,
        funding_gateway=FakeFundingGateway(status="ready", pusd_buying_power_usdc="5"),
        account_binding_gateway=FakeAccountBindingGateway(),
        account_identity_gateway=FakeAccountIdentityGateway(),
    )
    submitted = live_service.execute_order_preview(
        ExecutePredictionMarketOrderRequest(preview_id=preview.preview_id, user_confirmed=True, live_submission_confirmed=True)
    )
    assert submitted.state == "submitted"
    assert submitted.execution_mode == "live"
    assert submitted.submitted is True
    assert submitted.order_id == "0xfake_order"
    assert submitted.tx_hash == "0xfake_tx"
    assert submitted.core_action_id == "act_execute_fake"
    assert submitted.core_policy_decision_id == "policy_execute_fake"
    assert "audit_prediction_market_execution_requested" in submitted.core_audit_event_ids
    assert "audit_prediction_market_execution_policy_evaluated" in submitted.core_audit_event_ids

    funding_config = _config(live_mode=True)
    funding_config.require_funding_before_execution = True
    funding_blocked = ExecutionService(
        config=funding_config,
        preview_store=FakePreviewStore(preview),
        executors=executors,
        core_gateway=core_gateway,
        funding_gateway=FakeFundingGateway(status="pending_bridge", pusd_buying_power_usdc="0"),
        account_binding_gateway=FakeAccountBindingGateway(),
        account_identity_gateway=FakeAccountIdentityGateway(),
    ).execute_order_preview(
        ExecutePredictionMarketOrderRequest(preview_id=preview.preview_id, user_confirmed=True, live_submission_confirmed=True)
    )
    assert funding_blocked.state == "blocked"
    assert funding_blocked.submitted is False
    assert funding_blocked.next_action == "complete_funding_before_execution"

    funded = ExecutionService(
        config=funding_config,
        preview_store=FakePreviewStore(preview),
        executors=executors,
        core_gateway=core_gateway,
        funding_gateway=FakeFundingGateway(status="ready", pusd_buying_power_usdc="5"),
        account_binding_gateway=FakeAccountBindingGateway(),
        account_identity_gateway=FakeAccountIdentityGateway(),
    ).execute_order_preview(
        ExecutePredictionMarketOrderRequest(preview_id=preview.preview_id, user_confirmed=True, live_submission_confirmed=True)
    )
    assert funded.state == "submitted"
    assert funded.submitted is True

    kalshi_preview = _preview(platform="kalshi")
    kalshi = ExecutionService(config=_config(live_mode=True), preview_store=FakePreviewStore(kalshi_preview), executors=executors, core_gateway=core_gateway).execute_order_preview(
        ExecutePredictionMarketOrderRequest(preview_id=kalshi_preview.preview_id, user_confirmed=True, live_submission_confirmed=True)
    )
    assert kalshi.state == "blocked"
    assert kalshi.execution_mode == "blocked"
    assert kalshi.next_action == "check_execution_readiness"
    assert "EXECUTION_NOT_READY" in (kalshi.reason or "")

    missing = live_service.execute_order_preview(
        ExecutePredictionMarketOrderRequest(preview_id="missing", user_confirmed=True, live_submission_confirmed=True)
    )
    assert missing.state == "blocked"
    assert missing.next_action == "create_order_preview"

    loaded = live_service.get_execution(submitted.execution_id)
    assert loaded is not None
    assert loaded.execution_id == submitted.execution_id

    readiness = live_service.check_readiness()
    assert readiness.live_mode_enabled is True
    assert readiness.platforms["polymarket"].ready is True
    assert readiness.platforms["kalshi"].ready is False

    print(json.dumps({"status": "ok", "submitted_execution_id": submitted.execution_id, "dry_run_state": simulated.state}, indent=2))


if __name__ == "__main__":
    main()
