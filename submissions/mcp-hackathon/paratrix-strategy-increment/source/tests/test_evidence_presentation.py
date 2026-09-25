"""English result display and strict verification of historical Chinese evidence."""

import json
from copy import deepcopy
from pathlib import Path

import pytest

from app.domain.engine import InputError, evaluate, normalize_curve
from app.evidence import EvidenceError, build_evidence, reproduce
from app.storage import digest
from test_domain_engine import curve


def new_bundle():
    baseline, candidate = normalize_curve(curve([100, 80, 110])), normalize_curve(curve([100, 90, 105]))
    result = evaluate(baseline, candidate)
    record = {
        "experiment_id": "e_locale_test",
        "created_at": "2026-01-01T00:00:00Z",
        "config": {**{key: result["coverage"][key] for key in ("start", "end")}, "criteria": None},
        "provenance": {},
        "result": result,
    }
    return build_evidence(record, baseline, candidate)


def rehash(bundle):
    bundle["integrity"]["payload_sha256"] = digest({k: v for k, v in bundle.items() if k != "integrity"})


def test_new_evidence_is_english_and_reproduces_without_mutation():
    bundle = new_bundle()
    original = deepcopy(bundle)
    assert bundle["result"]["display_language"] == "en"
    assert "Initial 80% A" in bundle["result"]["scenarios"]["candidate"]["label"]
    assert reproduce(bundle)["verified"]
    assert bundle == original


def test_original_published_chinese_evidence_still_verifies_exactly():
    path = Path(__file__).resolve().parents[2] / "verification" / "local-evidence.json"
    original_bytes = path.read_bytes()
    bundle = json.loads(original_bytes)
    assert "display_language" not in bundle["result"]
    assert reproduce(bundle)["verified"]
    assert path.read_bytes() == original_bytes


@pytest.mark.parametrize("legacy", [False, True])
@pytest.mark.parametrize("field", ["summary", "scenario_label", "limitation", "number", "locale"])
def test_result_tampering_is_rejected_even_after_rehash(legacy, field):
    if legacy:
        path = Path(__file__).resolve().parents[2] / "verification" / "local-evidence.json"
        bundle = json.loads(path.read_bytes())
    else:
        bundle = new_bundle()
    if field == "summary":
        bundle["result"]["summary"] = "Altered conclusion"
    elif field == "scenario_label":
        bundle["result"]["scenarios"]["candidate"]["label"] = "Altered scenario"
    elif field == "limitation":
        bundle["result"]["limitations"].pop()
    elif field == "number":
        bundle["result"]["scenarios"]["candidate"]["total_return_pct"] = "1000000"
    else:
        bundle["result"]["display_language"] = "unsupported"
    rehash(bundle)
    with pytest.raises(EvidenceError):
        reproduce(bundle)


def test_language_selection_does_not_change_calculated_values():
    baseline, candidate = curve([100, 80, 110]), curve([100, 90, 105])
    english = evaluate(baseline, candidate)
    legacy = evaluate(baseline, candidate, display_language="zh")
    for field in ("method_version", "status", "coverage", "model", "series", "diagnostics"):
        assert english[field] == legacy[field]
    for scenario in english["scenarios"]:
        assert {k: v for k, v in english["scenarios"][scenario].items() if k != "label"} == {
            k: v for k, v in legacy["scenarios"][scenario].items() if k != "label"
        }


def test_invalid_input_issues_are_english():
    with pytest.raises(InputError) as caught:
        normalize_curve({})
    assert caught.value.issues
    assert all(issue["message"].isascii() for issue in caught.value.issues)
