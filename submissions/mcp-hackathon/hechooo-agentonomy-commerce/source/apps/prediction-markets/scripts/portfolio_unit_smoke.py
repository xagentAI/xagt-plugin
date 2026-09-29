import json
import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from services.portfolio_service.service import PortfolioService
from shared.config import AppConfig
from shared.schemas import AgentIdea, PredictionMarketExecution, PredictionMarketOrderPreview, UnifiedMarket
from storage.trading_ledger import TradingLedger


def _preview(preview_id: str, platform: str, amount: str, price: float, current_price: float, state: str) -> PredictionMarketOrderPreview:
    market = UnifiedMarket(
        platform=platform,
        market_id=f"{platform}_market_1",
        title="Kraken IPO by December 31, 2026?",
        yes_price=current_price,
        no_price=round(1 - current_price, 4),
        tradable=True,
        execution_ready=True,
    )
    return PredictionMarketOrderPreview(
        preview_id=preview_id,
        user_id="demo-user",
        agent_id="hermes_agent",
        platform=platform,
        market_id=market.market_id,
        title=market.title,
        outcome="Yes",
        side="buy",
        amount_usd=amount,
        limit_price=price,
        estimated_contracts=float(amount) / price,
        max_slippage_bps=100,
        max_slippage_usd="0.10",
        worst_case_price=price * 1.01,
        state=state,
        next_action="request_user_confirmation",
        requires_user_confirmation=True,
        live_mode=True,
        core_action_id=f"act_{preview_id}",
        core_policy_decision_id=f"policy_{preview_id}",
        core_audit_event_ids=[f"audit_{preview_id}"],
        market=market,
        created_at="2026-07-02T00:00:00Z",
        expires_at="2099-01-01T00:00:00Z",
    )


