from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, Field

Platform = Literal["polymarket", "kalshi"]


class StrategyRecord(BaseModel):
    strategy_id: str
    user_id: str
    agent_id: str
    topic: str
    hypothesis: str
    agent_reasoning: list[str] = Field(default_factory=list)
    status: Literal["draft", "active", "paused", "closed"] = "active"
    created_at: str
    updated_at: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentIdea(BaseModel):
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
    status: Literal["proposed", "preview_created", "executed", "dismissed", "failed"] = "proposed"
    strategy_id: str | None = None
    preview_id: str | None = None
    execution_id: str | None = None
    created_at: str
    updated_at: str
    metadata: dict[str, Any] = Field(default_factory=dict)


class UnifiedMarket(BaseModel):
    platform: Platform
    market_id: str
    event_id: str | None = None
    title: str
    subtitle: str | None = None
    category: str | None = None
    url: str | None = None
    status: str = "unknown"
    yes_price: float | None = None
    no_price: float | None = None
    bid_ask_spread: float | None = None
    liquidity_usd: float | None = None
    volume_24h_usd: float | None = None
    end_time: str | None = None
    rules_summary: str | None = None
    tradable: bool = False
    execution_ready: bool = False
    raw: dict[str, Any] = Field(default_factory=dict)


class SearchMarketsRequest(BaseModel):
    query: str | None = None
    platforms: list[Platform] = Field(default_factory=lambda: ["polymarket", "kalshi"])
    limit: int = 20
    tradable_only: bool = True


class SearchMarketsResult(BaseModel):
    source: str = "clink_prediction_markets_router"
    source_detail: str
    markets: list[UnifiedMarket]
    count: int


class ScoredMarket(BaseModel):
    market: UnifiedMarket
    score: float
    rationale: list[str] = Field(default_factory=list)


class ScoreMarketsRequest(BaseModel):
    query: str | None = None
    markets: list[UnifiedMarket]
    max_results: int = 5


class ScoreMarketsResult(BaseModel):
    source: str = "clink_prediction_markets_router"
    query: str | None = None
    opportunities: list[ScoredMarket]
    count: int


class CreateOrderPreviewRequest(BaseModel):
    user_id: str
    agent_id: str = "external_prediction_agent"
    market: UnifiedMarket
    outcome: str = "Yes"
    side: Literal["buy", "sell"] = "buy"
    amount_usd: str
    limit_price: float | None = None
    max_slippage_bps: int = 100
    requires_user_confirmation: bool = True
    live_mode: bool = False
    metadata: dict[str, Any] = Field(default_factory=dict)


class PredictionMarketOrderPreview(BaseModel):
    preview_id: str
    user_id: str
    agent_id: str
    platform: Platform
    market_id: str
    title: str
    outcome: str
    side: Literal["buy", "sell"]
    amount_usd: str
    limit_price: float
    estimated_contracts: float
    max_slippage_bps: int
    max_slippage_usd: str
    worst_case_price: float
    state: str
    execution_mode: str = "preview_only"
    next_action: str
    requires_user_confirmation: bool = True
    live_mode: bool = False
    core_action_id: str | None = None
    core_policy_decision_id: str | None = None
    core_audit_event_ids: list[str] = Field(default_factory=list)
    core_policy_decision: dict[str, Any] | None = None
    market: UnifiedMarket
    metadata: dict[str, Any] = Field(default_factory=dict)
    created_at: str
    expires_at: str
    event_log: list[dict[str, Any]] = Field(default_factory=list)


class OrderPreviewLookupRequest(BaseModel):
    preview_id: str


class PlatformExecutionReadiness(BaseModel):
    platform: str
    ready: bool = False
    missing: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    status: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class ExecutionReadiness(BaseModel):
    live_ready: bool
    live_mode_enabled: bool
    missing: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    platforms: dict[str, PlatformExecutionReadiness] = Field(default_factory=dict)
    next_action: str
    configured: dict[str, Any] = Field(default_factory=dict)


class ExecutePredictionMarketOrderRequest(BaseModel):
    preview_id: str
    user_confirmed: bool = False
    live_submission_confirmed: bool = False
    confirmation_message: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class CreatePolymarketOrderSigningSessionRequest(BaseModel):
    preview_id: str
    user_confirmed: bool = False
    live_submission_confirmed: bool = False
    confirmation_message: str | None = None
    expires_in_minutes: int = 10
    metadata: dict[str, Any] = Field(default_factory=dict)


class CompletePolymarketOrderSigningSessionRequest(BaseModel):
    signed_order: dict[str, Any]
    wallet_address: str | None = None
    order_type: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class PolymarketOrderSigningSession(BaseModel):
    session_id: str
    preview_id: str
    user_id: str | None = None
    binding_id: str | None = None
    projection_hash: str | None = None
    revision: int = 0
    agent_id: str | None = None
    market_id: str | None = None
    title: str | None = None
    outcome: str | None = None
    side: Literal["buy", "sell"] | None = None
    amount_usd: str | None = None
    limit_price: float | None = None
    order_type: str | None = None
    token_id: str | None = None
    order_payload: dict[str, Any] = Field(default_factory=dict)
    signing_url: str | None = None
    status: str
    reason: str | None = None
    next_action: str | None = None
    signed_order: dict[str, Any] | None = None
    execution_id: str | None = None
    core_action_id: str | None = None
    core_policy_decision_id: str | None = None
    core_audit_event_ids: list[str] = Field(default_factory=list)
    created_at: str
    expires_at: str | None = None
    completed_at: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    event_log: list[dict[str, Any]] = Field(default_factory=list)


