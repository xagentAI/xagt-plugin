"""Deterministic simulation research, with a local 50-digit Decimal context.

Numbers are bounded to 40 significant digits and adjusted exponents [-30, 30].
No data are fetched, sorted, repaired, filled, or silently intersected here.
"""

from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Context, Decimal, InvalidOperation, localcontext
import math
import re
from typing import Any

from app.domain.presentation import presentation

METHOD_VERSION = "fixed-initial-80-20/v1"
DECIMAL_PRECISION = 50
MAX_INPUT_DIGITS = 40
MAX_POINTS = 5000
_ZERO = Decimal(0)
_ONE = Decimal(1)
_HUNDRED = Decimal(100)
_WA, _WB = Decimal("0.8"), Decimal("0.2")
_DAY = timedelta(days=1)
_TIMESTAMP = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d{1,6})?(?:Z|\+00:00)$", re.ASCII)
_NUMBER = re.compile(r"^[+-]?(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?$", re.ASCII)
_FIELDS = frozenset(
    {
        "schema_version",
        "name",
        "strategy_id",
        "run_id",
        "source_kind",
        "currency",
        "frequency",
        "timezone",
        "timestamp_convention",
        "equity_kind",
        "completeness",
        "external_cash_flows",
        "cost_model",
        "initial",
        "points",
        "provenance",
    }
)
_SOURCES = frozenset({"inline_simulation", "recorded_local_aimm", "recorded_nexus", "synthetic"})
_SEMANTICS = {
    "frequency": "1d",
    "timezone": "UTC",
    "timestamp_convention": "valuation_boundary",
    "equity_kind": "mark_to_market",
    "completeness": "complete",
    "external_cash_flows": "none",
}
_UNKNOWN_COSTS = frozenset(
    {
        "unknown",
        "unspecified",
        "n/a",
        "na",
        "none",
        "null",
        "unavailable",
        "not specified",
        "not provided",
        "?",
        "未知",
        "不明",
        "未说明",
        "未提供",
        "不清楚",
    }
)
_PROVENANCE = frozenset({"description", "data_version", "engine_version", "reference", "observed_before"})
CRITERIA_KEYS = (
    "min_drawdown_improvement_pp",
    "max_return_sacrifice_pp",
    "min_return_above_cash_pp",
    "max_drawdown_above_cash_pp",
)


class InputError(ValueError):
    """Safe structured issues; raw input and exception text are never echoed."""

    def __init__(self, issues: list[dict[str, str]]):
        self.issues = issues
        super().__init__("Research inputs are invalid; correct the reported field issues.")


def _issue(issues: list, code: str, path: str, message: str) -> None:
    if len(issues) < 50:
        issues.append({"code": code, "path": path, "message": message})


def _decimal_text(value: Decimal) -> str:
    if value.is_zero():
        return "0"
    text = format(value, "f")
    return text.rstrip("0").rstrip(".") if "." in text else text


def _number(value: Any, path: str, issues: list, *, positive: bool = True) -> Decimal | None:
    if isinstance(value, bool) or not isinstance(value, (str, int, float, Decimal)):
        _issue(issues, "invalid_number", path, "Must be a finite decimal number; booleans are not accepted.")
        return None
    try:
        text = str(value)
        if len(text) > 160 or not _NUMBER.fullmatch(text):
            raise ValueError
        number = Decimal(text)
        if not number.is_finite():
            raise ValueError
    except (InvalidOperation, ValueError, OverflowError):
        _issue(
            issues,
            "invalid_number",
            path,
            "Must be a finite decimal number represented by at most 160 characters.",
        )
        return None
    digits = number.as_tuple().digits
    trailing = 0
    for digit in reversed(digits):
        if digit:
            break
        trailing += 1
    if max(1, len(digits) - trailing) > MAX_INPUT_DIGITS or (number and not -30 <= number.adjusted() <= 30):
        _issue(
            issues,
            "number_out_of_range",
            path,
            "Numbers may contain at most 40 significant digits; nonzero adjusted decimal exponents must be between -30 and 30.",
        )
        return None
    if positive and number <= 0:
        _issue(
            issues,
            "nonpositive_equity",
            path,
            "Equity must be positive; nonpositive equity is not supported.",
        )
        return None
    return number


