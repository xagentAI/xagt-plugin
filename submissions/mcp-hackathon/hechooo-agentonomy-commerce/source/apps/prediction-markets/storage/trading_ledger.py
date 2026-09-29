from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
from pathlib import Path
from typing import Any
from uuid import uuid4

from shared.schemas import (
    AgentIdea,
    PredictionMarketExecution,
    PredictionMarketOrderPreview,
    StrategyRecord,
    VenueAccountSnapshot,
    VenuePosition,
)

FAILED_OPERATION_STATES = ("failed", "blocked", "cancelled", "canceled", "expired", "rejected")


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS previews (
  preview_id TEXT PRIMARY KEY,
  user_id TEXT,
  agent_id TEXT,
  platform TEXT NOT NULL,
  market_id TEXT NOT NULL,
  title TEXT NOT NULL,
  outcome TEXT NOT NULL,
  side TEXT NOT NULL,
  amount_usd TEXT NOT NULL,
  limit_price TEXT NOT NULL,
  estimated_contracts TEXT NOT NULL,
  state TEXT NOT NULL,
  next_action TEXT,
  action_id TEXT,
  policy_decision_id TEXT,
  audit_event_ids TEXT NOT NULL DEFAULT '[]',
  market_json TEXT NOT NULL,
  raw_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS executions (
  execution_id TEXT PRIMARY KEY,
  preview_id TEXT NOT NULL,
  user_id TEXT,
  agent_id TEXT,
  platform TEXT,
  market_id TEXT,
  title TEXT,
  outcome TEXT,
  side TEXT,
  amount_usd TEXT,
  limit_price TEXT,
  estimated_contracts TEXT,
  state TEXT NOT NULL,
  execution_mode TEXT NOT NULL,
  submitted INTEGER NOT NULL,
  order_id TEXT,
  reason TEXT,
  next_action TEXT,
  action_id TEXT,
  policy_decision_id TEXT,
  audit_event_ids TEXT NOT NULL DEFAULT '[]',
  raw_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS positions (
  position_id TEXT PRIMARY KEY,
  execution_id TEXT NOT NULL,
  preview_id TEXT NOT NULL,
  platform TEXT NOT NULL,
  market_id TEXT NOT NULL,
  title TEXT NOT NULL,
  outcome TEXT NOT NULL,
  side TEXT NOT NULL,
  status TEXT NOT NULL,
  order_id TEXT,
  contracts TEXT NOT NULL,
  entry_price TEXT NOT NULL,
  mark_price TEXT NOT NULL,
  price_source TEXT NOT NULL,
  cost_basis_usd TEXT NOT NULL,
  current_value_usd TEXT NOT NULL,
  unrealized_pnl_usd TEXT NOT NULL,
  realized_pnl_usd TEXT NOT NULL DEFAULT '0.00',
  action_id TEXT,
  policy_decision_id TEXT,
  audit_event_ids TEXT NOT NULL DEFAULT '[]',
  raw_json TEXT NOT NULL,
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  UNIQUE(execution_id)
);

CREATE TABLE IF NOT EXISTS strategies (
  strategy_id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  agent_id TEXT NOT NULL,
  topic TEXT NOT NULL,
  hypothesis TEXT NOT NULL,
  agent_reasoning_json TEXT NOT NULL DEFAULT '[]',
  status TEXT NOT NULL,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS agent_ideas (
  idea_id TEXT PRIMARY KEY,
  user_id TEXT NOT NULL,
  agent_id TEXT NOT NULL,
  topic TEXT NOT NULL,
  agent_message TEXT NOT NULL,
  recommendation TEXT NOT NULL,
  confidence TEXT,
  market_json TEXT,
  suggested_trade_json TEXT NOT NULL DEFAULT '{}',
  risks_json TEXT NOT NULL DEFAULT '[]',
  status TEXT NOT NULL,
  strategy_id TEXT,
  preview_id TEXT,
  execution_id TEXT,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS strategy_links (
  strategy_id TEXT NOT NULL,
  entity_kind TEXT NOT NULL,
  entity_id TEXT NOT NULL,
  platform TEXT,
  metadata_json TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL,
  PRIMARY KEY(strategy_id, entity_kind, entity_id, platform),
  FOREIGN KEY(strategy_id) REFERENCES strategies(strategy_id)
);

CREATE TABLE IF NOT EXISTS account_balances (
  platform TEXT NOT NULL,
  currency TEXT NOT NULL,
  total TEXT NOT NULL,
  available TEXT NOT NULL,
  locked TEXT NOT NULL,
  raw_json TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  PRIMARY KEY(platform, currency)
);

CREATE TABLE IF NOT EXISTS venue_open_orders (
  platform TEXT NOT NULL,
  order_id TEXT NOT NULL,
  market_id TEXT NOT NULL,
  title TEXT,
  outcome TEXT NOT NULL,
  side TEXT NOT NULL,
  status TEXT NOT NULL,
  contracts TEXT NOT NULL,
  filled_contracts TEXT NOT NULL,
  limit_price TEXT NOT NULL,
  avg_price TEXT,
  cost_basis_usd TEXT NOT NULL,
  raw_json TEXT NOT NULL,
  created_at TEXT,
  updated_at TEXT NOT NULL,
  PRIMARY KEY(platform, order_id)
);

CREATE TABLE IF NOT EXISTS venue_fills (
  platform TEXT NOT NULL,
  fill_id TEXT NOT NULL,
  order_id TEXT,
  market_id TEXT NOT NULL,
  outcome TEXT NOT NULL,
  side TEXT NOT NULL,
  contracts TEXT NOT NULL,
  price TEXT NOT NULL,
  amount_usd TEXT NOT NULL,
  fee_usd TEXT NOT NULL,
  raw_json TEXT NOT NULL,
  filled_at TEXT NOT NULL,
  PRIMARY KEY(platform, fill_id)
);

CREATE TABLE IF NOT EXISTS venue_settlements (
  platform TEXT NOT NULL,
  settlement_id TEXT NOT NULL,
  market_id TEXT NOT NULL,
  title TEXT,
  realized_pnl_usd TEXT NOT NULL,
  payout_usd TEXT NOT NULL,
  raw_json TEXT NOT NULL,
  settled_at TEXT NOT NULL,
  PRIMARY KEY(platform, settlement_id)
);

CREATE TABLE IF NOT EXISTS sync_runs (
  sync_run_id TEXT PRIMARY KEY,
  source TEXT NOT NULL,
  status TEXT NOT NULL,
  started_at TEXT NOT NULL,
  completed_at TEXT,
  previews_ingested INTEGER NOT NULL DEFAULT 0,
  executions_ingested INTEGER NOT NULL DEFAULT 0,
  venue_snapshots_ingested INTEGER NOT NULL DEFAULT 0,
  balances_ingested INTEGER NOT NULL DEFAULT 0,
  open_orders_ingested INTEGER NOT NULL DEFAULT 0,
  fills_ingested INTEGER NOT NULL DEFAULT 0,
  settlements_ingested INTEGER NOT NULL DEFAULT 0,
  positions_reconciled INTEGER NOT NULL DEFAULT 0,
  error TEXT,
  metadata_json TEXT NOT NULL DEFAULT '{}'
);
"""


class TradingLedger:
    def __init__(self, db_file: Path | str) -> None:
        self.db_file = Path(db_file)
        self.db_file.parent.mkdir(parents=True, exist_ok=True)
        self._init_db()

    def upsert_preview(self, preview: PredictionMarketOrderPreview) -> None:
        now = self._utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO previews (
                  preview_id, user_id, agent_id, platform, market_id, title, outcome, side,
                  amount_usd, limit_price, estimated_contracts, state, next_action, action_id,
                  policy_decision_id, audit_event_ids, market_json, raw_json, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(preview_id) DO UPDATE SET
                  state=excluded.state,
                  next_action=excluded.next_action,
                  policy_decision_id=excluded.policy_decision_id,
                  audit_event_ids=excluded.audit_event_ids,
                  market_json=excluded.market_json,
                  raw_json=excluded.raw_json,
                  updated_at=excluded.updated_at
                """,
                (
                    preview.preview_id,
                    preview.user_id,
                    preview.agent_id,
                    preview.platform,
                    preview.market_id,
                    preview.title,
                    preview.outcome,
                    preview.side,
                    preview.amount_usd,
                    str(preview.limit_price),
                    str(preview.estimated_contracts),
                    preview.state,
                    preview.next_action,
                    preview.core_action_id,
                    preview.core_policy_decision_id,
                    json.dumps(preview.core_audit_event_ids),
                    json.dumps(preview.market.model_dump(), ensure_ascii=False),
                    json.dumps(preview.model_dump(), ensure_ascii=False),
                    preview.created_at,
                    now,
                ),
            )
            self._link_strategy_from_metadata(
                conn,
                preview.metadata,
                "preview",
                preview.preview_id,
                preview.platform,
            )

    def upsert_execution(self, execution: PredictionMarketExecution) -> None:
        now = self._utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO executions (
                  execution_id, preview_id, user_id, agent_id, platform, market_id, title,
                  outcome, side, amount_usd, limit_price, estimated_contracts, state,
                  execution_mode, submitted, order_id, reason, next_action, action_id,
                  policy_decision_id, audit_event_ids, raw_json, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(execution_id) DO UPDATE SET
                  state=excluded.state,
                  submitted=excluded.submitted,
                  order_id=excluded.order_id,
                  reason=excluded.reason,
                  next_action=excluded.next_action,
                  raw_json=excluded.raw_json,
                  updated_at=excluded.updated_at
                """,
                (
                    execution.execution_id,
                    execution.preview_id,
                    execution.user_id,
                    execution.agent_id,
                    execution.platform,
                    execution.market_id,
                    execution.title,
                    execution.outcome,
                    execution.side,
                    execution.amount_usd,
                    str(execution.limit_price or "0"),
                    str(execution.estimated_contracts or "0"),
                    execution.state,
                    execution.execution_mode,
                    1 if execution.submitted else 0,
                    execution.order_id,
                    execution.reason,
                    execution.next_action,
                    execution.core_action_id,
                    execution.core_policy_decision_id,
                    json.dumps(execution.core_audit_event_ids),
                    json.dumps(execution.model_dump(), ensure_ascii=False),
                    execution.created_at,
                    now,
                ),
            )
            self._link_strategy_from_metadata(
                conn,
                execution.metadata,
                "execution",
                execution.execution_id,
                execution.platform,
            )
            if execution.order_id:
                self._link_strategy_from_metadata(
                    conn,
                    execution.metadata,
                    "order",
                    execution.order_id,
                    execution.platform,
                )

    def reconcile_position_from_execution(
        self,
        execution: PredictionMarketExecution,
        preview: PredictionMarketOrderPreview | None,
    ) -> bool:
        if not execution.submitted or execution.state != "submitted":
            return False
        amount = self._decimal(execution.amount_usd or "0")
        contracts = self._decimal(execution.estimated_contracts or "0")
        entry_price = self._decimal(execution.limit_price or "0")
        mark_price, price_source = self._mark_price(execution, preview)
        current_value = contracts * mark_price
        unrealized = current_value - amount if (execution.side or "buy") == "buy" else amount - current_value
        position_id = f"pos_{execution.execution_id}"
        now = self._utc_now()
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO positions (
                  position_id, execution_id, preview_id, platform, market_id, title, outcome, side,
                  status, order_id, contracts, entry_price, mark_price, price_source, cost_basis_usd,
                  current_value_usd, unrealized_pnl_usd, realized_pnl_usd, action_id,
                  policy_decision_id, audit_event_ids, raw_json, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(execution_id) DO UPDATE SET
                  status=excluded.status,
                  order_id=excluded.order_id,
                  mark_price=excluded.mark_price,
                  price_source=excluded.price_source,
                  current_value_usd=excluded.current_value_usd,
                  unrealized_pnl_usd=excluded.unrealized_pnl_usd,
                  raw_json=excluded.raw_json,
                  updated_at=excluded.updated_at
                """,
                (
                    position_id,
                    execution.execution_id,
                    execution.preview_id,
                    str(execution.platform or "unknown"),
                    execution.market_id or "",
                    execution.title or "Untitled prediction market",
                    execution.outcome or "Yes",
                    execution.side or "buy",
                    "open",
                    execution.order_id,
                    self._decimal_string(contracts),
                    self._decimal_string(entry_price),
                    self._decimal_string(mark_price),
                    price_source,
                    self._money(amount),
                    self._money(current_value),
                    self._money(unrealized),
                    "0.00",
                    execution.core_action_id,
                    execution.core_policy_decision_id,
                    json.dumps(execution.core_audit_event_ids),
                    json.dumps(execution.model_dump(), ensure_ascii=False),
                    execution.created_at,
                    now,
                ),
            )
        return True

    def upsert_venue_account_snapshot(self, snapshot: VenueAccountSnapshot) -> dict[str, int]:
        counts = {
            "balances": 0,
            "open_orders": 0,
            "fills": 0,
            "positions": 0,
            "settlements": 0,
        }
        with self._connect() as conn:
            for balance in snapshot.balances:
                conn.execute(
                    """
                    INSERT INTO account_balances (
                      platform, currency, total, available, locked, raw_json, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(platform, currency) DO UPDATE SET
                      total=excluded.total,
                      available=excluded.available,
                      locked=excluded.locked,
                      raw_json=excluded.raw_json,
                      updated_at=excluded.updated_at
                    """,
                    (
                        balance.platform,
                        balance.currency,
                        balance.total,
                        balance.available,
                        balance.locked,
                        json.dumps(balance.model_dump(), ensure_ascii=False),
                        balance.updated_at or snapshot.captured_at,
                    ),
                )
                counts["balances"] += 1

            for order in snapshot.open_orders:
                conn.execute(
                    """
                    INSERT INTO venue_open_orders (
                      platform, order_id, market_id, title, outcome, side, status, contracts,
                      filled_contracts, limit_price, avg_price, cost_basis_usd, raw_json,
                      created_at, updated_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(platform, order_id) DO UPDATE SET
                      status=excluded.status,
                      contracts=excluded.contracts,
                      filled_contracts=excluded.filled_contracts,
                      avg_price=excluded.avg_price,
                      cost_basis_usd=excluded.cost_basis_usd,
                      raw_json=excluded.raw_json,
                      updated_at=excluded.updated_at
                    """,
                    (
                        order.platform,
                        order.order_id,
                        order.market_id,
                        order.title,
                        order.outcome,
                        order.side,
                        order.status,
                        order.contracts,
                        order.filled_contracts,
                        order.limit_price,
                        order.avg_price,
                        order.cost_basis_usd,
                        json.dumps(order.model_dump(), ensure_ascii=False),
                        order.created_at,
                        order.updated_at or snapshot.captured_at,
                    ),
                )
                counts["open_orders"] += 1

            for fill in snapshot.fills:
                conn.execute(
                    """
                    INSERT INTO venue_fills (
                      platform, fill_id, order_id, market_id, outcome, side, contracts,
                      price, amount_usd, fee_usd, raw_json, filled_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(platform, fill_id) DO UPDATE SET
                      order_id=excluded.order_id,
                      raw_json=excluded.raw_json
                    """,
                    (
                        fill.platform,
                        fill.fill_id,
                        fill.order_id,
                        fill.market_id,
                        fill.outcome,
                        fill.side,
                        fill.contracts,
                        fill.price,
                        fill.amount_usd,
                        fill.fee_usd,
                        json.dumps(fill.model_dump(), ensure_ascii=False),
                        fill.filled_at,
                    ),
                )
                counts["fills"] += 1

            for position in snapshot.positions:
                self._upsert_venue_position(conn, position)
                counts["positions"] += 1

            for settlement in snapshot.settlements:
                conn.execute(
                    """
                    INSERT INTO venue_settlements (
                      platform, settlement_id, market_id, title, realized_pnl_usd,
                      payout_usd, raw_json, settled_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(platform, settlement_id) DO UPDATE SET
                      realized_pnl_usd=excluded.realized_pnl_usd,
                      payout_usd=excluded.payout_usd,
                      raw_json=excluded.raw_json,
                      settled_at=excluded.settled_at
                    """,
                    (
                        settlement.platform,
                        settlement.settlement_id,
                        settlement.market_id,
                        settlement.title,
                        settlement.realized_pnl_usd,
                        settlement.payout_usd,
                        json.dumps(settlement.model_dump(), ensure_ascii=False),
                        settlement.settled_at,
                    ),
                )
                counts["settlements"] += 1
        return counts

    def upsert_strategy(self, strategy: StrategyRecord) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO strategies (
                  strategy_id, user_id, agent_id, topic, hypothesis, agent_reasoning_json,
                  status, metadata_json, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(strategy_id) DO UPDATE SET
                  topic=excluded.topic,
                  hypothesis=excluded.hypothesis,
                  agent_reasoning_json=excluded.agent_reasoning_json,
                  status=excluded.status,
                  metadata_json=excluded.metadata_json,
                  updated_at=excluded.updated_at
                """,
                (
                    strategy.strategy_id,
                    strategy.user_id,
                    strategy.agent_id,
                    strategy.topic,
                    strategy.hypothesis,
                    json.dumps(strategy.agent_reasoning, ensure_ascii=False),
                    strategy.status,
                    json.dumps(strategy.metadata, ensure_ascii=False),
                    strategy.created_at,
                    strategy.updated_at,
                ),
            )

    def upsert_agent_idea(self, idea: AgentIdea) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO agent_ideas (
                  idea_id, user_id, agent_id, topic, agent_message, recommendation,
                  confidence, market_json, suggested_trade_json, risks_json, status,
                  strategy_id, preview_id, execution_id, metadata_json, created_at, updated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(idea_id) DO UPDATE SET
                  topic=excluded.topic,
                  agent_message=excluded.agent_message,
                  recommendation=excluded.recommendation,
                  confidence=excluded.confidence,
                  market_json=excluded.market_json,
                  suggested_trade_json=excluded.suggested_trade_json,
                  risks_json=excluded.risks_json,
                  status=excluded.status,
                  strategy_id=excluded.strategy_id,
                  preview_id=excluded.preview_id,
                  execution_id=excluded.execution_id,
                  metadata_json=excluded.metadata_json,
                  updated_at=excluded.updated_at
                """,
                (
                    idea.idea_id,
                    idea.user_id,
                    idea.agent_id,
                    idea.topic,
                    idea.agent_message,
                    idea.recommendation,
                    str(idea.confidence) if idea.confidence is not None else None,
                    json.dumps(idea.market, ensure_ascii=False) if idea.market is not None else None,
                    json.dumps(idea.suggested_trade, ensure_ascii=False),
                    json.dumps(idea.risks, ensure_ascii=False),
                    idea.status,
                    idea.strategy_id,
                    idea.preview_id,
                    idea.execution_id,
                    json.dumps(idea.metadata, ensure_ascii=False),
                    idea.created_at,
                    idea.updated_at,
                ),
            )
            if idea.strategy_id:
                self._link_strategy_entity_conn(
                    conn,
                    idea.strategy_id,
                    "idea",
                    idea.idea_id,
                    (idea.market or {}).get("platform"),
                    idea.metadata,
                )

    def get_agent_idea(self, idea_id: str) -> AgentIdea | None:
        rows = self._fetch_all("SELECT * FROM agent_ideas WHERE idea_id = ?", (idea_id,))
        if not rows:
            return None
        return self._build_agent_idea(rows[0])

    def list_agent_ideas(self, limit: int = 20) -> list[dict[str, Any]]:
        rows = self._fetch_all(
            """
            SELECT *
            FROM agent_ideas
            WHERE status NOT IN ('failed', 'blocked', 'cancelled', 'canceled', 'expired', 'rejected')
              AND NOT EXISTS (
                SELECT 1
                FROM executions
                WHERE executions.execution_id = agent_ideas.execution_id
                  AND (
                    executions.submitted != 1
                    OR executions.state NOT IN ('submitted', 'matched', 'filled', 'settled')
                  )
              )
              AND NOT EXISTS (
                SELECT 1
                FROM previews
                WHERE previews.preview_id = agent_ideas.preview_id
                  AND previews.state IN ('failed', 'blocked', 'cancelled', 'canceled', 'expired', 'rejected')
              )
            ORDER BY updated_at DESC
            LIMIT ?
            """,
            (limit,),
        )
        return [self._build_agent_idea(row).model_dump() for row in rows]

    def link_strategy_entity(
        self,
        strategy_id: str,
        entity_kind: str,
        entity_id: str,
        platform: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        with self._connect() as conn:
            self._link_strategy_entity_conn(conn, strategy_id, entity_kind, entity_id, platform, metadata)

    def _upsert_venue_position(self, conn: sqlite3.Connection, position: VenuePosition) -> None:
        execution_id = f"venue_{position.platform}_{position.position_id}"
        raw_json = json.dumps(position.model_dump(), ensure_ascii=False)
        conn.execute(
            """
            INSERT INTO positions (
              position_id, execution_id, preview_id, platform, market_id, title, outcome, side,
              status, order_id, contracts, entry_price, mark_price, price_source, cost_basis_usd,
              current_value_usd, unrealized_pnl_usd, realized_pnl_usd, action_id,
              policy_decision_id, audit_event_ids, raw_json, created_at, updated_at
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(position_id) DO UPDATE SET
              status=excluded.status,
              order_id=excluded.order_id,
              contracts=excluded.contracts,
              entry_price=excluded.entry_price,
              mark_price=excluded.mark_price,
              price_source=excluded.price_source,
              cost_basis_usd=excluded.cost_basis_usd,
              current_value_usd=excluded.current_value_usd,
              unrealized_pnl_usd=excluded.unrealized_pnl_usd,
              realized_pnl_usd=excluded.realized_pnl_usd,
              raw_json=excluded.raw_json,
              updated_at=excluded.updated_at
            """,
            (
                position.position_id,
                execution_id,
                "",
                position.platform,
                position.market_id,
                position.title or "Untitled prediction market",
                position.outcome,
                position.side,
                position.status,
                position.order_id,
                position.contracts,
                position.entry_price,
                position.mark_price,
                "venue_account_snapshot",
                self._money(self._decimal(position.cost_basis_usd)),
                self._money(self._decimal(position.current_value_usd)),
                self._money(self._decimal(position.unrealized_pnl_usd)),
                self._money(self._decimal(position.realized_pnl_usd)),
                None,
                None,
                "[]",
                raw_json,
                position.updated_at,
                position.updated_at,
            ),
        )

    def record_sync_run(
        self,
        source: str,
        status: str,
        started_at: str,
        completed_at: str | None = None,
        previews_ingested: int = 0,
        executions_ingested: int = 0,
        positions_reconciled: int = 0,
        venue_snapshots_ingested: int = 0,
        balances_ingested: int = 0,
        open_orders_ingested: int = 0,
        fills_ingested: int = 0,
        settlements_ingested: int = 0,
        error: str | None = None,
        metadata: dict[str, Any] | None = None,
        sync_run_id: str | None = None,
    ) -> str:
        sync_run_id = sync_run_id or f"sync_{uuid4().hex[:12]}"
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO sync_runs (
                  sync_run_id, source, status, started_at, completed_at, previews_ingested,
                  executions_ingested, venue_snapshots_ingested, balances_ingested,
                  open_orders_ingested, fills_ingested, settlements_ingested,
                  positions_reconciled, error, metadata_json
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    sync_run_id,
                    source,
                    status,
                    started_at,
                    completed_at,
                    previews_ingested,
                    executions_ingested,
                    venue_snapshots_ingested,
                    balances_ingested,
                    open_orders_ingested,
                    fills_ingested,
                    settlements_ingested,
                    positions_reconciled,
                    error,
                    json.dumps(metadata or {}, ensure_ascii=False),
                ),
            )
        return sync_run_id

    def list_positions(self) -> list[dict[str, Any]]:
        return self._fetch_all("SELECT * FROM positions ORDER BY updated_at DESC")

    def list_account_balances(self) -> list[dict[str, Any]]:
        return self._fetch_all("SELECT * FROM account_balances ORDER BY platform, currency")

    def list_open_orders(self) -> list[dict[str, Any]]:
        return self._fetch_all("SELECT * FROM venue_open_orders WHERE status NOT IN ('filled', 'cancelled', 'canceled', 'closed') ORDER BY updated_at DESC")

    def list_fills(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._fetch_all("SELECT * FROM venue_fills ORDER BY filled_at DESC LIMIT ?", (limit,))

    def list_settlements(self, limit: int = 100) -> list[dict[str, Any]]:
        return self._fetch_all("SELECT * FROM venue_settlements ORDER BY settled_at DESC LIMIT ?", (limit,))

    def list_strategy_performance(self) -> list[dict[str, Any]]:
        strategies = self._fetch_all("SELECT * FROM strategies ORDER BY updated_at DESC")
        if not strategies:
            return []

        links = self._fetch_all("SELECT * FROM strategy_links")
        links_by_strategy: dict[str, list[dict[str, Any]]] = {}
        for link in links:
            links_by_strategy.setdefault(link["strategy_id"], []).append(link)

        open_orders = self.list_open_orders()
        fills = self.list_fills(limit=1000)
        positions = self.list_positions()
        settlements = self.list_settlements(limit=1000)

        performance = [
            self._build_strategy_performance(
                strategy,
                links_by_strategy.get(strategy["strategy_id"], []),
                open_orders,
                fills,
                positions,
                settlements,
            )
            for strategy in strategies
        ]
        return sorted(performance, key=lambda item: item["updated_at"], reverse=True)

    def _build_agent_idea(self, row: dict[str, Any]) -> AgentIdea:
        return AgentIdea(
            idea_id=row["idea_id"],
            user_id=row["user_id"],
            agent_id=row["agent_id"],
            topic=row["topic"],
            agent_message=row["agent_message"],
            recommendation=row["recommendation"],
            confidence=float(row["confidence"]) if row.get("confidence") is not None else None,
            market=self._loads(row.get("market_json")) if row.get("market_json") else None,
            suggested_trade=self._loads(row["suggested_trade_json"]),
            risks=self._loads(row["risks_json"]),
            status=row["status"],
            strategy_id=row["strategy_id"],
            preview_id=row["preview_id"],
            execution_id=row["execution_id"],
            metadata=self._loads(row["metadata_json"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    def list_pending_actions(self) -> list[dict[str, Any]]:
        attempted_preview_ids = {row["preview_id"] for row in self._fetch_all("SELECT preview_id FROM executions")}
        return [
            row
            for row in self._fetch_all("SELECT * FROM previews WHERE state = 'confirmation_required' ORDER BY created_at DESC")
            if row["preview_id"] not in attempted_preview_ids
        ]

    def list_timeline(self, limit: int = 100) -> list[dict[str, Any]]:
        items: list[dict[str, Any]] = []
        for row in self._fetch_all(
            "SELECT * FROM sync_runs WHERE status IN ('ok', 'success', 'synced')"
        ):
            items.append({
                "kind": "sync_run",
                "id": row["sync_run_id"],
                "preview_id": None,
                "platform": row["source"],
                "title": "Portfolio sync",
                "state": row["status"],
                "description": f"{row['source']} sync {row['status']}",
                "created_at": row["completed_at"] or row["started_at"],
                "action_id": None,
                "policy_decision_id": None,
                "audit_event_ids": [],
                "metadata": self._loads(row["metadata_json"]),
            })
        for row in self._fetch_all(
            "SELECT * FROM executions WHERE submitted = 1 AND state IN ('submitted', 'matched', 'filled', 'settled')"
        ):
            if row["state"] in FAILED_OPERATION_STATES:
                continue
            items.append({
                "kind": "execution",
                "id": row["execution_id"],
                "preview_id": row["preview_id"],
                "platform": row["platform"],
                "title": row["title"],
                "state": row["state"],
                "description": row["reason"] or f"{row['platform']} execution {row['state']}",
                "created_at": row["created_at"],
                "action_id": row["action_id"],
                "policy_decision_id": row["policy_decision_id"],
                "audit_event_ids": self._loads(row["audit_event_ids"]),
                "metadata": self._loads(row["raw_json"]).get("metadata", {}),
            })
        attempted_preview_ids = {row["preview_id"] for row in self._fetch_all("SELECT preview_id FROM executions")}
        for row in self._fetch_all("SELECT * FROM previews"):
            if row["preview_id"] in attempted_preview_ids:
                continue
            items.append({
                "kind": "preview",
                "id": row["preview_id"],
                "preview_id": row["preview_id"],
                "platform": row["platform"],
                "title": row["title"],
                "state": row["state"],
                "description": f"{row['platform']} {row['side']} {row['outcome']} preview needs {row['next_action']}",
                "created_at": row["created_at"],
                "action_id": row["action_id"],
                "policy_decision_id": row["policy_decision_id"],
                "audit_event_ids": self._loads(row["audit_event_ids"]),
                "metadata": self._loads(row["raw_json"]).get("metadata", {}),
            })
        return sorted(items, key=lambda item: item["created_at"], reverse=True)[:limit]

    def latest_sync_run(self) -> dict[str, Any] | None:
        rows = self._fetch_all(
            """
            SELECT *
            FROM sync_runs
            WHERE status IN ('ok', 'success', 'synced')
            ORDER BY COALESCE(completed_at, started_at) DESC
            LIMIT 1
            """
        )
        return rows[0] if rows else None

    def _init_db(self) -> None:
        with self._connect() as conn:
            conn.execute("PRAGMA journal_mode=WAL")
            conn.executescript(SCHEMA_SQL)
            self._ensure_column(conn, "sync_runs", "venue_snapshots_ingested", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(conn, "sync_runs", "balances_ingested", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(conn, "sync_runs", "open_orders_ingested", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(conn, "sync_runs", "fills_ingested", "INTEGER NOT NULL DEFAULT 0")
            self._ensure_column(conn, "sync_runs", "settlements_ingested", "INTEGER NOT NULL DEFAULT 0")

    def _build_strategy_performance(
        self,
        strategy: dict[str, Any],
        links: list[dict[str, Any]],
        open_orders: list[dict[str, Any]],
        fills: list[dict[str, Any]],
        positions: list[dict[str, Any]],
        settlements: list[dict[str, Any]],
    ) -> dict[str, Any]:
        linked_entities: dict[str, list[str]] = {}
        for link in links:
            linked_entities.setdefault(link["entity_kind"], []).append(link["entity_id"])

        linked_orders = set(linked_entities.get("order", []))
        linked_fills = set(linked_entities.get("fill", []))
        linked_positions = set(linked_entities.get("position", []))
        linked_settlements = set(linked_entities.get("settlement", []))

        strategy_orders = [
            order
            for order in open_orders
            if order["order_id"] in linked_orders
        ]
        strategy_fills = [
            fill
            for fill in fills
            if fill["fill_id"] in linked_fills or (fill.get("order_id") and fill["order_id"] in linked_orders)
        ]
        strategy_positions = [
            position
            for position in positions
            if position["position_id"] in linked_positions or (position.get("order_id") and position["order_id"] in linked_orders)
        ]
        strategy_settlements = [
            settlement
            for settlement in settlements
            if settlement["settlement_id"] in linked_settlements
        ]

        capital_deployed = sum((self._decimal(position["cost_basis_usd"]) for position in strategy_positions), Decimal("0"))
        if capital_deployed == 0:
            capital_deployed = sum((self._decimal(fill["amount_usd"]) for fill in strategy_fills), Decimal("0"))
        if capital_deployed == 0:
            capital_deployed = sum((self._decimal(order["cost_basis_usd"]) for order in strategy_orders), Decimal("0"))

        current_value = sum((self._decimal(position["current_value_usd"]) for position in strategy_positions), Decimal("0"))
        unrealized = sum((self._decimal(position["unrealized_pnl_usd"]) for position in strategy_positions), Decimal("0"))
        realized = sum((self._decimal(settlement["realized_pnl_usd"]) for settlement in strategy_settlements), Decimal("0"))
        total_pnl = unrealized + realized
        total_pnl_pct = (total_pnl / capital_deployed * Decimal("100")) if capital_deployed > 0 else Decimal("0")
        platforms = sorted(
            {
                value
                for value in [
                    *(order["platform"] for order in strategy_orders),
                    *(fill["platform"] for fill in strategy_fills),
                    *(position["platform"] for position in strategy_positions),
                    *(settlement["platform"] for settlement in strategy_settlements),
                    *(link["platform"] for link in links if link.get("platform")),
                ]
                if value
            }
        )

        return {
            "strategy_id": strategy["strategy_id"],
            "user_id": strategy["user_id"],
            "agent_id": strategy["agent_id"],
            "topic": strategy["topic"],
            "hypothesis": strategy["hypothesis"],
            "agent_reasoning": self._loads(strategy["agent_reasoning_json"]),
            "status": strategy["status"],
            "capital_deployed_usd": self._money(capital_deployed),
            "current_value_usd": self._money(current_value),
            "realized_pnl_usd": self._money(realized),
            "unrealized_pnl_usd": self._money(unrealized),
            "total_pnl_usd": self._money(total_pnl),
            "total_pnl_pct": self._money(total_pnl_pct),
            "open_orders": len(strategy_orders),
            "fills": len(strategy_fills),
            "open_positions": len([position for position in strategy_positions if position["status"] == "open"]),
            "settlements": len(strategy_settlements),
            "platforms": platforms,
            "linked_entities": {kind: sorted(ids) for kind, ids in sorted(linked_entities.items())},
            "metadata": self._loads(strategy["metadata_json"]),
            "created_at": strategy["created_at"],
            "updated_at": strategy["updated_at"],
        }

    def _link_strategy_from_metadata(
        self,
        conn: sqlite3.Connection,
        metadata: dict[str, Any] | None,
        entity_kind: str,
        entity_id: str,
        platform: str | None,
    ) -> None:
        strategy_id = (metadata or {}).get("strategy_id")
        if strategy_id:
            self._link_strategy_entity_conn(conn, strategy_id, entity_kind, entity_id, platform, metadata)

    def _link_strategy_entity_conn(
        self,
        conn: sqlite3.Connection,
        strategy_id: str,
        entity_kind: str,
        entity_id: str,
        platform: str | None = None,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        conn.execute(
            """
            INSERT OR IGNORE INTO strategy_links (
              strategy_id, entity_kind, entity_id, platform, metadata_json, created_at
            )
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                strategy_id,
                entity_kind,
                entity_id,
                platform,
                json.dumps(metadata or {}, ensure_ascii=False),
                self._utc_now(),
            ),
        )

    def _connect(self) -> sqlite3.Connection:
        conn = sqlite3.connect(self.db_file)
        conn.row_factory = sqlite3.Row
        return conn

    def _fetch_all(self, sql: str, args: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
        with self._connect() as conn:
            return [dict(row) for row in conn.execute(sql, args).fetchall()]

    @staticmethod
    def _ensure_column(conn: sqlite3.Connection, table: str, column: str, column_type: str) -> None:
        columns = {row["name"] for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
        if column not in columns:
            conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {column_type}")

    @staticmethod
    def _mark_price(execution: PredictionMarketExecution, preview: PredictionMarketOrderPreview | None) -> tuple[Decimal, str]:
        market = preview.market if preview else None
        outcome = (execution.outcome or "Yes").lower()
        if market is not None:
            price = market.no_price if outcome == "no" else market.yes_price
            if price is not None:
                return TradingLedger._decimal(price), "preview_market_snapshot"
        return TradingLedger._decimal(execution.limit_price or "0"), "entry_price_fallback"

    @staticmethod
    def _loads(value: str | None) -> Any:
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
    def _decimal_string(value: Decimal) -> str:
        return format(value.normalize(), "f")

    @staticmethod
    def _utc_now() -> str:
        return datetime.utcnow().isoformat() + "Z"
