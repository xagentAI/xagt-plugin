import unittest
from datetime import datetime

from app.adapters.demos import get_case, list_cases


class DemoAdapterTests(unittest.TestCase):
    def test_recorded_curve_uses_pre_bar_capital_and_close_boundaries(self):
        case = get_case("aimm-weight")
        a, b = case["baseline"], case["candidate"]
        self.assertEqual(a["initial"], {"timestamp": "2026-06-02T00:00:00Z", "equity": "10000"})
        self.assertEqual(a["points"][0], {"timestamp": "2026-06-03T00:00:00Z", "equity": "10431.46384428"})
        self.assertEqual(a["points"][-1]["timestamp"], "2026-08-01T00:00:00Z")
        self.assertEqual(len(a["points"]), 60)
        self.assertEqual(len(b["points"]), 60)
        self.assertNotEqual(a["points"], b["points"])
        self.assertEqual(a["cost_model"], b["cost_model"])
        self.assertEqual(a["source_kind"], "recorded_local_aimm")
        self.assertTrue(a["provenance"]["observed_before"])
        self.assertIn("次日 UTC", a["provenance"]["description"])

    def test_five_cases_have_fresh_objects_and_disclosed_provenance(self):
        summaries = list_cases()
        self.assertEqual(len(summaries), 5)
        self.assertEqual(len({row["id"] for row in summaries}), 5)
        summaries[0]["name"] = "changed"
        self.assertNotEqual(list_cases()[0]["name"], "changed")
        for row in list_cases():
            case = get_case(row["id"])
            for role in ("baseline", "candidate"):
                self.assertTrue(case[role]["provenance"]["observed_before"])
                case[role]["points"].clear()
                self.assertTrue(get_case(row["id"])[role]["points"])

    def test_copy_and_cash_are_exact_identities_with_explicit_derivation(self):
        clone = get_case("duplicate")
        self.assertEqual(clone["baseline"]["points"], clone["candidate"]["points"])
        self.assertNotEqual(clone["baseline"]["run_id"], clone["candidate"]["run_id"])
        self.assertEqual(clone["candidate"]["source_kind"], "synthetic")
        cash = get_case("cash")
        self.assertEqual({point["equity"] for point in cash["candidate"]["points"]}, {"10000"})
        self.assertEqual(cash["candidate"]["initial"]["equity"], "10000")

    def test_missing_day_remains_visible_not_filled_or_intersected(self):
        case = get_case("missing-day")
        self.assertEqual(len(case["baseline"]["points"]), 60)
        self.assertEqual(len(case["candidate"]["points"]), 59)
        before, after = (
            datetime.fromisoformat(point["timestamp"].replace("Z", "+00:00"))
            for point in case["candidate"]["points"][19:21]
        )
        self.assertEqual((after - before).days, 2)

    def test_unknown_case_does_not_become_path_input(self):
        for name in ("unknown", "../../manifest.json", ""):
            with self.assertRaises(KeyError):
                get_case(name)

    def test_engine_rejects_gap_and_preserves_cash_and_clone_identities(self):
        from app.domain.engine import InputError, evaluate

        gap = get_case("missing-day")
        with self.assertRaises(InputError):
            evaluate(gap["baseline"], gap["candidate"])
        clone = get_case("duplicate")
        result = evaluate(clone["baseline"], clone["candidate"])
        for point in result["series"]:
            self.assertEqual(point["baseline"], point["candidate"])
        cash = get_case("cash")
        result = evaluate(cash["baseline"], cash["candidate"])
        for point in result["series"]:
            self.assertEqual(point["cash"], point["candidate"])
        tradeoff = get_case("tradeoff")
        result = evaluate(tradeoff["baseline"], tradeoff["candidate"], criteria=tradeoff["criteria"])
        self.assertEqual(result["status"], "criteria_not_met")
        results = {row["key"]: row["met"] for row in result["criteria_results"]}
        self.assertFalse(results["max_return_sacrifice_pp"])
        self.assertTrue(results["min_drawdown_improvement_pp"])


if __name__ == "__main__":
    unittest.main()