def _timestamp(value: Any, path: str, issues: list) -> datetime | None:
    if not isinstance(value, str) or len(value) > 40 or not _TIMESTAMP.fullmatch(value):
        _issue(
            issues,
            "invalid_timestamp",
            path,
            "Must be a UTC ISO valuation timestamp ending in Z or +00:00, with at most 6 fractional-second digits.",
        )
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (ValueError, OverflowError):
        _issue(issues, "invalid_timestamp", path, "Valuation timestamp is not a valid UTC calendar time.")
        return None


def _time_text(value: datetime) -> str:
    return value.isoformat().replace("+00:00", "Z")


def _text(value: Any, path: str, issues: list, limit: int, *, multiline: bool = False) -> str | None:
    if not isinstance(value, str) or not value.strip() or len(value) > limit:
        _issue(issues, "invalid_text", path, f"Must be a nonempty string of at most {limit} characters.")
        return None
    allowed = {"\n", "\r", "\t"} if multiline else set()
    if any((ord(char) < 32 and char not in allowed) or 0xD800 <= ord(char) <= 0xDFFF for char in value):
        _issue(
            issues,
            "invalid_text",
            path,
            "Text must not contain control characters or invalid Unicode surrogates.",
        )
        return None
    return value


def _point(raw: Any, path: str, issues: list) -> tuple[dict | None, datetime | None]:
    if not isinstance(raw, dict):
        _issue(
            issues,
            "invalid_point",
            path,
            "A valuation point must be an object containing timestamp and equity.",
        )
        return None, None
    if set(raw) != {"timestamp", "equity"}:
        _issue(
            issues,
            "invalid_point_fields",
            path,
            "A valuation point must contain exactly timestamp and equity.",
        )
    ts = _timestamp(raw.get("timestamp"), path + ".timestamp", issues)
    amount = _number(raw.get("equity"), path + ".equity", issues)
    if ts is None or amount is None:
        return None, ts
    return {"timestamp": _time_text(ts), "equity": _decimal_text(amount)}, ts


def normalize_curve(raw: dict) -> dict:
    """Canonicalize a complete daily mark-to-market simulated equity curve."""
    issues: list[dict[str, str]] = []
    if not isinstance(raw, dict):
        raise InputError(
            [{"code": "invalid_curve", "path": "$", "message": "The curve must be a JSON object."}]
        )
    for field in sorted(_FIELDS.difference(raw)):
        _issue(issues, "missing_field", field, "Required field is missing.")
    if set(raw).difference(_FIELDS):
        _issue(
            issues,
            "unknown_field",
            "$",
            "The curve contains unsupported fields; only documented curve fields are accepted.",
        )
    result: dict[str, Any] = {"schema_version": 1}
    if type(raw.get("schema_version")) is not int or raw.get("schema_version") != 1:
        _issue(issues, "unsupported_schema", "schema_version", "schema_version must be the integer 1.")
    for field in ("name", "strategy_id", "run_id"):
        result[field] = _text(raw.get(field), field, issues, 120)
    currency = _text(raw.get("currency"), "currency", issues, 20)
    if currency is not None and not re.fullmatch(r"[A-Z][A-Z0-9]{1,19}", currency):
        _issue(
            issues,
            "invalid_currency",
            "currency",
            "Currency must contain 2 to 20 uppercase letters or digits and start with a letter.",
        )
    result["currency"] = currency
    kind = raw.get("source_kind")
    if not isinstance(kind, str) or kind not in _SOURCES:
        _issue(
            issues,
            "unsupported_source",
            "source_kind",
            "Only supported simulation sources are accepted; live account equity is not accepted.",
        )
    result["source_kind"] = kind
    for field, expected in _SEMANTICS.items():
        if raw.get(field) != expected:
            _issue(issues, "incompatible_semantics", field, f"This field must explicitly declare {expected}.")
        result[field] = expected
    result["cost_model"] = _text(raw.get("cost_model"), "cost_model", issues, 200)
    if result["cost_model"] is not None and result["cost_model"].strip().casefold() in _UNKNOWN_COSTS:
        _issue(
            issues,
            "unknown_cost_model",
            "cost_model",
            "Cost treatment is unknown; declare a cost model or an explicit zero-cost simulation model.",
        )
    result["initial"], previous_ts = _point(raw.get("initial"), "initial", issues)
    points = raw.get("points")
    normalized_points = []
    if not isinstance(points, list) or not 1 <= len(points) <= MAX_POINTS:
        _issue(
            issues,
            "invalid_points",
            "points",
            "Provide 1 to 5000 daily valuation points and a separate initial point.",
        )
    else:
        for index, point in enumerate(points):
            path = f"points[{index}]"
            normalized_point, ts = _point(point, path, issues)
            if ts is not None and previous_ts is not None:
                delta = ts - previous_ts
                if delta <= timedelta(0):
                    _issue(
                        issues,
                        "non_increasing_timestamp",
                        path + ".timestamp",
                        "Valuation timestamps must be strictly increasing, with no duplicates or reordering.",
                    )
                elif delta != _DAY:
                    _issue(
                        issues,
                        "non_daily_interval",
                        path + ".timestamp",
                        "Adjacent valuations must be exactly 86400 seconds apart; missing points or changing valuation times are not allowed.",
                    )
            if normalized_point is not None:
                normalized_points.append(normalized_point)
            previous_ts = ts
    result["points"] = normalized_points
    provenance = raw.get("provenance")
    normalized_provenance: dict[str, Any] = {}
    if not isinstance(provenance, dict):
        _issue(issues, "invalid_provenance", "provenance", "Provenance must be an object.")
    else:
        if set(provenance).difference(_PROVENANCE):
            _issue(
                issues,
                "unknown_provenance_field",
                "provenance",
                "Provenance contains unsupported fields; credentials and account fields are not accepted.",
            )
        for field in sorted(_PROVENANCE.intersection(provenance)):
            value = provenance[field]
            if field == "observed_before":
                if type(value) is not bool:
                    _issue(
                        issues,
                        "invalid_boolean",
                        "provenance.observed_before",
                        "The observed_before declaration must be a boolean.",
                    )
                normalized_provenance[field] = value
            else:
                limit = {"description": 2000, "reference": 500}.get(field, 120)
                normalized_provenance[field] = _text(
                    value, "provenance." + field, issues, limit, multiline=field == "description"
                )
    result["provenance"] = normalized_provenance
    if issues:
        raise InputError(issues)
    return result


