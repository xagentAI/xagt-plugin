from __future__ import annotations

from typing import Any

from pydantic import BaseModel, Field


class PortfolioSyncResult(BaseModel):
    sync_run_id: str
    source: str
    status: str
    started_at: str
    completed_at: str
    previews_ingested: int = 0
    executions_ingested: int = 0
    venue_snapshots_ingested: int = 0
    balances_ingested: int = 0
    open_orders_ingested: int = 0
    fills_ingested: int = 0
    settlements_ingested: int = 0
    positions_reconciled: int = 0
    error: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