class PredictionMarketExecution(BaseModel):
    execution_id: str
    preview_id: str
    user_id: str | None = None
    agent_id: str | None = None
    platform: Platform | None = None
    market_id: str | None = None
    title: str | None = None
    outcome: str | None = None
    side: Literal["buy", "sell"] | None = None
    amount_usd: str | None = None
    limit_price: float | None = None
    estimated_contracts: float | None = None
    state: str
    execution_mode: str
    submitted: bool = False
    live_mode_enabled: bool = False
    order_id: str | None = None
    tx_hash: str | None = None
    reason: str | None = None
    next_action: str | None = None
    core_action_id: str | None = None
    core_policy_decision_id: str | None = None
    core_audit_event_ids: list[str] = Field(default_factory=list)
    created_at: str
    event_log: list[dict[str, Any]] = Field(default_factory=list)
    metadata: dict[str, Any] = Field(default_factory=dict)


class VenueAccountBalance(BaseModel):
    platform: str
    currency: str
    total: str
    available: str
    locked: str = "0.00"
    raw: dict[str, Any] = Field(default_factory=dict)
    updated_at: str | None = None


class VenueOpenOrder(BaseModel):
    platform: str
    order_id: str
    market_id: str
    title: str | None = None
    outcome: str = "Yes"
    side: Literal["buy", "sell"] = "buy"
    status: str
    contracts: str
    filled_contracts: str = "0"
    limit_price: str
    avg_price: str | None = None
    cost_basis_usd: str = "0.00"
    created_at: str | None = None
    updated_at: str | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class VenueFill(BaseModel):
    platform: str
    fill_id: str
    order_id: str | None = None
    market_id: str
    outcome: str = "Yes"
    side: Literal["buy", "sell"] = "buy"
    contracts: str
    price: str
    amount_usd: str
    fee_usd: str = "0.00"
    filled_at: str
    raw: dict[str, Any] = Field(default_factory=dict)


class VenuePosition(BaseModel):
    platform: str
    position_id: str
    market_id: str
    title: str | None = None
    outcome: str = "Yes"
    side: Literal["buy", "sell"] = "buy"
    status: str = "open"
    order_id: str | None = None
    contracts: str
    entry_price: str
    mark_price: str
    cost_basis_usd: str
    current_value_usd: str
    unrealized_pnl_usd: str
    realized_pnl_usd: str = "0.00"
    updated_at: str
    raw: dict[str, Any] = Field(default_factory=dict)


class VenueSettlement(BaseModel):
    platform: str
    settlement_id: str
    market_id: str
    title: str | None = None
    realized_pnl_usd: str
    payout_usd: str
    settled_at: str
    raw: dict[str, Any] = Field(default_factory=dict)


class VenueAccountSnapshot(BaseModel):
    platform: str
    status: str
    captured_at: str
    balances: list[VenueAccountBalance] = Field(default_factory=list)
    open_orders: list[VenueOpenOrder] = Field(default_factory=list)
    fills: list[VenueFill] = Field(default_factory=list)
    positions: list[VenuePosition] = Field(default_factory=list)
    settlements: list[VenueSettlement] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
    raw: dict[str, Any] = Field(default_factory=dict)


class PredictionMarketDecisionRequest(BaseModel):
    topic: str
    goal: str | None = None
    platforms: list[Platform] = Field(default_factory=lambda: ["polymarket", "kalshi"])
    markets: list[UnifiedMarket] | None = None
    max_results: int = 5
    tradable_only: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class VenueComparison(BaseModel):
    platform: Platform
    market: UnifiedMarket
    topic_match_score: float
    tradability_score: float
    liquidity_score: float
    spread_score: float
    execution_score: float
    resolution_score: float
    risk_penalty: float
    overall_score: float
    rationale: list[str] = Field(default_factory=list)
    risk_flags: list[str] = Field(default_factory=list)


class PredictionMarketDecisionResult(BaseModel):
    topic: str
    goal: str | None = None
    recommended_action: Literal["single_platform_preview", "no_trade", "wait"]
    recommended_platform: Literal["polymarket", "kalshi", "none"]
    selected_markets: list[UnifiedMarket] = Field(default_factory=list)
    comparison: list[VenueComparison] = Field(default_factory=list)
    risk_flags: list[str] = Field(default_factory=list)
    reasoning: list[str] = Field(default_factory=list)
    next_tool_call: dict[str, Any] | None = None


class PredictionMarketContextRequest(BaseModel):
    topic: str
    goal: str | None = None
    platforms: list[Platform] = Field(default_factory=lambda: ["polymarket", "kalshi"])
    markets: list[UnifiedMarket] | None = None
    max_results: int = 8
    tradable_only: bool = True
    metadata: dict[str, Any] = Field(default_factory=dict)


class MarketEvidence(BaseModel):
    platform: Platform
    market: UnifiedMarket
    topic_match_score: float
    tradability_score: float
    liquidity_score: float
    spread_score: float
    execution_score: float
    resolution_score: float
    risk_penalty: float
    quality_score: float
    evidence_notes: list[str] = Field(default_factory=list)
    risk_flags: list[str] = Field(default_factory=list)


class PredictionMarketContextResult(BaseModel):
    topic: str
    goal: str | None = None
    agent_role: Literal["hermes_decides"] = "hermes_decides"
    clink_role: Literal["context_and_execution_infrastructure"] = "context_and_execution_infrastructure"
    markets_by_platform: dict[str, list[UnifiedMarket]] = Field(default_factory=dict)
    evidence: list[MarketEvidence] = Field(default_factory=list)
    available_routes: list[Literal["single_platform_preview", "wait", "no_trade"]] = Field(default_factory=list)
    suggested_next_tools: dict[str, str] = Field(default_factory=dict)
    risk_flags: list[str] = Field(default_factory=list)
    hermes_prompt_hints: list[str] = Field(default_factory=list)
    execution_constraints: dict[str, Any] = Field(default_factory=dict)
