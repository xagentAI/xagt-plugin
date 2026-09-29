from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field


class PortfolioSummary(BaseModel):
    portfolio_value_usd: str
    current_value_usd: str
    capital_deployed_usd: str
    available_budget_usd: str | None = None
    available_budget_status: Literal["ready", "unavailable"] = "unavailable"
    realized_pnl_usd: str
    unrealized_pnl_usd: str
    total_pnl_usd: str
    total_pnl_pct: str
    open_positions: int
    open_orders: int = 0
    fills_24h: int = 0
    settlements_24h: int = 0
    active_strategies: int = 0
    best_strategy_id: str | None = None
    pending_confirmations: int
    submitted_executions: int
    win_rate_pct: str
    account_equity_usd: str = "0.00"
    available_cash_usd: str = "0.00"
    locked_cash_usd: str = "0.00"
    platform_exposure_usd: dict[str, str] = Field(default_factory=dict)
    last_updated_at: str
    last_synced_at: str | None = None
    sync_status: str = "never_synced"
    sync_source: str | None = None
    sync_stale: bool = True


class PortfolioPosition(BaseModel):
    position_id: str
    execution_id: str
    preview_id: str
    platform: str
    market_id: str
    title: str
    outcome: str
    side: str
    status: str
    order_id: str | None = None
    entry_price: float
    current_price: float
    price_source: str
    contracts: str
    cost_basis_usd: str
    current_value_usd: str
    unrealized_pnl_usd: str
    pnl_pct: str
    action_id: str | None = None
    policy_decision_id: str | None = None
    audit_event_ids: list[str] = Field(default_factory=list)
    created_at: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class PendingAgentAction(BaseModel):
    preview_id: str
    platform: str
    market_id: str
    title: str
    outcome: str
    side: str
    amount_usd: str
    limit_price: float
    next_action: str
    action_id: str | None = None
    policy_decision_id: str | None = None
    audit_event_ids: list[str] = Field(default_factory=list)
    created_at: str


class PortfolioAccountBalance(BaseModel):
    platform: str
    currency: str
    total: str
    available: str
    locked: str
    updated_at: str


class PortfolioOpenOrder(BaseModel):
    platform: str
    order_id: str
    market_id: str
    title: str | None = None
    outcome: str
    side: str
    status: str
    contracts: str
    filled_contracts: str
    limit_price: str
    avg_price: str | None = None
    cost_basis_usd: str
    created_at: str | None = None
    updated_at: str


class PortfolioFill(BaseModel):
    platform: str
    fill_id: str
    order_id: str | None = None
    market_id: str
    outcome: str
    side: str
    contracts: str
    price: str
    amount_usd: str
    fee_usd: str
    filled_at: str


class PortfolioSettlement(BaseModel):
    platform: str
    settlement_id: str
    market_id: str
    title: str | None = None
    realized_pnl_usd: str
    payout_usd: str
    settled_at: str


class StrategyPerformance(BaseModel):
    strategy_id: str
    user_id: str
    agent_id: str
    topic: str
    hypothesis: str
    agent_reasoning: list[str] = Field(default_factory=list)
    status: str
    capital_deployed_usd: str
    current_value_usd: str
    realized_pnl_usd: str
    unrealized_pnl_usd: str
    total_pnl_usd: str
    total_pnl_pct: str
    open_orders: int
    fills: int
    open_positions: int
    settlements: int
    platforms: list[str] = Field(default_factory=list)
    linked_entities: dict[str, list[str]] = Field(default_factory=dict)
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str
    updated_at: str


class PortfolioAgentIdea(BaseModel):
    idea_id: str
    user_id: str
    agent_id: str
    topic: str
    agent_message: str
    recommendation: str
    confidence: float | None = None
    market: dict[str, Any] | None = None
    suggested_trade: dict[str, Any] = Field(default_factory=dict)
    risks: list[str] = Field(default_factory=list)
    status: str
    strategy_id: str | None = None
    preview_id: str | None = None
    execution_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str
    updated_at: str


class PortfolioTimelineItem(BaseModel):
    kind: str
    id: str
    preview_id: str | None = None
    platform: str | None = None
    title: str | None = None
    state: str | None = None
    description: str
    created_at: str
    action_id: str | None = None
    policy_decision_id: str | None = None
    audit_event_ids: list[str] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class PortfolioFundingStatus(BaseModel):
    status: str = "unavailable"
    settlement_rail: str | None = None
    native_facilitator_ready: bool = False
    relayer_address: str | None = None
    available_budget_usdc_by_venue: dict[str, str] = Field(default_factory=dict)
    settled_amount_usdc_by_venue: dict[str, str] = Field(default_factory=dict)
    bridge_status: str | None = None
    polymarket_deposit_address: str | None = None
    pusd_buying_power_usdc: str | None = None
    spending_authorization_count: int = 0
    receipt_count: int = 0
    latest_receipt_tx_hash: str | None = None
    error: str | None = None


class PortfolioSnapshot(BaseModel):
    summary: PortfolioSummary
    funding: PortfolioFundingStatus = Field(default_factory=PortfolioFundingStatus)
    strategies: list[StrategyPerformance] = Field(default_factory=list)
    agent_ideas: list[PortfolioAgentIdea] = Field(default_factory=list)
    positions: list[PortfolioPosition] = Field(default_factory=list)
    account_balances: list[PortfolioAccountBalance] = Field(default_factory=list)
    open_orders: list[PortfolioOpenOrder] = Field(default_factory=list)
    recent_fills: list[PortfolioFill] = Field(default_factory=list)
    recent_settlements: list[PortfolioSettlement] = Field(default_factory=list)
    pending_actions: list[PendingAgentAction] = Field(default_factory=list)
    timeline: list[PortfolioTimelineItem] = Field(default_factory=list)
