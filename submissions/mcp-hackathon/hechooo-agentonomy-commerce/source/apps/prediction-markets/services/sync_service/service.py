from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import TypeVar
from uuid import uuid4

from pydantic import BaseModel

from services.sync_service.schemas import PortfolioSyncResult
from services.sync_service.venue_adapters import VenueAccountSyncAdapter, default_venue_adapters
from shared.config import AppConfig
from shared.schemas import PredictionMarketExecution, PredictionMarketOrderPreview
from storage.trading_ledger import TradingLedger

ModelT = TypeVar("ModelT", bound=BaseModel)


class PortfolioSyncService:
    def __init__(
        self,
        config: AppConfig | None = None,
        ledger: TradingLedger | None = None,
        venue_adapters: list[VenueAccountSyncAdapter] | None = None,
    ) -> None:
        self.config = config or AppConfig.from_env()
        self.ledger = ledger or TradingLedger(self.config.ledger_db_file)
        self.preview_file = Path(self.config.preview_file)
        self.execution_file = Path(self.config.execution_file)
        self.venue_adapters = venue_adapters if venue_adapters is not None else default_venue_adapters(self.config)

    def sync_once(self) -> PortfolioSyncResult:
        sync_run_id = f"sync_{uuid4().hex[:12]}"
        started_at = self._utc_now()
        try:
            previews = self._latest_by_id(self._load_jsonl(self.preview_file, PredictionMarketOrderPreview), "preview_id")
            executions = self._latest_by_id(self._load_jsonl(self.execution_file, PredictionMarketExecution), "execution_id")

            for preview in previews.values():
                self.ledger.upsert_preview(preview)

            positions_reconciled = 0
            for execution in executions.values():
                self.ledger.upsert_execution(execution)
                if self.ledger.reconcile_position_from_execution(execution, previews.get(execution.preview_id)):
                    positions_reconciled += 1

            venue_snapshots_ingested = 0
            balances_ingested = 0
            open_orders_ingested = 0
            fills_ingested = 0
            settlements_ingested = 0
            venue_status: dict[str, str] = {}
            venue_warnings: dict[str, list[str]] = {}
            if self.config.sync_venue_accounts:
                for adapter in self.venue_adapters:
                    snapshot = adapter.fetch_account_snapshot()
                    venue_status[snapshot.platform] = snapshot.status
                    if snapshot.warnings:
                        venue_warnings[snapshot.platform] = snapshot.warnings
                    if snapshot.status in {"ok", "partial"}:
                        counts = self.ledger.upsert_venue_account_snapshot(snapshot)
                        venue_snapshots_ingested += 1
                        balances_ingested += counts["balances"]
                        open_orders_ingested += counts["open_orders"]
                        fills_ingested += counts["fills"]
                        positions_reconciled += counts["positions"]
                        settlements_ingested += counts["settlements"]

            completed_at = self._utc_now()
            self.ledger.record_sync_run(
                sync_run_id=sync_run_id,
                source="local_jsonl_reconciliation",
                status="ok",
                started_at=started_at,
                completed_at=completed_at,
                previews_ingested=len(previews),
                executions_ingested=len(executions),
                venue_snapshots_ingested=venue_snapshots_ingested,
                balances_ingested=balances_ingested,
                open_orders_ingested=open_orders_ingested,
                fills_ingested=fills_ingested,
                settlements_ingested=settlements_ingested,
                positions_reconciled=positions_reconciled,
                metadata={
                    "preview_file": str(self.preview_file),
                    "execution_file": str(self.execution_file),
                    "venue_status": venue_status,
                    "venue_warnings": venue_warnings,
                },
            )
            return PortfolioSyncResult(
                sync_run_id=sync_run_id,
                source="local_jsonl_reconciliation",
                status="ok",
                started_at=started_at,
                completed_at=completed_at,
                previews_ingested=len(previews),
                executions_ingested=len(executions),
                venue_snapshots_ingested=venue_snapshots_ingested,
                balances_ingested=balances_ingested,
                open_orders_ingested=open_orders_ingested,
                fills_ingested=fills_ingested,
                settlements_ingested=settlements_ingested,
                positions_reconciled=positions_reconciled,
                metadata={"venue_status": venue_status, "venue_warnings": venue_warnings},
            )
        except Exception as exc:
            completed_at = self._utc_now()
            self.ledger.record_sync_run(
                sync_run_id=sync_run_id,
                source="local_jsonl_reconciliation",
                status="error",
                started_at=started_at,
                completed_at=completed_at,
                error=str(exc),
                metadata={
                    "preview_file": str(self.preview_file),
                    "execution_file": str(self.execution_file),
                },
            )
            return PortfolioSyncResult(
                sync_run_id=sync_run_id,
                source="local_jsonl_reconciliation",
                status="error",
                started_at=started_at,
                completed_at=completed_at,
                error=str(exc),
            )

    def latest_sync_status(self) -> dict:
        latest = self.ledger.latest_sync_run()
        if latest is None:
            return {
                "status": "never_synced",
                "last_synced_at": None,
                "source": None,
                "stale": True,
            }
        completed_at = latest.get("completed_at") or latest.get("started_at")
        return {
            "status": latest.get("status"),
            "last_synced_at": completed_at,
            "source": latest.get("source"),
            "stale": self._is_stale(completed_at),
            "previews_ingested": latest.get("previews_ingested", 0),
            "executions_ingested": latest.get("executions_ingested", 0),
            "venue_snapshots_ingested": latest.get("venue_snapshots_ingested", 0),
            "balances_ingested": latest.get("balances_ingested", 0),
            "open_orders_ingested": latest.get("open_orders_ingested", 0),
            "fills_ingested": latest.get("fills_ingested", 0),
            "settlements_ingested": latest.get("settlements_ingested", 0),
            "positions_reconciled": latest.get("positions_reconciled", 0),
            "error": latest.get("error"),
        }

    def _is_stale(self, completed_at: str | None) -> bool:
        if not completed_at:
            return True
        try:
            completed = datetime.fromisoformat(completed_at.replace("Z", ""))
        except ValueError:
            return True
        elapsed = datetime.utcnow() - completed
        return elapsed.total_seconds() > self.config.sync_stale_after_seconds

    @staticmethod
    def _load_jsonl(path: Path, model: type[ModelT]) -> list[ModelT]:
        if not path.exists():
            return []
        records: list[ModelT] = []
        with path.open() as handle:
            for line in handle:
                if not line.strip():
                    continue
                records.append(model(**json.loads(line)))
        return records

    @staticmethod
    def _latest_by_id(records: list[ModelT], id_field: str) -> dict[str, ModelT]:
        latest: dict[str, ModelT] = {}
        for record in records:
            latest[str(getattr(record, id_field))] = record
        return latest

    @staticmethod
    def _utc_now() -> str:
        return datetime.utcnow().isoformat() + "Z"
