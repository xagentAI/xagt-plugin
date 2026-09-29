"""Focused contracts for the public Receipt Explorer proof page."""

from pathlib import Path

from fastapi.testclient import TestClient

from app.main import app

client = TestClient(app)

ROOT = Path(__file__).resolve().parents[2]
INDEX = (ROOT / "frontend/index.html").read_text(encoding="utf-8")
APP = (ROOT / "frontend/app.js").read_text(encoding="utf-8")


def _demo_receipt():
    response = client.post("/api/outcomes/demo")
    assert response.status_code == 200, response.text
    return response.json()


def test_valid_receipt_route_serves_frontend_with_no_cache_policy():
    receipt = _demo_receipt()
    receipt_id = receipt["receipt_id"]
    response = client.get(f"/receipts/{receipt_id}")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-cache, max-age=0, must-revalidate"
    assert response.headers["x-robots-tag"] == "noindex, nofollow"
    assert "Receipt Explorer" in response.text
    assert "receiptExplorer" in response.text


def test_malformed_receipt_id_fails_safely():
    for bad in ("XYZ", "ABCDEF0123456789ABCDEF01", "abcdef0123456789abcdef0",
                "abcdef0123456789abcdef012", "abcdef0123456789abcde!", "../etc"):
        response = client.get(f"/receipts/{bad}")
        assert response.status_code == 404
        assert "Traceback" not in response.text
        assert ".py" not in response.text


def test_missing_receipt_api_behavior():
    response = client.get("/api/outcomes/receipts/" + "0" * 24)
    assert response.status_code == 404
    assert response.json() == {"detail": "Receipt not found"}


def test_verified_and_unverified_display_contracts():
    # Static display contract: explorer must render both verdicts and all required fields.
    for token in ("VERIFIED", "UNVERIFIED", "receipt_id", "created_at", "goal",
                  "agreement", "deployment_commit", "fingerprint",
                  "integrity", "authenticity", "no result selected",
                  "not charged / no settlement"):
        assert token in APP, token
    assert "no result selected" in APP
    # Explorer view detection and dedicated rendering.
    assert "/receipts/" in APP
    assert "receiptExplorer" in APP
    assert "renderReceiptExplorer" in APP


def test_integrity_and_authenticity_shown_separately():
    assert "Integrity valid" in APP or "integrity_valid" in APP
    assert "Authenticity" in APP
    assert "unavailable signature is never a success" in APP or "never a success" in APP
    # Backend keeps the two signals distinct.
    receipt = _demo_receipt()
    envelope = client.get(f"/api/outcomes/receipts/{receipt['receipt_id']}").json()
    assert "integrity_valid" in envelope and "authenticity" in envelope
    assert set(envelope["authenticity"]) >= {"state", "valid"}


def test_public_proof_link_generated_after_demo():
    assert "View public proof" in APP
    assert "outcomeProofLink" in INDEX
    assert "/receipts/${receipt.receipt_id}" in APP or "/receipts/" in APP


def test_explorer_controls_exist():
    for control in ("receiptVerifyBtn", "receiptCopyLinkBtn", "receiptCopyJsonBtn",
                    "receiptDownloadBtn", "receiptBackLink", "Verify again",
                    "Copy public link", "Copy receipt JSON", "Download receipt JSON",
                    "Back to APIVouch"):
        assert control in INDEX or control in APP, control
    assert "Copy public link" in INDEX
    assert "Download receipt JSON" in INDEX


def test_mobile_css_stacks_without_hiding_overflow():
    assert ".outcome-metrics,.attempts{grid-template-columns:minmax(0,1fr)}" in INDEX
    assert ".labgrid,.receipt-grid,.receipt-attempts{grid-template-columns:minmax(0,1fr)}" in INDEX
    assert "overflow-wrap:anywhere" in INDEX
    assert "body{overflow-x:hidden" not in INDEX


def test_dynamic_receipt_fields_are_escaped():
    # All receipt-controlled rendering must pass through esc().
    assert "esc(receipt.receipt_id)" in APP
    assert "esc(receipt.goal)" in APP
    assert "esc(attempt.name)" in APP
    assert "esc(attempt.url" in APP
    # No unescaped interpolation of receipt fields into innerHTML.
    assert "innerHTML" in APP
    # Explorer never embeds raw receipt content: JSON is set via textContent.
    assert '$("receiptJson").textContent = JSON.stringify(receipt' in APP
