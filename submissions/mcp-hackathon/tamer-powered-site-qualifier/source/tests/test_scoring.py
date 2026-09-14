import unittest

from app.scoring import qualify


class ScoringTests(unittest.TestCase):
    def test_complete_site_is_deterministic(self):
        site = {"power_ready": True, "available_mw": 24, "energization_rfs_date": "2026-10-15", "utility_status": "interconnected", "grid_or_gas": "grid", "power_price": 0.045, "land_size": 120, "lease_sale_jv": "lease", "fiber": "on-site", "water": "municipal", "permitting_status": "approved", "expansion_capacity": 40, "intended_use": "both"}
        first = qualify(site)
        self.assertEqual(first, qualify(site))
        self.assertEqual(first["classification"], "READY")
        self.assertGreaterEqual(first["bitcoin_mining_readiness"]["score"], 80)
        self.assertGreaterEqual(first["ai_data_center_readiness"]["score"], 80)
        self.assertLessEqual(first["bitcoin_mining_readiness"]["score"], 100)
        self.assertLessEqual(first["ai_data_center_readiness"]["score"], 100)

    def test_unknowns_are_reported_not_guessed(self):
        result = qualify({"intended_use": "Bitcoin mining"})
        self.assertEqual(result["bitcoin_mining_readiness"]["score"], 0)
        self.assertEqual(result["classification"], "NOT SUITABLE")
        self.assertTrue(result["missing_information"])
        self.assertTrue(result["major_blockers"])

    def test_intended_use_controls_classification(self):
        site = {"power_ready": True, "available_mw": 24, "power_price": 0.05, "utility_status": "interconnected", "permitting_status": "approved", "intended_use": "Bitcoin mining"}
        result = qualify(site)
        self.assertIn(result["classification"], {"NEAR READY", "READY"})


if __name__ == "__main__":
    unittest.main()
