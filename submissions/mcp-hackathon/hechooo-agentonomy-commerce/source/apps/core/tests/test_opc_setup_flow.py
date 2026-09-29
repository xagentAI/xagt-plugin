from __future__ import annotations

import pytest

import json
import subprocess

from services.account_service.console import ACCOUNT_CONSOLE_JS


WALLET = "0x" + "a" * 40
TOKEN = "0x" + "1" * 40
SPENDER = "0x" + "2" * 40
NETWORK = "eip155:137"
GRANT_ID = "grant_opc_setup"
IDENTITY_ID = "wallet_identity_opc_setup"
PAIRING_ID = "opc_pairing_setup"
INSTALLATION_ID = "opc_installation_setup"
TX_HASH = "0x" + "4" * 64


def _run_setup_flow(
    scenario: str, *, preamble_extra: str = "", postamble_extra: str = "",
    hooks_extra: str = "",
) -> dict:
    """Run the actual setup controller against only synthetic browser boundaries.

    The hook is appended inside ACCOUNT_CONSOLE_JS's existing closure.  It only
    dispatches the production form/cancel listeners; all planning, guards,
    grant handling, and allowance encoding remain production code.
    """

    test_hooks = r'''
  globalThis.__clinkOpcSetupTest = {
    submit: () => {
      setupSubmitted = true;
      const form = elements["#opc-setup-form"];
      const event = {preventDefault() {}, currentTarget: form};
      if (form?.listeners.submit) return form.listeners.submit(event);
      const button = elements["#opc-setup-submit"];
      if (button?.listeners.click) {
        return button.listeners.click({currentTarget: button});
      }
      throw new Error("OPC setup primary action is not bound");
    },
    cancel: () => elements["#opc-setup-cancel"]?.listeners.click?.({
      currentTarget: elements["#opc-setup-cancel"]
    }),
    inspect: () => ({
      retryAttempts: allowanceVerificationRetryAttempts,
      retryTimer: allowanceVerificationRetryTimer !== null,
      retryInFlight: allowanceVerificationRetryInFlight,
      allowanceOperation: Boolean(allowanceOperation),
      pendingAllowance,
      uncertain: allowancePostSendUncertainIdentityId,
      recoveryBlocked: allowanceRecoveryBlocked,
      setupBlocked: opcSetupState.blocked,
      mismatchNotice: allowanceMismatchNotice,
      recoveryRecords: allowanceRecoveryRecords.map((record) => ({
        attempt_id: record.attempt_id,
        allowance_tx_hash: record.allowance_tx_hash,
        status: record.status
      })),
      networkApproval: {
        hidden: approvalButton.hidden,
        disabled: approvalButton.disabled
      },
      networkState: elements["#polygon-state"].textContent
    }),
    seedPendingAllowance: () => persistPendingAllowance({
      wallet_identity_id: identityId,
      network,
      token_address: token,
      spender_address: spender,
      allowance_tx_hash: transactionHash
    })
  };
'''
    javascript = ACCOUNT_CONSOLE_JS.removesuffix("})();\n") + test_hooks + hooks_extra + "})();\n"

    preamble = r'''
const scenario = __SCENARIO__;
const wallet = "0x" + "a".repeat(40);
const token = "0x" + "1".repeat(40);
const spender = "0x" + "2".repeat(40);
const network = "eip155:137";
const identityId = "wallet_identity_opc_setup";
const grantId = "grant_opc_setup";
const pairingId = "opc_pairing_setup";
const installationId = "opc_installation_setup";
const transactionHash = "0x" + "4".repeat(64);
const now = "2026-09-15T06:00:00.000Z";
const future = "2026-09-22T06:00:00.000Z";
const unknownAllowance = ["unknown", "unknown_new"].includes(scenario);
const cancelWalletChallenge = scenario === "cancel_wallet_challenge";
const replacementReadback = scenario === "replacement_readback";
const unverifiedNew = scenario === "new_unverified_insufficient";
const excessAllowance = scenario === "existing_excess";
const transferSelection = scenario === "new_transfer";
const summarySelection = scenario.startsWith("summary_");
const boundWalletMismatch = scenario === "bound_wallet_mismatch";
const pendingProviderRequest = scenario === "pending_provider_request";
const providerError = scenario === "provider_error";
const providerReject = scenario === "provider_reject";
const invalidSendResult = scenario === "invalid_send_result";
const lateAllowanceHash = ["late_allowance_hash", "late_allowance_hash_changed", "late_allowance_hash_never_ready"].includes(scenario);
const lateAllowanceRejection = [
  "late_allowance_rejected",
  "late_allowance_rejected_4900",
  "late_allowance_rejected_changed",
  "late_allowance_rejected_wallet_changed",
  "late_allowance_rejected_existing_hash",
  "late_allowance_rejected_cleanup_failure"
].includes(scenario);
const restoredUnknownLock = scenario === "restored_unknown_lock";
const existingExact = ["existing_exact", "discovered_lower_per_transaction", "discovered_lower_daily"].includes(scenario);
if ([pendingProviderRequest, providerError, providerReject, invalidSendResult, lateAllowanceHash, lateAllowanceRejection].some(Boolean)) {
  globalThis.__clinkProviderRequestTimeoutMs = 20;
}
if (scenario === "allowance_recovery" || lateAllowanceHash) {
  globalThis.__clinkAllowanceVerificationRetryDelayMs = 20;
}

Date.now = () => Date.parse(now);

const childText = (child) => child?.textContent ||
  (child?.children || []).map(childText).join("");
const makeElement = (extra = {}) => Object.assign({
  attributes: {},
  classList: {add() {}, remove() {}, toggle() {}},
  className: "",
  dataset: {},
  disabled: false,
  hidden: false,
  innerHTML: "",
  listeners: {},
  open: false,
  required: false,
  textContent: "",
  type: "",
  value: "",
  checked: false,
  children: [],
  addEventListener(type, listener) { this.listeners[type] = listener; },
  append(...children) {
    this.children.push(...children);
    this.textContent = this.children.map(childText).join("");
  },
  closest(selector) {
    if (selector === "[data-grant-action]") return this;
    if (selector === "[data-grant-id]") return this;
    return null;
  },
  querySelector(selector) {
    if (selector === "button") return this.submitButton || makeElement();
    return makeElement();
  },
  replaceChildren(...children) {
    this.children = children;
    this.textContent = this.children.map(childText).join("");
  },
  setAttribute(name, value) { this.attributes[name] = String(value); },
  removeAttribute(name) { delete this.attributes[name]; }
}, extra);

const elements = {};
const selectors = [
  "#page-status", "#page-eyebrow", "#page-heading", "#page-lede",
  "#wallet-state", "#wallet-details", "#permission-state", "#grant-details",
  "#audit-list", "#connect-wallet", "#cancel-wallet-selection",
  "#refresh-allowances", "#resume-wallet-disconnect", "#wallet-disconnect-state",
  "#refresh-audit", "#wallet-provider-options", "#wallet-account-options",
  "#wallet-selection-state", "#total-limit", "#transaction-limit", "#hourly-limit",
  "#daily-limit", "#expiry-days", "#trust-clink", "#trust-registry",
  "#notification-mode", "#permission-editor", "#permission-editor-label",
  "#new-limit-settings", "#permission-submit", "#limit-help", "#allowance-setup",
  "#allowance-setup-label", "#network-ledger", "#verify-pending-allowance",
  "#pending-allowance-state", "#wallet-session-dialog", "#wallet-session-qr",
  "#wallet-session-open", "#wallet-session-cancel", "#polygon-state",
  "#polygon-token", "#polygon-spender", "#embedded-authorization",
  "#embedded-state", "#embedded-notice", "#embedded-proof-state",
  "#embedded-mandate-state", "#embedded-approval-state", "#embedded-network",
  "#embedded-total-limit", "#embedded-hourly-limit", "#embedded-duration-days",
  "#embedded-current-expiry", "#embedded-permission-submit", "#embedded-plan",
  "#embedded-plan-terms", "#embedded-plan-allowance", "#embedded-plan-confirm",
  "#embedded-plan-cancel", "#embedded-plan-retry", "#embedded-approve",
  "#embedded-current-actions", "#embedded-revoke-warning",
  "#embedded-revoke-allowance", "#embedded-revoke-allowance-label",
  "#embedded-revoke-spending", "#embedded-pending-recovery",
  "#embedded-pending-recovery-state", "#embedded-verify-pending-allowance",
  "#embedded-approval-confirm", "#embedded-approval-confirm-text",
  "#embedded-approval-confirm-button", "#embedded-approval-cancel",
  "#opc-device-section", "#opc-device-state", "#opc-device-details",
  "#opc-device-grant", "#opc-device-status", "#opc-device-message",
  "#opc-refresh", "#opc-review-button", "#opc-sign-button", "#opc-cancel-button",
  "#opc-review", "#opc-exact-message", "#opc-recheck", "#opc-setup",
  "#opc-setup-state", "#opc-setup-heading", "#opc-setup-intro",
  "#opc-setup-device-summary", "#opc-setup-form", "#opc-setup-network",
  "#opc-setup-total", "#opc-setup-hourly", "#opc-setup-duration",
  "#opc-setup-marketplace", "#opc-setup-transfers",
  "#opc-setup-limits", "#opc-setup-allowance-help", "#opc-setup-review", "#opc-setup-submit",
  "#opc-setup-cancel", "#opc-setup-status", "#opc-setup-summary",
  "#opc-setup-details", "#opc-setup-technical", "#opc-setup-recovery",
  "#opc-setup-recovery-message", "#opc-setup-recover", "#opc-setup-revoke"
];
for (const selector of selectors) elements[selector] = makeElement();
const permissionButton = elements["#permission-submit"];
elements["#permission-form"] = makeElement({submitButton: permissionButton});
elements["#opc-setup-form"].querySelector = (selector) =>
  selector === "button" ? elements["#opc-setup-submit"] : makeElement();

const identity = {
  wallet_identity_id: identityId,
  wallet_address: boundWalletMismatch ? "0x" + "b".repeat(40) : wallet,
  status: cancelWalletChallenge || unverifiedNew ? "pending" : "active",
  verified_at: cancelWalletChallenge || unverifiedNew ? null : now
};
const grant = (overrides = {}) => {
  const values = {
    spending_grant_id: grantId,
    wallet_identity_id: identityId,
    agent_id: "hermes",
    status: "active",
    max_amount_usdc: "12.345678",
    per_transaction_limit_usdc: "1.234567",
    hourly_limit_usdc: "4.5",
    daily_limit_usdc: "12.345678",
    product_scopes: ["marketplace"],
    venue_scopes: ["clink_marketplace"],
    merchant_scopes: [],
    merchant_trust_scopes: ["clink_verified", "registry_verified"],
    notification_mode: "silent_under_limits",
    network_scopes: [network],
    asset_scopes: [token],
    starts_at: now,
    expires_at: future,
    limits_usdc: {
      per_transaction: "1.234567",
      rolling_hour: "4.5",
      daily: "12.345678",
      total: "12.345678"
    },
    used_usdc: {rolling_hour: "1.234567", daily: "1.234567", total: "1.234567"},
    reserved_usdc: {rolling_hour: "0", daily: "0", total: "0"},
    remaining_usdc: {rolling_hour: "11.111111", daily: "11.111111", total: "11.111111"}
  };
  return {
    ...values,
    limits_usdc: {...values.limits_usdc, ...(overrides.limits_usdc || {})},
    used_usdc: {...values.used_usdc, ...(overrides.used_usdc || {})},
    reserved_usdc: {...values.reserved_usdc, ...(overrides.reserved_usdc || {})},
    remaining_usdc: {...values.remaining_usdc, ...(overrides.remaining_usdc || {})},
    ...overrides
  };
};
const allowance = (observed) => ({
  asset_allowance_id: "asset_allowance_opc_setup",
  wallet_identity_id: identityId,
  network,
  token_address: token,
  token_symbol: "USDC",
  token_decimals: 6,
  spender_address: spender,
  approved_amount_atomic: String(observed),
  observed_allowance_atomic: String(observed),
  allowance_tx_hash: null,
  status: "active",
  confirmed_block: null,
  last_chain_check_at: now,
  created_at: now,
  updated_at: now
});

const existingFlow = [
      "existing_sufficient", "insufficient", "unknown", "allowance_recovery", "oversized_allowance",
      "replacement_readback", "approve_user_reject", "existing_excess", "provider_error",
      "provider_reject", "invalid_send_result", "late_allowance_hash", "late_allowance_hash_changed", "late_allowance_hash_never_ready", "pending_provider_request",
      "late_allowance_rejected", "late_allowance_rejected_4900", "late_allowance_rejected_changed",
      "late_allowance_rejected_wallet_changed", "late_allowance_rejected_existing_hash",
      "late_allowance_rejected_cleanup_failure", "restored_unknown_lock", "mismatch_submit", "mismatch_submit_history"
].includes(scenario);
const insufficientAllowance = [
      "insufficient", "allowance_recovery", "oversized_allowance", "approve_user_reject",
      "new_unverified_insufficient", "provider_error", "provider_reject", "invalid_send_result",
      "late_allowance_hash", "late_allowance_hash_changed", "late_allowance_hash_never_ready", "pending_provider_request",
      "late_allowance_rejected", "late_allowance_rejected_4900", "late_allowance_rejected_changed",
      "late_allowance_rejected_wallet_changed", "late_allowance_rejected_existing_hash",
      "late_allowance_rejected_cleanup_failure", "restored_unknown_lock", "mismatch_submit", "mismatch_submit_history"
].includes(scenario);
const mismatchSubmit = ["mismatch_submit", "mismatch_submit_history"].includes(scenario);
const currentGrant = existingFlow ? grant() : null;
const state = {
  wallet_identities: [identity],
  spending_grants: currentGrant ? [currentGrant] : [],
  current_spending_mandate: currentGrant,
  asset_allowances: [
    allowance(excessAllowance ? 100000000 : insufficientAllowance ? 1000000 :
      unknownAllowance ? 0 : 11111111)
  ],
  approval_targets: {
    [network]: {token_address: token, spender_address: spender}
  },
  network_configs: {
    [network]: {
      chain_id: 137,
      required_confirmations: 1,
      token_decimals: 6,
      token_symbol: "USDC"
    }
  },
  recent_audit_summary: [],
  allowance_recovery: [],
  readiness: {ready: false}
};

const bootstrap = {
  pairing: {
    pairing_id: pairingId,
    installation_id: installationId,
    label: "Synthetic OPC device",
    public_jwk_thumbprint: "synthetic-thumbprint",
    scope: "payments",
    agent_id: "hermes",
    status: existingFlow ? "active" : "pending",
    expires_at: future
  },
  network_configs: state.network_configs,
  approval_targets: state.approval_targets,
  defaults: {total_usdc: "20", hourly_usdc: "5", duration_days: 7}
};

let currentPairing = {
  ...bootstrap.pairing,
  consent_expires_at: "2026-10-15T06:00:00.000Z",
  wallet_identity_id: existingFlow ? identityId : null,
  spending_grant_id: existingFlow ? grantId : null
};
const calls = [];
const planRequests = [];
const planResults = [];
const grantRequests = [];
const personalSigns = [];
const providerMethods = [];
const verifyRequests = [];
let verifyAttempts = 0;
let accountReads = 0;
let pairingReads = 0;
let sendCount = 0;
let sendAttempts = 0;
let sentTransaction = null;
let grantSignaturePending = false;
let releaseGrantSignature = null;
let wrongReadback = false;
let walletChallengePending = false;
let releaseWalletChallenge = null;
let replacementApplied = false;
let recoveryMessageBefore = null;
let setupStageBefore = null;
let setupSubmitted = false;
let attemptBeginCount = 0;
let attemptSubmittedCount = 0;
let attemptRejectedCount = 0;
let allowanceAttempt = null;

const makeAllowanceAttempt = (payload, status = "awaiting_wallet", hash = null) => ({
  allowance_tx_hash: hash,
  amount_atomic: String(payload.amount_atomic),
  attempt_id: `allowance_attempt_${attemptBeginCount}`,
  created_at: now,
  next_check_at: status === "pending" ? future : null,
  network: payload.network,
  reason_code: null,
  spender_address: payload.spender_address,
  status,
  token_address: payload.token_address,
  updated_at: now,
  user_id: "user_opc_setup",
  wallet_identity_id: payload.wallet_identity_id
});

const termsFor = (payload) => {
  const products = Array.isArray(payload.products) && payload.products.length
    ? [...payload.products].sort() : ["marketplace"];
  const venues = products.map((product) => product === "transfers"
    ? "clink_transfers" : "clink_marketplace");
  if (payload.spending_grant_id) {
    const current = state.current_spending_mandate;
    return {
      wallet_identity_id: identityId,
      agent_id: "hermes",
      max_amount_usdc: current.max_amount_usdc,
      per_transaction_limit_usdc: current.per_transaction_limit_usdc,
      hourly_limit_usdc: current.hourly_limit_usdc,
      daily_limit_usdc: current.daily_limit_usdc,
      product_scopes: products,
      venue_scopes: venues,
      merchant_scopes: [...current.merchant_scopes],
      merchant_trust_scopes: [...current.merchant_trust_scopes],
      notification_mode: current.notification_mode,
      network_scopes: [...current.network_scopes],
      asset_scopes: [...current.asset_scopes],
      starts_at: current.starts_at,
      expires_at: current.expires_at,
      amends_spending_grant_id: current.spending_grant_id
    };
  }
  return {
    wallet_identity_id: identityId,
    agent_id: "hermes",
    max_amount_usdc: "20",
    per_transaction_limit_usdc: "5",
    hourly_limit_usdc: "5",
    daily_limit_usdc: "20",
    product_scopes: products,
    venue_scopes: venues,
    merchant_scopes: [],
    merchant_trust_scopes: ["clink_verified", "registry_verified"],
    notification_mode: "silent_under_limits",
    network_scopes: [network],
    asset_scopes: [token],
    starts_at: now,
    expires_at: "2026-09-22T06:00:00.000Z"
  };
};
const allowanceFor = () => {
  const insufficient = insufficientAllowance;
  const unknown = unknownAllowance;
  const oversized = scenario === "oversized_allowance";
  const existingAllowance = existingFlow || existingExact;
  const targetUsdc = oversized ? "100" : mismatchSubmit ? "20" : existingAllowance ? "11.111111" : "20";
  const targetAtomic = oversized ? "100000000" : mismatchSubmit ? "20000000" : existingAllowance ? "11111111" : "20000000";
  const requiredUsdc = mismatchSubmit ? "20" : existingExact ? "4.5" : existingAllowance ? "1.234567" : "5";
  return {
    status: unknown ? "unknown" : insufficient ? "insufficient" : "sufficient",
    required_usdc: requiredUsdc,
    target_usdc: targetUsdc,
      target_atomic: targetAtomic,
    observed_atomic: unknown ? null : String(excessAllowance ? 100000000 : insufficient ? 1000000 :
      existingAllowance ? 11111111 : 20000000),
    exceeds_budget: unknown ? null : excessAllowance,
    network,
    token_address: token,
    spender_address: spender,
    wallet_address: wallet,
    asset_allowance_id: "asset_allowance_opc_setup",
    observed_at: unknown ? null : now
  };
};
const response = (body, ok = true, status = 200) => ({
  ok, status,
  async json() { return body; }
});

const makeProvider = () => {
  const listeners = {};
  let chainId = "0x89";
  return {
    async request(request) {
      providerMethods.push(request.method);
      if (request.method === "eth_accounts" || request.method === "eth_requestAccounts") {
        if (pendingProviderRequest && request.method === "eth_accounts" && setupSubmitted) {
          await new Promise(() => {});
        }
        return [wallet];
      }
      if (request.method === "personal_sign") {
        const message = String(request.params[0]);
        personalSigns.push({message, address: request.params[1]});
        if (scenario === "cancel_signature" && message === "synthetic grant terms") {
          grantSignaturePending = true;
          await new Promise((resolve) => { releaseGrantSignature = resolve; });
        }
        return "0x" + "5".repeat(130);
      }
      if (request.method === "wallet_switchEthereumChain") {
        chainId = request.params[0].chainId;
        return null;
      }
      if (request.method === "eth_chainId") return chainId;
      if (request.method === "eth_call") return "0x0";
      if (request.method === "eth_sendTransaction") {
        sendAttempts += 1;
        if (scenario === "approve_user_reject" && sendAttempts === 1) {
          const error = new Error("User rejected the request");
          error.code = 4001;
          throw error;
        }
        if (providerReject) {
          const error = new Error("raw wallet rejection should not be shown");
          error.code = 4001;
          throw error;
        }
        if (providerError) {
          const error = new Error("provider secret should not be shown");
          error.code = 4900;
          throw error;
        }
        if (invalidSendResult) {
          sendCount += 1;
          sentTransaction = request.params[0];
          return "not-a-transaction-hash";
        }
        if (lateAllowanceRejection) {
          await new Promise((resolve) => setTimeout(resolve, 80));
          const error = new Error("late wallet provider response should stay private");
          error.code = scenario === "late_allowance_rejected_4900" ? 4900 : 4001;
          throw error;
        }
        if (lateAllowanceHash) {
          await new Promise((resolve) => setTimeout(resolve, 50));
        }
        sendCount += 1;
        sentTransaction = request.params[0];
        return transactionHash;
      }
      if (request.method === "eth_getTransactionReceipt") {
        return {blockNumber: "0x64", status: "0x1", transactionHash};
      }
      if (request.method === "eth_blockNumber") return "0x65";
      throw new Error(`Unexpected provider method ${request.method}`);
    },
    on(name, listener) { (listeners[name] ||= new Set()).add(listener); },
    removeListener(name, listener) { listeners[name]?.delete(listener); },
    emit(name, value) { for (const listener of [...(listeners[name] || [])]) listener(value); }
  };
};
const provider = makeProvider();

global.fetch = async (url, options = {}) => {
  const path = String(url);
  const method = options.method || "GET";
  const body = options.body || null;
  calls.push({url: path, method, body});
  if (path === "/account" && method === "GET") {
    accountReads += 1;
    if (existingExact && accountReads === 2) {
      const discovered = grant();
      discovered.per_transaction_limit_usdc = "4.5";
      discovered.limits_usdc.per_transaction = "4.5";
      if (scenario === "discovered_lower_per_transaction") {
        discovered.per_transaction_limit_usdc = "1";
        discovered.limits_usdc.per_transaction = "1";
      }
      if (scenario === "discovered_lower_daily") {
        discovered.daily_limit_usdc = "6";
        discovered.limits_usdc.daily = "6";
      }
      state.spending_grants = [discovered];
      state.current_spending_mandate = discovered;
      currentPairing = {
        ...currentPairing,
        status: "active",
        wallet_identity_id: identityId,
        spending_grant_id: grantId
      };
    }
    if (replacementReadback && accountReads >= 4 && planRequests.length >= 2 && !replacementApplied) {
      replacementApplied = true;
      const replacement = grant({spending_grant_id: "unexpected_replacement_grant"});
      state.spending_grants = [replacement];
      state.current_spending_mandate = replacement;
      currentPairing = {
        ...currentPairing,
        status: "active",
        wallet_identity_id: identityId,
        spending_grant_id: replacement.spending_grant_id
      };
    }
    return response(state);
  }
  if (path === "/account/opc/pairing" && method === "GET") {
    pairingReads += 1;
    return response({pairing: currentPairing});
  }
  if (path === "/account/authorization-plan" && method === "POST") {
    const payload = JSON.parse(body);
    planRequests.push(payload);
    const requestedProducts = Array.isArray(payload.products) && payload.products.length
      ? [...payload.products].sort() : ["marketplace"];
    const requestedVenues = requestedProducts.map((product) => product === "transfers"
      ? "clink_transfers" : "clink_marketplace");
    const current = payload.spending_grant_id ? state.current_spending_mandate : null;
    const scopeChanged = current && (
      JSON.stringify(current.product_scopes) !== JSON.stringify(requestedProducts) ||
      JSON.stringify(current.venue_scopes) !== JSON.stringify(requestedVenues)
    );
    const plan = {
      action: payload.spending_grant_id && !scopeChanged ? "none" : "sign",
      terms: termsFor(payload),
      allowance: allowanceFor()
    };
    planResults.push(plan);
    return response(plan);
  }
  if (path === "/account/grants" && method === "POST") {
    const payload = JSON.parse(body);
    grantRequests.push(payload);
    if (!payload.challenge_session_id) {
      return response({session_id: "grant_challenge", message_to_sign: "synthetic grant terms"});
    }
    if (scenario === "wrong_readback") {
      wrongReadback = true;
      const wrong = grant({max_amount_usdc: "19", limits_usdc: {
        per_transaction: "5", rolling_hour: "5", daily: "19", total: "19"
      }, remaining_usdc: {rolling_hour: "19", daily: "19", total: "19"}});
      state.spending_grants = [wrong];
      state.current_spending_mandate = wrong;
      currentPairing = {...currentPairing, status: "active", wallet_identity_id: identityId, spending_grant_id: grantId};
      return response(wrong);
    }
    if (scenario === "grant_response_lost") {
      return response({detail: "Signed grant response was lost"}, false, 503);
    }
    const requestedProducts = Array.isArray(payload.product_scopes) && payload.product_scopes.length
      ? [...payload.product_scopes].sort() : ["marketplace"];
    const requestedVenues = Array.isArray(payload.venue_scopes) && payload.venue_scopes.length
      ? [...payload.venue_scopes].sort() : ["clink_marketplace"];
    const created = grant({
      spending_grant_id: payload.amends_spending_grant_id || grantId,
      product_scopes: requestedProducts,
      venue_scopes: requestedVenues,
      max_amount_usdc: "20",
      per_transaction_limit_usdc: "5",
      hourly_limit_usdc: "5",
      daily_limit_usdc: "20",
      limits_usdc: {per_transaction: "5", rolling_hour: "5", daily: "20", total: "20"},
      used_usdc: {rolling_hour: "0", daily: "0", total: "0"},
      remaining_usdc: {rolling_hour: "5", daily: "20", total: "20"},
      expires_at: "2026-09-22T06:00:00.000Z"
    });
    state.spending_grants = [created];
    state.current_spending_mandate = created;
    currentPairing = {...currentPairing, status: "active", wallet_identity_id: identityId, spending_grant_id: grantId};
    return response(created, true, 201);
  }
  if (path === "/account/allowances/attempts" && method === "POST") {
    const payload = JSON.parse(body);
    attemptBeginCount += 1;
    allowanceAttempt = makeAllowanceAttempt(payload);
    return response({created: true, attempt: allowanceAttempt}, true, 201);
  }
  const submittedAttempt = path.match(/^\/account\/allowances\/attempts\/([^/]+)\/submitted$/);
  if (submittedAttempt && method === "POST") {
    const payload = JSON.parse(body);
    attemptSubmittedCount += 1;
    if (!allowanceAttempt || allowanceAttempt.attempt_id !== decodeURIComponent(submittedAttempt[1])) {
      return response({detail: "unknown allowance attempt"}, false, 404);
    }
    allowanceAttempt = {
      ...allowanceAttempt,
      allowance_tx_hash: payload.allowance_tx_hash,
      next_check_at: future,
      status: "pending",
      updated_at: now
    };
    return response(allowanceAttempt);
  }
  const rejectedAttempt = path.match(/^\/account\/allowances\/attempts\/([^/]+)\/rejected$/);
  if (rejectedAttempt && method === "POST") {
    attemptRejectedCount += 1;
    if (!allowanceAttempt || allowanceAttempt.attempt_id !== decodeURIComponent(rejectedAttempt[1])) {
      return response({detail: "unknown allowance attempt"}, false, 404);
    }
    allowanceAttempt = {
      ...allowanceAttempt,
      allowance_tx_hash: null,
      next_check_at: null,
      status: "rejected",
      updated_at: now
    };
    return response(allowanceAttempt);
  }
  if (path === "/account/allowances/verify" && method === "POST") {
    verifyAttempts += 1;
    verifyRequests.push(JSON.parse(body));
    if (scenario === "late_allowance_hash_never_ready" || ((scenario === "allowance_recovery" || lateAllowanceHash) && verifyAttempts === 1)) {
      return response({detail: "Core allowance verification is temporarily unavailable"}, false, 503);
    }
    const verifiedAtomic = unverifiedNew ? "20000000" : "11111111";
    state.asset_allowances[0] = {
      ...state.asset_allowances[0],
      approved_amount_atomic: verifiedAtomic,
      observed_allowance_atomic: verifiedAtomic,
      allowance_tx_hash: transactionHash,
      updated_at: now
    };
    return response(state.asset_allowances[0]);
  }
  if (path.endsWith("/wallet-challenge") && method === "POST") {
    if (cancelWalletChallenge) {
      walletChallengePending = true;
      await new Promise((resolve) => { releaseWalletChallenge = resolve; });
    }
    return response({session_id: "wallet_challenge", message_to_sign: "synthetic wallet proof"});
  }
  if (path.endsWith("/wallet-verify") && method === "POST") {
    identity.status = "active";
    return response(identity);
  }
  if (path.includes("/wallet-challenges/") && path.endsWith("/cancel") && method === "POST") {
    return response({});
  }
  return response({});
};

const windowListeners = {};
const storageValues = new Map();
const failUncertaintyCleanup = scenario === "late_allowance_rejected_cleanup_failure";
const sessionStorage = {
  get length() { return storageValues.size; },
  key(index) { return [...storageValues.keys()][index] ?? null; },
  getItem(key) { return storageValues.get(key) ?? null; },
  setItem(key, value) { storageValues.set(key, String(value)); },
  removeItem(key) {
    if (failUncertaintyCleanup && key.includes("allowance_post_send_uncertain")) return;
    storageValues.delete(key);
  }
};
if (restoredUnknownLock) {
  sessionStorage.setItem(
    `clink.account.allowance_post_send_uncertain.v1.${encodeURIComponent("/account")}.${identityId}`,
    "allowance_post_send_uncertain"
  );
}
global.document = {
  cookie: "clink_account_csrf=synthetic-csrf",
  body: {dataset: {accountView: "authorization", opcSetup: JSON.stringify(bootstrap)}},
  createElement(tagName) { return makeElement({tagName: String(tagName).toUpperCase()}); },
  querySelector(selector) {
    if (selector === `[data-approve-network="${network}"]`) return approvalButton;
    return elements[selector];
  },
  querySelectorAll(selector) {
    if (selector === "[data-approve-network]") return [approvalButton];
    if (selector === "[data-network-state]") return [elements["#polygon-state"]];
    if (selector === "[data-network-token], [data-network-spender]") {
      return [elements["#polygon-token"], elements["#polygon-spender"]];
    }
    if (selector === "#grant-details .grant-ledger") return [];
    return [];
  }
};
const approvalButton = makeElement({dataset: {approveNetwork: network}});
global.Event = class Event { constructor(type) { this.type = type; } };
global.window = {
  location: {origin: "https://clink.test", pathname: "/account"},
  sessionStorage,
      setTimeout(...args) {
        const timer = setTimeout(...args);
        if (!pendingProviderRequest) timer.unref?.();
        return timer;
      },
  clearTimeout,
  addEventListener(name, listener) { (windowListeners[name] ||= []).push(listener); },
  dispatchEvent(event) {
    if (event.type === "eip6963:requestProvider") {
      for (const listener of windowListeners["eip6963:announceProvider"] || []) {
        listener({detail: {info: {uuid: "synthetic-wallet", name: "Synthetic Wallet", rdns: "test.wallet"}, provider}});
      }
    }
    for (const listener of windowListeners[event.type] || []) listener(event);
  }
};

'''
    preamble = preamble.replace("__SCENARIO__", json.dumps(scenario))
    postamble = r'''
const tick = () => new Promise((resolve) => setTimeout(resolve, 0));
const waitUntil = async (predicate) => {
  for (let attempt = 0; attempt < 200; attempt += 1) {
    if (predicate()) return;
    await tick();
  }
  throw new Error("Timed out waiting for OPC setup harness condition: " + JSON.stringify({
    accountReads, pairingReads, pageStatus: elements["#page-status"].textContent,
    setupStatus: elements["#opc-setup-status"].textContent,
    selection: elements["#wallet-selection-state"].textContent
  }));
};

await waitUntil(() => elements["#wallet-provider-options"].children.some(
  (item) => item.listeners.click && item.dataset.providerUuid === "synthetic-wallet"
));
const providerButton = elements["#wallet-provider-options"].children.find(
  (item) => item.dataset.providerUuid === "synthetic-wallet"
);
await providerButton.listeners.click();
await waitUntil(() => elements["#wallet-account-options"].children.some(
  (item) => item.listeners.click && item.textContent === wallet
));
const accountButton = elements["#wallet-account-options"].children.find(
  (item) => item.listeners.click && item.textContent === wallet
);
await accountButton.listeners.click();
await waitUntil(() => accountReads > 0 && pairingReads > 0 &&
  elements["#opc-setup-form"].listeners.submit);

if (pendingProviderRequest) {
  await globalThis.__clinkOpcSetupTest.submit();
  await new Promise((resolve) => setTimeout(resolve, 200));
} else if (transferSelection) {
  elements["#opc-setup-marketplace"].checked = false;
  elements["#opc-setup-transfers"].checked = true;
}

if (summarySelection) {
  await tick();
  elements["#opc-setup-marketplace"].checked = scenario === "summary_combined";
  elements["#opc-setup-transfers"].checked = scenario !== "summary_empty";
  elements["#opc-setup-transfers"].listeners.change();
} else if (scenario === "cancel_signature") {
  const operation = globalThis.__clinkOpcSetupTest.submit();
  await waitUntil(() => grantSignaturePending);
  await globalThis.__clinkOpcSetupTest.cancel();
  releaseGrantSignature?.();
  await operation;
} else if (scenario === "cancel_wallet_challenge") {
  const operation = globalThis.__clinkOpcSetupTest.submit();
  await waitUntil(() => walletChallengePending);
  await globalThis.__clinkOpcSetupTest.cancel();
  releaseWalletChallenge?.();
  await operation;
} else if (scenario === "allowance_recovery") {
  await globalThis.__clinkOpcSetupTest.submit();
  setupStageBefore = elements["#opc-setup-status"].dataset.stage || null;
  await waitUntil(() => elements["#opc-setup-recovery"].hidden === false);
  const recoveryHiddenBefore = elements["#opc-setup-recovery"].hidden;
  const recover = elements["#opc-setup-recover"];
  if (!recover?.listeners.click) throw new Error("OPC setup recovery action is not bound");
  await recover.listeners.click({currentTarget: recover});
  await tick();
  globalThis.__clinkOpcSetupTest.recoveryHiddenBefore = recoveryHiddenBefore;
} else if (scenario === "grant_response_lost") {
  await globalThis.__clinkOpcSetupTest.submit();
  await waitUntil(() => elements["#opc-setup-recovery"].hidden === false);
  recoveryMessageBefore = elements["#opc-setup-recovery-message"].textContent;
  await globalThis.__clinkOpcSetupTest.submit();
  await tick();
} else if (scenario === "approve_user_reject") {
  await globalThis.__clinkOpcSetupTest.submit();
  await waitUntil(() => elements["#opc-setup-submit"].disabled === false);
  await globalThis.__clinkOpcSetupTest.submit();
} else if (existingExact) {
  elements["#opc-setup-total"].value = "12.345678";
  elements["#opc-setup-hourly"].value = "4.5";
  await globalThis.__clinkOpcSetupTest.submit();
} else if (lateAllowanceHash) {
  await globalThis.__clinkOpcSetupTest.submit();
  if (scenario === "late_allowance_hash_changed") {
    elements["#opc-setup-total"].value = "25";
    elements["#opc-setup-total"].listeners.change?.();
  }
  await new Promise((resolve) => setTimeout(resolve, 200));
} else if (lateAllowanceRejection) {
  await globalThis.__clinkOpcSetupTest.submit();
  if (scenario === "late_allowance_rejected_changed") {
    elements["#opc-setup-total"].value = "25";
    elements["#opc-setup-total"].listeners.change?.();
  } else if (scenario === "late_allowance_rejected_wallet_changed") {
    provider.emit("accountsChanged", ["0x" + "b".repeat(40)]);
  } else if (scenario === "late_allowance_rejected_existing_hash") {
    globalThis.__clinkOpcSetupTest.seedPendingAllowance();
  }
  await new Promise((resolve) => setTimeout(resolve, 200));
} else if (scenario === "duplicate_submit") {
  const first = globalThis.__clinkOpcSetupTest.submit();
  const second = globalThis.__clinkOpcSetupTest.submit();
  await Promise.all([first, second]);
} else {
  await globalThis.__clinkOpcSetupTest.submit();
}
await tick();

const grantBodies = grantRequests.map((item) => ({
  hasChallenge: Boolean(item.challenge_session_id),
  opcPairingId: item.opc_pairing_id || null,
  total: item.max_amount_usdc || null,
  hourly: item.hourly_limit_usdc || null
}));
const setupStatus = elements["#opc-setup-status"].textContent;
const setupState = elements["#opc-setup-state"].textContent;
const setupStage = elements["#opc-setup-status"].dataset.stage || null;
const allowanceApproval = sentTransaction ? {
  from: sentTransaction.from,
  to: sentTransaction.to,
  chainId: sentTransaction.chainId,
  amountAtomic: BigInt("0x" + sentTransaction.data.slice(-64)).toString(),
  data: sentTransaction.data
} : null;
console.log(JSON.stringify({
  scenario,
  setupState,
  setupStatus,
  setupStage,
  setupStageBefore,
  selectedSetupNetwork: elements["#opc-setup-network"]?.value || null,
  allowanceHelp: elements["#opc-setup-allowance-help"]?.textContent || null,
  inspect: globalThis.__clinkOpcSetupTest.inspect?.() ?? null,
  setupSummary: elements["#opc-setup-summary"].textContent,
  recoveryHidden: elements["#opc-setup-recovery"].hidden,
  recoveryMessage: elements["#opc-setup-recovery-message"].textContent,
  recoveryMessageBefore,
  recoveryHiddenBefore: globalThis.__clinkOpcSetupTest.recoveryHiddenBefore ?? null,
  accountReads,
  pairingReads,
  planRequests,
  planResults,
  grantBodies,
  personalSigns,
  providerMethods,
  calls,
  sendCount,
  sendAttempts,
  allowanceApproval,
  verifyRequests,
  verifyAttempts,
  attemptBeginCount,
  attemptSubmittedCount,
  attemptRejectedCount,
  allowanceAttempt,
  finalPairing: currentPairing,
  finalGrant: state.current_spending_mandate,
  wrongReadback,
  replacementApplied,
  storageKeys: [...storageValues.keys()]
}));
'''
    if postamble_extra:
        postamble = postamble.replace(
            "if (summarySelection) {",
            "if (true) {\n" + postamble_extra + "\n} else if (summarySelection) {",
            1,
        )
    script = preamble + preamble_extra + javascript + postamble
    result = subprocess.run(
        ["node", "--input-type=module", "-"],
        input=script,
        check=False,
        capture_output=True,
        text=True,
        timeout=20,
    )
    assert result.returncode == 0, result.stderr or result.stdout
    return json.loads(result.stdout)


