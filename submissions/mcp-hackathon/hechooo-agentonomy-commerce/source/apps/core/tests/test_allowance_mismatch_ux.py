"""Confirmed amount differences recover without another wallet submission."""
import json

import pytest

from services.account_service.opc_console import OPC_SETUP_HTML
from test_opc_setup_flow import _run_setup_flow


TX_HASH = "0x" + "4" * 64


PREAMBLE = r'''
const mismatchMode = __MODE__;
const mismatchBase = "eip155:8453";
const mismatchBaseToken = "0x" + "6".repeat(40);
const mismatchBaseSpender = "0x" + "7".repeat(40);
for (const suffix of ["state", "token", "spender"]) elements[`#base-${suffix}`] = makeElement();
const mismatchBaseButton = makeElement({dataset: {approveNetwork: mismatchBase}});
const originalMismatchQuerySelector = document.querySelector.bind(document);
document.querySelector = (selector) => selector === `[data-approve-network="${mismatchBase}"]`
  ? mismatchBaseButton : originalMismatchQuerySelector(selector);
const mismatchGrant = grant({
  max_amount_usdc: "20", per_transaction_limit_usdc: "20",
  hourly_limit_usdc: "20", daily_limit_usdc: "20",
  network_scopes: [network, mismatchBase], asset_scopes: [token, mismatchBaseToken],
  limits_usdc: {per_transaction: "20", rolling_hour: "20", daily: "20", total: "20"},
  used_usdc: {rolling_hour: "0", daily: "0", total: "0"},
  reserved_usdc: {rolling_hour: "0", daily: "0", total: "0"},
  remaining_usdc: {rolling_hour: "20", daily: "20", total: "20"}
});
if (mismatchMode === "t20_h5") {
  mismatchGrant.per_transaction_limit_usdc = "5";
  mismatchGrant.hourly_limit_usdc = "5";
  mismatchGrant.limits_usdc.per_transaction = "5";
  mismatchGrant.limits_usdc.rolling_hour = "5";
  mismatchGrant.remaining_usdc.rolling_hour = "5";
}
state.current_spending_mandate = mismatchGrant;
state.spending_grants = [mismatchGrant];
state.asset_allowances = [allowance("0")];
state.network_configs[mismatchBase] = {
  chain_id: 8453, required_confirmations: 1, token_decimals: 6, token_symbol: "USDC"
};
state.approval_targets[mismatchBase] = {
  token_address: mismatchBaseToken, spender_address: mismatchBaseSpender
};
if (["stale_covered", "newer_covered"].includes(mismatchMode)) {
  state.asset_allowances = [allowance("20000000")];
  state.asset_allowances[0].last_chain_check_at = mismatchMode === "stale_covered"
    ? "2026-09-14T06:00:00.000Z"
    : "2026-09-16T06:00:00.000Z";
}
currentPairing = {...currentPairing, status: "active", wallet_identity_id: identityId,
                  spending_grant_id: grantId};
bootstrap.pairing.status = "active";
document.body.dataset.opcSetup = JSON.stringify(bootstrap);
const mismatchRecord = {
  attempt_id: "allowance_attempt_mismatch", user_id: "user_opc_setup",
  wallet_identity_id: identityId, network, token_address: token,
  spender_address: spender, amount_atomic: "20000000",
  allowance_tx_hash: transactionHash, status: "confirmed_mismatch",
  reason_code: "amount_mismatch", created_at: now, updated_at: now,
  next_check_at: null, actual_approved_amount_atomic: "5000000",
  observed_allowance_atomic: "4000000", confirmed_block: 100,
  confirmed_block_hash: "0x" + "8".repeat(64), verified_at: now
};
const originalMismatchFetch = global.fetch;
global.fetch = async (url, options = {}) => {
  if (["http", "submit", "submit_history", "recover_verify"].includes(mismatchMode) && String(url).endsWith("/allowances/verify")) {
    calls.push({url: String(url), method: options.method || "GET"});
    verifyAttempts += 1;
    verifyRequests.push(JSON.parse(options.body));
    const recovery = ["submit", "submit_history"].includes(mismatchMode)
      ? {...mismatchRecord, attempt_id: allowanceAttempt?.attempt_id || mismatchRecord.attempt_id}
      : mismatchRecord;
    const historical = {...mismatchRecord, attempt_id: "allowance_attempt_older",
      allowance_tx_hash: "0x" + "9".repeat(64),
      verified_at: "2026-09-14T06:00:00.000Z"};
    state.allowance_recovery = mismatchMode === "submit_history"
      ? [historical, {...recovery, attempt_id: allowanceAttempt?.attempt_id || recovery.attempt_id}]
      : [recovery];
    return response({detail: "Confirmed with a different amount", code: "allowance_amount_mismatch",
                     recovery}, false, 409);
  }
  return originalMismatchFetch(url, options);
};
'''

