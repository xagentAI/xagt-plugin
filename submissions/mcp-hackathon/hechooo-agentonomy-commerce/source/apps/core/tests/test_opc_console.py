from __future__ import annotations

import json
import subprocess

from services.account_service.console import ACCOUNT_CONSOLE_JS


WALLET_A = "0x" + "a" * 40
WALLET_B = "0x" + "b" * 40
TOKEN = "0x" + "1" * 40
SPENDER = "0x" + "2" * 40
PAIRING_ID = "opc_pairing_1"
INSTALLATION_ID = "opc_installation_1"
EXACT_MESSAGE = "Clink OPC installation approval\n\nDo not share this signature."


def _run_opc_console(scenario: str) -> dict:
    test_hooks = r'''globalThis.__clinkOpcTest = {
  refresh: () => elements["#opc-refresh"].listeners.click?.({
    currentTarget: elements["#opc-refresh"]
  }),
  review: () => elements["#opc-review-button"].listeners.click?.({
    currentTarget: elements["#opc-review-button"]
  }),
  sign: () => elements["#opc-sign-button"].listeners.click?.({
    currentTarget: elements["#opc-sign-button"]
  }),
  cancel: () => elements["#opc-cancel-button"].listeners.click?.({
    currentTarget: elements["#opc-cancel-button"]
  }),
  reload: () => loadState()
};
'''
    javascript = ACCOUNT_CONSOLE_JS.removesuffix("})();\n") + test_hooks + "})();\n"
    harness = f"""
const scenario = {json.dumps(scenario)};
const walletA = {json.dumps(WALLET_A)};
const walletB = {json.dumps(WALLET_B)};
const token = {json.dumps(TOKEN)};
const spender = {json.dumps(SPENDER)};
const exactMessage = {json.dumps(EXACT_MESSAGE)};
Date.now = () => Date.parse("2026-09-14T06:00:00Z");

const childText = (child) => child?.textContent ||
  (child?.children || []).map(childText).join("");
const makeElement = (extra = {{}}) => Object.assign({{
  attributes: {{}},
  classList: {{add() {{}}, remove() {{}}, toggle() {{}}}},
  className: "",
  dataset: {{}},
  disabled: false,
  hidden: false,
  innerHTML: "",
  listeners: {{}},
  open: false,
  textContent: "",
  value: "",
  checked: false,
  children: [],
  addEventListener(type, listener) {{ this.listeners[type] = listener; }},
  append(...children) {{
    this.children.push(...children);
    this.textContent = this.children.map(childText).join("");
  }},
  closest(selector) {{
    if (selector === "[data-grant-action]") return this;
    if (selector === "[data-grant-id]") return this;
    return null;
  }},
  querySelector(selector) {{
    if (selector === "button") return this.submitButton || makeElement();
    return makeElement();
  }},
  replaceChildren(...children) {{
    this.children = children;
    this.textContent = this.children.map(childText).join("");
  }},
  setAttribute(name, value) {{ this.attributes[name] = String(value); }},
  removeAttribute(name) {{ delete this.attributes[name]; }}
}}, extra);

const elements = {{}};
const selectors = [
  "#page-status", "#wallet-state", "#wallet-details", "#permission-state",
  "#grant-details", "#audit-list", "#connect-wallet",
  "#cancel-wallet-selection", "#refresh-allowances", "#resume-wallet-disconnect",
  "#wallet-disconnect-state", "#refresh-audit", "#wallet-provider-options",
  "#wallet-account-options", "#wallet-selection-state", "#total-limit",
  "#transaction-limit", "#hourly-limit", "#daily-limit", "#expiry-days",
  "#trust-clink", "#trust-registry", "#notification-mode", "#permission-editor",
  "#permission-editor-label", "#new-limit-settings", "#permission-submit",
  "#limit-help", "#allowance-setup", "#allowance-setup-label", "#network-ledger",
  "#verify-pending-allowance", "#pending-allowance-state", "#wallet-session-dialog",
  "#wallet-session-qr", "#wallet-session-open", "#wallet-session-cancel",
  "#polygon-state", "#polygon-token", "#polygon-spender",
  "#opc-device-section", "#opc-device-state", "#opc-device-details",
  "#opc-device-grant", "#opc-device-status", "#opc-device-message",
  "#opc-refresh", "#opc-review-button", "#opc-sign-button", "#opc-cancel-button",
  "#opc-review", "#opc-exact-message", "#opc-recheck"
];
for (const selector of selectors) elements[selector] = makeElement();
elements["#opc-device-section"].hidden = true;
elements["#opc-review"].hidden = true;
elements["#opc-review-button"].disabled = true;
elements["#opc-sign-button"].hidden = true;
elements["#opc-sign-button"].disabled = true;
elements["#opc-cancel-button"].hidden = true;
elements["#opc-recheck"].hidden = true;
const permissionButton = elements["#permission-submit"];
elements["#permission-form"] = makeElement({{submitButton: permissionButton}});

const activeMandate = {{
  spending_grant_id: "spending_grant_1",
  wallet_identity_id: "wallet_identity_1",
  agent_id: "hermes",
  status: "active",
  max_amount_usdc: "25",
  per_transaction_limit_usdc: "5",
  hourly_limit_usdc: "10",
  daily_limit_usdc: "25",
  product_scopes: ["marketplace", "prediction_markets"],
  network_scopes: ["eip155:137"],
  asset_scopes: [token],
  limits_usdc: {{per_transaction: "5", rolling_hour: "10", daily: "25", total: "25"}},
  used_usdc: {{rolling_hour: "0", daily: "0", total: "0"}},
  reserved_usdc: {{rolling_hour: "0", daily: "0", total: "0"}},
  remaining_usdc: {{rolling_hour: "10", daily: "25", total: "25"}},
  starts_at: "2026-09-14T00:00:00Z",
  expires_at: "2026-10-14T00:00:00Z"
}};
const walletAddress = scenario === "selected-wallet-mismatch" ? walletB : walletA;
const state = {{
  wallet_identities: [{{
    wallet_identity_id: "wallet_identity_1",
    wallet_address: walletA,
    status: "active",
    verified_at: "2026-09-14T00:00:00Z"
  }}],
  spending_grants: scenario === "no-hermes-grant" ? [] : [activeMandate],
  current_spending_mandate: scenario === "no-hermes-grant" ? null : activeMandate,
  asset_allowances: [],
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
const pairing = scenario === "ordinary" ? null : {{
  pairing_id: {json.dumps(PAIRING_ID)},
  installation_id: {json.dumps(INSTALLATION_ID)},
  label: "Mac <script>alert(1)</script>",
  public_jwk_thumbprint: "fingerprint-123",
  scope: "payments",
  agent_id: "hermes",
  status: scenario === "expired-pairing" ? "expired" : "pending",
  expires_at: "2026-09-15T12:10:00Z",
  consent_expires_at: "2026-10-15T00:00:00Z",
  wallet_identity_id: null,
  spending_grant_id: null
}};
let currentPairing = pairing;

const providerListeners = {{}};
const personalSigns = [];
const calls = [];
let approvePosts = 0;
let claimPosts = 0;
let challengePosts = 0;
let challengeRelease;
let signatureRelease;
let approveRelease;
const provider = {{
  async request(request) {{
    if (request.method === "eth_accounts" || request.method === "eth_requestAccounts") return [walletAddress];
    if (request.method === "personal_sign") {{
      personalSigns.push({{message: request.params[0], address: request.params[1]}});
      if (scenario === "cancel-during-signature") {{
        await new Promise((resolve) => {{ signatureRelease = resolve; }});
      }}
      return "0x" + "4".repeat(130);
    }}
    throw new Error(`Unexpected provider method ${{request.method}}`);
  }},
  on(name, listener) {{ (providerListeners[name] ||= new Set()).add(listener); }},
  removeListener(name, listener) {{ providerListeners[name]?.delete(listener); }},
  emit(name) {{ for (const listener of [...(providerListeners[name] || [])]) listener(); }}
}};

const response = (body, ok = true, status = 200) => ({{
  ok, status,
  async json() {{ return body; }}
}});
global.fetch = async (url, options = {{}}) => {{
  calls.push({{url, options: {{...options}}}});
  if (url === "/account" && (!options.method || options.method === "GET")) return response(state);
  if (url === "/account/opc/pairing" && scenario === "expired-session-pairing") return response({{detail: "account session expired"}}, false, 410);
  if (url === "/account/opc/pairing") return response({{pairing: currentPairing}});
  if (url.endsWith(`/opc/pairings/${{pairing?.pairing_id}}/claim`)) {{
    claimPosts += 1;
    currentPairing = {{...currentPairing, status: "claimed"}};
    return response({{
      pairing_id: currentPairing.pairing_id,
      installation_id: currentPairing.installation_id,
      public_account_session_id: "public_opc_session_1",
      target_user_id: "opc_user_1",
      status: "claimed",
      expires_at: currentPairing.expires_at
    }});
  }}
  if (url.endsWith(`/opc/pairings/${{pairing?.pairing_id}}/challenge`)) {{
    challengePosts += 1;
    if (scenario === "account-switch-awaiting") {{
      await new Promise((resolve) => {{ challengeRelease = resolve; }});
    }}
    if (scenario === "expired-challenge") return response({{detail: "request could not be completed"}}, false, 400);
    return response({{
      session_id: "opc_challenge_1",
      message_to_sign: exactMessage,
      expires_at: scenario === "expired-challenge-response"
        ? "2026-09-14T00:00:00Z"
        : "2026-09-15T12:01:00Z"
    }});
  }}
  if (url === "/account/opc/installations/approve") {{
    approvePosts += 1;
    currentPairing = {{...currentPairing, status: "active", wallet_identity_id: "wallet_identity_1", spending_grant_id: "spending_grant_1"}};
    if (scenario === "cancel-during-approve") {{
      await new Promise((resolve) => {{ approveRelease = resolve; }});
    }}
    if (scenario === "approve-response-lost") throw new Error("response lost after approval");
    return response({{installation_id: {json.dumps(INSTALLATION_ID)}, status: "active"}});
  }}
  if (url === "/account/opc/pairing") return response({{pairing: currentPairing}});
  return response({{}});
}};

const windowListeners = {{}};
global.document = {{
  cookie: "clink_account_csrf=test-csrf",
  body: {{dataset: {{}}}},
  createElement(tagName) {{ return makeElement({{tagName: String(tagName).toUpperCase()}}); }},
  querySelector(selector) {{
    if (selector === `[data-approve-network="eip155:137"]`) return makeElement({{dataset: {{approveNetwork: "eip155:137"}}}});
    return elements[selector];
  }},
  querySelectorAll(selector) {{
    if (selector === "[data-approve-network]") return [];
    if (selector === "[data-network-state]") return [elements["#polygon-state"]];
    if (selector === "[data-network-token], [data-network-spender]") return [elements["#polygon-token"], elements["#polygon-spender"]];
    if (selector === "#grant-details .grant-ledger") return [];
    return [];
  }}
}};
global.Event = class Event {{ constructor(type) {{ this.type = type; }} }};
global.window = {{
  location: {{pathname: "/account"}},
  setTimeout(...args) {{
    const timer = setTimeout(...args);
    timer.unref?.();
    return timer;
  }},
  clearTimeout,
  sessionStorage: {{
    values: new Map(),
    get length() {{ return this.values.size; }},
    key(index) {{ return [...this.values.keys()][index] ?? null; }},
    getItem(key) {{ return this.values.get(key) ?? null; }},
    setItem(key, value) {{ this.values.set(key, String(value)); }},
    removeItem(key) {{ this.values.delete(key); }}
  }},
  addEventListener(name, listener) {{ (windowListeners[name] ||= []).push(listener); }},
  dispatchEvent(event) {{
    if (event.type === "eip6963:requestProvider") {{
      for (const listener of windowListeners["eip6963:announceProvider"] || []) listener({{detail: {{info: {{uuid: "provider-1", name: "Test Wallet", rdns: "test.wallet"}}, provider}}}});
    }}
    for (const listener of windowListeners[event.type] || []) listener(event);
  }}
}};

{javascript}

await new Promise((resolve) => setTimeout(resolve, 25));
const providerButton = elements["#wallet-provider-options"].children[0];
if (providerButton?.listeners.click) await providerButton.listeners.click();
const accountButton = elements["#wallet-account-options"].children[0];
if (accountButton?.listeners.click) await accountButton.listeners.click();
await new Promise((resolve) => setTimeout(resolve, 25));

const baseResult = () => ({{
  sectionHidden: elements["#opc-device-section"].hidden,
  deviceDetails: elements["#opc-device-details"].textContent,
  deviceGrant: elements["#opc-device-grant"].textContent,
  deviceStatus: elements["#opc-device-status"].textContent,
  reviewDisabled: elements["#opc-review-button"].disabled,
  reviewHidden: elements["#opc-review"].hidden,
  signHidden: elements["#opc-sign-button"].hidden,
  signDisabled: elements["#opc-sign-button"].disabled,
  exactMessage: elements["#opc-exact-message"].textContent,
  status: elements["#page-status"].textContent,
  claimPosts,
  challengePosts,
  approvePosts,
  personalSigns,
  calls: calls.map((call) => ({{url: call.url, method: call.options.method || "GET", body: call.options.body || null}}))
}});

    if (scenario === "pending" || scenario === "no-hermes-grant" || scenario === "selected-wallet-mismatch" || scenario === "expired-pairing" || scenario === "expired-challenge-response") {{
  await globalThis.__clinkOpcTest.review();
  await new Promise((resolve) => setTimeout(resolve, 20));
}}
if (scenario === "review-only") {{
  await globalThis.__clinkOpcTest.review();
  await new Promise((resolve) => setTimeout(resolve, 20));
}}
if (scenario === "confirm") {{
  await globalThis.__clinkOpcTest.review();
  await new Promise((resolve) => setTimeout(resolve, 20));
  await globalThis.__clinkOpcTest.sign();
  await new Promise((resolve) => setTimeout(resolve, 30));
}}
if (scenario === "cancel") {{
  await globalThis.__clinkOpcTest.review();
  await new Promise((resolve) => setTimeout(resolve, 20));
  await globalThis.__clinkOpcTest.cancel();
  await new Promise((resolve) => setTimeout(resolve, 20));
}}
if (scenario === "cancel-during-signature") {{
  await globalThis.__clinkOpcTest.review();
  await new Promise((resolve) => setTimeout(resolve, 20));
  const signPromise = globalThis.__clinkOpcTest.sign();
  await new Promise((resolve) => setTimeout(resolve, 5));
  await globalThis.__clinkOpcTest.cancel();
  signatureRelease?.();
  await signPromise;
  await new Promise((resolve) => setTimeout(resolve, 20));
}}
if (scenario === "cancel-during-approve") {{
  await globalThis.__clinkOpcTest.review();
  await new Promise((resolve) => setTimeout(resolve, 20));
  const signPromise = globalThis.__clinkOpcTest.sign();
  await new Promise((resolve) => setTimeout(resolve, 5));
  await globalThis.__clinkOpcTest.cancel();
  approveRelease?.();
  await signPromise;
  await new Promise((resolve) => setTimeout(resolve, 20));
}}
if (scenario === "account-switch-awaiting") {{
  const reviewPromise = globalThis.__clinkOpcTest.review();
  await new Promise((resolve) => setTimeout(resolve, 5));
  provider.emit("accountsChanged");
  challengeRelease?.();
  await reviewPromise;
  await new Promise((resolve) => setTimeout(resolve, 20));
}}
if (scenario === "account-switch-after-review") {{
  await globalThis.__clinkOpcTest.review();
  await new Promise((resolve) => setTimeout(resolve, 20));
  provider.emit("accountsChanged");
  await new Promise((resolve) => setTimeout(resolve, 20));
}}
if (scenario === "expired-challenge") {{
  await globalThis.__clinkOpcTest.review();
  await new Promise((resolve) => setTimeout(resolve, 20));
}}
if (scenario === "approve-response-lost") {{
  await globalThis.__clinkOpcTest.review();
  await new Promise((resolve) => setTimeout(resolve, 20));
  await globalThis.__clinkOpcTest.sign();
  await new Promise((resolve) => setTimeout(resolve, 30));
}}
const result = baseResult();
if (["approve-response-lost", "cancel-during-approve"].includes(scenario)) {{
  result.recheckHidden = elements["#opc-recheck"].hidden;
  result.uncertain = result.status.toLowerCase().includes("uncertain") || result.status.toLowerCase().includes("refresh");
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


def _forbidden_calls(result: dict) -> list[dict]:
    return [
        call
        for call in result["calls"]
        if any(
            marker in call["url"].lower()
            for marker in ("sendtransaction", "approve-token", "preview", "payment")
        )
    ]


def test_ordinary_account_session_keeps_device_section_hidden() -> None:
    result = _run_opc_console("ordinary")

    assert result["sectionHidden"] is True
    assert result["claimPosts"] == 0
    assert result["challengePosts"] == 0
    assert result["personalSigns"] == []
    assert _forbidden_calls(result) == []


def test_pending_device_shows_safe_identity_scope_and_current_grant() -> None:
    result = _run_opc_console("pending")

    assert result["sectionHidden"] is False
    assert "Mac <script>alert(1)</script>" in result["deviceDetails"]
    assert "fingerprint-123" in result["deviceDetails"]
    assert "payments" in result["deviceDetails"]
    assert "hermes" in result["deviceDetails"]
    assert "25" in result["deviceGrant"]
    assert result["claimPosts"] == 1
    assert result["challengePosts"] == 1
    assert result["personalSigns"] == []
    assert _forbidden_calls(result) == []


def test_no_active_hermes_grant_disables_device_review() -> None:
    result = _run_opc_console("no-hermes-grant")

    assert result["sectionHidden"] is False
    assert result["reviewDisabled"] is True
    assert result["claimPosts"] == 0
    assert result["challengePosts"] == 0
    assert result["personalSigns"] == []


def test_selected_wallet_mismatch_rejects_device_review_without_claiming() -> None:
    result = _run_opc_console("selected-wallet-mismatch")

    assert result["reviewDisabled"] is True
    assert result["claimPosts"] == 0
    assert result["challengePosts"] == 0
    assert result["personalSigns"] == []
    assert "match" in result["status"].lower() or "wallet" in result["status"].lower()


def test_review_claims_and_challenges_exact_pairing_but_does_not_sign() -> None:
    result = _run_opc_console("review-only")

    assert result["claimPosts"] == 1
    assert result["challengePosts"] == 1
    assert result["personalSigns"] == []
    assert result["reviewHidden"] is False
    assert result["signHidden"] is False
    assert result["signDisabled"] is False
    assert result["exactMessage"] == EXACT_MESSAGE
    assert _forbidden_calls(result) == []


def test_explicit_confirm_signs_verbatim_message_then_approves_once() -> None:
    result = _run_opc_console("confirm")

    assert result["claimPosts"] == 1
    assert result["challengePosts"] == 1
    assert result["personalSigns"] == [{"message": EXACT_MESSAGE, "address": WALLET_A}]
    assert result["approvePosts"] == 1
    approve_call = next(call for call in result["calls"] if call["url"].endswith("/installations/approve"))
    assert json.loads(approve_call["body"])["signed_message"] == EXACT_MESSAGE
    assert "active for the exact selected wallet" in result["status"]
    assert result["signHidden"] is True
    assert _forbidden_calls(result) == []


def test_cancel_after_review_performs_no_signature_or_approve() -> None:
    result = _run_opc_console("cancel")

    assert result["claimPosts"] == 1
    assert result["challengePosts"] == 1
    assert result["personalSigns"] == []
    assert result["approvePosts"] == 0
    assert result["reviewHidden"] is True
    assert _forbidden_calls(result) == []


def test_cancel_during_signature_does_not_claim_signature_was_never_requested() -> None:
    result = _run_opc_console("cancel-during-signature")

    assert result["personalSigns"] == [{"message": EXACT_MESSAGE, "address": WALLET_A}]
    assert result["approvePosts"] == 0
    assert result["reviewHidden"] is True
    assert "No wallet signature or device approval was sent" not in result["status"]
    assert _forbidden_calls(result) == []


def test_cancel_during_approve_requires_recheck_without_retry() -> None:
    result = _run_opc_console("cancel-during-approve")

    assert result["personalSigns"] == [{"message": EXACT_MESSAGE, "address": WALLET_A}]
    assert result["approvePosts"] == 1
    assert result["uncertain"] is True
    assert result["recheckHidden"] is False
    assert result["reviewHidden"] is True
    assert result["signHidden"] is True
    assert _forbidden_calls(result) == []


def test_wallet_change_while_review_awaits_invalidates_without_signing() -> None:
    result = _run_opc_console("account-switch-awaiting")

    assert result["claimPosts"] == 1
    assert result["challengePosts"] == 1
    assert result["personalSigns"] == []
    assert result["approvePosts"] == 0
    assert result["reviewHidden"] is True
    assert _forbidden_calls(result) == []


def test_wallet_change_after_review_invalidates_exact_message() -> None:
    result = _run_opc_console("account-switch-after-review")

    assert result["reviewHidden"] is True
    assert result["exactMessage"] == ""
    assert result["personalSigns"] == []
    assert result["approvePosts"] == 0
    assert _forbidden_calls(result) == []


def test_expired_pairing_or_challenge_fails_closed() -> None:
    expired_pairing = _run_opc_console("expired-pairing")
    expired_challenge = _run_opc_console("expired-challenge")
    expired_challenge_response = _run_opc_console("expired-challenge-response")

    assert expired_pairing["reviewDisabled"] is True
    assert expired_pairing["claimPosts"] == 0
    assert expired_pairing["personalSigns"] == []
    assert expired_challenge["claimPosts"] == 1
    assert expired_challenge["challengePosts"] == 1
    assert expired_challenge["personalSigns"] == []
    assert expired_challenge["approvePosts"] == 0
    assert expired_challenge_response["claimPosts"] == 1
    assert expired_challenge_response["challengePosts"] == 1
    assert expired_challenge_response["personalSigns"] == []
    assert expired_challenge_response["approvePosts"] == 0
    assert _forbidden_calls(expired_pairing) == []
    assert _forbidden_calls(expired_challenge) == []


def test_expired_opc_pairing_keeps_the_exact_account_session_message() -> None:
    result = _run_opc_console("expired-session-pairing")

    assert result["status"] == (
        "Account session expired. Open a new account management link and sign in "
        "to continue verification. Your spending authorization is unchanged; do "
        "not approve again."
    )
    assert result["personalSigns"] == []
    assert result["approvePosts"] == 0


def test_lost_approve_response_is_uncertain_without_automatic_resign_or_retry() -> None:
    result = _run_opc_console("approve-response-lost")

    assert result["personalSigns"] == [{"message": EXACT_MESSAGE, "address": WALLET_A}]
    assert result["approvePosts"] == 1
    assert result["uncertain"] is True
    assert result["recheckHidden"] is False
    assert _forbidden_calls(result) == []