def main() -> None:
    db_path = Path("/tmp/clink_prediction_portfolio.sqlite3")
    for path in [db_path, Path(f"{db_path}-wal"), Path(f"{db_path}-shm")]:
        path.unlink(missing_ok=True)

    submitted_preview = _preview("pm_preview_submitted", "polymarket", "10", 0.5, 0.6, "confirmation_required")
    pending_preview = _preview("pm_preview_pending", "kalshi", "4", 0.4, 0.4, "confirmation_required")
    failed_preview = _preview("pm_preview_failed", "polymarket", "1", 0.1, 0.1, "confirmation_required")

    execution = PredictionMarketExecution(
        execution_id="pm_exec_submitted",
        preview_id=submitted_preview.preview_id,
        user_id=submitted_preview.user_id,
        agent_id=submitted_preview.agent_id,
        platform=submitted_preview.platform,
        market_id=submitted_preview.market_id,
        title=submitted_preview.title,
        outcome=submitted_preview.outcome,
        side=submitted_preview.side,
        amount_usd=submitted_preview.amount_usd,
        limit_price=submitted_preview.limit_price,
        estimated_contracts=submitted_preview.estimated_contracts,
        state="submitted",
        execution_mode="live",
        submitted=True,
        live_mode_enabled=True,
        order_id="venue_order_1",
        core_action_id=submitted_preview.core_action_id,
        core_policy_decision_id=submitted_preview.core_policy_decision_id,
        core_audit_event_ids=submitted_preview.core_audit_event_ids,
        reason="polymarket order submitted with status matched",
        next_action="monitor_order_status",
        created_at="2026-07-02T00:01:00Z",
    )
    failed_execution = execution.model_copy(
        update={
            "execution_id": "pm_exec_failed",
            "preview_id": failed_preview.preview_id,
            "state": "failed",
            "submitted": False,
            "order_id": None,
            "reason": "venue rejected invalid order inputs",
            "next_action": "inspect_execution_error",
            "created_at": "2026-07-02T00:01:30Z",
        }
    )
    failed_idea = AgentIdea(
        idea_id="idea_failed",
        user_id="demo-user",
        agent_id="hermes_agent",
        topic="Failed execution should stay out of dashboard",
        agent_message="This failed trade should remain inspectable through execution APIs, not the main dashboard.",
        recommendation="do_not_show",
        confidence=0.1,
        market={"platform": "polymarket", "market_id": "failed_market"},
        suggested_trade={"side": "buy", "outcome": "Yes", "amount_usd": "1"},
        risks=["failed execution"],
        status="preview_created",
        preview_id=failed_preview.preview_id,
        execution_id=failed_execution.execution_id,
        created_at="2026-07-02T00:01:30Z",
        updated_at="2026-07-02T00:01:30Z",
    )

    ledger = TradingLedger(db_path)
    ledger.upsert_preview(submitted_preview)
    ledger.upsert_preview(pending_preview)
    ledger.upsert_preview(failed_preview)
    ledger.upsert_execution(execution)
    ledger.upsert_execution(failed_execution)
    ledger.upsert_agent_idea(failed_idea)
    ledger.reconcile_position_from_execution(execution, submitted_preview)
    ledger.record_sync_run(
        sync_run_id="sync_portfolio_smoke",
        source="local_jsonl_reconciliation",
        status="ok",
        started_at="2026-07-02T00:02:00Z",
        completed_at="2026-07-02T00:02:01Z",
        previews_ingested=3,
        executions_ingested=2,
        positions_reconciled=1,
    )
    ledger.record_sync_run(
        sync_run_id="sync_failed_smoke",
        source="venue_account_reconciliation",
        status="failed",
        started_at="2026-07-02T00:02:30Z",
        completed_at="2026-07-02T00:02:31Z",
        error="temporary venue error",
    )

    config = AppConfig.from_env()
    config.ledger_db_file = str(db_path)

    readiness_calls: list[str] = []

    def readiness_payload(
        user_id: str,
        *,
        per_transaction: str = "3",
        rolling_hour: str = "2",
    ) -> dict:
        return {
            "user_id": user_id,
            "active_spending_mandate": {
                "limits_usdc": {"per_transaction": per_transaction},
                "remaining_usdc": {
                    "rolling_hour": rolling_hour,
                    "daily": "4",
                    "total": "10",
                },
            },
        }

    def account_readiness(user_id: str) -> dict:
        assert user_id == "telegram_demo_user"
        readiness_calls.append(user_id)
        return readiness_payload(user_id)

    service = PortfolioService(
        config=config,
        ledger=ledger,
        account_readiness_fetcher=account_readiness,
    )
    anonymous_snapshot = service.build_snapshot()
    snapshot = service.build_snapshot(user_id="telegram_demo_user")

    sub_cent_snapshot = PortfolioService(
        config=config,
        ledger=ledger,
        account_readiness_fetcher=lambda user_id: readiness_payload(
            user_id,
            per_transaction="0.005000",
        ),
    ).build_snapshot(user_id="telegram_demo_user")

    non_amplified_snapshot = PortfolioService(
        config=config,
        ledger=ledger,
        account_readiness_fetcher=lambda user_id: readiness_payload(
            user_id,
            per_transaction="0.0050009",
        ),
    ).build_snapshot(user_id="telegram_demo_user")

    mismatched_snapshot = PortfolioService(
        config=config,
        ledger=ledger,
        account_readiness_fetcher=lambda _user_id: readiness_payload(
            "different_user"
        ),
    ).build_snapshot(user_id="telegram_demo_user")

    def readiness_without_user(user_id: str) -> dict:
        payload = readiness_payload(user_id)
        del payload["user_id"]
        return payload

    missing_user_snapshot = PortfolioService(
        config=config,
        ledger=ledger,
        account_readiness_fetcher=readiness_without_user,
    ).build_snapshot(user_id="telegram_demo_user")

    def unavailable_account_readiness(_user_id: str) -> dict:
        raise RuntimeError("Core Account is unavailable")

    unavailable_snapshot = PortfolioService(
        config=config,
        ledger=ledger,
        account_readiness_fetcher=unavailable_account_readiness,
    ).build_snapshot(user_id="telegram_demo_user")

    assert snapshot.summary.capital_deployed_usd == "10.00"
    assert snapshot.summary.current_value_usd == "12.00"
    assert readiness_calls == ["telegram_demo_user"]
    assert anonymous_snapshot.summary.available_budget_usd is None
    assert anonymous_snapshot.summary.available_budget_status == "unavailable"
    assert snapshot.summary.available_budget_usd == "2.000000"
    assert snapshot.summary.available_budget_status == "ready"
    assert sub_cent_snapshot.summary.available_budget_usd == "0.005000"
    assert sub_cent_snapshot.summary.available_budget_status == "ready"
    assert non_amplified_snapshot.summary.available_budget_usd == "0.005000"
    assert non_amplified_snapshot.summary.available_budget_status == "ready"
    assert mismatched_snapshot.summary.available_budget_usd is None
    assert mismatched_snapshot.summary.available_budget_status == "unavailable"
    assert missing_user_snapshot.summary.available_budget_usd is None
    assert missing_user_snapshot.summary.available_budget_status == "unavailable"
    assert unavailable_snapshot.summary.available_budget_usd is None
    assert unavailable_snapshot.summary.available_budget_status == "unavailable"
    assert snapshot.summary.unrealized_pnl_usd == "2.00"
    assert snapshot.summary.pending_confirmations == 1
    assert snapshot.summary.open_positions == 1
    assert snapshot.summary.platform_exposure_usd["polymarket"] == "10.00"
    assert snapshot.summary.sync_status == "ok"
    assert snapshot.summary.sync_stale is True
    assert snapshot.positions[0].pnl_pct == "20.00"
    assert snapshot.agent_ideas == []
    assert snapshot.pending_actions[0].preview_id == "pm_preview_pending"
    assert all(item.id != failed_execution.execution_id for item in snapshot.timeline)
    assert all(item.preview_id != failed_preview.preview_id for item in snapshot.timeline)
    assert all(item.state != "failed" for item in snapshot.timeline)
    assert snapshot.timeline[0].kind == "sync_run"
    assert snapshot.timeline[-1].kind == "preview"

    print(json.dumps({"status": "ok", "positions": len(snapshot.positions), "timeline": len(snapshot.timeline)}, indent=2))


if __name__ == "__main__":
    main()
