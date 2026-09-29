from life_exchange_rate.models import EventType
from life_exchange_rate.providers.official_rss import parse_feed


SAMPLE = """<?xml version='1.0'?>
<rss version='2.0'><channel>
<item>
<title>Federal Reserve issues FOMC statement on monetary policy</title>
<link>https://example.test/fomc</link>
<pubDate>Thu, 10 Sep 2026 18:00:00 GMT</pubDate>
</item>
</channel></rss>
"""


def test_rss_parser_keeps_headline_separate_from_quantified_event():
    rows = parse_feed(SAMPLE, source="fed")
    assert len(rows) == 1
    assert rows[0].event_type_hint == EventType.INTEREST_RATE_CHANGE
    assert rows[0].requires_quantification is True
    assert rows[0].publisher == "Federal Reserve Board"
