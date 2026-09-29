from __future__ import annotations

import pytest

from services.account_service.console import ACCOUNT_CONSOLE_JS
from services.account_service.opc_console import OPC_SETUP_CSS
from test_opc_setup_flow import _run_setup_flow


def test_selected_wallet_must_match_bound_wallet_before_any_wallet_signature() -> None:
    result = _run_setup_flow("bound_wallet_mismatch")

    assert result["personalSigns"] == []
    assert not any(call["url"].endswith("/wallet-challenge") for call in result["calls"])
    assert result["sendCount"] == 0
    assert "bound wallet" in result["setupStatus"].lower()


def test_pending_wallet_provider_request_has_bounded_visible_state() -> None:
    result = _run_setup_flow("pending_provider_request")

    assert result["personalSigns"] == []
    assert result["sendCount"] == 0
    assert result["providerMethods"].count("eth_requestAccounts") == 1
    assert result["setupStage"] == "wallet_confirmation"
    assert "timed out" in result["setupStatus"].lower()


def test_non_rejection_provider_failure_keeps_unknown_send_barrier_without_raw_error() -> None:
    result = _run_setup_flow("provider_error")

    assert result["sendAttempts"] == 1
    assert result["sendCount"] == 0
    assert result["setupStage"] == "submission_unknown"
    assert "4900" in result["setupStatus"]
    assert "provider secret" not in result["setupStatus"].lower()
    assert any("allowance_post_send_uncertain" in key for key in result["storageKeys"])


def test_invalid_send_result_is_distinguished_from_wallet_rejection_and_not_retried() -> None:
    result = _run_setup_flow("invalid_send_result")

    assert result["sendAttempts"] == 1
    assert result["sendCount"] == 1
    assert result["setupStage"] == "submission_unknown"
    assert "invalid transaction" in result["setupStatus"].lower()
    assert "rejected" not in result["setupStatus"].lower()
    assert any("allowance_post_send_uncertain" in key for key in result["storageKeys"])


def test_wallet_rejection_is_not_classified_as_unknown_submission() -> None:
    result = _run_setup_flow("provider_reject")

    assert result["sendAttempts"] == 1
    assert result["sendCount"] == 0
    assert result["setupStage"] == "wallet_confirmation"
    assert "rejected" in result["setupStatus"].lower()
    assert not any("allowance_post_send_uncertain" in key for key in result["storageKeys"])


def test_late_wallet_rejection_releases_only_the_original_uncertainty_without_resend() -> None:
    result = _run_setup_flow("late_allowance_rejected")

    assert result["sendAttempts"] == 1
    assert result["sendCount"] == 0
    assert result["verifyAttempts"] == 0
    assert result["inspect"]["pendingAllowance"] is None
    assert result["inspect"]["uncertain"] is None
    assert result["inspect"]["recoveryBlocked"] is False
    assert result["inspect"]["setupBlocked"] is False
    assert result["setupState"] == "Rejected"
    assert "rejected" in result["setupStatus"].lower()
    assert "not completed" in result["setupStatus"].lower()
    assert result["recoveryHidden"] is True
    assert not any("allowance_post_send_uncertain" in key for key in result["storageKeys"])


@pytest.mark.parametrize(
    "scenario",
    [
        "late_allowance_rejected_4900",
        "late_allowance_rejected_changed",
        "late_allowance_rejected_wallet_changed",
        "late_allowance_rejected_existing_hash",
        "late_allowance_rejected_cleanup_failure",
    ],
)
def test_late_rejection_does_not_release_changed_or_uncertain_context(scenario: str) -> None:
    result = _run_setup_flow(scenario)

    assert result["sendAttempts"] == 1
    assert result["sendCount"] == 0
    assert result["verifyAttempts"] == 0
    assert result["inspect"]["setupBlocked"] is True
    assert result["inspect"]["uncertain"] == "wallet_identity_opc_setup"
    assert result["setupState"] != "Saved"
    assert any("allowance_post_send_uncertain" in key for key in result["storageKeys"])


def test_restored_unknown_allowance_lock_cannot_be_cleared_without_live_rejection() -> None:
    result = _run_setup_flow("restored_unknown_lock")

    assert result["sendAttempts"] == 0
    assert result["sendCount"] == 0
    assert result["verifyAttempts"] == 0
    assert result["inspect"]["setupBlocked"] is True
    assert result["inspect"]["uncertain"] == "wallet_identity_opc_setup"
    assert result["setupState"] != "Saved"
    assert any("allowance_post_send_uncertain" in key for key in result["storageKeys"])


def test_late_allowance_hash_is_verified_without_resending_transaction() -> None:
    result = _run_setup_flow("late_allowance_hash")

    assert result["sendAttempts"] == 1
    assert result["sendCount"] == 1
    assert result["verifyAttempts"] >= 2
    assert result["verifyRequests"][-1]["allowance_tx_hash"] == "0x" + "4" * 64
    assert result["sendAttempts"] == 1
    assert result["setupState"] == "Saved"


def test_late_allowance_verification_cannot_accept_changed_form() -> None:
    result = _run_setup_flow("late_allowance_hash_changed")
    assert result["setupState"] != "Saved"
    assert result["sendAttempts"] == 1
    assert result["personalSigns"] == []


def test_automatic_allowance_verification_stops_after_three_failed_checks() -> None:
    result = _run_setup_flow("late_allowance_hash_never_ready")
    assert result["verifyAttempts"] == 3
    assert result["sendAttempts"] == 1
    assert result["setupState"] != "Saved"


def test_matching_discovered_authorization_continues_without_second_primary_click() -> None:
    result = _run_setup_flow("existing_exact")

    assert result["setupState"] == "Saved"
    assert result["personalSigns"] == []
    assert result["sendCount"] == 0
    assert len(result["planRequests"]) == 2


@pytest.mark.parametrize("scenario", ["discovered_lower_per_transaction", "discovered_lower_daily"])
def test_discovered_different_limits_require_review_without_authority_changes(scenario: str) -> None:
    result = _run_setup_flow(scenario)

    assert result["setupState"] == "Review required"
    assert result["personalSigns"] == []
    assert result["sendCount"] == 0
    assert result["planRequests"] == []


def test_provider_timeout_does_not_recommend_retrying_an_unknown_request() -> None:
    assert "close it before trying again" not in ACCOUNT_CONSOLE_JS
    assert "does not cancel the wallet request" in ACCOUNT_CONSOLE_JS


def test_opc_purpose_checkbox_does_not_inherit_full_width_text_input() -> None:
    assert '.opc-setup-products input[type="checkbox"]' in OPC_SETUP_CSS
    assert "flex: 0 0 18px" in OPC_SETUP_CSS


def test_known_allowance_hash_uses_core_verification_stage_not_unknown_submission() -> None:
    result = _run_setup_flow("allowance_recovery")
    assert result["setupStageBefore"] == "core_verification"
    assert result["sendCount"] == 1
    assert result["verifyAttempts"] == 2
