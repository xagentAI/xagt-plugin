from dataclasses import replace
from datetime import UTC, datetime, timedelta

import pytest

from services.policy_service.risk_policy import RISK_MAPPING_VERSION, map_risk_result
from services.policy_service.risk_provider import RiskProviderResult


def provider_result(
    *,
    score: int,
    risk_level: str,
    indicators: list[str] | None = None,
    risk_details: list[dict[str, str]] | None = None,
    hacking_event: str | None = None,
) -> RiskProviderResult:
    assessed_at = datetime(2026, 7, 31, tzinfo=UTC)
    return RiskProviderResult(
        provider="misttrack",
        endpoint="https://merchant.example/paid-resource",
        subject="0x1111111111111111111111111111111111111111",
        network="base",
        asset="USDC",
        coin="USDC",
        score=score,
        risk_level=risk_level,
        indicators=tuple(indicators or []),
        risk_details=tuple(risk_details or []),
        hacking_event=hacking_event,
        assessed_at=assessed_at,
        expires_at=assessed_at + timedelta(minutes=5),
        response_sha256="a" * 64,
    )


@pytest.mark.parametrize(
    ("score", "level", "expected"),
    [
        (30, "low", "allow"),
        (31, "moderate", "hold"),
        (70, "moderate", "hold"),
        (71, "high", "deny"),
        (90, "high", "deny"),
        (91, "severe", "deny"),
    ],
)
def test_maps_documented_score_boundaries(score, level, expected):
    result = provider_result(score=score, risk_level=level)

    assert map_risk_result(result).decision == expected


def test_direct_sanction_or_mixer_is_always_denied():
    result = provider_result(
        score=10,
        risk_level="low",
        risk_details=[{"risk_type": "sanctioned_entity", "exposure_type": "direct"}],
    )

    decision = map_risk_result(result)

    assert decision.decision == "deny"
    assert decision.reasons == ("direct_hard_risk",)


def test_direct_malicious_address_is_denied_at_low_score():
    result = provider_result(
        score=10,
        risk_level="low",
        risk_details=[{"risk_type": "malicious_address", "exposure_type": "direct"}],
    )

    assert map_risk_result(result).decision == "deny"


@pytest.mark.parametrize("risk_type", ["sanctioned_entity", "illicit_activity", "mixer"])
def test_each_direct_hard_risk_type_is_denied(risk_type):
    result = provider_result(
        score=10,
        risk_level="low",
        risk_details=[{"risk_type": risk_type, "exposure_type": "direct"}],
    )

    assert map_risk_result(result).decision == "deny"


@pytest.mark.parametrize("risk_type", ["sanctioned_entity", "illicit_activity", "mixer"])
def test_indirect_hard_risk_type_is_held_even_at_a_low_score(risk_type):
    result = provider_result(
        score=10,
        risk_level="low",
        risk_details=[{"risk_type": risk_type, "exposure_type": "indirect"}],
    )

    decision = map_risk_result(result)

    assert decision.decision == "hold"
    assert decision.reasons == ("risk_detail_present",)


def test_indirect_malicious_address_is_held_even_at_a_low_score():
    result = provider_result(
        score=10,
        risk_level="low",
        risk_details=[{"risk_type": "malicious_address", "exposure_type": "indirect"}],
    )

    decision = map_risk_result(result)

    assert decision.decision == "hold"
    assert decision.reasons == ("risk_detail_present",)


@pytest.mark.parametrize(
    "risk_detail",
    [
        {"risk_type": "mixer", "exposure_type": "unknown"},
        {"risk_type": "mixer"},
    ],
)
def test_known_risk_type_with_unknown_exposure_is_held(risk_detail):
    result = provider_result(score=10, risk_level="low", risk_details=[risk_detail])

    assert map_risk_result(result).decision == "hold"


@pytest.mark.parametrize("exposure_type", ["direct", "indirect"])
def test_unknown_risk_detail_is_held_instead_of_silently_allowed(exposure_type):
    result = provider_result(
        score=10,
        risk_level="low",
        risk_details=[{"risk_type": "new_risk_type", "exposure_type": exposure_type}],
    )

    decision = map_risk_result(result)

    assert decision.decision == "hold"
    assert decision.reasons == ("risk_detail_present",)


