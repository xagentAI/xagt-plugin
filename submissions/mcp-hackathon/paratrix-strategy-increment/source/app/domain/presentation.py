"""Versioned display resources; Chinese text reproduces historical v1 evidence exactly.

API and newly generated evidence use English. The legacy locale is retained as a
presentation resource so old evidence keeps full deterministic verification.
"""

_COPY = {
    "en": {
        "scenario_labels": {
            "baseline": "100% A",
            "candidate": "Initial 80% A + 20% B",
            "cash": "Initial 80% A + 20% cash",
        },
        "fact_labels": [
            "Drawdown improvement over A",
            "Return sacrifice versus A",
            "Return improvement over cash",
            "Additional drawdown versus cash",
        ],
        "summaries": {
            "comparison_only": "No research criteria were set; this compares historical simulated facts without a pass or fail decision.",
            "criteria_met": "All four research preferences were met over the selected historical simulation interval; this does not establish statistical significance or future returns.",
            "criteria_not_met": "At least one research preference was not met over the selected historical simulation interval; review the return and drawdown trade-offs.",
        },
        "limitations": [
            "This describes the supplied simulated equity and selected interval only; source declarations do not independently authenticate market data or authorship.",
            "Initial 80/20 weights remain fixed without rebalancing; cash earns zero and shared accounts, margin, liquidation, and capital-scale effects are not modeled.",
            "Metrics retain costs already reflected in source equity; no additional costs are deducted, and trading within a strategy is not assumed to be free.",
            "Drawdown is measured at daily valuations and does not represent intraday maximum drawdown; daily volatility is the unannualized sample standard deviation.",
            "Correlation is descriptive and does not determine whether criteria are met; user-selected thresholds do not establish future performance.",
        ],
        "small_sample": "The interval contains fewer than 30 daily returns; results are descriptive for a small sample and are not labeled statistically valid.",
        "one_return": "With only one daily return, sample standard deviation and return correlation are unavailable.",
        "duplicate": "B has exactly the same normalized path as A and provides no additional path variation or diversification evidence.",
        "synthetic": "Constructed data are included to explain the method and validate behavior, not as evidence of a profitable strategy.",
    },
    "zh": {
        "scenario_labels": {
            "baseline": "100% A",
            "candidate": "初始80% A + 20% B",
            "cash": "初始80% A + 20%现金",
        },
        "fact_labels": ["相对A回撤改善", "相对A收益牺牲", "相对现金收益增量", "相对现金新增回撤"],
        "summaries": {
            "comparison_only": "未设置研究标准；仅比较历史模拟事实，不作是否达标的判定。",
            "criteria_met": "在所选历史模拟区间内，四项研究偏好均达到；不代表统计显著性或未来收益。",
            "criteria_not_met": "在所选历史模拟区间内，至少一项研究偏好未达到；请查看逐项收益与回撤取舍。",
        },
        "limitations": [
            "仅描述输入的模拟净值及所选区间；来源声明不等于对行情真实性或作者身份的独立认证。",
            "固定初始80/20份额，不再平衡；现金收益为0，未模拟共享账户、保证金、强平或资本规模效应。",
            "指标保留来源净值已包含的费用；没有额外扣费，亦不表示策略内部交易免费。",
            "回撤仅在日频估值上计算，不能代表日内最大回撤；日波动使用样本标准差，未年化。",
            "相关性仅为辅助说明，不触发达标；研究阈值是用户偏好，不能证明未来表现。",
        ],
        "small_sample": "所选区间少于30个日收益，结果只适合小样本描述，不标记统计有效性。",
        "one_return": "只有一个日收益，样本标准差及收益相关性不可用。",
        "duplicate": "B的归一化路径与A完全一致，未提供新增路径差异或分散证据。",
        "synthetic": "包含构造数据，仅用于说明方法与验证行为，不是可盈利策略证据。",
    },
}


def presentation(language):
    if not isinstance(language, str) or language not in _COPY:
        raise ValueError("Unsupported result display language")
    return _COPY[language]
