from __future__ import annotations

from typing import Any, Iterable
import re

DOMAINS = (
    "AI_AGENT_SOFTWARE",
    "CRYPTO_ONCHAIN",
    "BITCOIN_NATIVE",
    "PREDICTION_INFOFI",
    "PRODUCT_BUSINESS_MODEL",
    "CREATOR_DISTRIBUTION",
    "DATA_INFRA",
    "GRANT_BOUNTY_PARTNERSHIP",
)

INNOVATION_TYPES = (
    "PROJECT",
    "ASSET",
    "MECHANISM",
    "PROTOCOL_PRIMITIVE",
    "TOOL",
    "API",
    "DATA_SOURCE",
    "RESEARCH_METHOD",
    "WORKFLOW",
    "BUSINESS_MODEL",
    "PRICING_MODEL",
    "DISTRIBUTION_CHANNEL",
    "INCENTIVE",
    "USER_BEHAVIOR",
    "RELATIONSHIP_PATH",
    "CROSS_DOMAIN_HYPOTHESIS",
)

_DOMAIN_TERMS = {
    "AI_AGENT_SOFTWARE": (
        "ai agent", "agentic", "copilot", "model api", "inference", "automation", "sdk", "workflow",
    ),
    "CRYPTO_ONCHAIN": (
        "onchain", "on-chain", "blockchain", "smart contract", "protocol", "token", "dex", "liquidity", "wallet", "chain",
    ),
    "BITCOIN_NATIVE": (
        "bitcoin native", "bitcoin-native", "ordinals", "runes", "alkanes", "spark", "btcfi", "btc fi",
    ),
    "PREDICTION_INFOFI": (
        "prediction market", "polymarket", "event contract", "infofi", "orderbook", "settlement source",
    ),
    "PRODUCT_BUSINESS_MODEL": (
        "b2b", "saas", "gtm", "pricing", "revenue", "conversion", "customer", "business model", "product", "monetization",
    ),
    "CREATOR_DISTRIBUTION": (
        "creator", "content", "distribution", "affiliate", "referral", "seo", "audience", "subscriber", "traffic",
    ),
    "DATA_INFRA": (
        "api", "data source", "dataset", "timestamp", "rpc", "indexer", "feed", "market data", "websocket",
    ),
    "GRANT_BOUNTY_PARTNERSHIP": (
        "grant", "bounty", "builder program", "hackathon", "partner", "partnership", "creator campaign", "x-points", "prize",
    ),
}

_TYPE_TERMS = {
    "ASSET": ("token", "coin", "nft", "asset", "mint", "market cap", "fdv"),
    "MECHANISM": ("mechanism", "settlement", "fee split", "reward", "rebate", "auction", "bonding curve", "market design"),
    "PROTOCOL_PRIMITIVE": ("protocol", "primitive", "permissionless", "smart contract", "onchain", "on-chain"),
    "TOOL": ("tool", "sdk", "copilot", "software", "platform", "agent"),
    "API": ("api", "websocket", "endpoint", "sdk"),
    "DATA_SOURCE": ("data source", "dataset", "orderbook", "timestamp", "feed", "market data", "resolution source"),
    "RESEARCH_METHOD": ("paper", "benchmark", "methodology", "backtest", "evaluation"),
    "WORKFLOW": ("workflow", "automation", "agent", "orchestration", "pipeline"),
    "BUSINESS_MODEL": ("business model", "saas", "revenue", "monetization", "customer", "pricing", "fee capture"),
    "PRICING_MODEL": ("pricing", "auction", "fee", "rebate", "bonding curve", "spread"),
    "DISTRIBUTION_CHANNEL": ("distribution", "affiliate", "referral", "seo", "audience", "channel", "creator"),
    "INCENTIVE": ("grant", "bounty", "reward", "rebate", "incentive", "points", "x-points", "prize"),
    "USER_BEHAVIOR": ("retention", "adoption", "user behavior", "conversion", "repeat user", "usage growth"),
    "RELATIONSHIP_PATH": ("partner", "partnership", "grant", "bounty", "builder", "api access", "creator campaign"),
    "CROSS_DOMAIN_HYPOTHESIS": ("cross-domain", "combine", "integrate", "could form", "plus prediction", "plus creator"),
}

_ALLOWED_INPUT_FIELDS = {"headline", "why_now", "candidate_class", "evidence"}
_ALLOWED_EVIDENCE_FIELDS = {"source_id", "kind", "first_party", "url", "note"}
_MAX_HEADLINE = 500
_MAX_WHY_NOW = 2_000
_MAX_CLASS = 120
_MAX_EVIDENCE = 12
_MAX_EVIDENCE_TEXT = 1_000


class InputError(ValueError):
    pass


