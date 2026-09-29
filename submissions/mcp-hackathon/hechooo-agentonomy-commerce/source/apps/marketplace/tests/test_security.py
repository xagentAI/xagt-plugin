import unittest

from shared.security import validate_public_https_url


class UrlSafetyTests(unittest.TestCase):
    def test_accepts_public_https_url(self) -> None:
        self.assertEqual(
            validate_public_https_url("https://api.example.com/v1/risk"),
            "https://api.example.com/v1/risk",
        )

    def test_rejects_http_and_private_hosts(self) -> None:
        rejected = [
            "http://api.example.com/risk",
            "https://127.0.0.1/risk",
            "https://localhost/risk",
            "https://10.1.2.3/risk",
            "https://169.254.169.254/latest/meta-data",
        ]
        for url in rejected:
            with self.subTest(url=url), self.assertRaises(ValueError):
                validate_public_https_url(url)


if __name__ == "__main__":
    unittest.main()
