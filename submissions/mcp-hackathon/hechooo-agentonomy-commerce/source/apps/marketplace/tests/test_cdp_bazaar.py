import unittest

from adapters.cdp_bazaar import CdpBazaarAdapter


RESOURCE = {
    "resource": "https://risk.example.com/v1/token/check",
    "serviceName": "Example Risk",
    "description": "Token and wallet risk screening for agents.",
    "tags": ["defi", "risk"],
    "extensions": {
        "bazaar": {
            "info": {
                "input": {"type": "http", "method": "POST", "bodyType": "json"},
                "output": {"type": "json", "example": {"risk": "low"}},
            },
            "schema": {
                "properties": {
                    "input": {"properties": {"body": {"type": "object"}}},
                    "output": {"properties": {"risk": {"type": "string"}}},
                }
            },
        }
    },
    "accepts": [
        {
            "scheme": "exact",
            "network": "eip155:137",
            "asset": "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359",
            "amount": "5000",
            "payTo": "0x1111111111111111111111111111111111111111",
            "maxTimeoutSeconds": 60,
        }
    ],
}


class FakeResponse:
    def raise_for_status(self) -> None:
        return None

    def json(self) -> dict:
        return {"resources": [RESOURCE]}


class FakeSession:
    def __init__(self) -> None:
        self.params = None

    def get(self, url: str, params: dict, timeout: float) -> FakeResponse:
        self.params = params
        return FakeResponse()


class InventoryResponse:
    def __init__(self, *, status_code=200, payload=None, etag=None) -> None:
        self.status_code = status_code
        self.payload = payload or {}
        self.headers = {"etag": etag} if etag else {}

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise RuntimeError("inventory request failed")

    def json(self) -> dict:
        return self.payload


class InventorySession:
    def __init__(self, response: InventoryResponse) -> None:
        self.response = response
        self.request = None

    def get(self, url: str, params: dict, headers: dict, timeout: float) -> InventoryResponse:
        self.request = {"url": url, "params": params, "headers": headers, "timeout": timeout}
        return self.response


class BazaarAdapterTests(unittest.TestCase):
    def test_normalizes_resource_and_polygon_usdc_price(self) -> None:
        provider, offering = CdpBazaarAdapter().normalize_resource(RESOURCE)

        self.assertEqual(provider.name, "Example Risk")
        self.assertEqual(provider.domain, "risk.example.com")
        self.assertEqual(offering.method, "POST")
        self.assertEqual(offering.tags, ["defi", "risk"])
        self.assertEqual(offering.payment_options[0].pay_to, RESOURCE["accepts"][0]["payTo"])
        self.assertEqual(str(offering.payment_options[0].price_usd), "0.005")
        self.assertEqual(
            offering.offering_id,
            CdpBazaarAdapter().normalize_resource(RESOURCE)[1].offering_id,
        )

    def test_normalizes_x402_v1_max_amount_and_network_alias(self) -> None:
        resource = {
            **RESOURCE,
            "resource": "https://pinata.example/v1/retrieve/private/cid",
            "serviceName": "Pinata private file retrieval",
            "x402Version": 1,
            "accepts": [
                {
                    "scheme": "exact",
                    "network": "base",
                    "asset": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
                    "maxAmountRequired": "100",
                    "payTo": "0x1111111111111111111111111111111111111111",
                    "maxTimeoutSeconds": 300,
                }
            ],
        }

        _, offering = CdpBazaarAdapter().normalize_resource(resource)

        payment = offering.payment_options[0]
        self.assertEqual(payment.amount_atomic, "100")
        self.assertEqual(payment.network, "eip155:8453")
        self.assertEqual(str(payment.price_usd), "0.0001")

    def test_search_uses_public_semantic_search_filters(self) -> None:
        session = FakeSession()
        adapter = CdpBazaarAdapter(session=session)

        results = adapter.search(
            "token risk",
            network="eip155:137",
            max_usd_price="0.05",
            limit=10,
        )

        self.assertEqual(len(results), 1)
        self.assertEqual(session.params["query"], "token risk")
        self.assertEqual(session.params["network"], "eip155:137")
        self.assertEqual(session.params["maxUsdPrice"], "0.05")
        self.assertEqual(session.params["limit"], 10)

    def test_fetch_page_uses_resources_pagination_and_conditional_etag(self) -> None:
        session = InventorySession(InventoryResponse(
            payload={"items": [RESOURCE], "pagination": {"offset": 2, "limit": 2, "total": 3}},
            etag="page-etag",
        ))
        adapter = CdpBazaarAdapter(resources_url="https://bazaar.example/resources", session=session)

        result = adapter.fetch_page(offset=2, limit=2, etag="known-etag")

        self.assertEqual(result["items"], [RESOURCE])
        self.assertEqual(result["offset"], 2)
        self.assertEqual(result["count"], 1)
        self.assertEqual(result["limit"], 2)
        self.assertEqual(result["total"], 3)
        self.assertEqual(result["etag"], "page-etag")
        self.assertEqual(session.request["url"], "https://bazaar.example/resources")
        self.assertEqual(session.request["params"], {"type": "http", "limit": 2, "offset": 2})
        self.assertEqual(session.request["headers"], {"If-None-Match": "known-etag"})

    def test_fetch_page_normalizes_not_modified_response(self) -> None:
        session = InventorySession(InventoryResponse(status_code=304))
        adapter = CdpBazaarAdapter(session=session)

        result = adapter.fetch_page(offset=4, limit=2, etag="known-etag")

        self.assertEqual(result, {"items": [], "offset": 4, "total": 4, "etag": "known-etag", "not_modified": True})

    def test_fetch_page_rejects_missing_or_mismatched_pagination(self) -> None:
        missing = InventorySession(InventoryResponse(payload={"items": [RESOURCE], "pagination": {"offset": 0}}))
        mismatched = InventorySession(InventoryResponse(payload={"items": [RESOURCE], "pagination": {"offset": 1, "total": 1}}))

        with self.assertRaisesRegex(ValueError, "pagination"):
            CdpBazaarAdapter(session=missing).fetch_page(offset=0, limit=1)
        with self.assertRaisesRegex(ValueError, "offset"):
            CdpBazaarAdapter(session=mismatched).fetch_page(offset=0, limit=1)


if __name__ == "__main__":
    unittest.main()
