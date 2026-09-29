from dataclasses import dataclass
from typing import Literal

from services.policy_service.risk_provider import RiskProviderResult


RISK_MAPPING_VERSION = "misttrack-policy-v1"

_LEVEL_SCORE_RANGES = {
    "low": range(0, 31),
    "moderate": range(31, 71),
    "high": range(71, 91),
    "severe": range(91, 101),
}
_DIRECT_HARD_RISK_TYPES = frozenset(
    {"sanctioned_entity", "illicit_activity", "malicious_address", "mixer"}
)
_HARD_RISK_INDICATORS = frozenset(
    {
        "malicious address",
        "sanctioned entity",
        "mixer",
        "involved theft activity",
        "involved ransom activity",
        "involved phishing activity",
        "involved illicit activity",
    }
)
_MALFORMED_RESULT_REASON = "malformed_risk_result"
_UNKNOWN_INDICATOR_REASON = "unknown_indicator_present"


@dataclass(frozen=True)
class RiskDecision:
    decision: Literal["allow", "hold", "deny", "unavailable"]
    mapping_version: str
    reasons: tuple[str, ...]


def map_risk_result(
    result: RiskProviderResult,
    hold_score: int = 31,
    deny_score: int = 71,
) -> RiskDecision:
    """Map one provider-neutral assessment to the Core risk vocabulary."""
    if not _has_valid_risk_collections(result):
        return _decision("unavailable", _MALFORMED_RESULT_REASON)

    direct_hard_risk = _direct_hard_risk_type(result)
    if direct_hard_risk is not None:
        return _decision("deny", "direct_hard_risk")

    hard_indicator = _hard_risk_indicator(result)
    if hard_indicator is not None:
        return _decision("deny", f"hard_risk_indicator:{hard_indicator}")

    if not _is_consistent_score_and_level(result.score, result.risk_level):
        return _decision("unavailable", "inconsistent_score_and_risk_level")

    score_decision = _score_decision(result.score, hold_score, deny_score)
    if result.hacking_event and score_decision != "deny":
        return _decision("hold", "hacking_event_present")

    if result.risk_details and score_decision != "deny":
        return _decision("hold", "risk_detail_present")

    unknown_indicator = _unknown_indicator(result)
    if unknown_indicator is not None and score_decision != "deny":
        return _decision("hold", _UNKNOWN_INDICATOR_REASON)

    return _decision(score_decision, f"score:{result.score}")


def _has_valid_risk_collections(result: RiskProviderResult) -> bool:
    return (
        isinstance(result.risk_details, tuple)
        and all(
            isinstance(detail, dict) and _has_valid_risk_detail_fields(detail)
            for detail in result.risk_details
        )
        and isinstance(result.indicators, tuple)
        and all(isinstance(indicator, str) for indicator in result.indicators)
        and isinstance(result.risk_level, str)
    )


def _has_valid_risk_detail_fields(detail: dict[str, str]) -> bool:
    return all(
        field not in detail or isinstance(detail[field], str)
        for field in ("risk_type", "exposure_type")
    )


def _direct_hard_risk_type(result: RiskProviderResult) -> str | None:
    for detail in result.risk_details:
        if (
            detail.get("exposure_type") == "direct"
            and detail.get("risk_type") in _DIRECT_HARD_RISK_TYPES
        ):
            return detail["risk_type"]
    return None


def _hard_risk_indicator(result: RiskProviderResult) -> str | None:
    for indicator in result.indicators:
        normalized = indicator.lower()
        if normalized in _HARD_RISK_INDICATORS:
            return normalized
    return None


def _unknown_indicator(result: RiskProviderResult) -> str | None:
    for indicator in result.indicators:
        if indicator and indicator.lower() not in _HARD_RISK_INDICATORS:
            return indicator
    return None


def _is_consistent_score_and_level(score: int, risk_level: str) -> bool:
    return type(score) is int and score in _LEVEL_SCORE_RANGES.get(risk_level, ())


def _score_decision(
    score: int,
    hold_score: int,
    deny_score: int,
) -> Literal["allow", "hold", "deny"]:
    if score >= deny_score:
        return "deny"
    if score >= hold_score:
        return "hold"
    return "allow"


def _decision(
    decision: Literal["allow", "hold", "deny", "unavailable"],
    reason: str,
) -> RiskDecision:
    return RiskDecision(
        decision=decision,
        mapping_version=RISK_MAPPING_VERSION,
        reasons=(reason,),
    )
