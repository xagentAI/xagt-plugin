"""Behavior and hand-calculated references for the pure domain engine."""

from copy import deepcopy
from datetime import datetime, timedelta
from decimal import Decimal, Inexact, ROUND_UP, getcontext, localcontext
import json
import math
import unittest

from app.domain.engine import CRITERIA_KEYS, InputError, evaluate, normalize_curve, validate_pair


def curve(amounts, *, initial_date="2026-01-01T00:00:00Z", name="A", **overrides):
    first = datetime.fromisoformat(initial_date.replace("Z", "+00:00"))
    points = [
        {
            "timestamp": (first + timedelta(days=index)).isoformat().replace("+00:00", "Z"),
            "equity": str(amount),
        }
        for index, amount in enumerate(amounts)
    ]
    result = {
        "schema_version": 1,
        "name": name,
        "strategy_id": name,
        "run_id": "example-run",
        "source_kind": "synthetic",
        "currency": "USDT",
        "frequency": "1d",
        "timezone": "UTC",
        "timestamp_convention": "valuation_boundary",
        "equity_kind": "mark_to_market",
        "completeness": "complete",
        "external_cash_flows": "none",
        "cost_model": "explicit-zero-cost-example-v1",
        "initial": points[0],
        "points": points[1:],
        "provenance": {"description": "Constructed mathematical example", "observed_before": True},
    }
    result.update(overrides)
    return result


def criteria(drawdown="0", sacrifice="1", cash_return="1", cash_drawdown="0"):
    return dict(zip(CRITERIA_KEYS, (drawdown, sacrifice, cash_return, cash_drawdown)))


class CurveValidationTests(unittest.TestCase):
    def assert_invalid(self, value, code=None):
        with self.assertRaises(InputError) as caught:
            normalize_curve(value)
        if code:
            self.assertIn(code, [issue["code"] for issue in caught.exception.issues])
        return caught.exception

    def test_normalization_is_idempotent_and_does_not_mutate_input(self):
        raw = curve(["1.0000e4", 10050])
        raw["initial"]["timestamp"] = "2026-01-01T00:00:00+00:00"
        before = deepcopy(raw)
        normalized = normalize_curve(raw)
        self.assertEqual(raw, before)
        self.assertEqual(normalized["initial"], {"timestamp": "2026-01-01T00:00:00Z", "equity": "10000"})
        self.assertEqual(normalize_curve(normalized), normalized)

    def test_bools_nonfinite_nonpositive_and_extreme_numbers_rejected(self):
        values = [
            True,
            False,
            float("inf"),
            float("nan"),
            "NaN",
            "Infinity",
            "1e9999999999999999999999",
            "1e31",
            "1e-31",
            0,
            -1,
            {},
            None,
            "1" * 41,
            "1" * 1000,
            "１２３",
        ]
        for value in values:
            with self.subTest(value=str(value)[:40]):
                raw = curve([100, 101])
                raw["points"][0]["equity"] = value
                self.assert_invalid(raw)

    def test_precision_bounds_allow_normal_numeric_extremes(self):
        normalize_curve(curve(["1e-30", "1e30"]))
        normalize_curve(curve(["1.123456789012345678901234567890123456789", "1.00"]))

    def test_missing_duplicate_and_reversed_dates_are_rejected(self):
        original = curve([100, 101, 102, 103])
        missing = deepcopy(original)
        missing["points"].pop(1)
        duplicate = deepcopy(original)
        duplicate["points"][1]["timestamp"] = duplicate["points"][0]["timestamp"]
        reversed_points = deepcopy(original)
        reversed_points["points"].reverse()
        for raw in (missing, duplicate, reversed_points):
            with self.subTest(raw=raw["points"]):
                before = deepcopy(raw)
                self.assert_invalid(raw)
                self.assertEqual(raw, before)

    def test_first_point_must_follow_independent_initial_valuation(self):
        raw = curve([100, 101, 102])
        raw["initial"]["timestamp"] = raw["points"][0]["timestamp"]
        self.assert_invalid(raw, "non_increasing_timestamp")

    def test_invalid_timezones_clock_changes_and_calendar_dates(self):
        for timestamp in (
            "2026-01-02",
            "2026-01-02T00:00:00",
            "2026-01-02T00:00:00+08:00",
            "2026-02-30T00:00:00Z",
            "2026-01-02T01:00:00Z",
            "2026-01-02T00:00:00.0000001Z",
        ):
            with self.subTest(timestamp=timestamp):
                raw = curve([100, 101])
                raw["points"][0]["timestamp"] = timestamp
                self.assert_invalid(raw)

    def test_consistent_fractional_utc_clock_is_accepted(self):
        normalize_curve(curve([100, 101], initial_date="2026-01-01T18:05:00.123000Z"))

    def test_required_semantics_are_never_inferred(self):
        for field, value in (
            ("timestamp_convention", "bar_open"),
            ("equity_kind", "realized_pnl"),
            ("completeness", "sampled"),
            ("external_cash_flows", "unknown"),
            ("frequency", "1h"),
            ("timezone", "Asia/Shanghai"),
            ("cost_model", ""),
            ("source_kind", "live_account"),
            ("currency", "usdt"),
        ):
            with self.subTest(field=field):
                self.assert_invalid(curve([100, 101], **{field: value}))

    def test_unknown_cost_declarations_are_not_treated_as_known(self):
        for value in ("unknown", " UNSPECIFIED ", "n/a", "none", "未知", "不明", "未说明", "not provided"):
            with self.subTest(value=value):
                self.assert_invalid(curve([100, 101], cost_model=value), "unknown_cost_model")
        normalize_curve(curve([100, 101], cost_model="explicit-zero-fees-v1"))

    def test_required_fields_schema_unknown_fields_and_secret_redaction(self):
        for field in tuple(curve([100, 101])):
            raw = curve([100, 101])
            del raw[field]
            self.assert_invalid(raw, "missing_field")
        self.assert_invalid(curve([100, 101], schema_version=True), "unsupported_schema")
        secret = "test-credential-never-echo"
        raw = curve([100, 101])
        raw[secret] = secret
        raw["provenance"]["api_key"] = secret
        error = self.assert_invalid(raw)
        self.assertNotIn(secret, str(error))
        self.assertNotIn(secret, json.dumps(error.issues))

    def test_point_and_metadata_bounds(self):
        self.assert_invalid(curve([100]), "invalid_points")
        self.assert_invalid(curve([100] * 5002), "invalid_points")
        self.assert_invalid(curve([100, 101], name="x" * 121), "invalid_text")
        raw = curve([100, 101])
        raw["points"][0]["account"] = "hidden"
        self.assert_invalid(raw, "invalid_point_fields")
        raw = curve([100, 101])
        raw["provenance"]["observed_before"] = 1
        self.assert_invalid(raw, "invalid_boolean")

    def test_lone_unicode_surrogate_rejected_before_storage_serialization(self):
        self.assert_invalid(curve([100, 101], name="\ud800"), "invalid_text")
        raw = curve([100, 101])
        raw["provenance"]["description"] = "\udfff"
        self.assert_invalid(raw, "invalid_text")

    def test_many_errors_are_bounded(self):
        raw = curve([100, 101])
        raw["points"] = [None] * 5000
        error = self.assert_invalid(raw)
        self.assertLessEqual(len(error.issues), 50)

    def test_rejects_non_objects_without_type_errors(self):
        for value in (None, [], "data", True, 1):
            with self.subTest(value=value):
                self.assert_invalid(value, "invalid_curve")


