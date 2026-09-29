import math
import os
import re
from pathlib import Path
from typing import Any, Callable, cast
import pytest
from pydantic import ValidationError
from app.demo import fixture
from app.research import research, features, replay, ResearchRequest, Candle, Feature
from app.audit import audit
from app.nexus import unpack


# Credential-specific signatures deliberately do not flag arbitrary public base64.
SECRET_PATTERN = re.compile(
    r"\bnxk_[A-Za-z0-9_-]{20,}\b"
    r"|\bgh[pousr]_[A-Za-z0-9]{36,}\b"
    r"|\bgithub_pat_[A-Za-z0-9_]{40,}\b"
    r"|\b(?:AKIA|ASIA)[A-Z0-9]{16}\b"
    r"|\bsk_live_[A-Za-z0-9]{20,}\b"
    r"|-----BEGIN (?:RSA |EC |OPENSSH |DSA |ENCRYPTED )?PRIVATE KEY-----"
)


def test_project_text_has_no_baseline_secret_signatures() -> None:
    root = Path(__file__).resolve().parents[1]
    excluded = {
        ".git",
        ".venv",
        "venv",
        "node_modules",
        "__pycache__",
        ".pytest_cache",
        ".mypy_cache",
        ".ruff_cache",
        "docs",
        "catalog",
        "catalogs",
    }
    findings: list[str] = []
    for folder, directories, filenames in os.walk(root, followlinks=False):
        directories[:] = [
            name for name in directories if name not in excluded and not (Path(folder) / name).is_symlink()
        ]
        for name in filenames:
            path = Path(folder) / name
            if path.is_symlink() or name == "nexus-docs.txt":
                continue
            try:
                text = path.read_text(encoding="utf-8-sig")
            except UnicodeError:
                continue
            if "\x00" not in text and SECRET_PATTERN.search(text):
                findings.append(path.relative_to(root).as_posix())
    # Never include matched content, even when the gate fails.
    assert not findings, "Potential credentials in: " + ", ".join(sorted(findings))


def test_baseline_secret_signatures_detect_keys_not_public_base64() -> None:
    samples = [
        "nxk_" + "a" * 20,
        "ghp_" + "a" * 36,
        "github_pat_" + "a" * 40,
        "AKIA" + "A" * 16,
        "sk_live_" + "a" * 20,
        "-----BEGIN " + "PRIVATE KEY-----",
    ]
    for index, sample in enumerate(samples):
        if SECRET_PATTERN.search(sample) is None:
            pytest.fail(f"Secret signature fixture {index} was not detected", pytrace=False)
    assert SECRET_PATTERN.search("nxk_" + "a" * 19) is None
    assert SECRET_PATTERN.search("UHVibGljIGRvY3VtZW50YXRpb24gZXhhbXBsZQ==") is None


def test_future_changes_cannot_change_training_or_threshold() -> None:
    request = fixture()
    original = research(request)
    split = int(len(request.candles) * 0.8)
    data = request.model_dump()
    for candle in data["candles"][split:]:
        for key in ("o", "h", "l", "c"):
            candle[key] *= 2
    request = ResearchRequest.model_validate(data)
    changed = research(request)
    assert original["strategy"] == changed["strategy"]
    assert original["folds"]["train"] == changed["folds"]["train"]
    assert original["folds"]["validation"] == changed["folds"]["validation"]


def test_next_open_execution_and_costs_match_hand_calculation() -> None:
    candles = [Candle(t=1 + i * 86400000, o=100, h=120, l=90, c=110, v=1) for i in range(3)]
    feat: list[Feature] = [{"long": True, "vol": 0.01} for _ in candles]
    r = replay(candles, feat, 1, 3, 100)
    expected = 10000 / (100 * 1.01) * 110 * 0.99
    assert r["equity"][-1]["equity"] == pytest.approx(expected, abs=1e-5)
    assert r["trades"][0]["entry_t"] == candles[1].t
    assert r["metrics"]["trade_count"] == 1
    units = 10000 / (100 * 1.01)
    assert r["metrics"]["execution_cost_usdt"] == pytest.approx(units * (100 + 110) * 0.01, abs=1e-4)
    assert r["trades"][0]["exit"] == "fold_end"
    assert r["trades"][0]["exit_t"] == candles[-1].t + 86400000 - 1


def test_a_trade_cannot_use_its_own_close_signal() -> None:
    candles = [Candle(t=1 + i * 86400000, o=100, h=101, l=99, c=100, v=1) for i in range(3)]
    feat: list[Feature] = [{"long": False, "vol": 0.01}, {"long": True, "vol": 0.01}, {"long": True, "vol": 0.01}]
    r = replay(candles, feat, 1, 3, 0)
    assert r["trades"][0]["entry_t"] == candles[2].t


def test_input_rejects_gaps_and_nonfinite_prices() -> None:
    data = fixture().model_dump()
    data["candles"][10]["t"] += 1
    with pytest.raises(ValidationError):
        ResearchRequest.model_validate(data)
    with pytest.raises(ValidationError):
        Candle(t=1, o=math.nan, h=10, l=1, c=5, v=2)


def test_synthetic_never_becomes_profit_evidence() -> None:
    r = research(fixture())
    assert r["decision"] == "WAIT"
    assert "SYNTHETIC_DATA_NOT_PROFIT_EVIDENCE" in r["reason_codes"]


def test_stale_and_mismatched_run_fail_closed() -> None:
    ev: dict[str, Any] = {k: {"status": "received", "data": {}} for k in ["signal", "metrics", "equity", "trades"]}
    ev["signal"]["data"] = {"symbol": "BTC/USDT", "trade_intent": "BUY", "timestamp": 1000}
    ev["equity"]["data"] = {"run_id": "a"}
    ev["trades"]["data"] = {"run_id": "b"}
    r = audit(ev, "BTC/USDT", now=100000)
    assert r["decision"] == "WAIT"
    assert "SIGNAL_FRESH" in r["reason_codes"]
    assert "RUN_CONSISTENCY" in r["reason_codes"]


def test_mcp_envelopes_unwrap_and_error_is_not_evidence() -> None:
    # The legacy adapter is outside this change's file scope.
    unwrap = cast(Callable[[dict[str, Any]], dict[str, Any]], unpack)
    assert unwrap({"content": [{"type": "text", "text": '{"trade_count": 4}'}]}) == {"trade_count": 4}
    with pytest.raises(ValueError):
        unwrap({"isError": True, "content": []})


def test_higher_costs_do_not_improve_fixed_path() -> None:
    request = fixture()
    feat = features(request.candles)
    low = replay(request.candles, feat, 720, 900, 10)
    high = replay(request.candles, feat, 720, 900, 100)
    assert high["metrics"]["return_pct"] <= low["metrics"]["return_pct"]


def test_features_are_prefix_causal() -> None:
    candles = fixture().candles
    assert features(candles[:720]) == features(candles)[:720]


def test_malformed_audit_evidence_fails_closed() -> None:
    result = audit(
        {
            "signal": None,
            "metrics": [],
            "equity": {"status": "received", "data": {"points": [None, {}]}},
            "trades": "invalid",
        },
        "BTC/USDT",
        now=0,
    )
    assert result["decision"] == "WAIT"
    assert "SIGNAL_FRESH" in result["reason_codes"]
    assert "EQUITY_INTEGRITY" in result["reason_codes"]


@pytest.mark.parametrize("cost", [-1, 1201, math.nan, math.inf])
def test_replay_rejects_invalid_costs(cost: float) -> None:
    candles = fixture().candles
    with pytest.raises(ValueError, match="costs"):
        replay(candles, features(candles), 720, 900, cost)