HOOKS = r'''
globalThis.__mismatchTest = {
  seed: () => {
    const context = {
      attempt_id: mismatchRecord.attempt_id, wallet_identity_id: identityId,
      network, token_address: token, spender_address: spender, amount_atomic: "20000000",
      request_key: "ab".repeat(32), status: "pending"
    };
    if (mismatchMode === "wrong_amount") context.amount_atomic = "19000000";
    if (mismatchMode === "wrong_attempt") context.attempt_id = "other_attempt";
    if (mismatchMode !== "uncertain_without_context") persistAllowanceAttemptContext(context);
    persistPendingAllowance({wallet_identity_id: identityId, network,
      token_address: token, spender_address: spender,
      allowance_tx_hash: mismatchMode === "wrong_hash" ? "0x" + "9".repeat(64) : transactionHash});
    if (mismatchMode !== "recover_verify") persistAllowancePostSendUncertain(identityId);
    opcSetupState.blocked = true;
    opcSetupState.blockedContext = {
      identity, allowance: {network, wallet_address: wallet, token_address: token,
        spender_address: spender, target_atomic: "20000000"},
      grantId, terms: {...mismatchGrant}, generation: opcSetupState.generation,
      selection: selectedWalletSnapshot(), pairing: opcPairing,
      pairingGeneration: opcPairingGeneration, attemptContext: context
    };
  },
  refresh: async () => {
    try {
      return await loadState();
    } catch (error) {
      if (["missing_evidence", "foreign_wallet", "same_amount", "overflow"].includes(mismatchMode)) {
        globalThis.__mismatchTest.validationError = error.message;
        return false;
      }
      throw error;
    }
  },
  verify: async () => {
    try { await verifyPendingAllowance(pendingAllowance); }
    catch (_error) { /* Expected non-success result; UI owns recovery messaging. */ }
  },
  submit: () => globalThis.__clinkOpcSetupTest.submit(),
  recover: () => opcSetupRecover(),
  selectBase: () => {
    elements["#opc-setup-network"].value = mismatchBase;
    elements["#opc-setup-network"].listeners.change?.();
  }
};
'''

FLOW = r'''
await tick();
if (mismatchMode === "direct_recover" || mismatchMode === "recover_verify") {
  globalThis.__mismatchTest.seed();
  if (mismatchMode === "direct_recover") state.allowance_recovery = [mismatchRecord];
  await globalThis.__mismatchTest.recover();
} else if (mismatchMode === "submit" || mismatchMode === "submit_history") {
  await globalThis.__mismatchTest.submit();
} else {
  if (mismatchMode !== "fresh") globalThis.__mismatchTest.seed();
  if (mismatchMode === "missing_evidence") delete mismatchRecord.verified_at;
  if (mismatchMode === "foreign_wallet") mismatchRecord.wallet_identity_id = "foreign_wallet";
  if (mismatchMode === "same_amount") mismatchRecord.actual_approved_amount_atomic = "20000000";
  if (mismatchMode === "overflow") mismatchRecord.actual_approved_amount_atomic = (1n << 256n).toString();
  if (mismatchMode === "storage_failure") {
    const originalRemove = sessionStorage.removeItem.bind(sessionStorage);
    sessionStorage.removeItem = (key) => {
      if (key.includes("allowance_post_send_uncertain")) return;
      originalRemove(key);
    };
  }
  if (mismatchMode === "http") {
    await globalThis.__mismatchTest.verify();
  } else {
    state.allowance_recovery = [mismatchRecord];
    if (mismatchMode === "history") {
      state.allowance_recovery.unshift({...mismatchRecord,
        attempt_id: "allowance_attempt_older",
        allowance_tx_hash: "0x" + "9".repeat(64),
        verified_at: "2026-09-14T06:00:00.000Z"});
    }
    if (mismatchMode === "other_open") {
      state.allowance_recovery.push({
        ...Object.fromEntries(Object.entries(mismatchRecord).filter(([key]) =>
          !["actual_approved_amount_atomic", "observed_allowance_atomic", "confirmed_block",
            "confirmed_block_hash", "verified_at"].includes(key))),
        attempt_id: "other_pending", network: mismatchBase, token_address: mismatchBaseToken,
        spender_address: mismatchBaseSpender, allowance_tx_hash: "0x" + "9".repeat(64),
        status: "pending", reason_code: "chain_pending", next_check_at: future
      });
    }
    await globalThis.__mismatchTest.refresh();
  }
}
if (["matching", "http"].includes(mismatchMode)) await globalThis.__mismatchTest.recover();
if (["fresh", "matching", "http"].includes(mismatchMode)) {
  globalThis.__mismatchTest.selectBase();
  await globalThis.__mismatchTest.refresh();
}
'''


