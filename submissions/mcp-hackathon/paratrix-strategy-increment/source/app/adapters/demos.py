"""Public examples; all their intervals have already been observed.

The recorded AIMM PerpEngine values a bar at its close but writes its opening
label as ``ts`` (upstream engines/perp.py:363-382, 731-742 at the commit in the
manifest). Daily values therefore belong to ts + one day. Initial capital is
the harness's explicit 10000 before the first scored bar, not its first NAV.
"""

from __future__ import annotations

import copy
from datetime import datetime, timedelta, timezone
from decimal import Decimal
import hashlib
import json
from pathlib import Path


_FIXTURES = Path(__file__).resolve().parents[2] / "fixtures" / "recorded" / "aimm"
try:
    from app._worker_build import FIXTURE_BYTES
except ModuleNotFoundError:
    FIXTURE_BYTES = None


def _fixture_bytes(name):
    if FIXTURE_BYTES is not None:
        return FIXTURE_BYTES[name]
    return (_FIXTURES / name).read_bytes()


_DAY_MS = 86_400_000
_CASE_SUMMARIES = (
    {
        "id": "aimm-weight",
        "name": "AIMM 权重变体",
        "kind": "recorded_local_aimm",
        "description": "真实本地 AIMM 模拟回测：比较 TA/形态权重 75/25 与 25/75；已观察区间，不是托管 Nexus 或实盘。",
    },
    {
        "id": "duplicate",
        "name": "复制基准策略",
        "kind": "synthetic",
        "description": "把 A 原样复制为 B；用于验证组合不能因复制曲线获得增量。",
    },
    {
        "id": "cash",
        "name": "候选为零收益现金",
        "kind": "synthetic",
        "description": "把 B 构造为恒定净值；用于验证 80% A + 20% B 等于现金对照。",
    },
    {
        "id": "missing-day",
        "name": "候选缺少一天",
        "kind": "synthetic",
        "description": "故意删去候选一个日频估值点；必须阻断计算，不能补点或静默缩短区间。",
    },
    {
        "id": "tradeoff",
        "name": "回撤改善但收益牺牲过大",
        "kind": "synthetic",
        "description": "人工构造的收益与回撤取舍教学案例；阈值仅为示例，不是投资标准。",
    },
)


def _stamp(milliseconds: int) -> str:
    return datetime.fromtimestamp(milliseconds / 1000, timezone.utc).isoformat().replace("+00:00", "Z")


def _load_recorded(case_id: str) -> dict:
    manifest = json.loads(_fixture_bytes("manifest.json"))
    case = next(row for row in manifest["cases"] if row["case"] == case_id)
    # File names come from the reviewed local manifest, never from a request.
    file_path = _FIXTURES / case["file"]
    if file_path.parent != _FIXTURES or file_path.suffix != ".jsonl":
        raise ValueError("Recorded fixture manifest has an invalid path")
    payload = _fixture_bytes(case["file"])
    if hashlib.sha256(payload).hexdigest() != case["sha256"]:
        raise ValueError("Recorded fixture integrity check failed")
    rows = [json.loads(line, parse_float=Decimal) for line in payload.splitlines() if line.strip()]
    if not rows or len(rows) != case["points"]:
        raise ValueError("Recorded fixture point count differs from manifest")
    first_ts = rows[0]["ts"]
    if type(first_ts) is not int:
        raise ValueError("Recorded fixture needs explicit millisecond timestamps")
    for index, row in enumerate(rows):
        if type(row["ts"]) is not int or row["ts"] != first_ts + index * _DAY_MS:
            raise ValueError("Recorded fixture is not a complete daily sequence")
    initial = str(manifest["initial_equity"])
    if initial != "10000" or manifest["frequency"] != "1d" or manifest["currency"] != "USDT":
        raise ValueError("Recorded fixture no longer matches the verified adapter contract")
    commit = manifest["upstream_commit"]
    return {
        "schema_version": 1,
        "name": "AIMM 基准 TA75/形态25" if case_id == "baseline_a" else "AIMM 变体 TA25/形态75",
        "strategy_id": "aimm-" + case_id.replace("_", "-"),
        "run_id": case_id,
        "source_kind": "recorded_local_aimm",
        "currency": "USDT",
        "frequency": "1d",
        "timezone": "UTC",
        "timestamp_convention": "valuation_boundary",
        "equity_kind": "mark_to_market",
        "completeness": "complete",
        "external_cash_flows": "none",
        "cost_model": "aimm-perp-dd7115-fee10bps-slip5bps-funding1bps-native-daily-v1",
        "initial": {"timestamp": _stamp(first_ts), "equity": initial},
        "points": [{"timestamp": _stamp(row["ts"] + _DAY_MS), "equity": str(row["equity"])} for row in rows],
        "provenance": {
            "description": "本地 AIMM 原生 perpetual 模拟回测，单品种 BTC/USDT。源 ts 为日 bar 开盘标签；净值在该 bar 收盘盯市，已转换到次日 UTC 估值边界。独立初始本金为 10000 USDT；净值已含 10bps 交易费、5bps 滑点及上游日频引擎的固定 1bps 资金费模型，不代表真实资金费率历史。不是实盘或托管 Nexus；区间已观察，行情来源未独立认证。",
            "data_version": "recorded-2026-09-24/" + case["sha256"],
            "engine_version": commit,
            "reference": manifest["upstream_repository"]
            + "/blob/"
            + commit
            + "/src/backtest/engines/perp.py#L363",
            "observed_before": True,
        },
    }