def _mutation_paths(result: dict) -> list[str]:
    return [
        call["url"]
        for call in result["calls"]
        if call["method"] == "POST"
        and any(marker in call["url"] for marker in ("/grants", "/allowances/verify", "/wallet-challenge"))
    ]


def test_new_verified_wallet_uses_real_terms_and_one_combined_grant_signature() -> None:
    result = _run_setup_flow("new_sufficient")

    assert result["setupState"] == "Saved"
    assert len(result["planRequests"]) == 2
    assert [plan["action"] for plan in result["planResults"]] == ["sign", "none"]
    assert "amends_spending_grant_id" not in result["planResults"][0]["terms"]
    assert result["planResults"][0]["terms"] == {
        "wallet_identity_id": IDENTITY_ID,
        "agent_id": "hermes",
        "max_amount_usdc": "20",
        "per_transaction_limit_usdc": "5",
        "hourly_limit_usdc": "5",
        "daily_limit_usdc": "20",
        "product_scopes": ["marketplace"],
        "venue_scopes": ["clink_marketplace"],
        "merchant_scopes": [],
        "merchant_trust_scopes": ["clink_verified", "registry_verified"],
        "notification_mode": "silent_under_limits",
        "network_scopes": [NETWORK],
        "asset_scopes": [TOKEN],
        "starts_at": "2026-09-15T06:00:00.000Z",
        "expires_at": "2026-09-22T06:00:00.000Z",
    }
    assert result["planResults"][1]["terms"]["amends_spending_grant_id"] == GRANT_ID
    assert result["grantBodies"] == [
        {"hasChallenge": False, "opcPairingId": PAIRING_ID, "total": "20", "hourly": "5"},
        {"hasChallenge": True, "opcPairingId": PAIRING_ID, "total": "20", "hourly": "5"},
    ]
    assert len(result["personalSigns"]) == 1
    assert result["personalSigns"][0]["message"] == "synthetic grant terms"
    assert result["finalPairing"]["status"] == "active"
    assert result["finalPairing"]["spending_grant_id"] == GRANT_ID
    assert result["sendCount"] == 0
    assert not any("/wallet-challenge" in path for path in _mutation_paths(result))
    assert not any(
        "purchase" in call["url"] or "payment" in call["url"]
        for call in result["calls"]
    )


