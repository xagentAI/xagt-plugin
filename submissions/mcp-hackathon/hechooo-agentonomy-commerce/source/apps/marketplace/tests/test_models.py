import unittest

from shared.models import ClinkServiceManifest, PaymentOption, ServiceOffering


class ModelTests(unittest.TestCase):
    def test_manifest_requires_at_least_one_offering(self) -> None:
        with self.assertRaises(ValueError):
            ClinkServiceManifest.model_validate(
                {
                    "provider": {
                        "name": "Empty Provider",
                        "domain": "https://empty.example",
                        "source": "clink_manifest",
                    },
                    "offerings": [],
                }
            )

    def test_payment_amount_must_be_positive(self) -> None:
        with self.assertRaises(ValueError):
            PaymentOption(
                scheme="exact",
                network="eip155:137",
                asset="0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359",
                amount_atomic="0",
                pay_to="0x0000000000000000000000000000000000000001",
            )

    def test_offering_id_is_deterministic(self) -> None:
        first = ServiceOffering.build_id("cdp_bazaar", "https://example.com/risk")
        second = ServiceOffering.build_id("cdp_bazaar", "https://example.com/risk")
        self.assertEqual(first, second)
        self.assertTrue(first.startswith("offering_"))

    def test_manifest_offering_does_not_require_internal_provider_id(self) -> None:
        manifest = ClinkServiceManifest.model_validate(
            {
                "provider": {
                    "name": "Risk Provider",
                    "domain": "risk.example.com",
                    "source": "clink_manifest",
                },
                "offerings": [
                    {
                        "name": "wallet-risk",
                        "description": "Screen a wallet before payment.",
                        "endpoint": "https://risk.example.com/v1/wallet",
                        "method": "POST",
                        "payment_options": [
                            {
                                "scheme": "exact",
                                "network": "eip155:137",
                                "asset": "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359",
                                "amount_atomic": "5000",
                                "pay_to": "0x1111111111111111111111111111111111111111",
                            }
                        ],
                    }
                ],
            }
        )

        offering = manifest.to_offerings()[0]
        self.assertEqual(offering.provider_id, manifest.provider.provider_id)
        self.assertEqual(offering.source, "clink_manifest")


if __name__ == "__main__":
    unittest.main()
