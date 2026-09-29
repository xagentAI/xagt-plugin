import base64
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import requests

from services.provider_verification import EndpointVerifier
from services.marketplace_repository import MarketplaceRepository
from shared.models import PaymentOption, Provider, ServiceOffering


class FakeResponse:
    status_code = 402

    def __init__(self, pay_to: str, *, amount: str = "5000") -> None:
        payload = {
            "x402Version": 2,
            "accepts": [
                {
                    "scheme": "exact",
                    "network": "eip155:137",
                    "asset": "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359",
                    "amount": amount,
                    "payTo": pay_to,
                }
            ],
        }
        encoded = base64.b64encode(json.dumps(payload).encode()).decode()
        self.headers = {"PAYMENT-REQUIRED": encoded}


class FakeSession:
    def __init__(self, pay_to: str, *, amount: str = "5000") -> None:
        self.pay_to = pay_to
        self.amount = amount

    def request(self, **_: object) -> FakeResponse:
        return FakeResponse(self.pay_to, amount=self.amount)


class FlakySession(FakeSession):
    def __init__(self, pay_to: str) -> None:
        super().__init__(pay_to)
        self.calls = 0

    def request(self, **_: object) -> FakeResponse:
        self.calls += 1
        if self.calls == 1:
            raise requests.ConnectionError("temporary route failure")
        return super().request()


class RecordingSession(FakeSession):
    def __init__(self, pay_to: str, *, amount: str = "5000") -> None:
        super().__init__(pay_to, amount=amount)
        self.calls: list[dict[str, object]] = []

    def request(self, **kwargs: object) -> FakeResponse:
        self.calls.append(kwargs)
        return super().request(**kwargs)


def offering(
    pay_to: str = "0x1111111111111111111111111111111111111111",
    *,
    method: str = "POST",
) -> ServiceOffering:
    provider = Provider(name="Risk", domain="risk.example.com", source="test")
    return ServiceOffering(
        provider_id=provider.provider_id,
        source="test",
        source_id="https://risk.example.com/check",
        name="Wallet Risk",
        endpoint="https://risk.example.com/check",
        method=method,
        status="submitted",
        payment_options=[
            PaymentOption(
                scheme="exact",
                network="eip155:137",
                asset="0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359",
                amount_atomic="5000",
                pay_to=pay_to,
            )
        ],
    )


class VerificationTests(unittest.TestCase):
    def test_read_only_mode_rejects_side_effecting_methods_before_dns_or_http(self) -> None:
        expected = "0x1111111111111111111111111111111111111111"
        for method in ("POST", "PUT", "PATCH", "DELETE"):
            with self.subTest(method=method), patch.dict(
                os.environ,
                {"MARKETPLACE_ENDPOINT_VERIFY_READ_ONLY": "true"},
            ):
                session = RecordingSession(expected)
                resolver_calls: list[str] = []
                verifier = EndpointVerifier(
                    session=session,
                    resolver=lambda hostname: resolver_calls.append(hostname)
                    or ["93.184.216.34"],
                )

                result = verifier.verify(offering(expected, method=method))

                self.assertFalse(result.verified)
                self.assertEqual(result.reason_code, "READ_ONLY_METHOD_NOT_ALLOWED")
                self.assertEqual(resolver_calls, [])
                self.assertEqual(session.calls, [])

    def test_read_only_mode_allows_get_without_changing_verification(self) -> None:
        expected = "0x1111111111111111111111111111111111111111"
        session = RecordingSession(expected)
        with patch.dict(
            os.environ,
            {"MARKETPLACE_ENDPOINT_VERIFY_READ_ONLY": "true"},
        ):
            verifier = EndpointVerifier(
                session=session,
                resolver=lambda _: ["93.184.216.34"],
            )

            result = verifier.verify(offering(expected, method="GET"))

        self.assertTrue(result.verified)
        self.assertEqual(len(session.calls), 1)
        self.assertEqual(session.calls[0]["method"], "GET")

    def test_default_mode_preserves_post_verification(self) -> None:
        expected = "0x1111111111111111111111111111111111111111"
        session = RecordingSession(expected)
        with patch.dict(os.environ, {}, clear=False):
            os.environ.pop("MARKETPLACE_ENDPOINT_VERIFY_READ_ONLY", None)
            verifier = EndpointVerifier(
                session=session,
                resolver=lambda _: ["93.184.216.34"],
            )

            result = verifier.verify(offering(expected, method="POST"))

        self.assertTrue(result.verified)
        self.assertEqual(len(session.calls), 1)
        self.assertEqual(session.calls[0]["method"], "POST")

    def test_invalid_read_only_configuration_fails_closed(self) -> None:
        with patch.dict(
            os.environ,
            {"MARKETPLACE_ENDPOINT_VERIFY_READ_ONLY": "sometimes"},
        ):
            with self.assertRaisesRegex(
                ValueError,
                "MARKETPLACE_ENDPOINT_VERIFY_READ_ONLY must be true or false",
            ):
                EndpointVerifier()

    def test_retries_transient_connection_failure(self) -> None:
        expected = "0x1111111111111111111111111111111111111111"
        session = FlakySession(expected)
        verifier = EndpointVerifier(
            session=session,
            resolver=lambda _: ["93.184.216.34"],
            request_attempts=2,
        )

        result = verifier.verify(offering(expected))

        self.assertTrue(result.verified)
        self.assertEqual(session.calls, 2)

    def test_verifies_live_402_when_recipient_matches(self) -> None:
        expected = "0x1111111111111111111111111111111111111111"
        verifier = EndpointVerifier(
            session=FakeSession(expected),
            resolver=lambda _: ["93.184.216.34"],
        )

        result = verifier.verify(offering(expected))

        self.assertTrue(result.verified)
        self.assertEqual(result.live_pay_to, [expected])

    def test_rejects_live_recipient_mismatch(self) -> None:
        verifier = EndpointVerifier(
            session=FakeSession("0x2222222222222222222222222222222222222222"),
            resolver=lambda _: ["93.184.216.34"],
        )

        result = verifier.verify(offering())

        self.assertFalse(result.verified)
        self.assertEqual(result.reason_code, "PAYMENT_RECIPIENT_MISMATCH")

    def test_rejects_live_price_mismatch_even_when_recipient_matches(self) -> None:
        expected = "0x1111111111111111111111111111111111111111"
        verifier = EndpointVerifier(
            session=FakeSession(expected, amount="500000"),
            resolver=lambda _: ["93.184.216.34"],
        )

        result = verifier.verify(offering(expected))

        self.assertFalse(result.verified)
        self.assertEqual(result.reason_code, "PAYMENT_REQUIREMENTS_MISMATCH")

    def test_registry_marks_offering_verified_only_after_success(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            repository = MarketplaceRepository(f"sqlite+pysqlite:///{Path(directory) / 'registry.sqlite3'}")
            row = offering()
            provider = Provider(
                provider_id=row.provider_id,
                name="Risk",
                domain="risk.example.com",
                source="test",
            )
            repository.upsert_provider(provider)
            repository.upsert_offering(row)
            verifier = EndpointVerifier(
                session=FakeSession(row.payment_options[0].pay_to),
                resolver=lambda _: ["93.184.216.34"],
            )
            result = verifier.verify(row)
            now = __import__("datetime").datetime.now(__import__("datetime").UTC)
            repository.upsert_offering(row.model_copy(update={"status":"verified"}),verified_at=now)

            self.assertTrue(result.verified)
            self.assertEqual(repository.get_offering(row.offering_id).status, "verified")


if __name__ == "__main__":
    unittest.main()