def test_new_transfer_choice_is_signed_and_read_back_exactly() -> None:
    result = _run_setup_flow("new_transfer")

    assert result["setupState"] == "Saved"
    assert result["planResults"][0]["terms"]["product_scopes"] == ["transfers"]
    assert result["planResults"][0]["terms"]["venue_scopes"] == ["clink_transfers"]
    assert result["finalGrant"]["product_scopes"] == ["transfers"]
    assert result["finalGrant"]["venue_scopes"] == ["clink_transfers"]
    assert "transfers" in result["setupSummary"]
    assert len(result["personalSigns"]) == 1


@pytest.mark.parametrize("scenario,expected,excluded", [
    ("summary_transfer", "transfers", "marketplace"),
    ("summary_combined", "marketplace, transfers", None),
    ("summary_empty", "No product selected", "marketplace"),
])
def test_product_summary_updates_before_any_wallet_signature(scenario, expected, excluded):
    result = _run_setup_flow(scenario)
    assert expected in result["setupSummary"]
    if excluded:
        assert excluded not in result["setupSummary"]
    assert result["personalSigns"] == []
    assert result["planRequests"] == []


def test_existing_active_grant_and_device_skip_signatures_when_allowance_is_sufficient() -> None:
    result = _run_setup_flow("existing_sufficient")

    assert result["setupState"] == "Saved"
    assert [plan["action"] for plan in result["planResults"]] == ["none", "none"]
    assert [plan["terms"]["amends_spending_grant_id"] for plan in result["planResults"]] == [
        GRANT_ID,
        GRANT_ID,
    ]
    assert result["personalSigns"] == []
    assert result["grantBodies"] == []
    assert result["sendCount"] == 0
    assert not any("/opc/pairings/" in call["url"] and call["method"] == "POST" for call in result["calls"])
    assert result["finalGrant"]["spending_grant_id"] == GRANT_ID
    assert result["finalGrant"]["limits_usdc"]["total"] == "12.345678"


