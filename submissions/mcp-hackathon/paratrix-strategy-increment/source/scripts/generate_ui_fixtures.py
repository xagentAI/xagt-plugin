"""Write explicitly constructed UI acceptance inputs; never real account/market data."""

import argparse
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
from pathlib import Path


def curve(name, values):
    start = datetime(2020, 1, 1, tzinfo=timezone.utc)
    stamps = [(start + timedelta(days=i)).isoformat().replace("+00:00", "Z") for i in range(len(values))]
    return {
        "schema_version": 1,
        "name": name,
        "strategy_id": name,
        "run_id": "constructed-ui-v1",
        "source_kind": "inline_simulation",
        "currency": "USDT",
        "frequency": "1d",
        "timezone": "UTC",
        "timestamp_convention": "valuation_boundary",
        "equity_kind": "mark_to_market",
        "completeness": "complete",
        "external_cash_flows": "none",
        "cost_model": "ui-zero-cost-v1",
        "initial": {"timestamp": stamps[0], "equity": str(values[0])},
        "points": [
            {"timestamp": stamp, "equity": str(value)} for stamp, value in zip(stamps[1:], values[1:])
        ],
        "provenance": {
            "description": "仅供功能验收的人工构造模拟净值，不代表真实市场或策略。",
            "data_version": "constructed-ui-v1",
            "observed_before": False,
        },
    }


def generate(destination):
    destination.mkdir(parents=True, exist_ok=True)
    baseline = curve("QA 手算基线 A", [100, 80, 110])
    candidate = curve("QA 手算候选 B", [100, 120, 105])
    for filename, value in [("baseline.json", baseline), ("candidate.json", candidate)]:
        (destination / filename).write_text(json.dumps(value, ensure_ascii=False, indent=2), encoding="utf-8")
    incompatible = deepcopy(candidate)
    incompatible.update(name="QA 不同币种 B", currency="USD")
    (destination / "incompatible.json").write_text(
        json.dumps(incompatible, ensure_ascii=False), encoding="utf-8"
    )
    invalid = deepcopy(candidate)
    invalid["points"].pop(0)
    (destination / "missing-day.json").write_text(json.dumps(invalid, ensure_ascii=False), encoding="utf-8")
    (destination / "invalid.json").write_text('{"not valid JSON', encoding="utf-8")
    (destination / "duplicate-key.json").write_text(
        '{"schema_version":1,"schema_version":1}', encoding="utf-8"
    )
    precision = curve("QA 原始数字精度", [100, 101, 102])
    payload = json.dumps(precision, ensure_ascii=False).replace(
        '"equity": "100"', '"equity": 100.123456789123456789'
    )
    (destination / "precision.json").write_text(payload, encoding="utf-8")
    (destination / "oversized.json").write_text(" " * (2 * 1024 * 1024 + 1), encoding="utf-8")
    return {
        "files": 8,
        "expected_full_range": {
            "A_return_pct": "10",
            "AB_return_pct": "9",
            "AC_return_pct": "8",
            "A_mdd_pct": "20",
            "AB_mdd_pct": "12",
            "AC_mdd_pct": "16",
            "four_deltas_pp": ["8", "1", "1", "-4"],
        },
        "example_criteria_pp": ["8", "1", "1", "0"],
        "expected_status": "criteria_met",
        "note": "Independently hand-computed fixed initial 80/20 references, not engine-generated expectations.",
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, default=Path("runtime/ui-fixtures"))
    args = parser.parse_args()
    print(json.dumps(generate(args.output), ensure_ascii=False, indent=2))