class PairValidationTests(unittest.TestCase):
    def test_complete_ranges_must_match_without_silent_intersection(self):
        a, b = curve([100, 110, 120, 130]), curve([100, 110, 120], initial_date="2026-01-02T00:00:00Z")
        result = validate_pair(a, b)
        self.assertFalse(result["comparable"])
        self.assertIsNone(result["coverage"])
        self.assertIn("mismatched_range", [issue["code"] for issue in result["issues"]])
        self.assertTrue(validate_pair(a, b, start="2026-01-02T00:00:00Z")["comparable"])

    def test_explicit_subperiod_rebases_both_curves(self):
        a, b = curve([100, 200, 220, 176]), curve([100, 50, 55, 66])
        result = evaluate(a, b, start="2026-01-02T00:00:00+00:00", end="2026-01-04T00:00:00Z")
        self.assertEqual(result["series"][0]["candidate"], "1")
        self.assertEqual(result["series"][-1]["candidate"], "0.968")
        self.assertEqual(result["coverage"]["observations"], 3)
        self.assertEqual(result["diagnostics"]["return_observations"], 2)

    def test_subperiod_requires_real_boundaries_and_positive_length(self):
        a = curve([100, 110, 120])
        for start, end in (
            ("2026-01-01T12:00:00Z", None),
            ("2026-01-02T00:00:00Z", "2026-01-02T00:00:00Z"),
            ("2026-01-03T00:00:00Z", "2026-01-01T00:00:00Z"),
            ([], None),
            (None, "2026-02-01T00:00:00Z"),
        ):
            with self.subTest(start=start, end=end):
                self.assertFalse(validate_pair(a, a, start=start, end=end)["comparable"])
                with self.assertRaises(InputError):
                    evaluate(a, a, start=start, end=end)

    def test_subperiod_cannot_hide_bad_full_input(self):
        a = curve([100, 101, 102, 103])
        b = deepcopy(a)
        b["points"][2]["equity"] = "unknown"
        self.assertFalse(validate_pair(a, b, end="2026-01-02T00:00:00Z")["comparable"])

    def test_omitted_mismatching_end_is_not_inferred(self):
        a, b = curve([100, 101, 102, 103]), curve([100, 101, 102])
        self.assertFalse(validate_pair(a, b, start="2026-01-02T00:00:00Z")["comparable"])
        self.assertTrue(
            validate_pair(a, b, start="2026-01-02T00:00:00Z", end="2026-01-03T00:00:00Z")["comparable"]
        )

    def test_currency_cost_and_clock_mismatch_block_pairing(self):
        a = curve([100, 101])
        for changes in (
            {"currency": "USD"},
            {"cost_model": "different-fees-v1"},
            {"initial_date": "2026-01-01T08:00:00Z"},
        ):
            with self.subTest(changes=changes):
                self.assertFalse(validate_pair(a, curve([100, 101], **changes))["comparable"])

    def test_both_curves_issues_are_labeled(self):
        result = validate_pair({}, {})
        self.assertFalse(result["comparable"])
        self.assertTrue(any(issue["path"].startswith("baseline.") for issue in result["issues"]))
        self.assertTrue(any(issue["path"].startswith("candidate.") for issue in result["issues"]))