def _normalize_pair(a: dict, b: dict) -> tuple[dict | None, dict | None, list]:
    normalized, issues = [], []
    for label, curve in (("baseline", a), ("candidate", b)):
        try:
            normalized.append(normalize_curve(curve))
        except InputError as error:
            normalized.append(None)
            for issue in error.issues:
                _issue(issues, issue["code"], label + "." + issue["path"], issue["message"])
    return normalized[0], normalized[1], issues


def _select(a: dict, b: dict, start: str | None, end: str | None) -> tuple[list, list, list]:
    issues: list = []
    for field in ("currency", "cost_model"):
        if a[field] != b[field]:
            _issue(
                issues,
                "incompatible_" + field,
                field,
                "A and B must use matching currencies and cost models.",
            )
    points_a, points_b = [a["initial"], *a["points"]], [b["initial"], *b["points"]]
    boundaries: dict[str, str | None] = {}
    for label, selected, index in (("start", start, 0), ("end", end, -1)):
        if selected is None:
            if points_a[index]["timestamp"] != points_b[index]["timestamp"]:
                _issue(
                    issues,
                    "mismatched_range",
                    label,
                    "Full-range boundaries differ; explicitly select valuation boundaries shared by both complete curves.",
                )
                boundaries[label] = None
            else:
                boundaries[label] = points_a[index]["timestamp"]
        else:
            parsed = _timestamp(selected, label, issues)
            boundaries[label] = _time_text(parsed) if parsed is not None else None
    begin, finish = boundaries["start"], boundaries["end"]
    if begin is not None and finish is not None:
        begin_dt = datetime.fromisoformat(begin.replace("Z", "+00:00"))
        finish_dt = datetime.fromisoformat(finish.replace("Z", "+00:00"))
        if begin_dt >= finish_dt:
            _issue(
                issues,
                "invalid_range",
                "start",
                "The start must precede the end and include at least one complete daily return.",
            )
    selected_curves = []
    for label, points in (("baseline", points_a), ("candidate", points_b)):
        indices = {point["timestamp"]: index for index, point in enumerate(points)}
        for boundary_name, boundary in (("start", begin), ("end", finish)):
            if boundary is not None and boundary not in indices:
                _issue(
                    issues,
                    "boundary_not_present",
                    label + "." + boundary_name,
                    "Selected boundaries must match existing valuation points exactly; interpolation and nearest-date alignment are not allowed.",
                )
        selected_curves.append(
            points[indices[begin] : indices[finish] + 1] if begin in indices and finish in indices else []
        )
    selected_a, selected_b = selected_curves
    if (
        selected_a
        and selected_b
        and [p["timestamp"] for p in selected_a] != [p["timestamp"] for p in selected_b]
    ):
        _issue(
            issues, "mismatched_clock", "points", "A and B must use the same complete valuation time grid."
        )
    return selected_a, selected_b, issues


