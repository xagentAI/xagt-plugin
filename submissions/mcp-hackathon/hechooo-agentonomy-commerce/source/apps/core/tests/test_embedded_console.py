from __future__ import annotations

import json
import subprocess

from services.account_service.console import (
    ACCOUNT_CONSOLE_CSS,
    ACCOUNT_CONSOLE_HTML,
    ACCOUNT_CONSOLE_JS,
)


def _run_embedded_console(scenario: str) -> dict:
    test_hooks = r'''globalThis.__clinkEmbeddedTest = {
  submit: () => elements["#embedded-permission-form"].listeners.submit({
    preventDefault() {},
    currentTarget: elements["#embedded-permission-form"]
  }),
  confirmGrant: () => elements["#embedded-plan-confirm"].listeners.click({
    currentTarget: elements["#embedded-plan-confirm"]
  }),
  cancelPlan: () => elements["#embedded-plan-cancel"].listeners.click({
    currentTarget: elements["#embedded-plan-cancel"]
  }),
  approve: () => elements["#embedded-approve"].listeners.click({
    currentTarget: elements["#embedded-approve"]
  }),
  confirmApproval: () => elements["#embedded-approval-confirm-button"].listeners.click({
    currentTarget: elements["#embedded-approval-confirm-button"]
  }),
  retry: () => elements["#embedded-plan-retry"].listeners.click({
    currentTarget: elements["#embedded-plan-retry"]
  }),
  verifyRecovery: () => elements["#embedded-verify-pending-allowance"].listeners.click({
    currentTarget: elements["#embedded-verify-pending-allowance"]
  }),
  reload: () => loadState(),
  revoke: () => elements["#embedded-revoke-spending"].listeners.click({
    currentTarget: elements["#embedded-revoke-spending"]
  })
};
'''
    javascript = ACCOUNT_CONSOLE_JS.removesuffix("})();\n") + test_hooks + "})();\n"
    harness = f"""
const scenario = {json.dumps(scenario)};
const wallet = "0x" + "a".repeat(40);
const token = "0x" + "1".repeat(40);
const spender = "0x" + "2".repeat(40);
const txHash = "0x" + "3".repeat(64);
const planTerms = {{
  wallet_identity_id: "wallet_identity_1",
  agent_id: "hermes",
  max_amount_usdc: "100",
  per_transaction_limit_usdc: "10",
  hourly_limit_usdc: "10",
  daily_limit_usdc: "100",
  product_scopes: ["marketplace"],
  venue_scopes: ["clink_marketplace"],
  merchant_scopes: [],
  merchant_trust_scopes: ["clink_verified"],
  notification_mode: "silent_under_limits",
  network_scopes: ["eip155:137"],
  asset_scopes: [token],
  starts_at: "2026-09-10T12:00:00Z",
  expires_at: "2026-10-10T12:00:00Z"
}};
const currentMandate = {{
  spending_grant_id: "grant_created",
  wallet_identity_id: "wallet_identity_1",
  agent_id: "hermes",
  status: scenario === "paused-current" ? "paused" : "active",
  max_amount_usdc: "100",
  per_transaction_limit_usdc: "10",
  hourly_limit_usdc: "10",
  daily_limit_usdc: "100",
  product_scopes: ["marketplace"],
  venue_scopes: ["clink_marketplace"],
  merchant_scopes: [],
  merchant_trust_scopes: ["clink_verified"],
  notification_mode: "silent_under_limits",
  network_scopes: ["eip155:137"],
  asset_scopes: [token],
  starts_at: "2026-09-10T12:00:00Z",
  expires_at: "2026-10-10T12:00:00Z",
  limits_usdc: {{per_transaction: "10", rolling_hour: "10", daily: "100", total: "100"}},
  used_usdc: {{rolling_hour: "0", daily: "0", total: "0"}},
  reserved_usdc: {{rolling_hour: "0", daily: "0", total: "0"}},
  remaining_usdc: {{rolling_hour: "10", daily: "100", total: "100"}}
}};
const recoveryAllowance = {{
  asset_allowance_id: "asset_allowance_recovery",
  wallet_identity_id: "wallet_identity_1",
  network: "eip155:137",
  token_address: token,
  token_symbol: "USDC",
  spender_address: spender,
  approved_amount_atomic: "50000000",
  observed_allowance_atomic: "50000000",
  status: "active"
}};
const state = {{
  wallet_identities: [{{
    wallet_identity_id: "wallet_identity_1",
    wallet_address: wallet,
    status: "active",
    verified_at: "2026-09-10T12:00:00Z"
  }}],
  spending_grants: ["approval-cancel", "approval-bad-observed", "paused-current"].includes(scenario) ? [currentMandate] : [],
  current_spending_mandate: ["approval-cancel", "approval-bad-observed", "paused-current"].includes(scenario) ? currentMandate : null,
  asset_allowances: scenario === "revoke-recovery" ? [recoveryAllowance] : [],
  approval_targets: {{
    "eip155:137": {{token_address: token, spender_address: spender}}
  }},
  network_configs: {{
    "eip155:137": {{
      chain_id: 137,
      required_confirmations: 1,
      token_decimals: 6,
      token_symbol: "USDC"
    }}
  }},
  recent_audit_summary: [],
  allowance_recovery: [],
  readiness: {{ready: false}}
}};
if (["multi-network", "approval-response-lost", "revoke-cancel", "revoke-response-lost", "revoke-other-target"].includes(scenario)) {{
  state.current_spending_mandate = currentMandate;
  state.spending_grants = [currentMandate];
}}
if (["revoke-cancel", "revoke-response-lost", "revoke-uncertain", "revoke-other-target"].includes(scenario)) {{
  state.asset_allowances = [recoveryAllowance];
}}
if (scenario === "revoke-uncertain" || scenario === "revoke-other-target") {{
  state.asset_allowances.unshift({{...recoveryAllowance, asset_allowance_id:"old_allowance", spender_address:"0x" + "9".repeat(40), observed_allowance_atomic:"0", status:"revoked"}});
}}
if (scenario === "multi-network") {{
  currentMandate.network_scopes.push("eip155:8453");
  state.network_configs["eip155:8453"] = {{...state.network_configs["eip155:137"], chain_id:8453}};
  state.approval_targets["eip155:8453"] = {{token_address:token, spender_address:spender}};
}}
const plan = {{
  action: (scenario === "noop" || scenario === "large" || scenario === "approval-cancel" || scenario === "approval-bad-observed" || scenario === "approval-response-lost" || scenario === "paused-current") ? "none" : "sign",
  terms: planTerms,
  allowance: {{
    status: scenario === "unknown" ? "unknown" : (scenario === "sufficient" || scenario === "large") ? "sufficient" : "insufficient",
    required_usdc: "10",
    target_usdc: scenario === "spent" ? "60" : "100",
    target_atomic: scenario === "spent" ? "60000000" : "100000000",
    observed_atomic: scenario === "unknown" ? null : scenario === "large" ? "200000000" : "0",
    exceeds_budget: scenario === "large",
    network: "eip155:137",
    token_address: token,
    spender_address: spender,
    wallet_address: wallet,
    asset_allowance_id: null,
    observed_at: null
  }}
}};
const elements = {{}};
const makeElement = (extra = {{}}) => Object.assign({{
  attributes: {{}},
  classList: {{add() {{}}, remove() {{}}, toggle() {{}}}},
  className: "",
  dataset: {{}},
  disabled: false,
  children: [],
  hidden: false,
  innerHTML: "",
  listeners: {{}},
  open: false,
  textContent: "",
  value: "",
  checked: false,
  addEventListener(type, listener) {{ this.listeners[type] = listener; }},
  append(...children) {{ this.children.push(...children); }},
  closest(selector) {{
    if (selector === "[data-grant-action]") return this;
    if (selector === "[data-grant-id]") return this;
    return null;
  }},
  querySelector(selector) {{
    if (selector === "button") return this.submitButton || makeElement();
    return makeElement();
  }},
  replaceChildren(...children) {{ this.children = children; }},
  setAttribute(name, value) {{ this.attributes[name] = String(value); }},
  removeAttribute(name) {{ delete this.attributes[name]; }}
}}, extra);

for (const selector of [
  "#page-eyebrow", "#page-heading", "#page-lede", "#page-status", "#wallet-state", "#wallet-details", "#permission-state",
  "#grant-details", "#audit-list", "#connect-wallet",
  "#cancel-wallet-selection", "#refresh-allowances", "#resume-wallet-disconnect",
  "#wallet-disconnect-state", "#refresh-audit", "#wallet-provider-options",
  "#wallet-account-options", "#wallet-selection-state", "#total-limit",
  "#polygon-state", "#polygon-token", "#polygon-spender", "#base-state", "#base-token", "#base-spender",
  "#transaction-limit", "#hourly-limit", "#daily-limit", "#expiry-days",
  "#trust-clink", "#trust-registry", "#notification-mode", "#permission-editor",
  "#permission-editor-label", "#new-limit-settings", "#permission-submit",
  "#limit-help", "#allowance-setup", "#allowance-setup-label", "#network-ledger",
  "#verify-pending-allowance", "#pending-allowance-state", "#wallet-session-dialog",
  "#wallet-session-qr", "#wallet-session-open", "#wallet-session-cancel",
  "#embedded-authorization", "#embedded-state", "#embedded-network", "#embedded-total-limit",
  "#embedded-hourly-limit", "#embedded-duration-days", "#embedded-current-expiry",
  "#embedded-permission-form", "#embedded-permission-submit", "#embedded-plan", "#embedded-plan-terms",
  "#embedded-plan-allowance", "#embedded-plan-confirm", "#embedded-plan-cancel",
  "#embedded-plan-retry", "#embedded-approve", "#embedded-approval-confirm",
  "#embedded-current-actions", "#embedded-revoke-warning", "#embedded-revoke-allowance",
  "#embedded-revoke-spending", "#embedded-pending-recovery", "#embedded-pending-recovery-state",
  "#embedded-verify-pending-allowance",
  "#embedded-approval-confirm-button", "#embedded-approval-cancel",
  "#embedded-proof-state", "#embedded-mandate-state", "#embedded-approval-state",
  "#embedded-notice"
]) elements[selector] = makeElement();
elements["#permission-form"] = makeElement({{submitButton: elements["#permission-submit"]}});
elements["#embedded-permission-form"].submitButton = elements["#embedded-plan-confirm"];
elements["#embedded-network"].value = "eip155:137";
elements["#embedded-total-limit"].value = "100";
elements["#embedded-hourly-limit"].value = "10";
elements["#embedded-duration-days"].value = "7";

const providerListeners = {{}};
let sendTransactions = 0;
const provider = {{
  async request(request) {{
    if (request.method === "eth_accounts" || request.method === "eth_requestAccounts") return [wallet];
    if (request.method === "eth_chainId") return "0x89";
    if (request.method === "wallet_switchEthereumChain") {{
      if (scenario === "approval-cancel" || scenario === "revoke-cancel") {{
        elements["#embedded-approval-cancel"].listeners.click({{currentTarget: elements["#embedded-approval-cancel"]}});
        await new Promise((resolve) => setTimeout(resolve, 10));
      }}
      return null;
    }}
    if (request.method === "personal_sign") {{
      if (scenario === "cancel-late") {{
        elements["#embedded-plan-cancel"].listeners.click({{currentTarget: elements["#embedded-plan-cancel"]}});
        await new Promise((resolve) => setTimeout(resolve, 10));
      }}
      return "0x" + "4".repeat(130);
    }}
    if (request.method === "eth_sendTransaction") {{
      sendTransactions += 1;
      if (scenario === "approval-response-lost" || scenario === "revoke-response-lost") throw new Error("provider response lost after submission");
      if (scenario === "approval-bad-observed") {{
        plan.allowance.status = "sufficient";
        plan.allowance.exceeds_budget = false;
        plan.allowance.observed_atomic = "90000000";
      }}
      return txHash;
    }}
    if (request.method === "eth_getTransactionReceipt") return {{blockNumber: "0x10"}};
    if (request.method === "eth_blockNumber") return "0x10";
    throw new Error(`Unexpected provider method ${{request.method}}`);
  }},
  on(name, listener) {{ (providerListeners[name] ||= new Set()).add(listener); }},
  removeListener(name, listener) {{ providerListeners[name]?.delete(listener); }}
}};

const response = (body, ok = true, status = 200) => ({{
  ok, status,
  async json() {{ return body; }}
}});
const calls = [];
let planCalls = 0;
let signedGrantPosts = 0;
let attemptBeginCount = 0;
let attemptSubmittedCount = 0;
let attemptRejectedCount = 0;
let allowanceAttempt = null;

const makeAllowanceAttempt = (payload, status = "awaiting_wallet", hash = null) => ({{
  allowance_tx_hash: hash,
  amount_atomic: String(payload.amount_atomic),
  attempt_id: `embedded_allowance_attempt_${{attemptBeginCount}}`,
  created_at: "2026-09-10T12:00:00Z",
  next_check_at: status === "pending" ? "2026-10-10T12:00:00Z" : null,
  network: payload.network,
  reason_code: null,
  spender_address: payload.spender_address,
  status,
  token_address: payload.token_address,
  updated_at: "2026-09-10T12:00:00Z",
  user_id: "user_embedded",
  wallet_identity_id: payload.wallet_identity_id
}});
global.fetch = async (url, options = {{}}) => {{
  calls.push({{url, options}});
  if (url === "/account" && (!options.headers || !options.headers.Accept)) return response(state);
  if (url === "/account") return response(state);
  if (url === "/account/authorization-plan") {{
    planCalls += 1;
    if (scenario === "malformed") return response({{action: "sign"}});
    return response(plan);
  }}
  if (url === "/account/allowances/attempts" && options.method === "POST") {{
    const payload = JSON.parse(options.body);
    attemptBeginCount += 1;
    allowanceAttempt = makeAllowanceAttempt(payload);
    return response({{created: true, attempt: allowanceAttempt}}, true, 201);
  }}
  const submittedAttempt = url.match(/^\/account\/allowances\/attempts\/([^/]+)\/submitted$/);
  if (submittedAttempt && options.method === "POST") {{
    const payload = JSON.parse(options.body);
    attemptSubmittedCount += 1;
    if (!allowanceAttempt || allowanceAttempt.attempt_id !== decodeURIComponent(submittedAttempt[1])) {{
      return response({{detail: "unknown allowance attempt"}}, false, 404);
    }}
    allowanceAttempt = {{
      ...allowanceAttempt,
      allowance_tx_hash: payload.allowance_tx_hash,
      next_check_at: "2026-10-10T12:00:00Z",
      status: "pending",
      updated_at: "2026-09-10T12:00:00Z"
    }};
    return response(allowanceAttempt);
  }}
  const rejectedAttempt = url.match(/^\/account\/allowances\/attempts\/([^/]+)\/rejected$/);
  if (rejectedAttempt && options.method === "POST") {{
    attemptRejectedCount += 1;
    if (!allowanceAttempt || allowanceAttempt.attempt_id !== decodeURIComponent(rejectedAttempt[1])) {{
      return response({{detail: "unknown allowance attempt"}}, false, 404);
    }}
    allowanceAttempt = {{
      ...allowanceAttempt,
      allowance_tx_hash: null,
      next_check_at: null,
      status: "rejected",
      updated_at: "2026-09-10T12:00:00Z"
    }};
    return response(allowanceAttempt);
  }}
  if (url === "/account/allowances/asset_allowance_recovery/refresh" || url === "/account/allowances/old_allowance/refresh") {{
    const record = url.includes("old_allowance") ? state.asset_allowances[0] : recoveryAllowance;
    return response({{
      ...record,
      wallet_identity_id: "wallet_identity_1",
      network: "eip155:137",
      token_address: token,
      spender_address: record.spender_address,
      observed_allowance_atomic: scenario.startsWith("revoke-cancel") || scenario === "revoke-response-lost" ? "50000000" : "0",
      status: scenario.startsWith("revoke-cancel") || scenario === "revoke-response-lost" ? "active" : "revoked"
    }});
  }}
  if (url === "/account/grants/grant_created/revoke") {{
    state.current_spending_mandate = null;
    state.spending_grants = [];
    return response({{status:"revoked"}});
  }}
  if (url === "/account/grants" && options.method === "POST") {{
    const body = options.body ? JSON.parse(options.body) : {{}};
    if (!body.challenge_session_id) return response({{
      session_id: "grant_challenge",
      message_to_sign: "Sign this grant"
    }});
    signedGrantPosts += 1;
    if (scenario === "grant-response-lost") {{
      state.current_spending_mandate = currentMandate;
      state.spending_grants = [currentMandate];
      plan.action = "none";
      throw new Error("signed grant response lost");
    }}
    return response({{}});
  }}
  if (url === "/account/grants") return response({{}});
  return response({{}});
}};

global.document = {{
  cookie: "clink_account_csrf=test-csrf",
  body: {{dataset: {{accountView: "authorization"}}}},
  createElement(tagName) {{ return makeElement({{tagName: String(tagName).toUpperCase()}}); }},
  querySelector(selector) {{
    const networkMatch = selector.match(/^\\[data-approve-network="([^"]+)"\\]$/);
    if (networkMatch) return makeElement({{dataset: {{approveNetwork: networkMatch[1]}}}});
    return elements[selector];
  }},
  querySelectorAll(selector) {{
    if (selector === "[data-approve-network]") return [];
    if (selector === "[data-network-state]" || selector === "[data-network-token], [data-network-spender]") return [];
    if (selector === "#grant-details .grant-ledger") return [];
    return [];
  }}
}};
global.Event = class Event {{ constructor(type) {{ this.type = type; }} }};
global.window = {{
  location: {{pathname: "/account"}},
  setTimeout,
  clearTimeout,
  navigator: {{locks: {{request: async (_name, _options, callback) => callback()}}}},
  sessionStorage: {{
    values: new Map(),
    get length() {{ return this.values.size; }},
    key(index) {{ return [...this.values.keys()][index] ?? null; }},
    getItem(key) {{ return this.values.get(key) ?? null; }},
    setItem(key, value) {{ this.values.set(key, String(value)); }},
    removeItem(key) {{ this.values.delete(key); }}
  }},
  listeners: {{}},
  addEventListener(name, listener) {{ this.listeners[name] = listener; }},
  dispatchEvent(event) {{
    if (event.type === "eip6963:requestProvider") {{
      this.listeners["eip6963:announceProvider"]?.({{detail: {{info: {{uuid: "provider-1", name: "Test Wallet", rdns: "test.wallet"}}, provider}}}});
    }}
    this.listeners[event.type]?.(event);
  }}
}};

if (scenario === "revoke-recovery" || scenario === "revoke-other-target") {{
  const key = "clink.account.allowance_revoke.v1." + encodeURIComponent("/account") + ".wallet_identity_1." + encodeURIComponent("eip155:137");
  window.sessionStorage.setItem(key, JSON.stringify({{
    allowance_tx_hash: txHash,
    asset_allowance_id: scenario === "revoke-other-target" ? "old_allowance" : "asset_allowance_recovery",
    network: "eip155:137",
    operation: "revoke",
    spender_address: scenario === "revoke-other-target" ? "0x" + "9".repeat(40) : spender,
    token_address: token,
    wallet_address: wallet,
    wallet_identity_id: "wallet_identity_1"
  }}));
}}
const uncertainKey = "clink.account.allowance_revoke_uncertain.v1." + encodeURIComponent("/account") + ".wallet_identity_1." + encodeURIComponent("eip155:137");
if (scenario === "revoke-uncertain") {{
  window.sessionStorage.setItem(uncertainKey, "allowance_revoke_post_send_uncertain");
}}

{javascript}

await new Promise((resolve) => setTimeout(resolve, 20));
const selectProvider = elements["#wallet-provider-options"].children[0];
if (selectProvider?.listeners.click) await selectProvider.listeners.click();
const selectAddress = elements["#wallet-account-options"].children[0];
if (selectAddress?.listeners.click) await selectAddress.listeners.click();
const result = {{
  status: elements["#page-status"].textContent,
  walletSelection: elements["#wallet-selection-state"].textContent,
  plan: elements["#embedded-plan"].innerHTML,
  allowance: elements["#embedded-plan-allowance"].textContent,
  approveHidden: elements["#embedded-approve"].hidden,
  calls: calls.map((call) => ({{url: call.url, method: call.options.method || "GET", body: call.options.body || null}})),
  planCalls
}};
if (scenario === "noop" || scenario === "sufficient" || scenario === "spent" || scenario === "large" || scenario === "unknown" || scenario === "malformed" || scenario === "grant-response-lost" || scenario === "approval-cancel" || scenario === "approval-bad-observed" || scenario === "approval-response-lost") {{
  await globalThis.__clinkEmbeddedTest.submit();
  await new Promise((resolve) => setTimeout(resolve, 20));
      result.afterSubmit = {{
        planCalls,
        plan: elements["#embedded-plan"].innerHTML,
        terms: elements["#embedded-plan-terms"].innerHTML,
        allowance: elements["#embedded-plan-allowance"].textContent,
        approveHidden: elements["#embedded-approve"].hidden,
        grantPosts: calls.filter((call) => call.url.endsWith("/grants") && call.options.body).length,
        signedGrantPosts,
        status: elements["#page-status"].textContent,
        attemptBeginCount,
        attemptSubmittedCount,
        attemptRejectedCount,
        allowanceAttempt
  }};
}}
if (scenario === "cancel-late") {{
  await globalThis.__clinkEmbeddedTest.submit();
  await new Promise((resolve) => setTimeout(resolve, 5));
  await globalThis.__clinkEmbeddedTest.confirmGrant();
  await new Promise((resolve) => setTimeout(resolve, 30));
  result.cancelled = true;
  result.grantPosts = calls.filter((call) => call.url.endsWith("/grants") && call.options.method === "POST").length;
  result.signedGrantPosts = signedGrantPosts;
  result.statusAfterCancel = elements["#page-status"].textContent;
}}
if (scenario === "grant-response-lost") {{
  await globalThis.__clinkEmbeddedTest.confirmGrant();
  await new Promise((resolve) => setTimeout(resolve, 20));
  result.afterUnknown = {{
    status: elements["#page-status"].textContent,
    signedGrantPosts,
    submitLabel: elements["#embedded-permission-submit"].textContent
  }};
  await globalThis.__clinkEmbeddedTest.submit();
  await new Promise((resolve) => setTimeout(resolve, 20));
  result.afterRecovery = {{
    status: elements["#page-status"].textContent,
    signedGrantPosts,
    planCalls,
    planHidden: elements["#embedded-plan"].hidden
  }};
}}
if (scenario === "approval-cancel") {{
  await globalThis.__clinkEmbeddedTest.approve();
  await globalThis.__clinkEmbeddedTest.confirmApproval();
  await new Promise((resolve) => setTimeout(resolve, 30));
  result.approvalCancel = {{
    sendTransactions,
    status: elements["#page-status"].textContent,
    approvalHidden: elements["#embedded-approval-confirm"].hidden
  }};
}}
if (scenario === "approval-bad-observed") {{
  await globalThis.__clinkEmbeddedTest.approve();
  await globalThis.__clinkEmbeddedTest.confirmApproval();
  await new Promise((resolve) => setTimeout(resolve, 30));
  result.approvalBadObserved = {{
    sendTransactions,
    status: elements["#page-status"].textContent
  }};
}}
if (scenario === "paused-current") {{
  result.currentActions = {{
    hidden: elements["#embedded-current-actions"].hidden,
    revokeHidden: elements["#embedded-revoke-spending"].hidden,
    submitDisabled: elements["#embedded-permission-submit"].disabled,
    state: elements["#embedded-mandate-state"].textContent
  }};
}}
if (scenario === "revoke-recovery") {{
  result.recovery = {{
    visible: !elements["#embedded-pending-recovery"].hidden,
    verifyVisible: !elements["#embedded-verify-pending-allowance"].hidden,
    message: elements["#embedded-pending-recovery-state"].textContent
  }};
  await globalThis.__clinkEmbeddedTest.verifyRecovery();
  await new Promise((resolve) => setTimeout(resolve, 20));
  result.afterRecovery = {{
    visible: !elements["#embedded-pending-recovery"].hidden,
    verifyVisible: !elements["#embedded-verify-pending-allowance"].hidden,
    status: elements["#page-status"].textContent
  }};
}}
if (scenario === "multi-network") {{
  elements["#embedded-network"].value = "eip155:8453";
  await globalThis.__clinkEmbeddedTest.reload();
  result.networkAfterReload = elements["#embedded-network"].value;
  result.networkDisabled = elements["#embedded-network"].disabled;
}}
if (scenario === "approval-response-lost") {{
  await globalThis.__clinkEmbeddedTest.approve();
  await globalThis.__clinkEmbeddedTest.confirmApproval();
  result.firstSendError = elements["#page-status"].textContent;
  await globalThis.__clinkEmbeddedTest.approve();
  await globalThis.__clinkEmbeddedTest.confirmApproval();
  result.sendTransactions = sendTransactions;
}}
if (scenario === "revoke-cancel" || scenario === "revoke-response-lost" || scenario === "revoke-other-target") {{
  elements["#embedded-revoke-allowance"].checked = true;
  await globalThis.__clinkEmbeddedTest.revoke();
  result.sendTransactions = sendTransactions;
  result.revokePosts = calls.filter((call) => call.url.endsWith("/revoke")).length;
  result.revokeStatus = elements["#page-status"].textContent;
  result.uncertainLock = window.sessionStorage.getItem(uncertainKey);
  result.storedRevokeRecords = [...window.sessionStorage.values.keys()].filter((key) => key.startsWith("clink.account.allowance_revoke.v1."));
}}
if (scenario === "revoke-uncertain") {{
  await globalThis.__clinkEmbeddedTest.verifyRecovery();
  result.uncertainLock = window.sessionStorage.getItem(uncertainKey);
  result.recoveryStatus = elements["#page-status"].textContent;
  result.allowanceRefreshes = calls.filter((call) => call.url.includes("/allowances/") && call.url.endsWith("/refresh")).length;
  result.sendTransactions = sendTransactions;
}}
  console.log(JSON.stringify(result));
"""
    result = subprocess.run(
        ["node", "--input-type=module", "-"],
        input=harness,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def test_authorization_markup_is_hidden_in_full_mode_and_has_read_stage_notice() -> None:
    assert 'id="embedded-authorization"' in ACCOUNT_CONSOLE_HTML
    assert 'id="embedded-network"' in ACCOUNT_CONSOLE_HTML
    assert 'id="embedded-total-limit"' in ACCOUNT_CONSOLE_HTML
    assert 'id="embedded-hourly-limit"' in ACCOUNT_CONSOLE_HTML
    assert 'id="embedded-duration-days"' in ACCOUNT_CONSOLE_HTML
    assert "does not enable purchasing or funding" in ACCOUNT_CONSOLE_HTML
    assert 'body[data-account-view="authorization"]' in ACCOUNT_CONSOLE_CSS


def test_full_grant_ledger_uses_actual_product_scopes() -> None:
    assert "Marketplace + prediction markets" not in ACCOUNT_CONSOLE_JS
    assert "item.product_scopes" in ACCOUNT_CONSOLE_JS


def test_embedded_approval_carries_cancel_guard_through_broadcast() -> None:
    assert "guard: () => embeddedOperationGuard(operation)" in ACCOUNT_CONSOLE_JS
    assert "embeddedOperationGuard(operation);" in ACCOUNT_CONSOLE_JS


def test_embedded_cancel_message_distinguishes_submitted_chain_work() -> None:
    assert "may already have been submitted" in ACCOUNT_CONSOLE_JS
    assert "query core before retrying" in ACCOUNT_CONSOLE_JS.lower()


def test_embedded_revoke_offers_explicit_optional_allowance_cleanup() -> None:
    assert 'id="embedded-revoke-allowance"' in ACCOUNT_CONSOLE_HTML
    assert "Clear the selected network allowance" in ACCOUNT_CONSOLE_HTML
    assert "shared with other businesses" in ACCOUNT_CONSOLE_HTML
    assert "revokeAllowance" in ACCOUNT_CONSOLE_JS


def test_embedded_approval_success_requires_exact_observed_target() -> None:
    assert "observed_atomic" in ACCOUNT_CONSOLE_JS
    assert "target_atomic" in ACCOUNT_CONSOLE_JS
    assert "exact finite chain allowance verified" in ACCOUNT_CONSOLE_JS.lower()


def test_embedded_plan_is_consumed_without_signing_for_noop() -> None:
    result = _run_embedded_console("noop")
    assert result["afterSubmit"]["planCalls"] >= 1
    assert result["afterSubmit"]["grantPosts"] == 0


def test_embedded_plan_renders_finite_unspent_target_without_refilling_spent_allowance() -> None:
    result = _run_embedded_console("spent")
    assert "60" in result["afterSubmit"]["allowance"]
    assert "100" not in result["afterSubmit"]["allowance"]


def test_embedded_unknown_allowance_only_offers_retry() -> None:
    result = _run_embedded_console("unknown")
    assert result["afterSubmit"]["approveHidden"] is True
    assert "retry" in result["afterSubmit"]["allowance"].lower()


def test_embedded_large_allowance_warns_before_any_adjustment() -> None:
    result = _run_embedded_console("large")
    assert "shared" in result["afterSubmit"]["allowance"].lower()
    assert result["afterSubmit"]["approveHidden"] is False


def test_embedded_cancel_during_wallet_confirmation_never_posts_signed_grant() -> None:
    result = _run_embedded_console("cancel-late")
    assert result["cancelled"] is True
    assert result["grantPosts"] == 1  # challenge only; no signed grant POST
    assert "cancel" in result["statusAfterCancel"].lower() or "expired" in result["statusAfterCancel"].lower()


def test_embedded_malformed_plan_fails_closed_without_signing() -> None:
    result = _run_embedded_console("malformed")
    assert result["afterSubmit"]["grantPosts"] == 0
    assert "invalid authorization plan" in result["afterSubmit"]["status"].lower()


def test_embedded_approval_cancelled_during_network_switch_never_broadcasts() -> None:
    result = _run_embedded_console("approval-cancel")
    assert result["approvalCancel"]["sendTransactions"] == 0
    assert "cancel" in result["approvalCancel"]["status"].lower() or "expired" in result["approvalCancel"]["status"].lower()


def test_embedded_approval_does_not_claim_success_for_inexact_observation() -> None:
    result = _run_embedded_console("approval-bad-observed")
    assert result["approvalBadObserved"]["sendTransactions"] == 1
    assert "exact allowance target" in result["approvalBadObserved"]["status"].lower()
    assert "verified by core" not in result["approvalBadObserved"]["status"].lower()


def test_embedded_signed_grant_response_loss_blocks_resubmission_until_refresh() -> None:
    result = _run_embedded_console("grant-response-lost")
    assert result["afterUnknown"]["signedGrantPosts"] == 1
    assert "do not sign or resend" in result["afterUnknown"]["status"].lower()
    assert result["afterRecovery"]["signedGrantPosts"] == 1
    assert result["afterRecovery"]["planCalls"] >= 2


def test_embedded_paused_authorization_remains_revokeable_without_resume() -> None:
    result = _run_embedded_console("paused-current")
    assert result["currentActions"]["hidden"] is False
    assert result["currentActions"]["revokeHidden"] is False
    assert result["currentActions"]["submitDisabled"] is True
    assert "will not be resumed" in result["currentActions"]["state"]


def test_embedded_revoke_recovery_remains_visible_after_grant_is_gone() -> None:
    result = _run_embedded_console("revoke-recovery")
    assert result["recovery"]["visible"] is True
    assert result["recovery"]["verifyVisible"] is True
    assert "no new transaction" in result["recovery"]["message"].lower()
    assert result["afterRecovery"]["visible"] is False
    assert result["afterRecovery"]["verifyVisible"] is False


def test_embedded_multi_network_selection_survives_account_refresh() -> None:
    result = _run_embedded_console("multi-network")
    assert result["networkAfterReload"] == "eip155:8453"
    assert result["networkDisabled"] is False


def test_embedded_approval_response_loss_does_not_broadcast_again() -> None:
    result = _run_embedded_console("approval-response-lost")
    assert result["sendTransactions"] == 1
    assert "do not retry" in result["firstSendError"].lower()


def test_embedded_revoke_cancellation_before_send_leaves_core_revoke_intact() -> None:
    result = _run_embedded_console("revoke-cancel")
    assert result["revokePosts"] == 1
    assert result["sendTransactions"] == 0
    assert "spending was revoked in core" in result["revokeStatus"].lower()
    assert "cleanup is incomplete" in result["revokeStatus"].lower()


def test_embedded_hashless_revoke_cannot_clear_lock_from_another_spender() -> None:
    result = _run_embedded_console("revoke-uncertain")
    assert result["sendTransactions"] == 0
    assert result["uncertainLock"] == "allowance_revoke_post_send_uncertain"
    assert result["allowanceRefreshes"] == 0
    assert "exact" in result["recoveryStatus"].lower()


def test_embedded_revoke_response_loss_persists_uncertainty() -> None:
    result = _run_embedded_console("revoke-response-lost")
    assert result["sendTransactions"] == 1
    assert result["uncertainLock"] == "allowance_revoke_post_send_uncertain"
    assert "do not resend" in result["revokeStatus"].lower()


def test_embedded_confirmation_shows_all_signed_business_limits() -> None:
    result = _run_embedded_console("spent")
    assert "hermes" in result["afterSubmit"]["terms"]
    assert "clink_verified" in result["afterSubmit"]["terms"]
    assert "silent_under_limits" in result["afterSubmit"]["terms"]


def test_embedded_revoke_cannot_reuse_another_spenders_stored_receipt() -> None:
    result = _run_embedded_console("revoke-other-target")
    assert result["sendTransactions"] == 0
    assert "cleanup is incomplete" in result["revokeStatus"].lower()
    assert "different allowance target" in result["revokeStatus"].lower()
    assert len(result["storedRevokeRecords"]) == 1


def test_embedded_wallet_selection_does_not_override_core_verified_status() -> None:
    result = _run_embedded_console("noop")
    assert "not signed in" not in result["walletSelection"].lower()
    assert "only if" in result["walletSelection"].lower()
