from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlsplit


@dataclass(frozen=True)
class BazaarTarget:
    category: str
    name: str
    first_party_domains: tuple[str, ...] = ()


DEFAULT_BAZAAR_TARGETS = (
    BazaarTarget("data", "CoinGecko", ("coingecko.com",)),
    BazaarTarget("data", "Nansen", ("nansen.ai",)),
    BazaarTarget("data", "Allium", ("allium.so",)),
    BazaarTarget("search", "Firecrawl", ("firecrawl.dev",)),
    BazaarTarget("search", "Exa", ("exa.ai",)),
    BazaarTarget("infrastructure", "Alchemy", ("alchemy.com",)),
    BazaarTarget("infrastructure", "Pinata", ("pinata.cloud",)),
    BazaarTarget("inference", "Venice", ("venice.ai",)),
    BazaarTarget("inference", "ElevenLabs", ("elevenlabs.io",)),
    BazaarTarget("media", "dTelecom", ("dtelecom.org",)),
)


def load_bazaar_targets(raw: str | None) -> tuple[BazaarTarget, ...]:
    if not raw:
        return DEFAULT_BAZAAR_TARGETS
    payload = json.loads(raw)
    if not isinstance(payload, list):
        raise ValueError("MARKETPLACE_BAZAAR_TARGETS_JSON must be a JSON list")
    targets = []
    for item in payload:
        if not isinstance(item, dict):
            raise ValueError("Bazaar target entries must be JSON objects")
        name = str(item.get("name") or "").strip()
        category = str(item.get("category") or "").strip().lower()
        domains = item.get("first_party_domains", [])
        if not name or not category or not isinstance(domains, list):
            raise ValueError("Bazaar target entries require name, category and domain list")
        targets.append(
            BazaarTarget(
                category,
                name,
                tuple(str(value).lower().rstrip(".") for value in domains if value),
            )
        )
    return tuple(targets)


def classify_target_resource(
    target: BazaarTarget, resource: dict[str, Any]
) -> str | None:
    endpoint = str(resource.get("resource") or "")
    hostname = (urlsplit(endpoint).hostname or "").lower().rstrip(".")
    service_name = str(resource.get("serviceName") or "")
    description = str(resource.get("description") or "")
    tags = " ".join(str(tag) for tag in resource.get("tags", []))
    target_key = _compact(target.name)
    if not target_key:
        return None
    haystack = _compact(" ".join((service_name, endpoint, description, tags)))
    if target_key not in haystack:
        return None
    if any(
        hostname == domain or hostname.endswith(f".{domain}")
        for domain in target.first_party_domains
    ):
        return "first_party"
    if target_key in _compact(service_name):
        return "branded"
    return "powered_by"


def target_metadata(target: BazaarTarget, relationship: str) -> dict[str, str]:
    return {
        "name": target.name,
        "category": target.category,
        "relationship": relationship,
    }


def _compact(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.lower())
