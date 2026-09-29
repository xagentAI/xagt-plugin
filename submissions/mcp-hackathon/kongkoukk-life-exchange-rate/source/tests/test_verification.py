import json
from pathlib import Path

from life_exchange_rate.main import app
from life_exchange_rate.models import TranslateRequest
from life_exchange_rate.service import translate_request

ROOT = Path(__file__).resolve().parents[1] / "verification"


def test_saved_openapi_matches_running_contract():
    assert json.loads((ROOT / "openapi.json").read_text(encoding="utf-8")) == app.openapi()


def test_saved_fx_response_matches_actual_calculation():
    request = TranslateRequest.model_validate_json((ROOT / "fixtures/fx-request.json").read_text(encoding="utf-8"))
    expected = json.loads((ROOT / "fixtures/fx-response.json").read_text(encoding="utf-8"))
    assert translate_request(request) == expected
    assert expected["direct_effect_home"] == 1739.13
    assert expected["work_hours_equivalent"] == 8.7


def test_policy_fixture_preserves_currency_boundary():
    request = TranslateRequest.model_validate_json((ROOT / "fixtures/policy-request.json").read_text(encoding="utf-8"))
    result = translate_request(request)
    assert request.event.affected_currencies == ["EUR"]
    assert request.profile.home_currency == "SEK"
    assert result["direct_effect_home"] is None
