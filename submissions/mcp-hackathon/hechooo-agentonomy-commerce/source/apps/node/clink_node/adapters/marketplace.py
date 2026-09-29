from __future__ import annotations

import hashlib
import re
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from .ownership import object_id, require_owner

from .http import (
    DownstreamError,
    JsonHttpClient,
    ProxyResponse,
    proxy_http_request,
)


MARKETPLACE_CAPABILITIES = (
    "search_clink_services",
    "get_clink_service_details",
    "compare_clink_service_quotes",
    "create_clink_purchase_preview",
    "execute_clink_purchase",
    "get_clink_purchase",
    "clink_marketplace_health",
)

CATEGORY_ORDER = (
    "data",
    "search",
    "infrastructure",
    "inference",
    "media",
    "other",
)

GENERAL_SUBCATEGORY = {
    "data": "general_data",
    "search": "general_search",
    "infrastructure": "general_infrastructure",
    "inference": "general_inference",
    "media": "general_media",
    "other": "other",
}

SUBCATEGORY_RULES = {
    "data": (
        ("risk_identity", {"risk", "identity", "kyc", "aml", "screening"}),
        ("market_data", {"market", "price", "prices", "trending", "coingecko"}),
        ("onchain_data", {"onchain", "blockchain", "wallet", "nansen", "allium"}),
        ("analytics", {"analytics", "metrics", "insights"}),
    ),
    "search": (
        ("content_extraction", {"scrape", "crawl", "content", "markdown", "extract"}),
        ("semantic_search", {"semantic", "vector"}),
        ("research", {"research", "answer"}),
        ("web_search", {"search", "exa", "firecrawl"}),
    ),
    "infrastructure": (
        ("rpc", {"rpc", "node", "alchemy"}),
        ("storage", {"storage", "ipfs", "pinata"}),
        ("automation", {"automation", "workflow", "job"}),
        ("developer_tools", {"developer", "sdk", "api", "debug"}),
    ),
    "inference": (
        ("voice_audio", {"voice", "speech", "audio", "elevenlabs"}),
        ("vision", {"vision", "image", "video"}),
        ("language_models", {"llm", "model", "inference", "venice", "chat"}),
    ),
    "media": (
        ("content_extraction", {"scrape", "crawl", "extract"}),
        ("audio_video", {"audio", "video", "stream", "dtelecom"}),
        ("content_processing", {"content", "markdown", "convert"}),
    ),
}

TAG_CATEGORY_RULES = (
    (
        "data",
        {
            "risk",
            "identity",
            "kyc",
            "aml",
            "market",
            "price",
            "onchain",
            "analytics",
            "coingecko",
            "nansen",
            "allium",
        },
    ),
    (
        "search",
        {
            "search",
            "semantic",
            "research",
            "crawl",
            "scrape",
            "exa",
            "firecrawl",
        },
    ),
    (
        "infrastructure",
        {
            "rpc",
            "node",
            "storage",
            "ipfs",
            "developer",
            "sdk",
            "automation",
            "alchemy",
            "pinata",
        },
    ),
    (
        "inference",
        {
            "llm",
            "model",
            "inference",
            "voice",
            "speech",
            "vision",
            "venice",
            "elevenlabs",
        },
    ),
    (
        "media",
        {"media", "audio", "video", "content", "markdown", "dtelecom"},
    ),
)

BRAND_KEYS = {
    "alchemy",
    "allium",
    "coingecko",
    "dtelecom",
    "elevenlabs",
    "exa",
    "firecrawl",
    "nansen",
    "pinata",
    "venice",
}


def _tokens(values: Any) -> set[str]:
    if not isinstance(values, list):
        return set()
    return {
        token
        for value in values
        if isinstance(value, str)
        for token in re.findall(r"[a-z0-9]+", value.lower())
    }


def _bazaar_markers(metadata: dict[str, Any]) -> list[dict[str, Any]]:
    markers = metadata.get("bazaar_targets")
    if not isinstance(markers, list):
        return []
    return [item for item in markers if isinstance(item, dict)]


