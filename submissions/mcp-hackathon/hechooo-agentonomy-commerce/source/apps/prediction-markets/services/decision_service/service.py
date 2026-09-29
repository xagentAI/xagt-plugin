from __future__ import annotations

import json
import urllib.error
import urllib.request
from math import log10
from typing import Any, Protocol

from shared.config import AppConfig
from shared.schemas import (
    MarketEvidence,
    PredictionMarketContextRequest,
    PredictionMarketContextResult,
    PredictionMarketDecisionRequest,
    PredictionMarketDecisionResult,
    SearchMarketsResult,
    UnifiedMarket,
    VenueComparison,
)


class RouterGateway(Protocol):
    def search_markets(self, request: PredictionMarketDecisionRequest) -> list[UnifiedMarket]: ...


class HttpRouterGateway:
    def __init__(self, config: AppConfig | None = None) -> None:
        self.config = config or AppConfig.from_env()

    def search_markets(self, request: PredictionMarketDecisionRequest) -> list[UnifiedMarket]:
        payload = {
            "query": request.topic,
            "platforms": request.platforms,
            "limit": max(request.max_results * 4, 10),
            "tradable_only": request.tradable_only,
        }
        data = json.dumps(payload).encode("utf-8")
        req = urllib.request.Request(f"{self.config.router_url}/markets/search", data=data, headers={"Content-Type": "application/json"}, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=20) as response:
                result = SearchMarketsResult(**json.loads(response.read().decode("utf-8")))
                return result.markets
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode("utf-8")
            raise RuntimeError(f"router request failed: {exc.code} {detail}") from exc
        except urllib.error.URLError as exc:
            raise RuntimeError(f"router request failed: {exc}") from exc