def test_insufficient_allowance_uses_exact_decimal_unspent_atomic_target() -> None:
    result = _run_setup_flow("insufficient")

    assert result["setupState"] == "Saved"
    assert result["personalSigns"] == []
    assert result["grantBodies"] == []
    assert result["sendCount"] == 1
    assert result["allowanceApproval"] == {
        "from": WALLET,
        "to": TOKEN,
        "chainId": "0x89",
        "amountAtomic": "11111111",
        "data": result["allowanceApproval"]["data"],
    }
    assert result["allowanceApproval"]["amountAtomic"] == "11111111"
    assert result["verifyRequests"] == [{
        "wallet_identity_id": IDENTITY_ID,
        "network": NETWORK,
        "token_address": TOKEN,
        "spender_address": SPENDER,
        "allowance_tx_hash": TX_HASH,
    }]


def test_unknown_allowance_stops_before_signature_or_chain_transaction() -> None:
    for scenario in ("unknown", "unknown_new"):
        result = _run_setup_flow(scenario)

        assert result["setupState"] != "Saved"
        assert "unknown" in result["setupStatus"].lower()
        assert result["personalSigns"] == []
        assert result["grantBodies"] == []
        assert result["sendCount"] == 0
        assert result["verifyRequests"] == []
        assert "eth_sendTransaction" not in result["providerMethods"]
        assert not any(call["method"] == "POST" and "/grants" in call["url"] for call in result["calls"])
        if scenario == "unknown_new":
            assert result["planResults"][0]["action"] == "sign"


