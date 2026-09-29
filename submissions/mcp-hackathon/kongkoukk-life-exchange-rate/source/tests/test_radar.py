from life_exchange_rate.providers.fixtures import demo_events, demo_profile
import pytest

from life_exchange_rate.radar import rank_events, score_market_significance


def test_demo_radar_prioritizes_personally_relevant_large_events():
    ranked = rank_events(demo_events(), demo_profile())
    assert len(ranked) == 3
    assert ranked[0].priority_score >= ranked[-1].priority_score
    jpy = next(item for item in ranked if item.event.event_id == "demo-jpy-sek-8pct")
    assert jpy.user_relevance == 100
    assert jpy.market_significance >= 75
    assert any("travel target" in reason for reason in jpy.relevance_reasons)


@pytest.mark.parametrize("invalid_z", [float("nan"), float("inf"), float("-inf"), True, "3.2", None, 10**500])
def test_invalid_metadata_z_score_uses_transparent_fallback(invalid_z):
    event = demo_events()[0]
    event.metadata["z_score"] = invalid_z
    score, method = score_market_significance(event)
    assert 0 <= score <= 100
    assert method == "fallback_fx_percent_move"