class DecisionService:
    def __init__(self, router_gateway: RouterGateway | None = None, config: AppConfig | None = None) -> None:
        self.config = config or AppConfig.from_env()
        self.router_gateway = router_gateway or HttpRouterGateway(self.config)


    def build_context(self, request: PredictionMarketContextRequest) -> PredictionMarketContextResult:
        decision_request = PredictionMarketDecisionRequest(
            topic=request.topic,
            goal=request.goal,
            platforms=request.platforms,
            markets=request.markets,
            max_results=request.max_results,
            tradable_only=request.tradable_only,
            metadata=request.metadata,
        )
        markets = request.markets if request.markets is not None else self.router_gateway.search_markets(decision_request)
        comparisons = [self._compare_market(request.topic, market) for market in markets]
        comparisons.sort(key=lambda item: item.overall_score, reverse=True)
        comparisons = comparisons[: request.max_results]
        evidence = [
            MarketEvidence(
                platform=item.platform,
                market=item.market,
                topic_match_score=item.topic_match_score,
                tradability_score=item.tradability_score,
                liquidity_score=item.liquidity_score,
                spread_score=item.spread_score,
                execution_score=item.execution_score,
                resolution_score=item.resolution_score,
                risk_penalty=item.risk_penalty,
                quality_score=item.overall_score,
                evidence_notes=item.rationale,
                risk_flags=item.risk_flags,
            )
            for item in comparisons
        ]
        markets_by_platform: dict[str, list[UnifiedMarket]] = {}
        for item in evidence:
            markets_by_platform.setdefault(item.platform, []).append(item.market)
        available_routes = self._available_routes(evidence)
        return PredictionMarketContextResult(
            topic=request.topic,
            goal=request.goal,
            markets_by_platform=markets_by_platform,
            evidence=evidence,
            available_routes=available_routes,
            suggested_next_tools={
                "single_platform_preview": "create_prediction_market_order_preview",
                "execution_readiness": "check_prediction_market_execution_readiness",
            },
            risk_flags=self._collect_context_risk_flags(evidence),
            hermes_prompt_hints=[
                "Use this context as evidence; Hermes should make the final trading judgment.",
                "Explain why a route is chosen before asking Clink to create a preview.",
                "If evidence is weak or rules are unclear, choose wait or no_trade instead of forcing a preview.",
            ],
            execution_constraints={
                "final_decision_owner": "Hermes",
                "clink_role": "context, policy, preview, confirmation, and execution infrastructure",
                "does_clink_make_trade_decision": False,
                "preview_required_before_execution": True,
                "human_confirmation_required": True,
            },
        )

    def analyze_topic(self, request: PredictionMarketDecisionRequest) -> PredictionMarketDecisionResult:
        markets = request.markets if request.markets is not None else self.router_gateway.search_markets(request)
        comparisons = [self._compare_market(request.topic, market) for market in markets]
        comparisons.sort(key=lambda item: item.overall_score, reverse=True)
        comparisons = comparisons[: request.max_results]
        risk_flags = self._collect_risk_flags(comparisons)
        if not comparisons:
            return self._no_trade(request, [], ["No matching markets found."])

        best = comparisons[0]
        if best.overall_score < 35 or not best.market.tradable:
            return self._no_trade(request, comparisons, risk_flags or ["Best candidate score is too low for a preview."])
        if best.overall_score < 50:
            return PredictionMarketDecisionResult(
                topic=request.topic,
                goal=request.goal,
                recommended_action="wait",
                recommended_platform="none",
                selected_markets=[],
                comparison=comparisons,
                risk_flags=risk_flags or ["Best candidate is marginal; waiting is safer."],
                reasoning=["The current market set is not strong enough to create a preview yet."],
                next_tool_call=None,
            )
        return PredictionMarketDecisionResult(
            topic=request.topic,
            goal=request.goal,
            recommended_action="single_platform_preview",
            recommended_platform=best.platform,
            selected_markets=[best.market],
            comparison=comparisons,
            risk_flags=risk_flags,
            reasoning=[
                f"{best.platform} has the best overall score for this topic.",
                "The selected market is tradable and has clearer execution context than the alternatives.",
                f"Top score: {best.overall_score:.2f}.",
            ],
            next_tool_call={
                "tool": "create_prediction_market_order_preview",
                "arguments": {"market": best.market.model_dump(), "outcome": "Yes", "side": "buy", "amount_usd": "1"},
            },
        )

    def _compare_market(self, topic: str, market: UnifiedMarket) -> VenueComparison:
        topic_score, topic_reason = self._topic_score(topic, market)
        tradability_score = 15.0 if market.tradable else 0.0
        liquidity_score = self._liquidity_score(market)
        spread_score = self._spread_score(market)
        execution_score = 10.0 if market.execution_ready else 3.0 if market.tradable else 0.0
        resolution_score = 10.0 if market.rules_summary else 3.0
        risk_flags: list[str] = []
        risk_penalty = 0.0
        if not market.tradable:
            risk_flags.append("market is not tradable")
            risk_penalty += 20.0
        if market.bid_ask_spread is not None and market.bid_ask_spread > 0.12:
            risk_flags.append("wide spread")
            risk_penalty += 8.0
        if not market.rules_summary:
            risk_flags.append("missing or unclear resolution rules")
            risk_penalty += 5.0
        if market.liquidity_usd is None and market.volume_24h_usd is None:
            risk_flags.append("liquidity unavailable")
            risk_penalty += 4.0
        score = topic_score + tradability_score + liquidity_score + spread_score + execution_score + resolution_score - risk_penalty
        rationale = [item for item in [topic_reason, "tradable" if market.tradable else "not tradable"] if item]
        if market.execution_ready:
            rationale.append("execution context ready")
        return VenueComparison(
            platform=market.platform,
            market=market,
            topic_match_score=round(topic_score, 4),
            tradability_score=round(tradability_score, 4),
            liquidity_score=round(liquidity_score, 4),
            spread_score=round(spread_score, 4),
            execution_score=round(execution_score, 4),
            resolution_score=round(resolution_score, 4),
            risk_penalty=round(risk_penalty, 4),
            overall_score=round(max(score, 0.0), 4),
            rationale=rationale,
            risk_flags=risk_flags,
        )

    @staticmethod
    def _topic_score(topic: str, market: UnifiedMarket) -> tuple[float, str | None]:
        words = [word for word in topic.lower().replace("-", " ").split() if len(word) > 2]
        haystack = " ".join([market.title or "", market.subtitle or "", market.category or "", market.rules_summary or ""]).lower()
        if not words:
            return 10.0, None
        matches = sum(1 for word in words if word in haystack)
        score = 25.0 * matches / len(words)
        return score, f"topic match {matches}/{len(words)}"

    @staticmethod
    def _liquidity_score(market: UnifiedMarket) -> float:
        value = market.liquidity_usd if market.liquidity_usd is not None else market.volume_24h_usd
        if value is None or value <= 0:
            return 0.0
        return min(20.0, 5.0 + log10(max(value, 1.0)) * 4.0)

    @staticmethod
    def _spread_score(market: UnifiedMarket) -> float:
        if market.bid_ask_spread is None:
            return 8.0 if market.tradable else 0.0
        return max(0.0, 15.0 * (1.0 - min(market.bid_ask_spread, 0.3) / 0.3))

    @staticmethod
    def _collect_risk_flags(comparisons: list[VenueComparison]) -> list[str]:
        flags: list[str] = []
        for comparison in comparisons:
            for flag in comparison.risk_flags:
                rendered = f"{comparison.platform}:{comparison.market.market_id}: {flag}"
                if rendered not in flags:
                    flags.append(rendered)
        return flags

    @staticmethod
    def _available_routes(evidence: list[MarketEvidence]) -> list[str]:
        routes: list[str] = []
        tradable = [item for item in evidence if item.market.tradable and item.quality_score >= 35]
        if tradable:
            routes.append("single_platform_preview")
        routes.append("wait")
        routes.append("no_trade")
        return routes

    @staticmethod
    def _collect_context_risk_flags(evidence: list[MarketEvidence]) -> list[str]:
        flags: list[str] = []
        for item in evidence:
            for flag in item.risk_flags:
                rendered = f"{item.platform}:{item.market.market_id}: {flag}"
                if rendered not in flags:
                    flags.append(rendered)
        return flags

    @staticmethod
    def _no_trade(request: PredictionMarketDecisionRequest, comparisons: list[VenueComparison], risk_flags: list[str]) -> PredictionMarketDecisionResult:
        return PredictionMarketDecisionResult(
            topic=request.topic,
            goal=request.goal,
            recommended_action="no_trade",
            recommended_platform="none",
            selected_markets=[],
            comparison=comparisons,
            risk_flags=risk_flags,
            reasoning=["No market currently passes the minimum quality and safety threshold for a preview."],
            next_tool_call=None,
        )
