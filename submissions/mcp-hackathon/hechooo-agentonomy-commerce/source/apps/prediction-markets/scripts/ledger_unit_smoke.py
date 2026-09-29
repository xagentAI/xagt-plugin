import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from storage.trading_ledger import TradingLedger
from shared.schemas import PredictionMarketExecution, PredictionMarketOrderPreview, UnifiedMarket


def _preview() -> PredictionMarketOrderPreview:
    market = UnifiedMarket(
        platform="polymarket",
        market_id="pm_kraken",
        title="Kraken IPO by December 31, 2026?",
        yes_price=0.62,
        no_price=0.38,
        tradable=True,
        execution_ready=True,
    )
    return PredictionMarketOrderPreview(
        preview_id="pm_preview_ledger",
        user_id="demo-user",
        agent_id="hermes_agent",
        platform="polymarket",
        market_id=market.market_id,
        title=market.title,
        outcome="Yes",
        side="buy",
        amount_usd="10",
        limit_price=0.5,
        estimated_contracts=20,
        max_slippage_bps=100,
        max_slippage_usd="0.10",
        worst_case_price=0.505,
        state="confirmation_required",
        next_action="request_user_confirmation",
        requires_user_confirmation=True,
        live_mode=True,
        core_action_id="act_ledger",
        core_policy_decision_id="policy_ledger",
        core_audit_event_ids=["audit_ledger"],
        market=market,
        created_at="2026-07-02T00:00:00Z",
        expires_at="2099-01-01T00:00:00Z",
    )


def _execution(preview: PredictionMarketOrderPreview) -> PredictionMarketExecution:
    return PredictionMarketExecution(
        execution_id="pm_exec_ledger",
        preview_id=preview.preview_id,
        user_id=preview.user_id,
        agent_id=preview.agent_id,
        platform=preview.platform,
        market_id=preview.market_id,
        title=preview.title,
        outcome=preview.outcome,
        side=preview.side,
        amount_usd=preview.amount_usd,
        limit_price=preview.limit_price,
        estimated_contracts=preview.estimated_contracts,
        state="submitted",
        execution_mode="live",
        submitted=True,
        live_mode_enabled=True,
        order_id="venue_order_ledger",
        core_action_id=preview.core_action_id,
        core_policy_decision_id=preview.core_policy_decision_id,
        core_audit_event_ids=preview.core_audit_event_ids,
        reason="polymarket order submitted with status matched",
        next_action="monitor_order_status",
        created_at="2026-07-02T00:01:00Z",
    )


def main() -> None:
    db_path = Path("/tmp/clink_prediction_ledger_unit.sqlite3")
    db_path.unlink(missing_ok=True)
    ledger = TradingLedger(db_path)
    preview = _preview()
    execution = _execution(preview)

    ledger.upsert_preview(preview)
    ledger.upsert_execution(execution)
    ledger.reconcile_position_from_execution(execution, preview)
    ledger.record_sync_run(
        source="local_jsonl_reconciliation",
        status="ok",
        started_at="2026-07-02T00:02:00Z",
        completed_at="2026-07-02T00:02:01Z",
        metadata={"previews": 1, "executions": 1},
    )

    positions = ledger.list_positions()
    assert len(positions) == 1
    assert positions[0]["position_id"] == "pos_pm_exec_ledger"
    assert positions[0]["mark_price"] == "0.62"
    assert positions[0]["unrealized_pnl_usd"] == "2.40"

    pending = ledger.list_pending_actions()
    assert pending == []

    timeline = ledger.list_timeline()
    assert len(timeline) == 2
    assert timeline[0]["kind"] == "sync_run"
    assert timeline[1]["kind"] == "execution"
    assert all(item["kind"] != "preview" for item in timeline)

    latest_sync = ledger.latest_sync_run()
    assert latest_sync is not None
    assert latest_sync["status"] == "ok"

    print(json.dumps({"status": "ok", "positions": len(positions), "latest_sync": latest_sync["status"]}, indent=2))


if __name__ == "__main__":
    main()