def test_cancel_during_wallet_challenge_posts_no_signature_or_verify() -> None:
    result = _run_setup_flow("cancel_wallet_challenge")

    assert result["setupState"] != "Saved"
    assert result["personalSigns"] == []
    assert not any(
        call["method"] == "POST" and call["url"].endswith("/wallet-verify")
        for call in result["calls"]
    )
    assert result["grantBodies"] == []
    assert result["sendCount"] == 0
    assert result["verifyRequests"] == []


def test_cancel_during_grant_signature_posts_no_later_mutation() -> None:
    result = _run_setup_flow("cancel_signature")

    assert result["setupState"] != "Saved"
    assert len(result["grantBodies"]) == 1
    assert result["grantBodies"][0]["hasChallenge"] is False
    assert result["personalSigns"] == [{"message": "synthetic grant terms", "address": WALLET}]
    assert result["sendCount"] == 0
    assert result["verifyRequests"] == []
    assert not any(call["method"] == "POST" and "/opc/installations/approve" in call["url"] for call in result["calls"])


def test_wrong_grant_terms_readback_never_reports_success() -> None:
    result = _run_setup_flow("wrong_readback")

    assert result["setupState"] != "Saved"
    assert result["wrongReadback"] is True
    assert len(result["grantBodies"]) == 2
    assert result["personalSigns"] == [{"message": "synthetic grant terms", "address": WALLET}]
    assert result["sendCount"] == 0
    assert result["verifyRequests"] == []
    assert "exact spending authorization" in result["setupStatus"].lower()


