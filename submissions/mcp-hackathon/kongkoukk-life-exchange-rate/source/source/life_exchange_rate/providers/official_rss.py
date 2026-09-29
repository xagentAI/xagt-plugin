from __future__ import annotations

import hashlib
from datetime import datetime
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree as ET

import httpx

from ..models import EventType, MacroHeadline


FEEDS = {
    "fed": {
        "publisher": "Federal Reserve Board",
        "jurisdiction": "US",
        "url": "https://www.federalreserve.gov/feeds/press_monetary.xml",
    },
    "ecb": {
        "publisher": "European Central Bank",
        "jurisdiction": "EU",
        "url": "https://www.ecb.europa.eu/rss/press.html",
    },
}


def _text(node: ET.Element | None) -> str | None:
    return node.text.strip() if node is not None and node.text else None


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return parsedate_to_datetime(value)
    except (TypeError, ValueError):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None


def _classify(title: str) -> tuple[EventType | None, list[str]]:
    lower = title.lower()
    tags: list[str] = []
    hint = None
    if any(term in lower for term in ["monetary policy", "fomc", "interest rate", "policy rate", "rates"]):
        hint = EventType.INTEREST_RATE_CHANGE
        tags.append("monetary-policy")
    if any(term in lower for term in ["inflation", "consumer prices", "price stability"]):
        tags.append("inflation")
    if any(term in lower for term in ["economic outlook", "projections", "forecast"]):
        tags.append("outlook")
    return hint, tags


def parse_feed(xml_text: str, source: str, limit: int = 20) -> list[MacroHeadline]:
    if source not in FEEDS:
        raise ValueError("Unsupported official RSS source")
    if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 50:
        raise ValueError("limit must be an integer from 1 to 50")
    cfg = FEEDS[source]
    root = ET.fromstring(xml_text)
    items = root.findall(".//item")
    headlines: list[MacroHeadline] = []
    for item in items[:limit]:
        title = _text(item.find("title"))
        link = _text(item.find("link"))
        published = _text(item.find("pubDate")) or _text(item.find("date"))
        if not title or not link:
            continue
        hint, tags = _classify(title)
        digest = hashlib.sha256(f"{source}|{link}".encode()).hexdigest()[:16]
        headlines.append(
            MacroHeadline(
                headline_id=f"{source}-{digest}",
                title=title,
                publisher=cfg["publisher"],
                published_at=_parse_date(published),
                url=link,
                jurisdiction=cfg["jurisdiction"],
                event_type_hint=hint,
                tags=tags,
            )
        )
    return headlines


class OfficialRSSProvider:
    def __init__(self, timeout: float = 10.0):
        self.timeout = timeout

    async def headlines(self, source: str, limit: int = 20) -> list[MacroHeadline]:
        source = source.lower()
        if source not in FEEDS:
            raise ValueError(f"Unsupported official RSS source: {source}")
        if isinstance(limit, bool) or not isinstance(limit, int) or not 1 <= limit <= 50:
            raise ValueError("limit must be an integer from 1 to 50")
        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
            response = await client.get(FEEDS[source]["url"])
            response.raise_for_status()
        return parse_feed(response.text, source=source, limit=limit)