def run_mismatch(mode):
    return _run_setup_flow(
        "mismatch_" + mode,
        preamble_extra=PREAMBLE.replace("__MODE__", json.dumps(mode)),
        hooks_extra=HOOKS, postamble_extra=FLOW,
    )


@pytest.mark.parametrize("mode", ["fresh", "matching", "http"])
def test_confirmed_polygon_amount_difference_does_not_block_base_review(mode):
    result = run_mismatch(mode)
    assert result["inspect"]["recoveryBlocked"] is False
    assert result["inspect"]["pendingAllowance"] is None
    assert result["inspect"]["uncertain"] is None
    assert result["inspect"]["setupBlocked"] is False
    assert result["setupState"] != "Saved"
    assert result["sendAttempts"] == 0
    assert result["personalSigns"] == []
    assert result["grantBodies"] == []
    assert result["finalGrant"]["max_amount_usdc"] == "20"
    assert not any("allowance_post_send_uncertain" in key or "allowance_attempt" in key
                   for key in result["storageKeys"])
    assert result["selectedSetupNetwork"] == "eip155:8453"
    assert "transaction approved 5 USDC" in result["inspect"]["mismatchNotice"]
    assert "requested 20 USDC" in result["inspect"]["mismatchNotice"]
    assert "observed allowance at verification 4 USDC" in result["inspect"]["mismatchNotice"]
    assert "2026-09-15T06:00:00.000Z" in result["inspect"]["mismatchNotice"]


def test_live_submit_hash_then_structured_mismatch_returns_to_review_without_resend():
    result = run_mismatch("submit")
    assert result["setupState"] == "Review"
    assert result["inspect"]["recoveryBlocked"] is False
    assert result["inspect"]["setupBlocked"] is False
    assert result["inspect"]["pendingAllowance"] is None
    assert result["inspect"]["uncertain"] is None
    assert result["sendAttempts"] == 1
    assert result["sendCount"] == 1
    assert result["verifyAttempts"] == 1
    assert result["grantBodies"] == []
    assert result["personalSigns"] == []
    assert result["finalGrant"]["max_amount_usdc"] == "20"
    assert result["inspect"]["networkApproval"] == {"hidden": False, "disabled": False}
    assert "transaction approved 5 USDC" in result["setupStatus"]
    assert "requested 20 USDC" in result["setupStatus"]
    assert "observed allowance at verification 4 USDC" in result["setupStatus"]
    assert "No transaction was resent" in result["setupStatus"]
    assert "Budget unchanged" in result["setupStatus"]
    assert result["setupState"] != "Saved"
    assert not any("allowance_post_send_uncertain" in key or "allowance_attempt" in key
                   for key in result["storageKeys"])


def test_live_submit_with_historical_terminal_record_cleans_only_exact_result():
    result = run_mismatch("submit_history")
    assert result["setupState"] == "Review"
    assert result["inspect"]["recoveryBlocked"] is False
    assert result["inspect"]["setupBlocked"] is False
    assert result["inspect"]["pendingAllowance"] is None
    assert result["inspect"]["uncertain"] is None
    assert result["sendCount"] == 1
    assert result["sendAttempts"] == 1
    assert result["verifyAttempts"] == 1
    assert result["inspect"]["networkApproval"] == {"hidden": False, "disabled": False}
    assert result["inspect"]["recoveryRecords"] == [
        {
            "attempt_id": "allowance_attempt_older",
            "allowance_tx_hash": "0x" + "9" * 64,
            "status": "confirmed_mismatch",
        },
        {
            "attempt_id": "allowance_attempt_1",
            "allowance_tx_hash": TX_HASH,
            "status": "confirmed_mismatch",
        },
    ]
    assert "No transaction was resent" in result["setupStatus"]
    assert result["setupState"] != "Saved"