def _trusted_bazaar_markers(
    item: dict[str, Any],
    metadata: dict[str, Any],
) -> list[dict[str, Any]]:
    if item.get("status") != "registry_verified":
        return []
    return _bazaar_markers(metadata)


def _category_from_tokens(tokens: set[str]) -> str | None:
    return next(
        (
            category
            for category, keywords in TAG_CATEGORY_RULES
            if tokens & keywords
        ),
        None,
    )


def _subcategory_from_tokens(
    category: str,
    tokens: set[str],
) -> str | None:
    return next(
        (
            value
            for value, keywords in SUBCATEGORY_RULES.get(category, ())
            if tokens & keywords
        ),
        None,
    )


def _service_classification(
    item: dict[str, Any],
) -> tuple[str, str]:
    metadata = item.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    markers = _trusted_bazaar_markers(item, metadata)
    marker_categories = {
        marker.get("category")
        for marker in markers
        if marker.get("relationship") in {"first_party", "branded"}
        if marker.get("category") in CATEGORY_ORDER[:-1]
    }
    powered_by_categories = {
        marker.get("category")
        for marker in markers
        if marker.get("relationship") == "powered_by"
        if marker.get("category") in CATEGORY_ORDER[:-1]
    }
    tags = _tokens(item.get("tags"))
    content_tokens = _tokens(
        [item.get("name", ""), item.get("description", "")]
    )
    marker_tokens = _tokens(
        [str(marker.get("name") or "") for marker in markers]
    )
    category = next(
        (
            candidate
            for candidate in CATEGORY_ORDER[:-1]
            if candidate in marker_categories
        ),
        None,
    )
    if category is None:
        category = _category_from_tokens(tags)
    if category is None:
        category = _category_from_tokens(content_tokens)
    if category is None:
        category = next(
            (
                candidate
                for candidate in CATEGORY_ORDER[:-1]
                if candidate in powered_by_categories
            ),
            "other",
        )
    subcategory = _subcategory_from_tokens(
        category,
        tags - BRAND_KEYS,
    )
    if subcategory is None:
        subcategory = _subcategory_from_tokens(
            category,
            content_tokens | marker_tokens,
        )
    return (
        category,
        subcategory or GENERAL_SUBCATEGORY[category],
    )


def _slug(value: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "-", str(value or "").lower()).strip("-")


def _icon_text(name: str) -> str:
    words = re.findall(r"[A-Za-z0-9]+", name)
    if len(words) >= 2:
        return f"{words[0][0]}{words[1][0]}".upper()
    if words:
        return words[0][:2].upper()
    return "?"


def _icon_identity(
    item: dict[str, Any],
    name: str,
) -> tuple[str, str]:
    metadata = item.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    for marker in _trusted_bazaar_markers(item, metadata):
        relationship = marker.get("relationship")
        brand = _slug(marker.get("name"))
        if relationship in {"first_party", "branded"} and brand in BRAND_KEYS:
            return f"brand-{brand}", _icon_text(name)
    offering_id = str(item.get("offering_id") or name)
    digest = hashlib.sha256(offering_id.encode("utf-8")).hexdigest()[:12]
    return f"service-{digest}", _icon_text(name)


def _non_negative_int(value: Any) -> int:
    if isinstance(value, bool):
        return 0
    try:
        return max(int(value), 0)
    except (TypeError, ValueError):
        return 0


def _starting_price(options: Any) -> str | None:
    if not isinstance(options, list):
        return None
    prices: list[Decimal] = []
    for option in options:
        if not isinstance(option, dict):
            continue
        try:
            price = Decimal(str(option.get("price_usd")))
        except (InvalidOperation, TypeError, ValueError):
            continue
        if price.is_finite() and price > 0:
            prices.append(price)
    return format(min(prices), "f") if prices else None


