import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from services.sync_service.service import PortfolioSyncService
from shared.config import AppConfig
from shared.schemas import PredictionMarketExecution, PredictionMarketOrderPreview, UnifiedMarket
from storage.trading_ledger import TradingLedger


def _preview() -> PredictionMarketOrderPreview:
    market = UnifiedMarket(
        platform="kalshi",
        market_id="KXKRAKENIPO-26DEC31",
        title="Will Kraken IPO before 2027?",
        yes_price=0.45,
        no_price=0.55,
        tradable=True,
        execution_ready=True,
        raw={"ticker": "KXKRAKENIPO-26DEC31"},
    )
    return PredictionMarketOrderPreview(
        preview_id="pm_preview_sync",
        user_id="demo-user",
        agent_id="hermes_agent",
        platform="kalshi",
        market_id=market.market_id,
        title=market.title,
        outcome="Yes",
        side="buy",
        amount_usd="9",
        limit_price=0.4,
        estimated_contracts=22.5,
        max_slippage_bps=100,
        max_slippage_usd="0.09",
        worst_case_price=0.404,
        state="confirmation_required",
        next_action="request_user_confirmation",
        requires_user_confirmation=True,
        live_mode=True,
        core_action_id="act_sync",
        core_policy_decision_id="policy_sync",
        core_audit_event_ids=["audit_sync"],
        market=market,
        created_at="2026-07-02T01:00:00Z",
        expires_at="2099-01-01T00:00:00Z",
    )


def _execution(preview: PredictionMarketOrderPreview) -> PredictionMarketExecution:
    return PredictionMarketExecution(
        execution_id="pm_exec_sync",
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
        order_id="kalshi_order_sync",
        core_action_id=preview.core_action_id,
        core_policy_decision_id=preview.core_policy_decision_id,
        core_audit_event_ids=preview.core_audit_event_ids,
        reason="kalshi order submitted with status submitted",
        next_action="monitor_order_status",
        created_at="2026-07-02T01:01:00Z",
    )


def main() -> None:
    db_path = Path("/tmp/clink_prediction_sync.sqlite3")
    preview_file = Path("/tmp/clink_prediction_sync_previews.jsonl")
    execution_file = Path("/tmp/clink_prediction_sync_executions.jsonl")
    for path in [db_path, preview_file, execution_file]:
        path.unlink(missing_ok=True)

    preview = _preview()
    execution = _execution(preview)
    preview_file.write_text(json.dumps(preview.model_dump()) + "\n")
    execution_file.write_text(json.dumps(execution.model_dump()) + "\n")

    config = AppConfig.from_env()
    config.ledger_db_file = str(db_path)
    config.preview_file = str(preview_file)
    config.execution_file = str(execution_file)
    config.sync_stale_after_seconds = 60

    result = PortfolioSyncService(config=config).sync_once()
    assert result.status == "ok"
    assert result.previews_ingested == 1
    assert result.executions_ingested == 1
    assert result.positions_reconciled == 1

    ledger = TradingLedger(db_path)
    positions = ledger.list_positions()
    assert len(positions) == 1
    assert positions[0]["platform"] == "kalshi"
    assert positions[0]["mark_price"] == "0.45"
    assert ledger.latest_sync_run()["status"] == "ok"

    print(json.dumps({"status": "ok", "positions": len(positions), "sync_run_id": result.sync_run_id}, indent=2))


if __name__ == "__main__":
    main()