def test_empty_risk_detail_is_held_instead_of_silently_allowed():
    result = provider_result(score=10, risk_level="low", risk_details=[{}])

    decision = map_risk_result(result)

    assert decision.decision == "hold"
    assert decision.reasons == ("risk_detail_present",)


@pytest.mark.parametrize(
    "indicator",
    [
        "malicious address",
        "sanctioned entity",
        "mixer",
        "involved theft activity",
        "involved ransom activity",
        "involved phishing activity",
        "involved illicit activity",
    ],
)
def test_known_hard_indicator_is_denied_after_lowercase_normalization(indicator):
    result = provider_result(score=10, risk_level="low", indicators=[indicator.upper()])

    assert map_risk_result(result).decision == "deny"


def test_unknown_indicator_is_held_instead_of_silently_allowed():
    result = provider_result(score=10, risk_level="low", indicators=["new signal"])

    assert map_risk_result(result).decision == "hold"


def test_unknown_indicator_reason_is_stable_and_does_not_echo_provider_text():
    provider_text = "provider supplied arbitrary indicator payload"
    result = provider_result(score=10, risk_level="low", indicators=[provider_text])

    decision = map_risk_result(result)

    assert decision.decision == "hold"
    assert decision.reasons == ("unknown_indicator_present",)
    assert provider_text not in decision.reasons


def test_non_dict_risk_detail_fails_closed_as_unavailable():
    result = provider_result(score=10, risk_level="low")
    result = replace(result, risk_details=("not a mapping",))  # type: ignore[arg-type]

    decision = map_risk_result(result)

    assert decision.decision == "unavailable"
    assert decision.reasons == ("malformed_risk_result",)


def test_non_string_indicator_fails_closed_as_unavailable():
    result = provider_result(score=10, risk_level="low")
    result = replace(result, indicators=(None,))  # type: ignore[arg-type]

    decision = map_risk_result(result)

    assert decision.decision == "unavailable"
    assert decision.reasons == ("malformed_risk_result",)


@pytest.mark.parametrize(
    "risk_detail",
    [
        {"risk_type": [], "exposure_type": "direct"},
        {"risk_type": "mixer", "exposure_type": []},
        {"risk_type": 7, "exposure_type": "direct"},
    ],
)
def test_malformed_risk_detail_fields_fail_closed_as_unavailable(risk_detail):
    result = provider_result(score=10, risk_level="low")
    result = replace(result, risk_details=(risk_detail,))

    decision = map_risk_result(result)

    assert decision.decision == "unavailable"
    assert decision.reasons == ("malformed_risk_result",)


@pytest.mark.parametrize("risk_level", [[], 7])
def test_non_string_or_unhashable_risk_level_fails_closed_as_unavailable(risk_level):
    result = provider_result(score=10, risk_level="low")
    result = replace(result, risk_level=risk_level)  # type: ignore[arg-type]

    decision = map_risk_result(result)

    assert decision.decision == "unavailable"
    assert decision.reasons == ("malformed_risk_result",)


def test_nonempty_hacking_event_holds_a_low_score_with_a_fixed_reason():
    result = provider_result(
        score=10,
        risk_level="low",
        hacking_event="provider supplied incident text",
    )

    decision = map_risk_result(result)

    assert decision.decision == "hold"
    assert decision.reasons == ("hacking_event_present",)
    assert "provider supplied incident text" not in decision.reasons[0]


def test_nonempty_hacking_event_does_not_downgrade_a_high_score_denial():
    result = provider_result(
        score=80,
        risk_level="high",
        hacking_event="provider supplied incident text",
    )

    assert map_risk_result(result).decision == "deny"


@pytest.mark.parametrize("indicator", ["previously malicious address", "mixer service"])
def test_indicator_matching_is_exact_not_substring_based(indicator):
    result = provider_result(score=10, risk_level="low", indicators=[indicator])

    assert map_risk_result(result).decision == "hold"


def test_inconsistent_score_and_level_is_unavailable():
    result = provider_result(score=80, risk_level="low")

    assert map_risk_result(result).decision == "unavailable"


def test_includes_the_documented_mapping_version():
    decision = map_risk_result(provider_result(score=10, risk_level="low"))

    assert decision.mapping_version == RISK_MAPPING_VERSION == "misttrack-policy-v1"
