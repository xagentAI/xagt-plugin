"""Deterministic, explainable powered-site qualification scoring."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any

INTENDED_USES = ("Bitcoin mining", "AI data center", "both")


@dataclass(frozen=True)
class Factor:
    key: str
    label: str
    weight: int
    positive: str
    missing: str
    blocker: str | None = None


BITCOIN_FACTORS = (
    Factor("power_ready", "Power ready now", 20, "Power is ready now", "Confirm whether power is ready now", "No power-ready date or status"),
    Factor("available_mw", "Available MW", 15, "Capacity is useful for mining scale", "Confirm firm available MW", "No available MW stated"),
    Factor("power_price", "Power price", 15, "Known power pricing supports underwriting", "Confirm all-in power price and tariff structure"),
    Factor("utility_status", "Utility/interconnection", 10, "Utility/interconnection status is advanced", "Confirm utility, interconnection, and deliverability evidence", "Interconnection status is unresolved"),
    Factor("grid_or_gas", "Power source", 8, "Power-source pathway is identified", "Confirm grid or gas-to-power pathway"),
    Factor("expansion_capacity", "Expansion capacity", 7, "Expansion potential supports phased deployment", "Confirm expansion MW, schedule, and constraints"),
    Factor("land_size", "Land", 6, "Land information supports site layout", "Confirm usable acreage, zoning, and setbacks"),
    Factor("permitting_status", "Permitting", 6, "Permitting path is identified", "Confirm permits, zoning, and environmental status", "Permitting path is unresolved"),
    Factor("lease_sale_jv", "Commercial structure", 4, "Lease/sale/JV path is identified", "Confirm lease, sale, or JV structure"),
    Factor("energization_rfs_date", "Energization/RFS", 4, "Energization/RFS timing is stated", "Confirm energization/RFS date and milestones"),
    Factor("fiber", "Fiber", 3, "Fiber availability supports operations", "Confirm carrier, route, redundancy, and committed capacity"),
    Factor("water", "Water", 2, "Water information supports site planning", "Confirm water source, rights, and cooling constraints"),
)

AI_FACTORS = (
    Factor("power_ready", "Power ready now", 14, "Power is ready now", "Confirm whether power is ready now", "No power-ready date or status"),
    Factor("available_mw", "Available MW", 11, "Capacity is useful for AI/data-center scale", "Confirm firm available MW", "No available MW stated"),
    Factor("power_price", "Power price", 8, "Known power pricing supports underwriting", "Confirm all-in power price and tariff structure"),
    Factor("utility_status", "Utility/interconnection", 10, "Utility/interconnection status is advanced", "Confirm utility, interconnection, and deliverability evidence", "Interconnection status is unresolved"),
    Factor("grid_or_gas", "Power source", 5, "Power-source pathway is identified", "Confirm grid or gas-to-power pathway"),
    Factor("fiber", "Fiber", 15, "Fiber information supports low-latency operations", "Confirm carrier, route, redundancy, latency, and committed capacity", "Fiber is not confirmed"),
    Factor("water", "Water", 10, "Water information supports cooling planning", "Confirm water source, rights, quality, and cooling design", "Cooling/water path is unresolved"),
    Factor("expansion_capacity", "Expansion capacity", 8, "Expansion potential supports phased AI growth", "Confirm expansion MW, schedule, and constraints"),
    Factor("permitting_status", "Permitting", 8, "Permitting path is identified", "Confirm permits, zoning, environmental, and data-center approvals", "Permitting path is unresolved"),
    Factor("land_size", "Land", 4, "Land information supports campus layout", "Confirm usable acreage, zoning, setbacks, and flood risk"),
    Factor("energization_rfs_date", "Energization/RFS", 4, "Energization/RFS timing is stated", "Confirm energization/RFS date and milestones"),
    Factor("lease_sale_jv", "Commercial structure", 3, "Commercial path is identified", "Confirm lease, sale, or JV structure"),
)


def _present(value: Any) -> bool:
    return value is not None and value != "" and value != []


def _yes(value: Any) -> bool:
    return str(value).strip().lower() in {"yes", "true", "y", "1"}


def _status_score(value: Any, good: set[str], partial: set[str]) -> int:
    if not _present(value):
        return 0
    normalized = str(value).strip().lower()
    if normalized in good:
        return 100
    if normalized in partial:
        return 55
    return 20


def _factor_percent(key: str, site: dict[str, Any]) -> int:
    value = site.get(key)
    if key == "power_ready":
        return 100 if _yes(value) else (20 if _present(value) else 0)
    if key == "available_mw":
        try:
            mw = float(value)
        except (TypeError, ValueError):
            return 0
        return 100 if mw >= 20 else 80 if mw >= 10 else 60 if mw >= 5 else 35 if mw > 0 else 0
    if key == "power_price":
        try:
            price = float(value)
        except (TypeError, ValueError):
            return 0
        return 100 if price <= 0.05 else 80 if price <= 0.07 else 55 if price <= 0.10 else 25
    if key == "utility_status":
        return _status_score(value, {"energized", "interconnected", "executed interconnection agreement", "ready"}, {"advanced", "in progress", "study complete", "queued"})
    if key == "grid_or_gas":
        return _status_score(value, {"grid", "gas-to-power", "gas", "grid + gas-to-power"}, {"planned", "available nearby", "under development"})
    if key == "permitting_status":
        return _status_score(value, {"complete", "permitted", "approved", "ready"}, {"in progress", "substantially complete", "zoned"})
    if key == "energization_rfs_date":
        try:
            days = (date.fromisoformat(str(value)) - date.today()).days
        except ValueError:
            return 40 if _present(value) else 0
        return 100 if days <= 90 else 75 if days <= 365 else 45 if days <= 730 else 20
    if key == "fiber":
        return _status_score(value, {"available", "on-site", "dark fiber", "lit fiber"}, {"nearby", "planned", "feasible"})
    if key == "water":
        return _status_score(value, {"available", "on-site", "secured", "municipal", "reclaimed"}, {"nearby", "planned", "feasible"})
    if key == "expansion_capacity":
        try:
            capacity = float(value)
            return 100 if capacity >= 20 else 75 if capacity >= 10 else 45 if capacity > 0 else 0
        except (TypeError, ValueError):
            return 45 if _present(value) else 0
    if key == "land_size":
        try:
            acres = float(value)
            return 100 if acres >= 100 else 75 if acres >= 40 else 50 if acres >= 10 else 25 if acres > 0 else 0
        except (TypeError, ValueError):
            return 40 if _present(value) else 0
    if key == "lease_sale_jv":
        return _status_score(value, {"lease", "sale", "jv", "joint venture", "lease / sale / jv"}, {"flexible", "under discussion", "available"})
    return 0


def _score_track(site: dict[str, Any], factors: tuple[Factor, ...]) -> tuple[int, list[str], list[str], list[str]]:
    score = 0.0
    positives: list[str] = []
    missing: list[str] = []
    blockers: list[str] = []
    for factor in factors:
        value = site.get(factor.key)
        if not _present(value):
            missing.append(factor.missing)
            if factor.blocker:
                blockers.append(factor.blocker)
            continue
        percent = _factor_percent(factor.key, site)
        score += factor.weight * percent / 100
        if percent >= 75:
            positives.append(factor.positive)
        if factor.blocker and percent < 40:
            blockers.append(factor.blocker)
    return round(score), positives, missing, blockers


def _classification(bitcoin: int, ai: int, intended: str) -> str:
    relevant = [bitcoin, ai] if intended == "both" else [bitcoin if intended == "Bitcoin mining" else ai]
    minimum = min(relevant)
    return "READY" if minimum >= 80 else "NEAR READY" if minimum >= 60 else "NEEDS DEVELOPMENT" if minimum >= 35 else "NOT SUITABLE"


def qualify(site: dict[str, Any]) -> dict[str, Any]:
    intended = site.get("intended_use", "both")
    if intended not in INTENDED_USES:
        intended = "both"
    bitcoin, bp, bm, bb = _score_track(site, BITCOIN_FACTORS)
    ai, ap, am, ab = _score_track(site, AI_FACTORS)
    missing = list(dict.fromkeys(bm + am))
    blockers = list(dict.fromkeys(bb + ab))
    positives = list(dict.fromkeys(bp + ap))
    return {
        "bitcoin_mining_readiness": {"score": bitcoin, "basis": "weighted, known inputs only"},
        "ai_data_center_readiness": {"score": ai, "basis": "weighted, known inputs only"},
        "key_positives": positives,
        "missing_information": missing,
        "major_blockers": blockers,
        "recommended_next_questions": missing[:8],
        "classification": _classification(bitcoin, ai, intended),
        "intended_use": intended,
        "method": {"deterministic": True, "unknowns_are_not_guessed": True, "scores_are_not_advice": True},
    }