def _coverage(a: dict, points: list) -> dict:
    return {
        "start": points[0]["timestamp"],
        "end": points[-1]["timestamp"],
        "observations": len(points),
        "currency": a["currency"],
        "frequency": "1d",
    }


def validate_pair(a: dict, b: dict, start: str | None = None, end: str | None = None) -> dict:
    """Validate full curves and explicit selection without inferring common range."""
    a, b, issues = _normalize_pair(a, b)
    if issues:
        return {"comparable": False, "issues": issues, "coverage": None}
    selected_a, _, issues = _select(a, b, start, end)
    return {
        "comparable": not issues,
        "issues": issues,
        "coverage": _coverage(a, selected_a) if not issues else None,
    }


def _criteria(raw: Any) -> dict[str, Decimal] | None:
    if raw is None:
        return None
    if not isinstance(raw, dict) or set(raw) != set(CRITERIA_KEYS):
        raise InputError(
            [
                {
                    "code": "incomplete_criteria",
                    "path": "criteria",
                    "message": "Provide all four research criteria or null for comparison-only mode; partial and extra criteria are not accepted.",
                }
            ]
        )
    normalized, issues = {}, []
    for key in CRITERIA_KEYS:
        number = _number(raw[key], "criteria." + key, issues, positive=False)
        if number is not None:
            if not 0 <= number <= 10000:
                _issue(
                    issues,
                    "criteria_out_of_range",
                    "criteria." + key,
                    "Criteria must be finite percentage-point values between 0 and 10000.",
                )
            normalized[key] = number
    if issues:
        raise InputError(issues)
    return normalized


def _returns(values: list[Decimal]) -> list[Decimal]:
    return [current / previous - 1 for previous, current in zip(values, values[1:])]


def _sample_volatility(returns: list[Decimal]) -> Decimal | None:
    if len(returns) < 2:
        return None
    mean = sum(returns, _ZERO) / len(returns)
    variance = sum(((value - mean) ** 2 for value in returns), _ZERO) / (len(returns) - 1)
    return variance.sqrt() * _HUNDRED


def _drawdowns(values: list[Decimal]) -> list[Decimal]:
    peak, result = values[0], []
    for value in values:
        peak = max(peak, value)
        result.append((_ONE - value / peak) * _HUNDRED)
    return result


def _correlation(a: list[Decimal], b: list[Decimal]) -> float | None:
    if len(a) < 2:
        return None
    mean_a, mean_b = sum(a, _ZERO) / len(a), sum(b, _ZERO) / len(b)
    dev_a, dev_b = [value - mean_a for value in a], [value - mean_b for value in b]
    sum_a, sum_b = (
        sum((value * value for value in dev_a), _ZERO),
        sum((value * value for value in dev_b), _ZERO),
    )
    if not sum_a or not sum_b:
        return None
    covariance = sum((x * y for x, y in zip(dev_a, dev_b)), _ZERO)
    value = float(covariance / (sum_a * sum_b).sqrt())
    return max(-1.0, min(1.0, value)) if math.isfinite(value) else None