def test_duplicate_primary_submission_runs_only_one_authorization_operation() -> None:
    result = _run_setup_flow("duplicate_submit")

    assert result["setupState"] == "Saved"
    assert len(result["grantBodies"]) == 2
    assert result["personalSigns"] == [{"message": "synthetic grant terms", "address": WALLET}]
    assert result["sendCount"] == 0
    assert len([payload for payload in result["planRequests"] if not payload.get("spending_grant_id")]) == 1


def test_allowance_target_over_budget_fails_closed_before_chain_send() -> None:
    result = _run_setup_flow("oversized_allowance")

    assert result["setupState"] != "Saved"
    assert "budget" in result["setupStatus"].lower()
    assert result["sendCount"] == 0
    assert result["verifyRequests"] == []
    assert result["personalSigns"] == []


def test_failed_allowance_verification_recovers_without_resending_transaction() -> None:
    result = _run_setup_flow("allowance_recovery")

    assert result["recoveryHiddenBefore"] is False
    assert result["recoveryHidden"] is True
    assert result["verifyAttempts"] == 2
    assert len(result["verifyRequests"]) == 2
    assert result["sendCount"] == 1
    assert result["setupState"] != "Saved"


def test_final_readback_rejects_replacement_grant_even_when_terms_match() -> None:
    result = _run_setup_flow("replacement_readback")

    assert result["replacementApplied"] is True
    assert result["setupState"] != "Saved"
    assert result["finalGrant"]["spending_grant_id"] == "unexpected_replacement_grant"
    assert result["finalPairing"]["spending_grant_id"] == "unexpected_replacement_grant"
    assert result["sendCount"] == 0