def _networks(options: Any) -> list[str]:
    if not isinstance(options, list):
        return []
    return sorted(
        {
            network
            for option in options
            if isinstance(option, dict)
            if isinstance((network := option.get("network")), str)
            and network
        }
    )


def _project_service(
    item: dict[str, Any],
) -> dict[str, Any] | None:
    offering_id = item.get("offering_id")
    name = item.get("name")
    if not isinstance(offering_id, str) or not isinstance(name, str):
        return None
    metadata = item.get("metadata")
    metadata = metadata if isinstance(metadata, dict) else {}
    quality = metadata.get("quality")
    quality = quality if isinstance(quality, dict) else {}
    description = item.get("description")
    trust_tier = metadata.get("trust_tier")
    category, subcategory = _service_classification(item)
    icon_key, icon_text = _icon_identity(item, name)
    return {
        "offering_id": offering_id,
        "name": name,
        "description": (
            description if isinstance(description, str) else ""
        ),
        "starting_price_usd": _starting_price(
            item.get("payment_options")
        ),
        "networks": _networks(item.get("payment_options")),
        "trust_tier": (
            trust_tier
            if isinstance(trust_tier, str) and trust_tier
            else str(item.get("status") or "verified")
        ),
        "calls_30d": _non_negative_int(
            quality.get("l30DaysTotalCalls")
        ),
        "category": category,
        "subcategory": subcategory,
        "icon_key": icon_key,
        "icon_text": icon_text,
    }


class MarketplaceHttpAdapter:
    name = "marketplace"

    def __init__(
        self,
        *,
        base_url: str,
        internal_token: str,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.transport = transport
        self.http = JsonHttpClient(
            self.name,
            internal_token=internal_token,
            transport=transport,
        )

    def health(self) -> dict[str, Any]:
        return self.http.get(f"{self.base_url}/healthz")

    def capabilities(self) -> list[dict[str, Any]]:
        return [
            {"name": name, "module": self.name}
            for name in MARKETPLACE_CAPABILITIES
        ]

    def get_purchase_preview(self, *, user_id: str, preview_id: str) -> dict[str, Any]:
        preview_id = object_id(preview_id)
        payload = self.http.get(f"{self.base_url}/purchases/previews/{preview_id}")
        return require_owner(payload, user_id=user_id, id_field="preview_id",
                             expected_id=preview_id, service=self.name)

    def get_purchase(self, *, user_id: str, purchase_id: str) -> dict[str, Any]:
        purchase_id = object_id(purchase_id)
        payload = self.http.get(f"{self.base_url}/purchases/{purchase_id}")
        return require_owner(payload, user_id=user_id, id_field="purchase_id",
                             expected_id=purchase_id, service=self.name)

    def list_services(self, limit: int = 20) -> dict[str, Any]:
        payload = self.http.post(
            f"{self.base_url}/catalog/search",
            {"query": "", "limit": limit},
        )
        offerings = payload.get("offerings")
        if not isinstance(offerings, list):
            raise DownstreamError(
                self.name,
                200,
                "catalog offerings must be an array",
            )
        services = []
        for item in offerings:
            if not isinstance(item, dict):
                continue
            service = _project_service(item)
            if service is not None:
                services.append(service)
        return {"count": len(services), "services": services}

    def proxy_public_request(
        self,
        *,
        method: str,
        path: str,
        query: str,
        headers: list[tuple[str, str]],
        body: bytes,
    ) -> ProxyResponse:
        allowed = (
            path.startswith("/x402/checkout/")
            or path
            in {
                "/assets/x402_checkout.css",
                "/assets/x402_checkout.js",
            }
        )
        if not allowed:
            raise ValueError(
                "only public Marketplace checkout routes may be proxied"
            )
        return proxy_http_request(
            service="marketplace-checkout",
            base_url=self.base_url,
            method=method,
            path=path,
            query=query,
            headers=headers,
            body=body,
            transport=self.transport,
        )