def _bounded_string(value: Any, field: str, limit: int, *, required: bool = False) -> str:
    if value is None and not required:
        return ""
    if not isinstance(value, str):
        raise InputError(f"{field} must be a string")
    normalized = re.sub(r"\s+", " ", value).strip()
    if required and not normalized:
        raise InputError(f"{field} is required")
    if len(normalized) > limit:
        raise InputError(f"{field} exceeds {limit} characters")
    return normalized


def validate_request(payload: Any) -> dict[str, Any]:
    if not isinstance(payload, dict):
        raise InputError("request body must be a JSON object")
    unknown = sorted(set(payload) - _ALLOWED_INPUT_FIELDS)
    if unknown:
        raise InputError("unknown fields: " + ", ".join(unknown))

    headline = _bounded_string(payload.get("headline"), "headline", _MAX_HEADLINE, required=True)
    why_now = _bounded_string(payload.get("why_now"), "why_now", _MAX_WHY_NOW)
    candidate_class = _bounded_string(payload.get("candidate_class"), "candidate_class", _MAX_CLASS) or "GENERAL_OPPORTUNITY"

    evidence_value = payload.get("evidence", [])
    if not isinstance(evidence_value, list):
        raise InputError("evidence must be an array")
    if len(evidence_value) > _MAX_EVIDENCE:
        raise InputError(f"evidence exceeds {_MAX_EVIDENCE} items")

    evidence: list[dict[str, Any]] = []
    for index, row in enumerate(evidence_value):
        if not isinstance(row, dict):
            raise InputError(f"evidence[{index}] must be an object")
        extra = sorted(set(row) - _ALLOWED_EVIDENCE_FIELDS)
        if extra:
            raise InputError(f"evidence[{index}] unknown fields: " + ", ".join(extra))
        first_party = row.get("first_party", False)
        if not isinstance(first_party, bool):
            raise InputError(f"evidence[{index}].first_party must be boolean")
        evidence.append({
            "source_id": _bounded_string(row.get("source_id"), f"evidence[{index}].source_id", 200),
            "kind": _bounded_string(row.get("kind"), f"evidence[{index}].kind", 120),
            "first_party": first_party,
            "url": _bounded_string(row.get("url"), f"evidence[{index}].url", _MAX_EVIDENCE_TEXT),
            "note": _bounded_string(row.get("note"), f"evidence[{index}].note", _MAX_EVIDENCE_TEXT),
        })

    return {
        "headline": headline,
        "why_now": why_now,
        "candidate_class": candidate_class,
        "evidence": evidence,
    }


def _flatten(value: Any) -> Iterable[str]:
    if value is None:
        return
    if isinstance(value, str):
        yield value
    elif isinstance(value, dict):
        for key, item in value.items():
            yield str(key)
            yield from _flatten(item)
    elif isinstance(value, (list, tuple, set)):
        for item in value:
            yield from _flatten(item)
    elif isinstance(value, (int, float, bool)):
        yield str(value)


def _ordered(values: Iterable[str], universe: tuple[str, ...]) -> list[str]:
    present = set(values)
    return [value for value in universe if value in present]


def _evidence_classes(evidence: list[dict[str, Any]]) -> list[str]:
    classes: set[str] = set()
    for row in evidence:
        kind = str(row.get("kind") or "").upper()
        source_id = str(row.get("source_id") or "").lower()
        if row.get("first_party") is True or "official" in source_id or "OFFICIAL" in kind:
            classes.add("FIRST_PARTY")
        if any(term in kind for term in ("CODE", "REPO", "RELEASE", "COMMIT")) or "github" in source_id:
            classes.add("CODE")
        if any(term in kind for term in ("ORDERBOOK", "MARKET", "QUOTE", "DATA")):
            classes.add("MARKET_OR_DATA")
        if any(term in kind for term in ("PARTNER", "GRANT", "BOUNTY", "CAMPAIGN")):
            classes.add("COMMERCIAL")
        if any(term in kind for term in ("PAPER", "RESEARCH", "REPORT")):
            classes.add("RESEARCH")
    return sorted(classes) or ["UNKNOWN"]