def evaluate(
    a: dict,
    b: dict,
    *,
    start: str | None = None,
    end: str | None = None,
    criteria: dict | None = None,
    display_language: str = "en",
) -> dict:
    """Evaluate A, initial 80%A+20%B, and initial 80%A+20%zero-yield cash."""
    display = presentation(display_language)
    a, b, issues = _normalize_pair(a, b)
    if issues:
        raise InputError(issues)
    points_a, points_b, issues = _select(a, b, start, end)
    if issues:
        raise InputError(issues)
    thresholds = _criteria(criteria)
    # A new Context also prevents caller rounding and trap settings leaking in.
    with localcontext(Context(prec=DECIMAL_PRECISION)):
        initial_a, initial_b = Decimal(points_a[0]["equity"]), Decimal(points_b[0]["equity"])
        nav_a = [Decimal(point["equity"]) / initial_a for point in points_a]
        nav_b = [Decimal(point["equity"]) / initial_b for point in points_b]
        cash = [_WA * value + _WB for value in nav_a]
        # Preserve exact algebraic identities, even for recurring-decimal ratios.
        combined = [
            value_a
            if value_a == value_b
            else (cash[index] if value_b == _ONE else _WA * value_a + _WB * value_b)
            for index, (value_a, value_b) in enumerate(zip(nav_a, nav_b))
        ]
        paths = {"baseline": nav_a, "candidate": combined, "cash": cash}
        labels = display["scenario_labels"]
        drawdowns = {key: _drawdowns(path) for key, path in paths.items()}
        metrics = {
            key: {
                "return": (path[-1] - 1) * _HUNDRED,
                "drawdown": max(drawdowns[key]),
                "volatility": _sample_volatility(_returns(path)),
            }
            for key, path in paths.items()
        }
        scenarios = {
            key: {
                "label": labels[key],
                "total_return_pct": _decimal_text(values["return"]),
                "max_drawdown_pct": _decimal_text(values["drawdown"]),
                "daily_volatility_pct": _decimal_text(values["volatility"])
                if values["volatility"] is not None
                else None,
            }
            for key, values in metrics.items()
        }
        fact_values = [
            metrics["baseline"]["drawdown"] - metrics["candidate"]["drawdown"],
            metrics["baseline"]["return"] - metrics["candidate"]["return"],
            metrics["candidate"]["return"] - metrics["cash"]["return"],
            metrics["candidate"]["drawdown"] - metrics["cash"]["drawdown"],
        ]
        fact_labels = display["fact_labels"]
        comparison_facts = [
            {"key": key, "label": label, "actual_pp": _decimal_text(actual)}
            for key, label, actual in zip(CRITERIA_KEYS, fact_labels, fact_values)
        ]
        criteria_results = []
        if thresholds is not None:
            for fact, actual, operator in zip(comparison_facts, fact_values, (">=", "<=", ">=", "<=")):
                threshold = thresholds[fact["key"]]
                met = actual >= threshold if operator == ">=" else actual <= threshold
                criteria_results.append(
                    {**fact, "threshold_pp": _decimal_text(threshold), "operator": operator, "met": met}
                )
        status = (
            "comparison_only"
            if thresholds is None
            else ("criteria_met" if all(item["met"] for item in criteria_results) else "criteria_not_met")
        )
        summaries = display["summaries"]
        returns_a, returns_b = _returns(nav_a), _returns(nav_b)
        duplicate = nav_a == nav_b
        limitations = list(display["limitations"])
        if len(returns_a) < 30:
            limitations.append(display["small_sample"])
        if len(returns_a) < 2:
            limitations.append(display["one_return"])
        if duplicate:
            limitations.append(display["duplicate"])
        if a["source_kind"] == "synthetic" or b["source_kind"] == "synthetic":
            limitations.append(display["synthetic"])
        return {
            "method_version": METHOD_VERSION,
            "display_language": display_language,
            "status": status,
            "coverage": _coverage(a, points_a),
            "model": {
                "weights": {"baseline": "0.8", "candidate": "0.2"},
                "cash_return": "0",
                "rebalancing": "none",
            },
            "scenarios": scenarios,
            "series": [
                {
                    "timestamp": point["timestamp"],
                    **{key: _decimal_text(path[index]) for key, path in paths.items()},
                    **{key + "_drawdown_pct": _decimal_text(path[index]) for key, path in drawdowns.items()},
                }
                for index, point in enumerate(points_a)
            ],
            "comparison_facts": comparison_facts,
            "criteria_results": criteria_results,
            "diagnostics": {
                "return_correlation": _correlation(returns_a, returns_b),
                "joint_loss_count": sum(x < 0 and y < 0 for x, y in zip(returns_a, returns_b)),
                "return_observations": len(returns_a),
                "duplicate_curves": duplicate,
            },
            "summary": summaries[status],
            "limitations": limitations,
        }
