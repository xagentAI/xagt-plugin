from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_DOWN, ROUND_HALF_UP
from pathlib import Path
from typing import Callable

from services.portfolio_service.schemas import (
    PendingAgentAction,
    PortfolioAgentIdea,
    PortfolioAccountBalance,
    PortfolioFill,
    PortfolioFundingStatus,
    PortfolioOpenOrder,
    PortfolioPosition,
    PortfolioSettlement,
    PortfolioSnapshot,
    PortfolioSummary,
    PortfolioTimelineItem,
    StrategyPerformance,
)
from shared.config import AppConfig
from shared.core_account_client import CoreAccountClient
from storage.trading_ledger import TradingLedger


class PortfolioService:
    def __init__(
        self,
        config: AppConfig | None = None,
        preview_file: Path | str | None = None,
        execution_file: Path | str | None = None,
        ledger: TradingLedger | None = None,
        funding_status_fetcher: Callable[[str, str], dict] | None = None,
        account_readiness_fetcher: Callable[[str], dict] | None = None,
    ) -> None:
        self.config = config or AppConfig.from_env()
        self.preview_file = Path(preview_file or self.config.preview_file)
        self.execution_file = Path(execution_file or self.config.execution_file)
        self.ledger = ledger or TradingLedger(self.config.ledger_db_file)
        self.funding_status_fetcher = funding_status_fetcher
        self.account_readiness_fetcher = account_readiness_fetcher

    def build_snapshot(
        self,
        *,
        user_id: str | None = None,
        funding_operation_id: str | None = None,
    ) -> PortfolioSnapshot:
        positions = [self._build_position(row) for row in self.ledger.list_positions()]
        account_balances = [self._build_account_balance(row) for row in self.ledger.list_account_balances()]
        open_orders = [self._build_open_order(row) for row in self.ledger.list_open_orders()]
        recent_fills = [self._build_fill(row) for row in self.ledger.list_fills(limit=100)]
        recent_settlements = [self._build_settlement(row) for row in self.ledger.list_settlements(limit=100)]
        strategies = [self._build_strategy(row) for row in self.ledger.list_strategy_performance()]
        agent_ideas = [self._build_agent_idea(row) for row in self.ledger.list_agent_ideas()]
        pending_actions = [self._build_pending_action(row) for row in self.ledger.list_pending_actions()]
        timeline = [self._build_timeline_item(row) for row in self.ledger.list_timeline()]
        funding = self._build_funding_status(
            user_id=user_id,
            funding_operation_id=funding_operation_id,
        )
        summary = self._build_summary(
            positions,
            account_balances,
            open_orders,
            recent_fills,
            recent_settlements,
            strategies,
            pending_actions,
            len(positions),
            self.ledger.latest_sync_run(),
            user_id=user_id,
        )
        return PortfolioSnapshot(
            summary=summary,
            funding=funding,
            strategies=strategies,
            agent_ideas=agent_ideas,
            positions=positions,
            account_balances=account_balances,
            open_orders=open_orders,
            recent_fills=recent_fills,
            recent_settlements=recent_settlements,
            pending_actions=pending_actions,
            timeline=timeline,
        )

    def _build_funding_status(
        self,
        *,
        user_id: str | None,
        funding_operation_id: str | None,
    ) -> PortfolioFundingStatus:
        if not user_id or not funding_operation_id:
            return PortfolioFundingStatus(
                status="unavailable",
                error="funding operation scope is required",
            )
        try:
            payload = (
                self.funding_status_fetcher(user_id, funding_operation_id)
                if self.funding_status_fetcher
                else self._fetch_funding_status(
                    user_id=user_id,
                    funding_operation_id=funding_operation_id,
                )
            )
        except Exception as exc:
            return PortfolioFundingStatus(status="unavailable", error=str(exc))

        operation_status = str(payload.get("status") or "unavailable")
        finalized = operation_status == "finalized"
        tx_hash = payload.get("core_tx_hash")
        return PortfolioFundingStatus(
            status=operation_status,
            settled_amount_usdc_by_venue=(
                {"polymarket": str(payload.get("amount_usdc"))}
                if finalized and payload.get("amount_usdc") is not None
                else {}
            ),
            bridge_status=payload.get("bridge_status"),
            receipt_count=1 if tx_hash else 0,
            latest_receipt_tx_hash=tx_hash,
            error=payload.get("failure_reason_code"),
        )

    def _fetch_funding_status(
        self,
        *,
        user_id: str,
        funding_operation_id: str,
    ) -> dict:
        operation_path = urllib.parse.quote(funding_operation_id, safe="")
        query = urllib.parse.urlencode({"user_id": user_id})
        token = self.config.prediction_markets_internal_api_token.strip()
        if not token:
            raise RuntimeError(
                "PREDICTION_MARKETS_INTERNAL_API_TOKEN is required for funding adapter requests"
            )
        request = urllib.request.Request(
            f"{self.config.funding_adapter_url}/polymarket/funding-operations/"
            f"{operation_path}?{query}",
            headers={"Authorization": f"Bearer {token}"},
            method="GET",
        )
        try:
            with urllib.request.urlopen(request, timeout=5) as response:
                return json.loads(response.read().decode("utf-8"))
        except urllib.error.HTTPError as exc:
            raise RuntimeError(
                f"funding operation returned HTTP {exc.code}"
            ) from exc
        except (urllib.error.URLError, json.JSONDecodeError) as exc:
            raise RuntimeError("funding operation is unavailable") from exc

    def _build_position(self, row: dict) -> PortfolioPosition:
        cost_basis = self._decimal(row["cost_basis_usd"])
        pnl = self._decimal(row["unrealized_pnl_usd"])
        pnl_pct = (pnl / cost_basis * Decimal("100")) if cost_basis > 0 else Decimal("0")
        raw = self._loads(row.get("raw_json"))
        return PortfolioPosition(
            position_id=row["position_id"],
            execution_id=row["execution_id"],
            preview_id=row["preview_id"],
            platform=row["platform"],
            market_id=row["market_id"],
            title=row["title"],
            outcome=row["outcome"],
            side=row["side"],
            status=row["status"],
            order_id=row["order_id"],
            entry_price=float(row["entry_price"]),
            current_price=float(row["mark_price"]),
            price_source=row["price_source"],
            contracts=row["contracts"],
            cost_basis_usd=row["cost_basis_usd"],
            current_value_usd=row["current_value_usd"],
            unrealized_pnl_usd=row["unrealized_pnl_usd"],
            pnl_pct=self._money(pnl_pct),
            action_id=row["action_id"],
            policy_decision_id=row["policy_decision_id"],
            audit_event_ids=self._loads(row["audit_event_ids"]),
            created_at=row["created_at"],
            metadata=raw.get("metadata", {}),
        )

    @staticmethod
    def _build_account_balance(row: dict) -> PortfolioAccountBalance:
        return PortfolioAccountBalance(
            platform=row["platform"],
            currency=row["currency"],
            total=row["total"],
            available=row["available"],
            locked=row["locked"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _build_open_order(row: dict) -> PortfolioOpenOrder:
        return PortfolioOpenOrder(
            platform=row["platform"],
            order_id=row["order_id"],
            market_id=row["market_id"],
            title=row["title"],
            outcome=row["outcome"],
            side=row["side"],
            status=row["status"],
            contracts=row["contracts"],
            filled_contracts=row["filled_contracts"],
            limit_price=row["limit_price"],
            avg_price=row["avg_price"],
            cost_basis_usd=row["cost_basis_usd"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _build_fill(row: dict) -> PortfolioFill:
        return PortfolioFill(
            platform=row["platform"],
            fill_id=row["fill_id"],
            order_id=row["order_id"],
            market_id=row["market_id"],
            outcome=row["outcome"],
            side=row["side"],
            contracts=row["contracts"],
            price=row["price"],
            amount_usd=row["amount_usd"],
            fee_usd=row["fee_usd"],
            filled_at=row["filled_at"],
        )

    @staticmethod
    def _build_settlement(row: dict) -> PortfolioSettlement:
        return PortfolioSettlement(
            platform=row["platform"],
            settlement_id=row["settlement_id"],
            market_id=row["market_id"],
            title=row["title"],
            realized_pnl_usd=row["realized_pnl_usd"],
            payout_usd=row["payout_usd"],
            settled_at=row["settled_at"],
        )

    @staticmethod
    def _build_strategy(row: dict) -> StrategyPerformance:
        return StrategyPerformance(**row)

    @staticmethod
    def _build_agent_idea(row: dict) -> PortfolioAgentIdea:
        return PortfolioAgentIdea(**row)

    def _build_pending_action(self, row: dict) -> PendingAgentAction:
        return PendingAgentAction(
            preview_id=row["preview_id"],
            platform=row["platform"],
            market_id=row["market_id"],
            title=row["title"],
            outcome=row["outcome"],
            side=row["side"],
            amount_usd=row["amount_usd"],
            limit_price=float(row["limit_price"]),
            next_action=row["next_action"],
            action_id=row["action_id"],
            policy_decision_id=row["policy_decision_id"],
            audit_event_ids=self._loads(row["audit_event_ids"]),
            created_at=row["created_at"],
        )

    @staticmethod
    def _build_timeline_item(row: dict) -> PortfolioTimelineItem:
        return PortfolioTimelineItem(**row)

    def _build_summary(
        self,
        positions: list[PortfolioPosition],
        account_balances: list[PortfolioAccountBalance],
        open_orders: list[PortfolioOpenOrder],
        recent_fills: list[PortfolioFill],
        recent_settlements: list[PortfolioSettlement],
        strategies: list[StrategyPerformance],
        pending_actions: list[PendingAgentAction],
        submitted_executions: int,
        latest_sync: dict | None,
        *,
        user_id: str | None,
    ) -> PortfolioSummary:
        account_equity = sum((self._decimal(balance.total) for balance in account_balances), Decimal("0"))
        available_cash = sum((self._decimal(balance.available) for balance in account_balances), Decimal("0"))
        locked_cash = sum((self._decimal(balance.locked) for balance in account_balances), Decimal("0"))
        capital_deployed = sum((self._decimal(position.cost_basis_usd) for position in positions), Decimal("0"))
        current_value = sum((self._decimal(position.current_value_usd) for position in positions), Decimal("0"))
        unrealized = sum((self._decimal(position.unrealized_pnl_usd) for position in positions), Decimal("0"))
        realized = sum((self._decimal(settlement.realized_pnl_usd) for settlement in recent_settlements), Decimal("0"))
        total_pnl = unrealized + realized
        total_pnl_pct = (total_pnl / capital_deployed * Decimal("100")) if capital_deployed > 0 else Decimal("0")
        winners = len([position for position in positions if self._decimal(position.unrealized_pnl_usd) > 0])
        win_rate = Decimal(winners) / Decimal(len(positions)) * Decimal("100") if positions else Decimal("0")
        active_strategies = len([strategy for strategy in strategies if strategy.status == "active"])
        best_strategy = max(strategies, key=lambda strategy: self._decimal(strategy.total_pnl_usd), default=None)
        platform_exposure: dict[str, Decimal] = {}
        for position in positions:
            platform_exposure.setdefault(position.platform, Decimal("0"))
            platform_exposure[position.platform] += self._decimal(position.cost_basis_usd)
        available_budget, available_budget_status = self._effective_core_budget(
            user_id
        )
        return PortfolioSummary(
            portfolio_value_usd=self._money(current_value),
            current_value_usd=self._money(current_value),
            capital_deployed_usd=self._money(capital_deployed),
            available_budget_usd=available_budget,
            available_budget_status=available_budget_status,
            realized_pnl_usd=self._money(realized),
            unrealized_pnl_usd=self._money(unrealized),
            total_pnl_usd=self._money(total_pnl),
            total_pnl_pct=self._money(total_pnl_pct),
            open_positions=len(positions),
            open_orders=len(open_orders),
            fills_24h=len(recent_fills),
            settlements_24h=len(recent_settlements),
            active_strategies=active_strategies,
            best_strategy_id=best_strategy.strategy_id if best_strategy else None,
            pending_confirmations=len(pending_actions),
            submitted_executions=submitted_executions,
            win_rate_pct=self._money(win_rate),
            account_equity_usd=self._money(account_equity),
            available_cash_usd=self._money(available_cash),
            locked_cash_usd=self._money(locked_cash),
            platform_exposure_usd={platform: self._money(amount) for platform, amount in sorted(platform_exposure.items())},
            last_updated_at=datetime.utcnow().isoformat() + "Z",
            last_synced_at=self._sync_completed_at(latest_sync),
            sync_status=latest_sync["status"] if latest_sync else "never_synced",
            sync_source=latest_sync["source"] if latest_sync else None,
            sync_stale=self._sync_stale(latest_sync),
        )

    def _effective_core_budget(
        self,
        user_id: str | None,
    ) -> tuple[str | None, str]:
        if not isinstance(user_id, str) or not user_id.strip():
            return None, "unavailable"
        try:
            readiness = (
                self.account_readiness_fetcher(user_id)
                if self.account_readiness_fetcher
                else CoreAccountClient(
                    self.config.clink_core_account_service_url,
                    self.config.clink_core_internal_api_token,
                ).readiness(user_id)
            )
            if readiness.get("user_id") != user_id:
                raise ValueError("Core readiness subject does not match request")
            mandate = readiness["active_spending_mandate"]
            limits = mandate["limits_usdc"]
            remaining = mandate["remaining_usdc"]
            values = [
                Decimal(str(limits["per_transaction"])),
                Decimal(str(remaining["rolling_hour"])),
                Decimal(str(remaining["daily"])),
                Decimal(str(remaining["total"])),
            ]
            if any(not value.is_finite() or value < Decimal("0") for value in values):
                raise ValueError("Core budget values must be finite and non-negative")
            return self._usdc_amount(min(values)), "ready"
        except Exception:
            return None, "unavailable"

    def _sync_stale(self, latest_sync: dict | None) -> bool:
        completed_at = self._sync_completed_at(latest_sync)
        if not completed_at:
            return True
        try:
            completed = datetime.fromisoformat(completed_at.replace("Z", ""))
        except ValueError:
            return True
        return (datetime.utcnow() - completed).total_seconds() > self.config.sync_stale_after_seconds

    @staticmethod
    def _sync_completed_at(latest_sync: dict | None) -> str | None:
        if not latest_sync:
            return None
        return latest_sync.get("completed_at") or latest_sync.get("started_at")

    @staticmethod
    def _loads(value: str | None):
        if not value:
            return {}
        return json.loads(value)

    @staticmethod
    def _decimal(value: object) -> Decimal:
        try:
            return Decimal(str(value))
        except (InvalidOperation, ValueError) as exc:
            raise ValueError(f"Invalid decimal value: {value}") from exc

    @staticmethod
    def _money(value: Decimal) -> str:
        return str(value.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))

    @staticmethod
    def _usdc_amount(value: Decimal) -> str:
        return format(
            value.quantize(Decimal("0.000001"), rounding=ROUND_DOWN),
            "f",
        )
