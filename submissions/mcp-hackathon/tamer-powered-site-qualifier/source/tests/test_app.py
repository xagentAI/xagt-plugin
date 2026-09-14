import unittest
from unittest.mock import patch

from starlette.requests import Request

from app.main import COMMIT, SiteQualificationRequest, app, health, landing_page, paid_qualify, verification


class AppTests(unittest.TestCase):
    def setUp(self):
        self.assertIsNotNone(app)

    def test_root_is_html_landing_page(self):
        response = landing_page()
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.media_type, "text/html")
        self.assertIn("charset=utf-8", response.headers["content-type"])
        self.assertIn("Powered-Site Qualifier", response.body.decode())
        self.assertIn("Site Data", response.body.decode())
        self.assertIn("Run Qualification", response.body.decode())
        self.assertIn("Load Example Site", response.body.decode())
        self.assertIn("/v1/qualify", response.body.decode())
        self.assertIn("/v1/paid/qualify", response.body.decode())
        self.assertIn("Voltage", response.body.decode())
        self.assertIn("Utility / interconnection status", response.body.decode())
        self.assertIn("payment-network", response.body.decode())

    def test_health_and_paid_boundary_remain_available(self):
        self.assertEqual(health()["status"], "ok")
        scope = {"type": "http", "method": "POST", "path": "/v1/paid/qualify", "headers": [], "query_string": b"", "scheme": "http", "server": ("testserver", 80), "client": ("testclient", 50000), "root_path": ""}
        with patch.dict("os.environ", {"X402_PAY_TO": "0.0.10489770", "X402_FEE_PAYER": "0.0.7162784"}):
            response = paid_qualify(Request(scope), SiteQualificationRequest())
        self.assertEqual(response.status_code, 402)
        self.assertEqual(response.body.decode()[:1], "{")
        self.assertIn(b"hedera:testnet", response.body)
        self.assertIn(b"0.0.10489770", response.body)

    def test_verification_binds_to_runtime_commit(self):
        self.assertEqual(verification()["commit"], COMMIT)


if __name__ == "__main__":
    unittest.main()