def build_profile(candidate: dict[str, Any]) -> dict[str, Any]:
    text = " ".join(_flatten(candidate)).lower()
    text = re.sub(r"\s+", " ", text).strip()
    domains = _ordered(
        (domain for domain, terms in _DOMAIN_TERMS.items() if any(term in text for term in terms)),
        DOMAINS,
    ) or ["PRODUCT_BUSINESS_MODEL"]

    inferred_types = {name for name, terms in _TYPE_TERMS.items() if any(term in text for term in terms)}
    candidate_class = candidate["candidate_class"].upper()
    if any(term in candidate_class for term in ("TOKEN", "ASSET", "NFT")):
        inferred_types.add("ASSET")
    if any(term in candidate_class for term in ("PROTOCOL", "MECHANISM")):
        inferred_types.add("MECHANISM")
    if "MECHANISM" in inferred_types and "CRYPTO_ONCHAIN" in domains:
        inferred_types.add("PROTOCOL_PRIMITIVE")
    innovation_types = _ordered(inferred_types or {"PROJECT"}, INNOVATION_TYPES)

    evidence_classes = _evidence_classes(candidate["evidence"])
    if "CROSS_DOMAIN_HYPOTHESIS" in innovation_types and len(domains) >= 2:
        signal_state = "CROSS_DOMAIN_SEED"
    elif "MECHANISM" in innovation_types:
        signal_state = "MECHANISM_SEED"
    elif evidence_classes != ["UNKNOWN"] and candidate["why_now"]:
        signal_state = "READY_FOR_VALIDATION"
    else:
        signal_state = "WEAK_SIGNAL"

    unknowns: list[str] = []
    if "FIRST_PARTY" not in evidence_classes:
        unknowns.append("FIRST_PARTY_EVIDENCE_NOT_PRESENT")
    if "GRANT_BOUNTY_PARTNERSHIP" in domains and not candidate["why_now"]:
        unknowns.append("DEADLINE_OR_TERMS_NOT_PROVIDED")

    return {
        "schema": "opportunity_lens_profile.v1",
        "primary_domain": domains[0],
        "domains": domains,
        "innovation_types": innovation_types,
        "signal_state": signal_state,
        "evidence_classes": evidence_classes,
        "unknowns": unknowns,
        "execution_authorized": False,
        "capital_effect": False,
        "human_notification_authorized": False,
    }


def select_validation(profile: dict[str, Any]) -> dict[str, Any]:
    domains = set(profile["domains"])
    types = set(profile["innovation_types"])
    if "GRANT_BOUNTY_PARTNERSHIP" in domains:
        action, reason = "COMMERCIAL_REVIEW", "GRANT_BOUNTY_OR_PARTNERSHIP"
    elif "CROSS_DOMAIN_HYPOTHESIS" in types:
        action, reason = "CROSS_DOMAIN_SYNTHESIS", "CROSS_DOMAIN_SEED"
    elif "PREDICTION_INFOFI" in domains and types & {"API", "DATA_SOURCE", "MECHANISM", "RESEARCH_METHOD"}:
        action, reason = "STRATEGY_TEST", "PREDICTION_METHOD_OR_DATA"
    elif "PRODUCT_BUSINESS_MODEL" in domains and types & {"TOOL", "WORKFLOW", "BUSINESS_MODEL", "PRICING_MODEL"}:
        action, reason = "PRODUCT_TRIAL", "PRODUCT_OR_BUSINESS_MODEL"
    elif "CREATOR_DISTRIBUTION" in domains:
        action, reason = "CREATOR_TEST", "CREATOR_OR_DISTRIBUTION"
    elif "DATA_INFRA" in domains and types & {"API", "DATA_SOURCE", "RESEARCH_METHOD"}:
        action, reason = "DATA_CHECK", "DATA_OR_INFRA"
    elif "CRYPTO_ONCHAIN" in domains and types & {"ASSET", "MECHANISM", "PROTOCOL_PRIMITIVE"}:
        action, reason = "CHAIN_OBSERVATION", "ONCHAIN_OBJECT"
    else:
        action, reason = "PUBLIC_RESEARCH", "DEFAULT_PUBLIC_RESEARCH"

    next_checks = {
        "COMMERCIAL_REVIEW": [
            "Verify eligibility, deadline, source-code rights, reward economics, and selection terms from first-party documents.",
            "Estimate incremental build, deployment, and maintenance effort before committing.",
        ],
        "STRATEGY_TEST": ["Validate the data contract and run a bounded paper test before any live use."],
        "PRODUCT_TRIAL": ["Run a bounded user workflow and measure whether it removes a real manual step."],
        "CREATOR_TEST": ["Run a reversible distribution test and measure qualified conversion."],
        "DATA_CHECK": ["Verify provenance, freshness, failure behavior, and reproducibility."],
        "CHAIN_OBSERVATION": ["Verify first-party mechanics and observe on-chain behavior without granting transaction authority."],
        "CROSS_DOMAIN_SYNTHESIS": ["Write a falsifiable cross-domain hypothesis and define the smallest validation."],
        "PUBLIC_RESEARCH": ["Collect first-party evidence and define the unresolved trigger."],
    }[action]

    return {
        "schema": "opportunity_lens_validation.v1",
        "mode": "ADVISORY_ONLY",
        "action_type": action,
        "reason_codes": [reason],
        "next_checks": next_checks,
        "actual_routing_enabled": False,
        "execution_authorized": False,
        "capital_effect": False,
        "human_notification_authorized": False,
    }


def analyze(payload: Any) -> dict[str, Any]:
    candidate = validate_request(payload)
    profile = build_profile(candidate)
    validation = select_validation(profile)
    return {
        "schema": "opportunity_lens_response.v1",
        "profile": profile,
        "validation": validation,
        "safety": {
            "advisory_only": True,
            "execution_authorized": False,
            "capital_effect": False,
            "account_effect": False,
            "public_publish_authorized": False,
        },
    }
