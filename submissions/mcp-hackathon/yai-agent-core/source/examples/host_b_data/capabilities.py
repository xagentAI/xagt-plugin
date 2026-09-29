"""宿主 B：一个极简销售数据应用的业务能力层（与宿主 A 完全不同的领域）。"""

from __future__ import annotations

_RECORDS = [
    {"order": "A001", "category": "硬件", "amount": 1200, "region": "华东"},
    {"order": "A002", "category": "软件", "amount": 800, "region": "华南"},
    {"order": "A003", "category": "硬件", "amount": 1500, "region": "华东"},
    {"order": "A004", "category": "服务", "amount": 600, "region": "华北"},
]


def list_records() -> list[dict]:
    """列出全部销售记录。"""
    return _RECORDS


def filter_by_category(category: str = "") -> list[dict]:
    """按品类筛选销售记录，品类为空时返回全部。"""
    if category:
        return [r for r in _RECORDS if r["category"] == category]
    return _RECORDS


def sum_amount(category: str = "") -> int:
    """统计销售额，可按品类筛选后汇总。"""
    rows = _RECORDS
    if category:
        rows = [r for r in _RECORDS if r["category"] == category]
    return sum(r["amount"] for r in rows)