class NumericalBehaviorTests(unittest.TestCase):
    def test_hand_computed_fixed_initial_paths_do_not_rebalance(self):
        result = evaluate(curve([100, 150, 120]), curve([100, 50, 100]))
        self.assertEqual([point["candidate"] for point in result["series"]], ["1", "1.3", "1.16"])
        self.assertEqual([point["cash"] for point in result["series"]], ["1", "1.4", "1.16"])
        self.assertEqual(result["scenarios"]["baseline"]["total_return_pct"], "20")
        self.assertEqual(result["scenarios"]["candidate"]["total_return_pct"], "16")
        self.assertEqual(result["scenarios"]["baseline"]["max_drawdown_pct"], "20")
        self.assertAlmostEqual(
            float(result["scenarios"]["candidate"]["max_drawdown_pct"]), 100 * 14 / 130, places=12
        )
        self.assertEqual(result["model"]["rebalancing"], "none")

    def test_identical_and_scaled_identical_curves_preserve_exact_paths(self):
        for b in (curve([3, 1, 2]), curve([6, 2, 4])):
            result = evaluate(curve([3, 1, 2]), b)
            for point in result["series"]:
                self.assertEqual(point["candidate"], point["baseline"])
                self.assertEqual(point["candidate_drawdown_pct"], point["baseline_drawdown_pct"])
            self.assertTrue(result["diagnostics"]["duplicate_curves"])
            self.assertIn("no additional path variation", " ".join(result["limitations"]))

    def test_cash_candidate_equals_cash_comparison_exactly(self):
        result = evaluate(curve([3, 1, 2]), curve([7, 7, 7]))
        for point in result["series"]:
            self.assertEqual(point["candidate"], point["cash"])
            self.assertEqual(point["candidate_drawdown_pct"], point["cash_drawdown_pct"])
        self.assertIsNone(result["diagnostics"]["return_correlation"])

    def test_initial_point_is_included_in_early_drawdown(self):
        result = evaluate(curve([100, 80, 90]), curve([100, 100, 100]))
        self.assertEqual(result["scenarios"]["baseline"]["max_drawdown_pct"], "20")
        self.assertEqual(result["scenarios"]["baseline"]["total_return_pct"], "-10")

    def test_volatility_is_daily_sample_standard_deviation(self):
        result = evaluate(curve([100, 110, 99]), curve([100, 100, 100]))
        self.assertAlmostEqual(
            float(result["scenarios"]["baseline"]["daily_volatility_pct"]), math.sqrt(200), places=12
        )
        self.assertEqual(result["diagnostics"]["return_observations"], 2)

    def test_one_return_has_no_sample_volatility_or_correlation(self):
        result = evaluate(curve([100, 110]), curve([100, 105]))
        self.assertIsNone(result["scenarios"]["baseline"]["daily_volatility_pct"])
        self.assertIsNone(result["diagnostics"]["return_correlation"])

    def test_zero_volatility_is_zero_and_correlation_is_unavailable(self):
        result = evaluate(curve([100, 100, 100]), curve([100, 100, 100]))
        self.assertEqual(result["scenarios"]["baseline"]["daily_volatility_pct"], "0")
        self.assertIsNone(result["diagnostics"]["return_correlation"])

    def test_facts_mode_has_no_implicit_thresholds(self):
        result = evaluate(curve([100, 101]), curve([100, 102]))
        self.assertEqual(result["status"], "comparison_only")
        self.assertEqual(result["criteria_results"], [])

    def test_facts_mode_exposes_hand_computed_deltas_without_thresholds(self):
        a, b = curve([100, 80, 110]), curve([100, 120, 105])
        result = evaluate(a, b)
        # A: return10%, MDD20%; AB: return9%, MDD12%; AC: return8%, MDD16%.
        facts = result["comparison_facts"]
        self.assertEqual([fact["actual_pp"] for fact in facts], ["8", "1", "1", "-4"])
        self.assertEqual([fact["key"] for fact in facts], list(CRITERIA_KEYS))
        self.assertTrue(all(set(fact) == {"key", "label", "actual_pp"} for fact in facts))
        self.assertEqual(result["status"], "comparison_only")
        self.assertEqual(result["criteria_results"], [])
        judged = evaluate(a, b, criteria=criteria())
        self.assertEqual(judged["comparison_facts"], facts)
        for fact, criterion in zip(facts, judged["criteria_results"]):
            self.assertEqual(fact, {key: criterion[key] for key in fact})

    def test_exact_inclusive_thresholds_pass(self):
        result = evaluate(curve([100, 110]), curve([100, 105]), criteria=criteria())
        self.assertEqual(result["status"], "criteria_met")
        self.assertEqual([item["actual_pp"] for item in result["criteria_results"]], ["0", "1", "1", "0"])
        self.assertTrue(all(item["met"] for item in result["criteria_results"]))

    def test_unrounded_threshold_failure_even_when_display_looks_equal(self):
        result = evaluate(
            curve([100, 110]),
            curve([100, 105]),
            criteria=criteria(sacrifice="0.9999999999999999999999999999999999999999"),
        )
        self.assertEqual(result["status"], "criteria_not_met")
        item = result["criteria_results"][1]
        self.assertEqual(round(float(item["actual_pp"]), 2), round(float(item["threshold_pp"]), 2))
        self.assertFalse(item["met"])

    def test_drawdown_improvement_does_not_override_excess_return_sacrifice(self):
        result = evaluate(
            curve([100, 200, 110]),
            curve([100, 100, 100]),
            criteria=criteria(drawdown="1", sacrifice="1", cash_return="0"),
        )
        self.assertEqual(result["status"], "criteria_not_met")
        self.assertTrue(result["criteria_results"][0]["met"])
        self.assertFalse(result["criteria_results"][1]["met"])
        self.assertEqual(result["criteria_results"][1]["actual_pp"], "2")

    def test_uncorrelated_losing_candidate_does_not_automatically_pass(self):
        result = evaluate(
            curve([100, 110, 99, "108.9", "98.01"]),
            curve([100, 99, "97.02", "94.1094", "92.227212"]),
            criteria=criteria(sacrifice="100", cash_return="0", cash_drawdown="100"),
        )
        self.assertAlmostEqual(result["diagnostics"]["return_correlation"], 0, places=12)
        self.assertEqual(result["status"], "criteria_not_met")
        self.assertFalse(result["criteria_results"][2]["met"])
        self.assertEqual(result["diagnostics"]["joint_loss_count"], 2)

    def test_partial_extra_or_invalid_criteria_are_input_errors(self):
        invalid = [{}, {CRITERIA_KEYS[0]: 0}, [], {**criteria(), "extra": 1}]
        for value in (True, "NaN", "Infinity", -1, "10000.1", None, "1e999999"):
            values = criteria()
            values[CRITERIA_KEYS[1]] = value
            invalid.append(values)
        for value in invalid:
            with self.subTest(value=value):
                with self.assertRaises(InputError):
                    evaluate(curve([100, 110]), curve([100, 105]), criteria=value)

    def test_results_are_deterministic_json_safe_and_independent_of_decimal_context(self):
        a, b = curve([3, 1, 2]), curve([7, 8, 6])
        expected = evaluate(a, b)
        before = (getcontext().prec, getcontext().rounding)
        with localcontext() as context:
            context.prec = 3
            context.rounding = ROUND_UP
            context.traps[Inexact] = True
            actual = evaluate(a, b)
            self.assertEqual(context.prec, 3)
            self.assertTrue(context.traps[Inexact])
        self.assertEqual(actual, expected)
        self.assertEqual((getcontext().prec, getcontext().rounding), before)
        self.assertEqual(json.loads(json.dumps(actual, allow_nan=False)), actual)

    def test_extreme_valid_inputs_remain_finite(self):
        result = evaluate(curve(["1e-30", "1e30", "1e-30"]), curve(["1e30", "1e-30", "1e30"]))
        json.dumps(result, allow_nan=False)
        for scenario in result["scenarios"].values():
            for field in ("total_return_pct", "max_drawdown_pct", "daily_volatility_pct"):
                self.assertTrue(Decimal(scenario[field]).is_finite())


if __name__ == "__main__":
    unittest.main()