def test_uncertain_grant_submit_keeps_recovery_lock_without_resigning() -> None:
    result = _run_setup_flow("grant_response_lost")

    assert result["recoveryMessageBefore"]
    assert "uncertain" in result["recoveryMessageBefore"].lower()
    assert result["recoveryHidden"] is False
    assert len(result["grantBodies"]) == 2
    assert result["personalSigns"] == [{"message": "synthetic grant terms", "address": WALLET}]
    assert result["sendCount"] == 0


def test_user_rejected_allowance_transaction_can_retry_without_uncertain_lock() -> None:
    result = _run_setup_flow("approve_user_reject")

    assert result["sendAttempts"] == 2
    assert result["sendCount"] == 1
    assert result["setupState"] == "Saved"
    assert result["recoveryHidden"] is True
    assert not any("allowance_post_send_uncertain" in key for key in result["storageKeys"])


def test_unverified_new_wallet_runs_proof_grant_and_one_twenty_usdc_approval() -> None:
    result = _run_setup_flow("new_unverified_insufficient")

    assert result["setupState"] == "Saved"
    assert result["personalSigns"] == [
        {"message": "synthetic wallet proof", "address": WALLET},
        {"message": "synthetic grant terms", "address": WALLET},
    ]
    assert len([call for call in result["calls"] if call["url"].endswith("/wallet-challenge")]) == 1
    assert len([call for call in result["calls"] if call["url"].endswith("/wallet-verify")]) == 1
    assert result["grantBodies"] == [
        {"hasChallenge": False, "opcPairingId": PAIRING_ID, "total": "20", "hourly": "5"},
        {"hasChallenge": True, "opcPairingId": PAIRING_ID, "total": "20", "hourly": "5"},
    ]
    assert result["sendCount"] == 1
    assert result["sendAttempts"] == 1
    assert result["allowanceApproval"]["amountAtomic"] == "20000000"
    assert result["allowanceApproval"]["from"] == WALLET
    assert result["allowanceApproval"]["to"] == TOKEN
    assert result["allowanceApproval"]["chainId"] == "0x89"
    assert result["verifyRequests"] == [{
        "wallet_identity_id": IDENTITY_ID,
        "network": NETWORK,
        "token_address": TOKEN,
        "spender_address": SPENDER,
        "allowance_tx_hash": TX_HASH,
    }]
    assert not any(
        call["method"] == "POST" and "/opc/pairings/" in call["url"]
        for call in result["calls"]
    )
    assert result["finalPairing"]["status"] == "active"
    assert result["finalPairing"]["spending_grant_id"] == GRANT_ID


def test_existing_excess_allowance_is_persistently_disclosed_in_final_summary() -> None:
    result = _run_setup_flow("existing_excess")

    assert result["setupState"] == "Saved"
    assert result["personalSigns"] == []
    assert result["sendCount"] == 0
    summary = result["setupSummary"].lower()
    assert "shared allowance" in summary
    assert "not reduced automatically" in summary