def _synthetic_like(curve: dict, *, name: str, identifier: str, description: str) -> dict:
    result = copy.deepcopy(curve)
    result.update(name=name, strategy_id=identifier, run_id=identifier + "-v1", source_kind="synthetic")
    result["provenance"] = {
        "description": description + " 此教学区间已观察。",
        "data_version": "demo-v1",
        "observed_before": True,
    }
    return result


def _tradeoff_curve(name: str, identifier: str, values: list[str]) -> dict:
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    return {
        "schema_version": 1,
        "name": name,
        "strategy_id": identifier,
        "run_id": identifier + "-v1",
        "source_kind": "synthetic",
        "currency": "USDT",
        "frequency": "1d",
        "timezone": "UTC",
        "timestamp_convention": "valuation_boundary",
        "equity_kind": "mark_to_market",
        "completeness": "complete",
        "external_cash_flows": "none",
        "cost_model": "synthetic-zero-fees-v1",
        "initial": {"timestamp": start.isoformat().replace("+00:00", "Z"), "equity": "10000"},
        "points": [
            {"timestamp": (start + timedelta(days=i)).isoformat().replace("+00:00", "Z"), "equity": value}
            for i, value in enumerate(values, 1)
        ],
        "provenance": {
            "description": "人工构造教学模拟净值，费用设为零；不代表任何真实策略。区间及结果均已观察。",
            "data_version": "tradeoff-demo-v1",
            "observed_before": True,
        },
    }


def list_cases() -> list[dict]:
    """Return fresh public summary objects, without mutable global state."""
    return copy.deepcopy(list(_CASE_SUMMARIES))


def get_case(case_id: str) -> dict:
    """Return one fresh case; the intentionally invalid case stays invalid."""
    summary = next((row for row in _CASE_SUMMARIES if row["id"] == case_id), None)
    if summary is None:
        raise KeyError(case_id)
    result = copy.deepcopy(summary)
    result["criteria"] = None
    if case_id == "tradeoff":
        result["baseline"] = _tradeoff_curve("高收益高回撤 A", "synthetic-a", ["12000", "9000", "13000"])
        result["candidate"] = _tradeoff_curve("缓慢增长 B", "synthetic-b", ["10100", "10200", "10300"])
        result["criteria"] = {
            "min_drawdown_improvement_pp": "1",
            "max_return_sacrifice_pp": "2",
            "min_return_above_cash_pp": "0",
            "max_drawdown_above_cash_pp": "1",
        }
        return result
    baseline = _load_recorded("baseline_a")
    result["baseline"] = baseline
    if case_id == "aimm-weight":
        candidate = _load_recorded("weight_variant")
    elif case_id == "duplicate":
        candidate = _synthetic_like(
            baseline,
            name="基准 A 的教学复制",
            identifier="duplicate-a",
            description="从公开 AIMM 基准模拟净值原样复制，不是另一次独立回测。费用口径沿用原始记录。",
        )
    elif case_id == "cash":
        candidate = _synthetic_like(
            baseline,
            name="零收益现金 B",
            identifier="constant-cash",
            description="人工构造恒定净值，现金不交易，不产生交易费用；比较保留 A 的原始净费用口径。",
        )
        for point in candidate["points"]:
            point["equity"] = baseline["initial"]["equity"]
    else:
        candidate = _synthetic_like(
            _load_recorded("weight_variant"),
            name="缺一天的教学 B",
            identifier="missing-day-b",
            description="从公开 AIMM 变体故意删除一个估值点；complete 字段与事实冲突，预期由输入验证阻断。",
        )
        del candidate["points"][20]
    result["candidate"] = candidate
    return result