def test_total_budget_mismatch_cleanup_does_not_compare_current_per_transaction_limit():
    result = run_mismatch("t20_h5")
    assert result["setupState"] == "Review"
    assert result["inspect"]["recoveryBlocked"] is False
    assert result["inspect"]["setupBlocked"] is False
    assert result["inspect"]["pendingAllowance"] is None
    assert result["inspect"]["uncertain"] is None
    assert result["finalGrant"]["max_amount_usdc"] == "20"
    assert result["finalGrant"]["per_transaction_limit_usdc"] == "5"
    assert result["finalGrant"]["limits_usdc"]["per_transaction"] == "5"
    assert result["sendAttempts"] == 0
    assert result["grantBodies"] == []
    assert result["personalSigns"] == []


def test_direct_recovery_stops_after_confirmed_mismatch_and_returns_to_review():
    result = run_mismatch("direct_recover")
    assert result["setupState"] == "Review"
    assert result["inspect"]["recoveryBlocked"] is False
    assert result["inspect"]["setupBlocked"] is False
    assert result["inspect"]["pendingAllowance"] is None
    assert result["inspect"]["uncertain"] is None
    assert result["sendAttempts"] == 0
    assert result["grantBodies"] == []
    assert result["personalSigns"] == []
    assert "No transaction was resent" in result["setupStatus"]
    assert result["setupState"] != "Saved"
    assert not any("allowance_post_send_uncertain" in key or "allowance_attempt" in key
                   for key in result["storageKeys"])


def test_recovery_verify_mismatch_returns_to_review_without_reopening_old_flow():
    result = run_mismatch("recover_verify")
    assert result["setupState"] == "Review"
    assert result["inspect"]["recoveryBlocked"] is False
    assert result["inspect"]["setupBlocked"] is False
    assert result["inspect"]["pendingAllowance"] is None
    assert result["inspect"]["uncertain"] is None
    assert result["verifyAttempts"] == 1
    assert result["sendAttempts"] == 0
    assert result["grantBodies"] == []
    assert result["personalSigns"] == []
    assert "No transaction was resent" in result["setupStatus"]
    assert result["setupState"] != "Saved"


@pytest.mark.parametrize("mode,notice_visible", [("stale_covered", True), ("newer_covered", False)])
def test_current_allowance_snapshot_only_replaces_older_mismatch_when_newer(mode, notice_visible):
    result = run_mismatch(mode)
    assert result["inspect"]["recoveryBlocked"] is False
    assert result["inspect"]["setupBlocked"] is False
    assert result["inspect"]["networkApproval"] == {"hidden": True, "disabled": True}
    assert "ready for up to 20 USDC" in result["inspect"]["networkState"]
    assert ("transaction approved 5 USDC" in result["inspect"]["networkState"]) is notice_visible
    assert ("transaction approved 5 USDC" in result["inspect"]["mismatchNotice"]) is notice_visible


@pytest.mark.parametrize("mode", [
    "wrong_amount", "wrong_attempt", "wrong_hash", "uncertain_without_context",
    "missing_evidence", "foreign_wallet", "same_amount", "overflow", "other_open",
    "storage_failure",
])
def test_unrelated_or_incomplete_terminal_evidence_cannot_clear_recovery(mode):
    result = run_mismatch(mode)
    assert result["inspect"]["setupBlocked"] is True
    assert result["setupState"] != "Saved"
    assert result["sendAttempts"] == 0
    assert result["personalSigns"] == []
    assert result["grantBodies"] == []
    assert result["inspect"]["uncertain"] is not None


def test_finite_approve_amount_is_already_prefilled_not_a_second_input():
    result = _run_setup_flow("insufficient")
    assert result["sendAttempts"] == 1
    assert result["allowanceApproval"]["amountAtomic"] == "11111111"
    assert result["allowanceApproval"]["data"].startswith("0x095ea7b3")
    assert "This amount is filled in for your wallet confirmation" in OPC_SETUP_HTML
    assert "No need to enter it again" in OPC_SETUP_HTML
