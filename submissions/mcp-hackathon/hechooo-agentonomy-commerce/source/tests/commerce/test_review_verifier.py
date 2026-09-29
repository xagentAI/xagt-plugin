from __future__ import annotations

from dataclasses import dataclass, field
import json
from urllib.parse import urlsplit

import pytest

from scripts.verify_review_api import VerificationError, verify_api


TOKEN = "review-verifier-token-" + "v" * 40
COMMIT = "a" * 40
SLUG = "hechooo-agentonomy-commerce"


@dataclass
class FakeReviewHTTP:
    used: str = "0.00"
    submissions: int = 0
    deliveries: int = 0
    preview_id: str = "preview_fake123"
    purchase_id: str = "purchase_fake123"
    calls: list[tuple[str, str]] = field(default_factory=list)

    def __call__(self, method: str, url: str, *, token: str | None = None,
                 payload: dict | None = None, headers: dict | None = None,
                 timeout: float = 10.0):
        del headers, timeout
        path = urlsplit(url).path
        self.calls.append((method, path))
        if path == "/health":
            return 200, {
                "status": "ok",
                "commit": COMMIT,
                "real_funds": False,
                "settlement_mode": "simulated",
                "service_transport": "http",
            }
        if path == "/.well-known/xagent-verification.json":
            return 200, {"schemaVersion": 1, "slug": SLUG, "commit": COMMIT}
        if not (token and token == TOKEN):
            return 401, {"error": "unauthorized"}
        if path == "/v1/budget" and method == "GET":
            return 200, self._budget()
        if path == "/v1/previews" and method == "POST":
            return 200, {
                "preview_id": self.preview_id,
                "offering_id": "csv-reconciliation-v1",
                "state": "preview_created",
                "real_funds": False,
                "settlement_mode": "simulated",
                "service_transport": "http",
            }
        if path == f"/v1/purchases/{self.purchase_id}" and method == "GET":
            return 200, self._purchase()
        if path == "/v1/purchases" and method == "POST":
            if payload != {"preview_id": self.preview_id}:
                return 404, {"detail": "not_found"}
            if self.submissions == 0:
                self.used = "0.30"
                self.submissions = 1
                self.deliveries = 1
            return 200, self._purchase()
        return 404, {"detail": "not_found"}

    def _budget(self) -> dict:
        return {
            "budget_usdc": "1.00",
            "used_amount_usdc": self.used,
            "remaining_amount_usdc": f"{1 - float(self.used):.2f}",
            "settlement_submissions": self.submissions,
            "merchant_deliveries": self.deliveries,
            "real_funds": False,
            "settlement_mode": "simulated",
            "service_transport": "http",
        }

    def _purchase(self) -> dict:
        return {
            "purchase_id": self.purchase_id,
            "preview_id": self.preview_id,
            "state": "delivered",
            "real_funds": False,
            "settlement_mode": "simulated",
            "service_transport": "http",
            "service_result": {
                "unique_transaction_count": 2,
                "duplicate_ids": ["t1"],
                "net_totals": {"USD": "27.50"},
            },
        }


def test_verifier_checks_public_proof_auth_purchase_and_replay_without_second_charge():
    fake = FakeReviewHTTP()

    evidence = verify_api(
        "https://review.local",
        COMMIT,
        TOKEN,
        project_slug=SLUG,
        requester=fake,
    )

    assert evidence["purchase_id"] == fake.purchase_id
    assert evidence["preview_id"] == fake.preview_id
    assert evidence["unauthorized_status"] == 401
    assert evidence["purchase"]["service_result"]["net_totals"] == {"USD": "27.50"}
    assert evidence["replay"]["charge_unchanged"] is True
    assert fake.calls.count(("POST", "/v1/previews")) == 1
    assert fake.calls.count(("POST", "/v1/purchases")) == 2

    restarted = verify_api(
        "https://review.local",
        COMMIT,
        TOKEN,
        project_slug=SLUG,
        purchase_id=fake.purchase_id,
        preview_id=fake.preview_id,
        requester=fake,
    )

    assert restarted["restart_check"]["charge_unchanged"] is True
    assert restarted["restart_check"]["same_result"] is True
    assert fake.calls.count(("POST", "/v1/previews")) == 1
    assert fake.calls.count(("POST", "/v1/purchases")) == 3


def test_verifier_rejects_public_commit_mismatch_without_printing_token():
    fake = FakeReviewHTTP()
    with pytest.raises(VerificationError, match="commit") as error:
        verify_api(
            "https://review.local",
            "b" * 40,
            TOKEN,
            project_slug=SLUG,
            requester=fake,
        )
    assert TOKEN not in str(error.value)


def test_verifier_evidence_is_json_serializable_and_sanitized():
    fake = FakeReviewHTTP()
    evidence = verify_api(
        "https://review.local",
        COMMIT,
        TOKEN,
        project_slug=SLUG,
        requester=fake,
    )
    encoded = json.dumps(evidence, sort_keys=True)
    assert TOKEN not in encoded
    assert "csv_text" not in encoded
    assert "receipt_signing_key" not in encoded
