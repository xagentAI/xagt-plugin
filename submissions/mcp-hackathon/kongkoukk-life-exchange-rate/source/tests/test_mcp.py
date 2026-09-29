import pytest
from mcp import Client

from life_exchange_rate import mcp_server as server
from life_exchange_rate.providers.fixtures import demo_events, demo_profile


EXPECTED_TOOLS = {
    "get_macro_events", "get_official_macro_headlines", "get_live_fx_event",
    "get_policy_rate_event", "get_energy_event", "rank_events_for_user",
    "translate_event_to_life", "convert_to_life_units", "compare_event_scenarios",
}


def data(result):
    assert not result.is_error, result.content
    assert result.structured_content is not None
    structured = result.structured_content
    return structured["result"] if set(structured) == {"result"} else structured


@pytest.mark.asyncio
async def test_mcp_discovery_calls_validation_and_errors(monkeypatch):
    async def fixture_fx(*args, **kwargs):
        return demo_events()[0]

    async def fixture_headlines(*args, **kwargs):
        return [{"headline_id": "test-headline", "title": "Fixture headline, not an observation", "requires_quantification": True}]

    monkeypatch.setattr(server, "fetch_live_fx_event", fixture_fx)
    monkeypatch.setattr(server, "get_official_headlines", fixture_headlines)
    profile = demo_profile().model_dump(mode="json")
    async with Client(server.mcp) as client:
        listed = await client.list_tools()
        assert {tool.name for tool in listed.tools} == EXPECTED_TOOLS
        translate_schema = next(tool.input_schema for tool in listed.tools if tool.name == "translate_event_to_life")
        assert "assumptions" in translate_schema["properties"]
        events = data(await client.call_tool("get_macro_events", {"mode": "demo"}))
        assert len(events) == 3
        event = data(await client.call_tool("get_live_fx_event", {"base_currency": "SEK", "quote_currency": "JPY"}))
        headlines = data(await client.call_tool("get_official_macro_headlines", {"source": "fed", "limit": 1}))
        assert headlines[0]["requires_quantification"] is True
        for tool_name in ("get_policy_rate_event", "get_energy_event"):
            fixture = data(await client.call_tool(tool_name, {"mode": "fixture"}))
            assert fixture["provenance"]["source_type"] == "synthetic_fixture"
        ranked = data(await client.call_tool("rank_events_for_user", {"events": events, "profile": profile}))
        assert len(ranked) == 3
        assert ranked[0]["priority_score"] >= ranked[-1]["priority_score"]
        impact = data(await client.call_tool("translate_event_to_life", {"event": event, "profile": profile}))
        assert impact["direct_effect_home"] == 1739.13
        assert impact["work_hours_equivalent"] == 8.7
        assert impact["calculation_trace"]
        conversion = data(await client.call_tool("convert_to_life_units", {"amount": 1739.13, "currency": "SEK", "profile": profile}))
        assert conversion["work_hours_equivalent"] == 8.7
        zero_pass_through = {"interest_rate_pass_through": 0, "oil_to_fuel_pass_through": 0}
        oil_impact = data(await client.call_tool("translate_event_to_life", {
            "event": events[2], "profile": profile, "assumptions": zero_pass_through,
        }))
        assert oil_impact["direct_effect_home"] == 0
        scenarios = data(await client.call_tool("compare_event_scenarios", {
            "event": events[2], "profile": profile, "assumptions": zero_pass_through,
        }))
        assert len(scenarios) == 3
        assert all(item["result"]["direct_effect_home"] == 0 for item in scenarios)

        invalid_calls = [
            ("get_macro_events", {"mode": "invent"}),
            ("get_live_fx_event", {"base_currency": "SEK", "quote_currency": "SEK"}),
            ("get_live_fx_event", {"base_currency": "12!", "quote_currency": "JPY"}),
            ("get_live_fx_event", {"base_currency": "SEK", "quote_currency": "JPY", "lookback_days": 1}),
            ("get_official_macro_headlines", {"source": "untrusted"}),
            ("get_official_macro_headlines", {"source": "fed", "limit": 51}),
            ("get_policy_rate_event", {"mode": "invent"}),
            ("get_energy_event", {"lookback_days": 366}),
            ("translate_event_to_life", {"event": headlines[0], "profile": profile}),
            ("translate_event_to_life", {"event": events[2], "profile": profile, "assumptions": {"oil_to_fuel_pass_through": 2}}),
            ("convert_to_life_units", {"amount": 100, "currency": "USD", "profile": profile}),
            ("compare_event_scenarios", {"event": event, "profile": profile, "mild_multiplier": 0}),
        ]
        for tool_name, arguments in invalid_calls:
            result = await client.call_tool(tool_name, arguments)
            assert result.is_error, tool_name

        async def failed_fetch(*args, **kwargs):
            raise RuntimeError("https://provider.invalid/?api_key=DO_NOT_LEAK")

        monkeypatch.setattr(server, "fetch_energy_event", failed_fetch)
        failed = await client.call_tool("get_energy_event", {"mode": "live"})
        assert failed.is_error
        assert "DO_NOT_LEAK" not in str(failed.content)
        assert "provider.invalid" not in str(failed.content)
