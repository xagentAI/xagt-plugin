from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import UTC, datetime, timedelta
from decimal import Decimal

import anyio
import httpx
import pytest
from eth_account import Account
from eth_account.messages import encode_defunct
from sqlalchemy import inspect, text

from services.account_service.app import create_app
from services.account_service.console import ACCOUNT_CONSOLE_JS
from services.account_service.repository import AccountRepository, AccountSessionRow
from services.account_service.schemas import AssetAllowance, SpendingGrant, WalletIdentity
from services.account_service.service import (
    AMOY_NETWORK,
    AMOY_NETWORK_CONFIG,
    AccountService,
)
from services.audit_service.schemas import WriteAuditEventRequest
from services.audit_service.service import AuditService


NOW = datetime(2026, 7, 15, 12, 0, tzinfo=UTC)
INTERNAL_TOKEN = "core-internal-token-that-must-never-leak"
POLYGON = "eip155:137"
BASE = "eip155:8453"
TOKEN = "0x3c499c542cef5e3811e1192ce70d8cc03d5c3359"
BASE_TOKEN = "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913"
SPENDER = "0x" + "33" * 20
BASE_SPENDER = "0x" + "66" * 20
TX_HASH = "0x" + "44" * 32
PENDING_STORAGE_PREFIX = "clink.account.pending_allowance.v1."
PENDING_STORAGE_V2_PREFIX = "clink.account.pending_allowance.v2."
UNCERTAIN_STORAGE_PREFIX = "clink.account.allowance_post_send_uncertain.v1."
UNCERTAIN_STORAGE_V2_PREFIX = "clink.account.allowance_post_send_uncertain.v2."
ATTEMPT_STORAGE_PREFIX = "clink.account.allowance_attempt.v1."
UNCERTAIN_STORAGE_LABEL = "allowance_post_send_uncertain"


def pending_storage_key(pathname: str, wallet_identity_id: str) -> str:
    return f"{PENDING_STORAGE_V2_PREFIX}{wallet_identity_id}"


def legacy_pending_storage_key(pathname: str, wallet_identity_id: str) -> str:
    encoded_path = pathname.replace("/", "%2F")
    return f"{PENDING_STORAGE_PREFIX}{encoded_path}.{wallet_identity_id}"


def uncertain_storage_key(pathname: str, wallet_identity_id: str) -> str:
    return f"{UNCERTAIN_STORAGE_V2_PREFIX}{wallet_identity_id}"


def legacy_uncertain_storage_key(pathname: str, wallet_identity_id: str) -> str:
    encoded_path = pathname.replace("/", "%2F")
    return f"{UNCERTAIN_STORAGE_PREFIX}{encoded_path}.{wallet_identity_id}"


def attempt_storage_key(wallet_identity_id: str) -> str:
    return f"{ATTEMPT_STORAGE_PREFIX}{wallet_identity_id}"


def run_wallet_selection_console(javascript: str, scenario: str) -> dict:
    harness = f"""
const scenario = {json.dumps(scenario)};
const walletA = "0x" + "a".repeat(40);
const walletB = "0x" + "b".repeat(40);
const walletC = "0x" + "c".repeat(40);
const makeElement = (extra = {{}}) => Object.assign({{
  attributes: {{}},
  classList: {{add() {{}}, toggle() {{}}}},
  className: "",
  dataset: {{}},
  disabled: true,
  children: [],
  hidden: false,
  href: "",
  innerHTML: "",
  listeners: {{}},
  open: false,
  src: "",
  tagName: "",
  textContent: "",
  value: "",
  addEventListener(type, listener) {{ this.listeners[type] = listener; }},
  append(...children) {{ this.children.push(...children); }},
  closest() {{ return null; }},
  querySelector() {{ return makeElement(); }},
  removeAttribute(name) {{ delete this[name]; }},
  replaceChildren(...children) {{ this.children = children; }},
  setAttribute(name, value) {{ this.attributes[name] = String(value); }},
  showModal() {{ this.open = true; }},
  close() {{ this.open = false; }}
}}, extra);

const permissionButton = makeElement();
const permissionForm = makeElement({{
  querySelector() {{ return permissionButton; }}
}});
const polygonButton = makeElement({{dataset: {{approveNetwork: "{POLYGON}"}}}});
const baseButton = makeElement({{dataset: {{approveNetwork: "{BASE}"}}}});
const elements = {{}};
for (const selector of [
  "#page-status", "#wallet-state", "#wallet-details", "#permission-state",
  "#grant-details", "#polygon-state", "#polygon-amoy-state", "#base-state", "#polygon-token",
  "#polygon-amoy-token", "#polygon-spender", "#polygon-amoy-spender", "#base-token", "#base-spender", "#audit-list",
  "#connect-wallet", "#cancel-wallet-selection", "#refresh-allowances",
  "#resume-wallet-disconnect", "#wallet-disconnect-state", "#refresh-audit",
  "#wallet-provider-options", "#wallet-account-options", "#wallet-selection-state",
  "#total-limit", "#transaction-limit", "#hourly-limit", "#daily-limit",
  "#expiry-days", "#trust-clink", "#trust-registry", "#notification-mode",
  "#permission-editor", "#permission-editor-label", "#new-limit-settings",
  "#permission-submit", "#limit-help", "#allowance-setup",
  "#allowance-setup-label",
  "#network-ledger",
  "#verify-pending-allowance", "#pending-allowance-state",
  "#wallet-session-dialog", "#wallet-session-qr", "#wallet-session-open",
  "#wallet-session-cancel"
]) elements[selector] = makeElement();
elements["#permission-form"] = permissionForm;

global.document = {{
  cookie: "clink_account_csrf=test-csrf",
  createElement(tagName) {{
    return makeElement({{tagName: String(tagName).toUpperCase()}});
  }},
  querySelector(selector) {{
    if (selector === `[data-approve-network="{POLYGON}"]`) return polygonButton;
    if (selector === `[data-approve-network="{BASE}"]`) return baseButton;
    return elements[selector];
  }},
  querySelectorAll(selector) {{
    if (selector === "[data-approve-network]") {{
      return [polygonButton, baseButton];
    }}
    if (selector === "[data-network-state]") {{
      return [elements["#polygon-state"], elements["#base-state"]];
    }}
    if (selector === "[data-network-token], [data-network-spender]") {{
      return [
        elements["#polygon-token"],
        elements["#polygon-spender"],
        elements["#base-token"],
        elements["#base-spender"]
      ];
    }}
    if (selector === "#grant-details .grant-ledger") {{
      return elements["#grant-details"].innerHTML.match(
        /class="grant-ledger"/g
      ) || [];
    }}
    return [];
  }}
}};

const providerCalls = {{alpha: [], beta: [], betaReplacement: []}};
const providerListeners = {{alpha: {{}}, beta: {{}}, betaReplacement: {{}}}};
const restoredSessionScenarios = new Set([
  "restored_session",
  "restored_session_cancel",
  "restored_session_retry",
  "restored_then_wallet_disconnected"
]);
const accountStateGuardScenarios = new Set([
  "locked_account_state",
  "malformed_authenticated_state",
  "non_array_allowances",
  "empty_network_configs"
]);
const providerAccountState = {{
  alpha: [],
  beta: restoredSessionScenarios.has(scenario) ? [walletC] : [],
  betaReplacement: []
}};
let passiveCancelTriggered = false;
let replacementBetaProvider;
const makeProvider = (name) => ({{
  async request(request) {{
    providerCalls[name].push(request.method);
    if (request.method === "eth_requestAccounts") {{
      if (scenario === "cancel_pending_provider") {{
        await elements["#cancel-wallet-selection"].listeners.click();
      }}
      if (scenario === "account_access_rejected") {{
        throw new Error("account access rejected");
      }}
      if (scenario === "empty_accounts") return [];
      if (scenario === "invalid_accounts") return ["not-an-address"];
      providerAccountState[name] = name === "alpha"
        ? [walletA]
        : [walletB, walletC];
      return providerAccountState[name];
    }}
    if (request.method === "wallet_revokePermissions") {{
      if (scenario === "revoke_unsupported") {{
        const error = new Error("method not found");
        error.code = -32601;
        throw error;
      }}
      providerAccountState[name] = scenario === "revoke_still_authorized"
        ? [walletC]
        : [];
      return null;
    }}
    if (request.method === "eth_accounts") {{
      if (
        scenario === "cancel_during_passive_probe" &&
        name === "beta" &&
        !passiveCancelTriggered
      ) {{
        passiveCancelTriggered = true;
        await elements["#cancel-wallet-selection"].listeners.click();
      }}
      if (scenario === "passive_accounts_error" && name === "beta") {{
        throw new Error("passive account access failed");
      }}
      if (scenario === "passive_accounts_invalid" && name === "beta") {{
        return {{address: walletC}};
      }}
      return providerAccountState[name];
    }}
    if (request.method === "personal_sign") {{
      if (scenario === "signature_rejected") {{
        throw new Error("signature rejected");
      }}
      if (scenario === "cancel_during_signature") {{
        elements["#cancel-wallet-selection"].listeners.click();
      }}
      const changedEvent = {{
        accounts_changed: "accountsChanged",
        chain_changed: "chainChanged",
        disconnected: "disconnect"
      }}[scenario];
      if (changedEvent) this.emit(changedEvent);
      return "0xsigned-c";
    }}
    throw new Error(`Unexpected ${{name}} provider method ${{request.method}}`);
  }},
  on(eventName, listener) {{
    (providerListeners[name][eventName] ||= new Set()).add(listener);
  }},
  removeListener(eventName, listener) {{
    if (scenario === "listener_cleanup_throws" && name === "beta") {{
      throw new Error("listener cleanup failed");
    }}
    providerListeners[name][eventName]?.delete(listener);
  }},
  emit(eventName) {{
    for (const listener of [...(providerListeners[name][eventName] || [])]) {{
      listener();
    }}
  }}
}});
const alphaProvider = makeProvider("alpha");
const betaProvider = makeProvider("beta");
replacementBetaProvider = makeProvider("betaReplacement");
const providerDetails = [
  {{
    info: {{
      uuid: "alpha",
      name: "Alpha Wallet",
      icon: "data:image/png;base64,AA==",
      rdns: "alpha.wallet"
    }},
    provider: alphaProvider
  }},
  {{
    info: {{
      uuid: "beta",
      name: "Beta Wallet",
      icon: "https://wallet.example/icon.png",
      rdns: "beta.wallet"
    }},
    provider: betaProvider
  }}
];

const windowListeners = {{}};
const storageValues = new Map();
global.window = {{
  location: {{origin: "https://clink.test", pathname: "/account"}},
  sessionStorage: {{
    get length() {{ return storageValues.size; }},
    key(index) {{ return [...storageValues.keys()][index] ?? null; }},
    getItem(key) {{ return storageValues.get(key) ?? null; }},
    setItem(key, value) {{ storageValues.set(key, String(value)); }},
    removeItem(key) {{ storageValues.delete(key); }}
  }},
  setTimeout,
  addEventListener(type, listener) {{
    (windowListeners[type] ||= []).push(listener);
  }},
  dispatchEvent(event) {{
    if (event.type !== "eip6963:requestProvider") return;
    for (const detail of providerDetails) {{
      for (const listener of windowListeners["eip6963:announceProvider"] || []) {{
        listener({{detail}});
      }}
    }}
  }}
}};

const validGuardAllowance = {{
  asset_allowance_id: "asset_allowance_guard",
  wallet_identity_id: "wallet_identity_guard",
  network: "eip155:137",
  token_address: "0x" + "1".repeat(40),
  token_symbol: "USDC",
  spender_address: "0x" + "2".repeat(40),
  status: "active",
  approved_amount_atomic: "1",
  observed_allowance_atomic: "1"
}};
const mandateGrant = (spendingGrantId, status) => ({{
  spending_grant_id: spendingGrantId,
  wallet_identity_id: "wallet_identity_guard",
  agent_id: "hermes",
  status,
  max_amount_usdc: "25",
  per_transaction_limit_usdc: "1",
  hourly_limit_usdc: "2",
  daily_limit_usdc: "5",
  product_scopes: ["marketplace", "prediction_markets"],
  network_scopes: ["eip155:137", "eip155:8453"],
  asset_scopes: ["{TOKEN}"]
}});
const currentMandate = {{
  ...mandateGrant("spending_grant_active", "active"),
  limits_usdc: {{
    per_transaction: "1",
    rolling_hour: "2",
    daily: "5",
    total: "25"
  }},
  used_usdc: {{rolling_hour: "0.5", daily: "1", total: "3"}},
  reserved_usdc: {{rolling_hour: "0.25", daily: "0.5", total: "1"}},
  remaining_usdc: {{rolling_hour: "1.25", daily: "3.5", total: "21"}}
}};
const accountState = {{
  wallet_identities:
    scenario === "malformed_authenticated_state"
      ? {{}}
      : [
          "stale_authenticated_response_after_lock",
          "stale_account_session_expired_response"
        ].includes(scenario)
        ? [{{
            wallet_identity_id: "wallet_identity_guard",
            wallet_address: walletA,
            status: "active",
            verified_at: "now"
          }}]
        : [],
  spending_grants: scenario === "renders_only_current_mandate"
    ? [
        mandateGrant("spending_grant_revoked_a", "revoked"),
        mandateGrant("spending_grant_revoked_b", "revoked"),
        mandateGrant("spending_grant_revoked_c", "revoked"),
        mandateGrant("spending_grant_active", "active")
      ]
    : [],
  current_spending_mandate:
    scenario === "renders_only_current_mandate" ? currentMandate : null,
  asset_allowances:
    scenario === "non_array_allowances"
      ? {{}}
      : [
          "malformed_authenticated_state",
          "stale_authenticated_response_after_lock",
          "stale_account_session_expired_response"
        ].includes(scenario)
        ? [validGuardAllowance]
        : [],
  approval_targets: {{}},
  network_configs: scenario === "empty_network_configs" ? {{}} : {{
    "{POLYGON}": {{
      chain_id: 137,
      required_confirmations: 3,
      token_symbol: "USDC",
      token_decimals: 6
    }},
    "{BASE}": {{
      chain_id: 8453,
      required_confirmations: 3,
      token_symbol: "USDC",
      token_decimals: 6
    }}
  }},
  recent_audit_summary: [],
  allowance_recovery: [],
  readiness: {{ready: false}}
}};
const challengeRequests = [];
const verifyRequests = [];
const cancelRequests = [];
const fetchCalls = [];
let accountStateFetchCount = 0;
let releaseStaleAuthenticatedResponse = null;
global.fetch = async (url, options = {{}}) => {{
  fetchCalls.push({{
    url: String(url),
    method: options.method || "GET"
  }});
  if (String(url).endsWith("/wallet-challenge")) {{
    challengeRequests.push(JSON.parse(options.body));
    return {{
      ok: true,
      status: 200,
      async json() {{
        return {{
          session_id: "wallet_session",
          message_to_sign: "wallet proof"
        }};
      }}
    }};
  }}
  if (String(url).endsWith("/wallet-verify")) {{
    verifyRequests.push(JSON.parse(options.body));
    return {{
      ok: true,
      status: 200,
      async json() {{
        return scenario === "suspended_cleanup_reauth"
          ? {{
              wallet_identity_id: "wallet_identity_suspended",
              wallet_address: walletC,
              status: "suspended"
            }}
          : {{}};
      }}
    }};
  }}
  if (String(url).endsWith(
    "/wallet-identities/wallet_identity_suspended/disconnect-state"
  )) {{
    return {{
      ok: true,
      status: 200,
      async json() {{
        return {{
          wallet_identity: {{
            wallet_identity_id: "wallet_identity_suspended",
            wallet_address: walletC,
            status: "suspended"
          }},
          disconnect_complete: false,
          asset_allowances: [],
          approval_targets: {{}},
          network_configs: accountState.network_configs
        }};
      }}
    }};
  }}
  if (String(url).endsWith("/cancel")) {{
    cancelRequests.push(
      String(url).split("/wallet-challenges/")[1].split("/cancel")[0]
    );
    return {{
      ok: true,
      status: 200,
      async json() {{ return {{cancelled: true}}; }}
    }};
  }}
  if (scenario === "post_verify_refresh_failure" && verifyRequests.length) {{
    return {{
      ok: false,
      status: 503,
      async json() {{ return {{detail: "account refresh unavailable"}}; }}
    }};
  }}
  if (
    [
      "stale_authenticated_response_after_lock",
      "stale_account_session_expired_response"
    ].includes(scenario) &&
    String(url).includes("/allowances/")
  ) {{
    return {{
      ok: true,
      status: 200,
      async json() {{ return validGuardAllowance; }}
    }};
  }}
  if (
    [
      "stale_authenticated_response_after_lock",
      "stale_account_session_expired_response"
    ].includes(scenario)
  ) {{
    accountStateFetchCount += 1;
    if (accountStateFetchCount === 1) {{
      return await new Promise((resolve) => {{
        releaseStaleAuthenticatedResponse = () => resolve({{
          ok: true,
          status: 200,
          async json() {{ return accountState; }}
        }});
      }});
    }}
    return scenario === "stale_account_session_expired_response"
      ? {{
          ok: false,
          status: 410,
          async json() {{
            return {{detail: "account session expired"}};
          }}
        }}
      : {{
          ok: false,
          status: 401,
          async json() {{
            return {{detail: "wallet authentication required"}};
          }}
        }};
  }}
  if (
    restoredSessionScenarios.has(scenario) ||
    scenario === "locked_account_state"
  ) {{
    return {{
      ok: false,
      status: 401,
      async json() {{
        return {{detail: "wallet authentication required"}};
      }}
    }};
  }}
  if (
    scenario === "suspended_cleanup_reauth" &&
    verifyRequests.length
  ) {{
    return {{
      ok: false,
      status: 401,
      async json() {{
        return {{detail: "wallet authentication required"}};
      }}
    }};
  }}
  return {{
    ok: true,
    status: 200,
    async json() {{ return accountState; }}
  }};
}};
""" + javascript + """

const tick = () => new Promise((resolve) => setTimeout(resolve, 0));
setTimeout(async () => {
  if (scenario === "renders_only_current_mandate") {
    await tick();
    await tick();
    console.log(JSON.stringify({
      html: document.querySelector("#grant-details").innerHTML,
      editorOpen: elements["#permission-editor"].open,
      currentCount: document.querySelectorAll(
        "#grant-details .grant-ledger"
      ).length
    }));
    return;
  }
  if (
    [
      "stale_authenticated_response_after_lock",
      "stale_account_session_expired_response"
    ].includes(scenario)
  ) {
    for (let attempt = 0; attempt < 100; attempt += 1) {
      if (releaseStaleAuthenticatedResponse) break;
      await tick();
    }
    if (!releaseStaleAuthenticatedResponse) {
      throw new Error("Initial account request was not deferred");
    }
    await elements["#refresh-audit"].listeners.click();
    const lockedBeforeStaleResponse = {
      refreshDisabled: elements["#refresh-allowances"].disabled,
      walletState: elements["#wallet-state"].textContent,
      permissionState: elements["#permission-state"].textContent,
      polygonState: elements["#polygon-state"].textContent,
      baseState: elements["#base-state"].textContent
    };
    releaseStaleAuthenticatedResponse();
    await tick();
    await tick();
    const stateAfterStaleResponse = {
      refreshDisabled: elements["#refresh-allowances"].disabled,
      walletState: elements["#wallet-state"].textContent,
      permissionState: elements["#permission-state"].textContent,
      polygonState: elements["#polygon-state"].textContent,
      baseState: elements["#base-state"].textContent
    };
    const fetchCountBeforeRefresh = fetchCalls.length;
    await elements["#refresh-allowances"].listeners.click();
    await tick();
    console.log(JSON.stringify({
      lockedBeforeStaleResponse,
      stateAfterStaleResponse,
      pageStatus: elements["#page-status"].textContent,
      refreshFetchCount: fetchCalls.length - fetchCountBeforeRefresh,
      allowanceRefreshFetches: fetchCalls.filter(
        (item) => item.url.includes("/allowances/")
      )
    }));
    return;
  }
  if (accountStateGuardScenarios.has(scenario)) {
    await tick();
    await tick();
    const fetchCountBeforeRefresh = fetchCalls.length;
    await elements["#refresh-allowances"].listeners.click();
    await tick();
    console.log(JSON.stringify({
      refreshDisabled: elements["#refresh-allowances"].disabled,
      walletState: elements["#wallet-state"].textContent,
      refreshFetchCount: fetchCalls.length - fetchCountBeforeRefresh,
      allowanceRefreshFetches: fetchCalls.filter(
        (item) => item.url.includes("/allowances/")
      )
    }));
    return;
  }
  const providerButtons = elements["#wallet-provider-options"].children.filter(
    (item) => item.listeners.click
  );
  const betaButton = providerButtons.find(
    (item) => item.dataset.providerUuid === "beta"
  );
  await betaButton.listeners.click();
  await tick();

  const failureScenarios = [
    "account_access_rejected", "empty_accounts", "invalid_accounts",
    "cancel_pending_provider"
  ];
  if (
    !failureScenarios.includes(scenario) &&
    ![
      "accounts_without_choice",
      "restored_session",
      "restored_session_cancel",
      "restored_session_retry",
      "restored_then_wallet_disconnected"
    ].includes(scenario)
  ) {
    const walletCButton = elements["#wallet-account-options"].children.find(
      (item) => item.textContent === walletC
    );
    walletCButton.listeners.click();
  }

  if (scenario === "restored_then_wallet_disconnected") {
    providerAccountState.beta = [];
    const freshBetaButton = elements["#wallet-provider-options"].children.find(
      (item) => item.dataset.providerUuid === "beta"
    );
    await freshBetaButton.listeners.click();
    await tick();
  }

  if (scenario === "restored_session_retry") {
    const blockedBetaButton = elements["#wallet-provider-options"].children.find(
      (item) => item.dataset.providerUuid === "beta"
    );
    await blockedBetaButton.listeners.click();
    await tick();
  }

  if (scenario === "listener_cleanup_throws") {
    try {
      betaProvider.emit("accountsChanged");
    } catch (_error) {}
  }

  if ([
    "cancel_after_selection", "cancel_then_reselect",
    "revoke_unsupported", "revoke_still_authorized",
    "restored_session_cancel"
  ].includes(scenario)) {
    await elements["#cancel-wallet-selection"].listeners.click();
    await tick();
  }

  if (scenario === "cancel_then_reselect") {
    const freshBetaButton = elements["#wallet-provider-options"].children.find(
      (item) => item.dataset.providerUuid === "beta"
    );
    await freshBetaButton.listeners.click();
    await tick();
  }

  if ([
    "bind_second_account", "signature_rejected", "post_verify_refresh_failure",
    "accounts_changed", "chain_changed", "disconnected",
    "cancel_during_signature", "suspended_cleanup_reauth"
  ].includes(scenario)) {
    await elements["#connect-wallet"].listeners.click({
      currentTarget: elements["#connect-wallet"]
    });
    await tick();
  }

  const currentProviderButton = elements["#wallet-provider-options"].children.find(
    (item) => item.attributes["aria-pressed"] === "true"
  );
  const selectedAccountButton = elements["#wallet-account-options"].children.find(
    (item) => item.attributes["aria-checked"] === "true"
  );
  const alphaIcon = providerButtons[0].children[0].children.find(
    (item) => item.tagName === "IMG"
  );
  alphaIcon?.listeners.error?.();
  const providerIcons = providerButtons.map((item) => {
    const iconSlot = item.children[0];
    const image = iconSlot.children.find((child) => child.tagName === "IMG");
    const fallback = iconSlot.children.find(
      (child) => child.className === "wallet-choice-icon-fallback"
    );
    return {
      imageSource: image?.src || null,
      imageHidden: image?.hidden ?? null,
      fallback: fallback?.textContent || null
    };
  });
  console.log(JSON.stringify({
    providerNames: providerButtons.map(
      (item) => item.children[1].children[0].textContent
    ),
    providerIcons,
    accountAddresses: elements["#wallet-account-options"].children
      .filter((item) => item.listeners.click)
      .map((item) => item.textContent),
    selectedProvider: currentProviderButton?.dataset.providerUuid || null,
    selectedAddress: selectedAccountButton?.textContent || null,
    challengeRequests,
    verifyRequests,
    cancelRequests,
    providerCalls,
    bindDisabled: elements["#connect-wallet"].disabled,
    cancelDisabled: elements["#cancel-wallet-selection"].disabled,
    status: elements["#wallet-selection-state"].textContent,
    pageStatus: elements["#page-status"].textContent,
    recoveryHidden: elements["#resume-wallet-disconnect"].hidden,
    recoveryMessage: elements["#wallet-disconnect-state"].textContent,
    storage: Object.fromEntries(storageValues)
  }));
}, 20);
"""
    result = subprocess.run(
        ["node", "-"],
        input=harness,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def run_allowance_console(javascript: str, scenario: str) -> dict:
    harness = f"""
const scenario = {json.dumps(scenario)};
const polygon = "{POLYGON}";
const base = "{BASE}";
const amoy = "{AMOY_NETWORK}";
const token = "{TOKEN}";
const baseToken = "{BASE_TOKEN}";
const amoyToken = "{AMOY_NETWORK_CONFIG['token_address']}";
const spender = "{SPENDER}";
const baseSpender = "{BASE_SPENDER}";
const allowanceTotal = [
  "allowance_insufficient",
  "allowance_upgrade",
  "allowance_sufficient"
].includes(scenario) ? "25" : "15";
const configuredSingle = scenario === "allowance_insufficient" ? "2" : "5";
const walletA = "0x" + "a".repeat(40);
const walletB = "0x" + "b".repeat(40);
const walletC = "0x" + "c".repeat(40);
const makeElement = (extra = {{}}) => Object.assign({{
  attributes: {{}},
  classList: {{add() {{}}, toggle() {{}}}},
  dataset: {{}},
  disabled: true,
  children: [],
  href: "",
  innerHTML: "",
  listeners: {{}},
  open: false,
  src: "",
  textContent: "",
  value: "",
  addEventListener(type, listener) {{ this.listeners[type] = listener; }},
  append(...children) {{ this.children.push(...children); }},
  closest() {{ return null; }},
  querySelector() {{ return makeElement(); }},
  removeAttribute(name) {{ delete this[name]; }},
  replaceChildren(...children) {{ this.children = children; }},
  setAttribute(name, value) {{ this.attributes[name] = String(value); }},
  showModal() {{ this.open = true; }},
  close() {{ this.open = false; }}
}}, extra);

const polygonButton = makeElement({{dataset: {{approveNetwork: polygon}}}});
const baseButton = makeElement({{dataset: {{approveNetwork: base}}}});
const amoyButton = makeElement({{dataset: {{approveNetwork: amoy}}}});
const elements = {{}};
for (const selector of [
  "#page-status", "#wallet-state", "#wallet-details", "#permission-state",
  "#grant-details", "#polygon-state", "#base-state", "#polygon-token",
  "#polygon-spender", "#base-token", "#base-spender", "#audit-list",
  "#polygon-amoy-state", "#polygon-amoy-token", "#polygon-amoy-spender",
  "#connect-wallet", "#cancel-wallet-selection", "#permission-form",
  "#resume-wallet-disconnect", "#wallet-disconnect-state",
  "#refresh-allowances", "#refresh-audit",
  "#wallet-provider-options", "#wallet-account-options", "#wallet-selection-state",
  "#total-limit", "#transaction-limit", "#hourly-limit", "#daily-limit",
  "#expiry-days", "#trust-clink", "#trust-registry", "#notification-mode",
  "#permission-editor", "#permission-editor-label", "#new-limit-settings",
  "#permission-submit", "#limit-help", "#allowance-setup",
  "#allowance-setup-label",
  "#network-ledger",
  "#verify-pending-allowance", "#pending-allowance-state",
  "#wallet-session-dialog", "#wallet-session-qr", "#wallet-session-open",
  "#wallet-session-cancel"
]) elements[selector] = makeElement();
elements["#total-limit"].value = "25";
elements["#transaction-limit"].value = "0.1";
elements["#hourly-limit"].value = "1";
elements["#daily-limit"].value = "5";
elements["#expiry-days"].value = "30";
elements["#trust-clink"].checked = true;
elements["#trust-registry"].checked = true;
elements["#notification-mode"].value = "silent_under_limits";

global.document = {{
  cookie: "clink_account_csrf=test-csrf",
  createElement() {{ return makeElement(); }},
  querySelector(selector) {{
    if (selector === `[data-approve-network="${{polygon}}"]`) return polygonButton;
    if (selector === `[data-approve-network="${{base}}"]`) return baseButton;
    if (selector === `[data-approve-network="${{amoy}}"]`) return amoyButton;
    return elements[selector];
  }},
  querySelectorAll(selector) {{
    if (selector === "[data-approve-network]") {{
      return scenario === "amoy"
        ? [amoyButton]
        : [polygonButton, baseButton];
    }}
    if (selector === "[data-network-state]") {{
      return scenario === "amoy"
        ? [elements["#polygon-amoy-state"]]
        : [elements["#polygon-state"], elements["#base-state"]];
    }}
    if (selector === "[data-network-token], [data-network-spender]") {{
      return scenario === "amoy"
        ? [elements["#polygon-amoy-token"], elements["#polygon-amoy-spender"]]
        : [
            elements["#polygon-token"],
            elements["#polygon-spender"],
            elements["#base-token"],
            elements["#base-spender"]
          ];
    }}
    return [];
  }}
}};

const state = {{
  wallet_identities: [
    {{wallet_identity_id: "wallet_identity_a", wallet_address: walletA, status: "active", verified_at: "now"}},
    {{wallet_identity_id: "wallet_identity_b", wallet_address: walletB, status: "active", verified_at: "now"}}
  ],
  spending_grants: scenario === "amoy" ? [] : [
    {{spending_grant_id: "grant_a", wallet_identity_id: scenario === "allowance_upgrade" ? "wallet_identity_b" : "wallet_identity_a", status: "active", agent_id: "hermes", max_amount_usdc: "25", daily_limit_usdc: "25", per_transaction_limit_usdc: scenario === "allowance_upgrade" ? "25" : "5", product_scopes: ["prediction_markets", "marketplace"], network_scopes: [polygon, base], asset_scopes: [token]}},
    {{spending_grant_id: "grant_b", wallet_identity_id: "wallet_identity_b", status: "active", agent_id: "hermes", max_amount_usdc: allowanceTotal, daily_limit_usdc: "10", per_transaction_limit_usdc: "5", product_scopes: ["prediction_markets", "marketplace"], network_scopes: [polygon, base], asset_scopes: [token]}}
  ],
  current_spending_mandate: scenario === "amoy" ? null : [
    "grant", "mandate_challenge_changed"
  ].includes(scenario) ? null : {{
    spending_grant_id: "grant_b",
    wallet_identity_id: "wallet_identity_b",
    status: "active",
    agent_id: "hermes",
    max_amount_usdc: allowanceTotal,
    daily_limit_usdc: ["reduce_total", "unchanged_total"].includes(scenario) ? allowanceTotal : "10",
    per_transaction_limit_usdc: ["reduce_total", "unchanged_total"].includes(scenario) ? allowanceTotal : configuredSingle,
    hourly_limit_usdc: ["reduce_total", "unchanged_total"].includes(scenario) ? allowanceTotal : "10",
    product_scopes: ["prediction_markets", "marketplace"],
    venue_scopes: ["polymarket", "clink_marketplace"],
    merchant_scopes: [],
    merchant_trust_scopes: ["clink_verified", "registry_verified"],
    notification_mode: "silent_under_limits",
    network_scopes: [polygon, base],
    asset_scopes: scenario === "base_approval" ? [baseToken] : [token],
    starts_at: "2026-07-15T12:00:00Z",
    expires_at: "2026-07-22T12:00:00Z",
    limits_usdc: {{
      per_transaction: ["reduce_total", "unchanged_total"].includes(scenario) ? allowanceTotal : configuredSingle,
      rolling_hour: ["reduce_total", "unchanged_total"].includes(scenario) ? allowanceTotal : "10",
      daily: ["reduce_total", "unchanged_total"].includes(scenario) ? allowanceTotal : "10",
      total: allowanceTotal
    }},
    used_usdc: {{rolling_hour: "0", daily: "0", total: "0"}},
    reserved_usdc: {{rolling_hour: "0", daily: "0", total: "0"}},
    remaining_usdc: {{rolling_hour: "10", daily: "10", total: allowanceTotal}}
  }},
  asset_allowances: scenario === "amoy" ? [] : [
    "allowance_insufficient",
    "allowance_upgrade",
    "allowance_sufficient"
  ].includes(scenario) ? [{{
    asset_allowance_id: "asset_allowance_polygon",
    wallet_identity_id: "wallet_identity_b",
    network: polygon,
    token_address: token,
    token_symbol: "USDC",
    token_decimals: 6,
    spender_address: spender,
    approved_amount_atomic: scenario === "allowance_sufficient"
      ? "25000000"
      : scenario === "allowance_insufficient"
        ? "3000000"
        : "500000",
    observed_allowance_atomic: scenario === "allowance_sufficient"
      ? "25000000"
      : scenario === "allowance_insufficient"
        ? "3000000"
        : "500000",
    allowance_tx_hash: null,
    status: "active",
    confirmed_block: null,
    last_chain_check_at: null,
    created_at: "now",
    updated_at: "now"
  }}].concat(scenario === "allowance_sufficient" ? [{{
    asset_allowance_id: "asset_allowance_base",
    wallet_identity_id: "wallet_identity_b",
    network: base,
    token_address: baseToken,
    token_symbol: "USDC",
    token_decimals: 6,
    spender_address: baseSpender,
    approved_amount_atomic: "25000000",
    observed_allowance_atomic: "25000000",
    allowance_tx_hash: null,
    status: "active",
    confirmed_block: null,
    last_chain_check_at: null,
    created_at: "now",
    updated_at: "now"
  }}] : []) : [],
  approval_targets: scenario === "amoy" ? {{
    [amoy]: {{token_address: amoyToken, spender_address: spender}}
  }} : scenario === "unsupported" ? {{}} : {{
    [polygon]: {{token_address: token, spender_address: spender}},
    [base]: {{
      token_address: ["grant", "allowance_sufficient", "base_approval"].includes(scenario)
        ? baseToken
        : token,
      spender_address: ["grant", "allowance_sufficient", "base_approval"].includes(scenario)
        ? baseSpender
        : spender
    }}
  }},
  network_configs: scenario === "amoy" ? {{
    [amoy]: {{
      chain_id: 80002,
      required_confirmations: 3,
      token_symbol: "USDC",
      token_decimals: 6
    }}
  }} : {{
    [polygon]: {{
      chain_id: 137,
      required_confirmations: 3,
      token_symbol: "USDC",
      token_decimals: 6
    }},
    [base]: {{
      chain_id: 8453,
      required_confirmations: 2,
      token_symbol: "USDC",
      token_decimals: 6
    }}
  }},
  recent_audit_summary: [],
  allowance_recovery: [],
  readiness: {{ready: false}}
}};
const activateAmoyState = () => {{
  state.current_spending_mandate = {{
    spending_grant_id: "grant_amoy",
    wallet_identity_id: "wallet_identity_b",
    status: "active",
    agent_id: "hermes",
    max_amount_usdc: "25",
    daily_limit_usdc: "25",
    per_transaction_limit_usdc: "25",
    hourly_limit_usdc: "25",
    product_scopes: ["prediction_markets", "marketplace"],
    venue_scopes: ["polymarket", "clink_marketplace"],
    merchant_scopes: [],
    merchant_trust_scopes: ["clink_verified", "registry_verified"],
    notification_mode: "silent_under_limits",
    network_scopes: [amoy],
    asset_scopes: [amoyToken],
    starts_at: "2026-07-15T12:00:00Z",
    expires_at: "2026-07-22T12:00:00Z",
    limits_usdc: {{
      per_transaction: "25",
      rolling_hour: "25",
      daily: "25",
      total: "25"
    }},
    used_usdc: {{rolling_hour: "0", daily: "0", total: "0"}},
    reserved_usdc: {{rolling_hour: "0", daily: "0", total: "0"}},
    remaining_usdc: {{rolling_hour: "25", daily: "25", total: "25"}}
  }};
  state.asset_allowances = [{{
    asset_allowance_id: "asset_allowance_amoy",
    wallet_identity_id: "wallet_identity_b",
    network: amoy,
    token_address: amoyToken,
    token_symbol: "USDC",
    token_decimals: 6,
    spender_address: spender,
    approved_amount_atomic: "0",
    observed_allowance_atomic: "0",
    allowance_tx_hash: null,
    status: "active",
    confirmed_block: null,
    last_chain_check_at: null,
    created_at: "now",
    updated_at: "now"
  }}];
}};

const calls = [];
const grantRequests = [];
const reduceRequests = [];
const switchRequests = [];
const confirmationBlockNumbers = [];
let verification = null;
let sentTransaction = null;
let personalSignRequest = null;
let sendCount = 0;
let attemptBeginCount = 0;
let attemptSubmittedCount = 0;
let attemptRejectedCount = 0;
let attemptRecord = null;
const attemptBeginRequests = [];
const attemptSubmittedRequests = [];
const attemptRejectedRequests = [];
const httpEvents = [];
const attemptNow = "2026-07-15T12:00:00.000Z";
const makeAttemptRecord = (payload, status = "awaiting_wallet", hash = null) => ({{
  attempt_id: "attempt_1",
  user_id: "user_1",
  wallet_identity_id: payload.wallet_identity_id,
  network: payload.network,
  token_address: payload.token_address,
  spender_address: payload.spender_address,
  amount_atomic: payload.amount_atomic,
  allowance_tx_hash: hash,
  status,
  reason_code: null,
  created_at: attemptNow,
  updated_at: attemptNow,
  next_check_at: status === "pending" ? attemptNow : null
}});
let releaseFirstSend = null;
let verificationCount = 0;
let releaseFirstCoreVerify = null;
let changedAfterSendEmitted = false;
let chainReadCount = 0;
let concurrentSwitchCount = 0;
const selectedAccount = scenario === "mismatch" ? walletC : walletB;
const requestedProviderAccounts = [...new Set([walletA, selectedAccount])];
let exposedProviderAccounts = [];
const providerListeners = {{}};
const provider = {{
  id: "test-wallet",
  name: "Test Wallet",
  connected() {{ return exposedProviderAccounts.length > 0; }},
  async disconnect() {{
    calls.push("disconnect");
    exposedProviderAccounts = [];
  }},
  async request(request) {{
    calls.push(request.method);
    if (request.method === "eth_accounts") return exposedProviderAccounts;
    if (request.method === "eth_requestAccounts") {{
      exposedProviderAccounts = requestedProviderAccounts;
      return exposedProviderAccounts;
    }}
    if (request.method === "personal_sign") {{
      personalSignRequest = request;
      return "0xsigned";
    }}
    if (request.method === "wallet_switchEthereumChain") {{
      if (scenario === "switch_failure") throw new Error("switch rejected");
      if (scenario === "chain_changed_on_switch") this.emit("chainChanged");
      if (scenario === "concurrent_approve") concurrentSwitchCount += 1;
      if (["amoy", "base_approval"].includes(scenario)) {{
        switchRequests.push(request.params[0]);
      }}
      return null;
    }}
    if (request.method === "eth_chainId") {{
      chainReadCount += 1;
      if (scenario === "wrong_chain") return "0x1";
      if (scenario === "delayed_chain_changed" && chainReadCount === 2) {{
        this.emit("chainChanged");
      }}
      if (scenario === "concurrent_approve") {{
        if (concurrentSwitchCount === 1) return "0x89";
        return chainReadCount % 2 === 1 ? "0x89" : "0x2105";
      }}
      if (scenario === "amoy") return "0x13882";
      if (scenario === "base_approval") return "0x2105";
      return "0x89";
    }}
    if (request.method === "eth_sendTransaction") {{
      sendCount += 1;
      httpEvents.push("send");
      sentTransaction = request.params[0];
      if (scenario === "concurrent_approve" && sendCount === 1) {{
        return await new Promise((resolve) => {{
          releaseFirstSend = () => resolve("0x" + "4".repeat(64));
        }});
      }}
      if ([
        "invalid_hash_post_send_uncertain",
        "invalid_hash_storage_write_failure",
        "invalid_hash_lock_reauth"
      ].includes(scenario)) {{
        return "malformed-provider-secret-transaction-result";
      }}
      return "0x" + "4".repeat(64);
    }}
    if (request.method === "eth_getTransactionReceipt") {{
      httpEvents.push("receipt");
      if (scenario === "provider_confirmation_failure") {{
        throw new Error("provider receipt unavailable");
      }}
      if (scenario === "changed_after_send" && !changedAfterSendEmitted) {{
        changedAfterSendEmitted = true;
        this.emit("accountsChanged");
      }}
      return {{blockNumber: "0x64"}};
    }}
    if (request.method === "eth_blockNumber") {{
      let block = "0x66";
      if (scenario === "amoy") {{
        block = ["0x64", "0x65", "0x66"][
          Math.min(confirmationBlockNumbers.length, 2)
        ];
      }} else if (scenario === "base_approval") {{
        block = ["0x64", "0x65"][
          Math.min(confirmationBlockNumbers.length, 1)
        ];
      }}
      if (["amoy", "base_approval"].includes(scenario)) {{
        confirmationBlockNumbers.push(block);
      }}
      return block;
    }}
    throw new Error(`Unexpected provider method ${{request.method}}`);
  }},
  on(eventName, listener) {{
    (providerListeners[eventName] ||= new Set()).add(listener);
  }},
  removeListener(eventName, listener) {{
    providerListeners[eventName]?.delete(listener);
  }},
  emit(eventName) {{
    for (const listener of [...(providerListeners[eventName] || [])]) listener();
  }}
}};

const windowListeners = {{}};
const storageValues = new Map();
const currentPath = scenario === "cross_path_record" ? "/account/current" : "/account";
const storageKey = (pathname, walletIdentityId) =>
  "clink.account.pending_allowance.v1." +
  encodeURIComponent(pathname) + "." + walletIdentityId;
const uncertainStorageKey = (_pathname, walletIdentityId) =>
  "clink.account.allowance_post_send_uncertain.v2." + walletIdentityId;
const legacyUncertainStorageKey = (pathname, walletIdentityId) =>
  "clink.account.allowance_post_send_uncertain.v1." +
  encodeURIComponent(pathname) + "." + walletIdentityId;
const oldPendingAllowance = {{
  wallet_identity_id: "wallet_identity_b",
  network: polygon,
  token_address: token,
  spender_address: spender,
  allowance_tx_hash: "0x" + "4".repeat(64)
}};
const newerPendingAllowance = {{
  wallet_identity_id: "wallet_identity_b",
  network: base,
  token_address: baseToken,
  spender_address: baseSpender,
  allowance_tx_hash: oldPendingAllowance.allowance_tx_hash
}};
if ([
  "reload_verify", "reload_invalid_storage", "stale_verify_cleanup"
].includes(scenario)) {{
  storageValues.set(storageKey(currentPath, "wallet_identity_b"), JSON.stringify({{
    ...oldPendingAllowance,
    ...(scenario === "reload_invalid_storage" ? {{provider: "must-not-load"}} : {{}})
  }}));
}}
if (scenario === "cross_path_record") {{
  storageValues.set(
    storageKey("/account/other", "wallet_identity_b"),
    JSON.stringify(oldPendingAllowance)
  );
}}
if (scenario === "inactive_identity_storage") {{
  storageValues.set(
    storageKey(currentPath, "wallet_identity_inactive"),
    JSON.stringify({{...oldPendingAllowance, wallet_identity_id: "wallet_identity_inactive"}})
  );
}}
if (scenario === "key_record_mismatch") {{
  storageValues.set(
    storageKey(currentPath, "wallet_identity_b"),
    JSON.stringify({{...oldPendingAllowance, wallet_identity_id: "wallet_identity_a"}})
  );
}}
if ([
  "invalid_hash_same_path_reload",
  "invalid_hash_sentinel_read_failure"
].includes(scenario)) {{
  storageValues.set(
    uncertainStorageKey(currentPath, "wallet_identity_b"),
    "allowance_post_send_uncertain"
  );
}}
if (scenario === "uncertain_cross_path") {{
  storageValues.set(
    legacyUncertainStorageKey("/account/other", "wallet_identity_b"),
    "allowance_post_send_uncertain"
  );
}}
if (scenario === "uncertain_inactive_identity") {{
  storageValues.set(
    legacyUncertainStorageKey(currentPath, "wallet_identity_inactive"),
    "allowance_post_send_uncertain"
  );
}}
let removeItemCalls = 0;
let probeRemoveItemCalls = 0;
const probeMarkers = [];
let storageUnavailable = false;
const schedule = ["amoy", "base_approval"].includes(scenario)
  ? (callback, _delay) => setTimeout(callback, 0)
  : setTimeout;
const sessionStorage = {{
  get length() {{
    if (storageUnavailable) throw new Error("sessionStorage unavailable");
    return storageValues.size;
  }},
  key(index) {{
    if (storageUnavailable) throw new Error("sessionStorage unavailable");
    return [...storageValues.keys()][index] ?? null;
  }},
  getItem(key) {{
    if (storageUnavailable) throw new Error("sessionStorage unavailable");
    if (
      scenario === "invalid_hash_sentinel_read_failure" &&
      (
        key.startsWith("clink.account.allowance_post_send_uncertain.v1.") ||
        key.startsWith("clink.account.allowance_post_send_uncertain.v2.")
      )
    ) {{
      throw new Error("uncertain sentinel read failed");
    }}
    return storageValues.get(key) ?? null;
  }},
  setItem(key, value) {{
    if (storageUnavailable) throw new Error("sessionStorage unavailable");
    if (
      scenario === "invalid_hash_storage_write_failure" &&
      (
        key.startsWith("clink.account.allowance_post_send_uncertain.v1.") ||
        key.startsWith("clink.account.allowance_post_send_uncertain.v2.")
      )
    ) {{
      throw new Error("uncertain sentinel write failed");
    }}
    if (
      [
        "storage_write_failure_refresh_core_failure",
        "storage_write_failure_lock_reauth_core_failure"
      ].includes(scenario) &&
      key.includes("pending_allowance") &&
      !key.includes("pending_allowance_probe")
    ) {{
      throw new Error("sessionStorage record write failed");
    }}
    if (key.includes("pending_allowance_probe")) {{
      probeMarkers.push(String(value));
    }}
    storageValues.set(key, String(value));
  }},
  removeItem(key) {{
    if (storageUnavailable) throw new Error("sessionStorage unavailable");
    if (
      scenario === "persistent_probe_remove_failure" &&
      key.includes("pending_allowance_probe")
    ) {{
      probeRemoveItemCalls += 1;
      throw new Error("sessionStorage probe cleanup failed");
    }}
    if (
      key.startsWith("clink.account.pending_allowance.v1.") ||
      key.startsWith("clink.account.pending_allowance.v2.")
    ) {{
      removeItemCalls += 1;
      if (scenario === "core_success_cleanup_failure") {{
        throw new Error("sessionStorage record cleanup failed");
      }}
    }}
    storageValues.delete(key);
  }}
}};
global.window = {{
  location: {{origin: "https://clink.test", pathname: currentPath}},
  sessionStorage,
  setTimeout: schedule,
  addEventListener(type, listener) {{
    (windowListeners[type] ||= []).push(listener);
  }},
  dispatchEvent(event) {{
    if (
      event.type !== "eip6963:requestProvider" ||
      ["missing_provider", "reload_verify", "stale_verify_cleanup"].includes(
        scenario
      )
    ) return;
    for (const listener of windowListeners["eip6963:announceProvider"] || []) {{
      listener({{detail: {{
        info: {{
          uuid: "test-wallet",
          name: "Test Wallet",
          icon: "",
          rdns: "test.wallet"
        }},
        provider
      }}}});
    }}
  }}
}};
let accountFetchCount = 0;
let walletVerifyCount = 0;
let releasePostCleanupLoad = null;
global.fetch = async (url, options = {{}}) => {{
  if (String(url).endsWith("/wallet-challenge")) {{
    return {{
      ok: true,
      status: 200,
      async json() {{
        return {{
          session_id: "wallet_session",
          message_to_sign: "wallet proof"
        }};
      }}
    }};
  }}
  if (String(url).endsWith("/wallet-verify")) {{
    walletVerifyCount += 1;
    return {{ok: true, status: 200, async json() {{ return {{}}; }}}};
  }}
  if (String(url).endsWith("/grants")) {{
    const body = JSON.parse(options.body);
    grantRequests.push(body);
    if (!body.challenge_session_id) {{
      if (scenario === "mandate_challenge_changed") provider.emit("accountsChanged");
      return {{ok: true, async json() {{ return {{session_id: "grant_session", message_to_sign: "grant terms"}}; }}}};
    }}
    if (scenario === "amoy") activateAmoyState();
    return {{ok: true, async json() {{ return {{}}; }}}};
  }}
  if (String(url).endsWith("/grants/grant_b/reduce")) {{
    reduceRequests.push(JSON.parse(options.body));
    return {{ok: true, async json() {{ return {{}}; }}}};
  }}
  if (
    String(url).endsWith("/allowances/attempts") &&
    options.method === "POST"
  ) {{
    attemptBeginCount += 1;
    const body = JSON.parse(options.body);
    attemptBeginRequests.push(body);
    httpEvents.push("begin");
    attemptRecord = makeAttemptRecord(body);
    if (scenario === "session_expired_during_prepare") {{
      await elements["#refresh-audit"].listeners.click();
    }}
    return {{
      ok: true,
      status: 200,
      async json() {{ return {{created: true, attempt: attemptRecord}}; }}
    }};
  }}
  if (
    /\/allowances\/attempts\/[^/]+\/submitted$/.test(String(url)) &&
    options.method === "POST"
  ) {{
    attemptSubmittedCount += 1;
    const body = JSON.parse(options.body);
    attemptSubmittedRequests.push(body);
    httpEvents.push("submitted");
    attemptRecord = makeAttemptRecord(
      attemptRecord,
      "pending",
      body.allowance_tx_hash
    );
    return {{
      ok: true,
      status: 200,
      async json() {{ return attemptRecord; }}
    }};
  }}
  if (
    /\/allowances\/attempts\/[^/]+\/rejected$/.test(String(url)) &&
    options.method === "POST"
  ) {{
    attemptRejectedCount += 1;
    const body = JSON.parse(options.body);
    attemptRejectedRequests.push(body);
    httpEvents.push("rejected");
    attemptRecord = makeAttemptRecord(
      attemptRecord,
      "rejected",
      null
    );
    return {{
      ok: true,
      status: 200,
      async json() {{ return attemptRecord; }}
    }};
  }}
  if (String(url).endsWith("/allowances/verify")) {{
    verificationCount += 1;
    verification = JSON.parse(options.body);
    if (scenario === "allowance_upgrade") {{
      state.asset_allowances[0].approved_amount_atomic = "25000000";
      state.asset_allowances[0].observed_allowance_atomic = "25000000";
    }}
    if (scenario === "amoy") {{
      state.asset_allowances[0].approved_amount_atomic = "25000000";
      state.asset_allowances[0].observed_allowance_atomic = "25000000";
    }}
    if (scenario === "stale_verify_cleanup") {{
      storageValues.set(
        storageKey(currentPath, "wallet_identity_b"),
        JSON.stringify(newerPendingAllowance)
      );
      await elements["#refresh-audit"].listeners.click();
    }}
    if (
      scenario === "core_verify_failure" ||
      scenario === "storage_write_failure_refresh_core_failure" ||
      scenario === "storage_write_failure_lock_reauth_core_failure" ||
      (
        scenario === "core_verify_failure_then_retry" &&
        verificationCount === 1
      )
    ) {{
      return {{
        ok: false,
        status: 503,
        async json() {{ return {{detail: "Core verification temporarily unavailable"}}; }}
      }};
    }}
    if (
      scenario === "manual_verify_during_auto_verify" &&
      verificationCount === 1
    ) {{
      await new Promise((resolve) => {{
        releaseFirstCoreVerify = resolve;
      }});
    }}
    return {{ok: true, async json() {{ return {{}}; }}}};
  }}
  accountFetchCount += 1;
  if (
    scenario === "expired_session_reauth" &&
    accountFetchCount === 1
  ) {{
    return {{
      ok: false,
      status: 410,
      async json() {{
        return {{detail: "account session expired"}};
      }}
    }};
  }}
  if (
    scenario === "session_expired_during_prepare" &&
    accountFetchCount >= 2
  ) {{
    return {{
      ok: false,
      status: 410,
      async json() {{
        return {{detail: "account session expired"}};
      }}
    }};
  }}
  if (
    [
      "storage_write_failure_lock_reauth_core_failure",
      "invalid_hash_lock_reauth"
    ].includes(scenario) &&
    accountFetchCount === 2
  ) {{
    return {{
      ok: false,
      status: 401,
      async json() {{ return {{detail: "wallet authentication required"}}; }}
    }};
  }}
  if (scenario === "stale_verify_cleanup" && accountFetchCount === 3) {{
    return await new Promise((resolve) => {{
      releasePostCleanupLoad = () => resolve({{
        ok: true,
        async json() {{ return state; }}
      }});
    }});
  }}
  return {{ok: true, async json() {{ return state; }}}};
}};
""" + javascript + """

setTimeout(async () => {
  const tick = () => new Promise((resolve) => setTimeout(resolve, 0));
  const waitUntil = async (predicate) => {
    for (let attempt = 0; attempt < 100; attempt += 1) {
      if (predicate()) return;
      await tick();
    }
    throw new Error("Timed out waiting for browser harness condition");
  };
  const initialCalls = [...calls];
  if (![
    "missing_provider", "discovery", "reload_verify", "stale_verify_cleanup"
  ].includes(scenario)) {
    const providerButton = elements["#wallet-provider-options"].children.find(
      (item) => item.dataset.providerUuid === "test-wallet"
    );
    await providerButton.listeners.click();
    const accountButton = elements["#wallet-account-options"].children.find(
      (item) => item.textContent === selectedAccount
    );
    accountButton.listeners.click();
    await tick();
  }
  calls.length = 0;
  if (scenario === "pre_send_storage_inaccessible") {
    storageUnavailable = true;
  }
  let approvalDisabledBeforeRace = null;
  let approvalDisabledAfterFirstClick = null;
  let sendCountWhileFirstDelayed = null;
  let storageBeforeCleanupReload = null;
  let pendingMessageHiddenBeforeCleanupReload = null;
  let recoveryDisabledDuringAutoVerify = null;
  let verificationCountWhileAutoVerifyDelayed = null;
  let approvalDisabledWhileLocked = null;
  let approvalDisabledDuringReauthentication = null;
  let approvalDisabledAfterReauthentication = null;
  let recoveryHiddenWhileLocked = null;
  let recoveryHiddenAfterReauthentication = null;
  let sendCountAfterMalformedHash = null;
  let sendCountAfterBlockedRetry = null;
  let uncertainApprovalDisabledAfterMalformed = null;
  let uncertainMessageAfterMalformed = null;
  let uncertainApprovalDisabledWhileLocked = null;
  let uncertainApprovalDisabledAfterReauthentication = null;
  let uncertainMessageWhileLocked = null;
  let uncertainMessageAfterReauthentication = null;
  const probeRefreshApprovalDisabled = [];
  const probeRefreshRecoveryMessages = [];
  if (["grant", "mandate_challenge_changed", "amoy"].includes(scenario)) {
    await elements["#permission-form"].listeners.submit({
      preventDefault() {},
      currentTarget: elements["#permission-form"]
    });
    if (scenario === "amoy") {
      await waitUntil(() => amoyButton.listeners.click && !amoyButton.disabled);
      await amoyButton.listeners.click();
    }
  } else if (scenario === "reduce_total") {
    elements["#total-limit"].value = "8";
    await elements["#permission-form"].listeners.submit({
      preventDefault() {},
      currentTarget: elements["#permission-form"]
    });
  } else if (scenario === "increase_total") {
    elements["#total-limit"].value = "20";
    await elements["#permission-form"].listeners.submit({
      preventDefault() {},
      currentTarget: elements["#permission-form"]
    });
  } else if (scenario === "unchanged_total") {
    await elements["#permission-form"].listeners.submit({
      preventDefault() {},
      currentTarget: elements["#permission-form"]
    });
  } else if (scenario === "concurrent_approve") {
    approvalDisabledBeforeRace = [polygonButton.disabled, baseButton.disabled];
    const polygonClick = polygonButton.listeners.click();
    approvalDisabledAfterFirstClick = [polygonButton.disabled, baseButton.disabled];
    const baseClick = baseButton.listeners.click();
    await waitUntil(() => releaseFirstSend);
    await tick();
    sendCountWhileFirstDelayed = sendCount;
    releaseFirstSend();
    await Promise.all([polygonClick, baseClick]);
  } else if (scenario === "manual_verify_during_auto_verify") {
    const automaticVerify = polygonButton.listeners.click();
    await waitUntil(() => releaseFirstCoreVerify);
    recoveryDisabledDuringAutoVerify =
      elements["#verify-pending-allowance"].disabled;
    const manualVerify = elements["#verify-pending-allowance"].listeners.click({
      currentTarget: elements["#verify-pending-allowance"]
    });
    await tick();
    verificationCountWhileAutoVerifyDelayed = verificationCount;
    releaseFirstCoreVerify();
    await Promise.all([automaticVerify, manualVerify]);
  } else if (scenario === "base_approval") {
    await waitUntil(() => baseButton.listeners.click && !baseButton.disabled);
    await baseButton.listeners.click();
  } else if (scenario === "allowance_sufficient") {
    if (!polygonButton.disabled && polygonButton.listeners.click) {
      await polygonButton.listeners.click();
    }
  } else if (![
        "discovery", "reload_verify", "stale_verify_cleanup", "cross_path_record",
        "inactive_identity_storage", "persistent_probe_remove_failure",
        "allowance_insufficient", "expired_session_reauth"
  ].includes(scenario)) {
    await polygonButton.listeners.click();
  }
  if ([
    "invalid_hash_post_send_uncertain",
    "invalid_hash_storage_write_failure",
    "invalid_hash_lock_reauth"
  ].includes(scenario)) {
    await tick();
    sendCountAfterMalformedHash = sendCount;
    uncertainApprovalDisabledAfterMalformed = [
      polygonButton.disabled,
      baseButton.disabled
    ];
    uncertainMessageAfterMalformed =
      elements["#pending-allowance-state"].textContent;
    await polygonButton.listeners.click();
    await tick();
    sendCountAfterBlockedRetry = sendCount;
  }
  if (scenario === "invalid_hash_storage_write_failure") {
    await elements["#refresh-audit"].listeners.click();
    await tick();
    await polygonButton.listeners.click();
  }
  if (scenario === "invalid_hash_lock_reauth") {
    await elements["#refresh-audit"].listeners.click();
    await tick();
    uncertainApprovalDisabledWhileLocked = [
      polygonButton.disabled,
      baseButton.disabled
    ];
    uncertainMessageWhileLocked =
      elements["#pending-allowance-state"].textContent;
    await polygonButton.listeners.click();
    await elements["#connect-wallet"].listeners.click({
      currentTarget: elements["#connect-wallet"]
    });
    await tick();
    uncertainApprovalDisabledAfterReauthentication = [
      polygonButton.disabled,
      baseButton.disabled
    ];
    uncertainMessageAfterReauthentication =
      elements["#pending-allowance-state"].textContent;
    await polygonButton.listeners.click();
  }
  if (scenario === "expired_session_reauth") {
    await elements["#connect-wallet"].listeners.click({
      currentTarget: elements["#connect-wallet"]
    });
    await tick();
    approvalDisabledAfterReauthentication = [
      polygonButton.disabled,
      baseButton.disabled
    ];
  }
  if (scenario === "storage_write_failure_refresh_core_failure") {
    await elements["#refresh-audit"].listeners.click();
  }
  if (scenario === "storage_write_failure_lock_reauth_core_failure") {
    await elements["#refresh-audit"].listeners.click();
    await tick();
    approvalDisabledWhileLocked = [polygonButton.disabled, baseButton.disabled];
    recoveryHiddenWhileLocked =
      elements["#verify-pending-allowance"].hidden;
    await polygonButton.listeners.click();
    const reauthentication = elements["#connect-wallet"].listeners.click({
      currentTarget: elements["#connect-wallet"]
    });
    approvalDisabledDuringReauthentication = [
      polygonButton.disabled,
      baseButton.disabled
    ];
    await reauthentication;
    await tick();
    approvalDisabledAfterReauthentication = [
      polygonButton.disabled,
      baseButton.disabled
    ];
    recoveryHiddenAfterReauthentication =
      elements["#verify-pending-allowance"].hidden;
    await polygonButton.listeners.click();
    await elements["#verify-pending-allowance"].listeners.click({
      currentTarget: elements["#verify-pending-allowance"]
    });
  }
  if (scenario === "persistent_probe_remove_failure") {
    for (let refresh = 0; refresh < 2; refresh += 1) {
      await elements["#refresh-audit"].listeners.click();
      await tick();
      probeRefreshApprovalDisabled.push([
        polygonButton.disabled,
        baseButton.disabled
      ]);
      probeRefreshRecoveryMessages.push(
        elements["#pending-allowance-state"].textContent
      );
    }
    await polygonButton.listeners.click();
  }
  if (scenario === "reload_verify") {
    await elements["#verify-pending-allowance"].listeners.click?.({
      currentTarget: elements["#verify-pending-allowance"]
    });
  }
  if (scenario === "core_verify_failure_then_retry") {
    await baseButton.listeners.click();
    await elements["#verify-pending-allowance"].listeners.click({
      currentTarget: elements["#verify-pending-allowance"]
    });
  }
  if (scenario === "stale_verify_cleanup") {
    const staleVerify = elements["#verify-pending-allowance"].listeners.click({
      currentTarget: elements["#verify-pending-allowance"]
    });
    await waitUntil(() => releasePostCleanupLoad);
    storageBeforeCleanupReload = Object.fromEntries(storageValues);
    pendingMessageHiddenBeforeCleanupReload =
      elements["#pending-allowance-state"].hidden;
    releasePostCleanupLoad();
    await staleVerify;
  }
  await tick();
  console.log(JSON.stringify({
    calls,
    initial_calls: initialCalls,
    provider_choices: elements["#wallet-provider-options"].children.filter((item) => item.listeners.click).length,
    account_choices: elements["#wallet-account-options"].children.filter((item) => item.listeners.click).length,
    connect_disabled: elements["#connect-wallet"].disabled,
    disabled: polygonButton.disabled,
    approvalDisabled: [polygonButton.disabled, baseButton.disabled],
    sentTransaction,
    verification,
    grantRequests,
    networkLedger: elements["#network-ledger"].innerHTML,
    switchRequests,
    confirmationBlockNumbers,
    reduceRequests,
        personalSignRequest,
        walletVerifyCount,
        sendCount,
        attemptBeginCount,
        attemptSubmittedCount,
        attemptRejectedCount,
        attemptBeginRequests,
        attemptSubmittedRequests,
        attemptRejectedRequests,
        attemptRecordReflectedRequestKey:
          Boolean(attemptRecord && Object.prototype.hasOwnProperty.call(
            attemptRecord,
            "request_key"
          )),
        httpEvents,
        storage: Object.fromEntries(storageValues),
    approvalDisabledBeforeRace,
    approvalDisabledAfterFirstClick,
    sendCountWhileFirstDelayed,
    storageBeforeCleanupReload,
    pendingMessageHiddenBeforeCleanupReload,
    removeItemCalls,
    probeRemoveItemCalls,
    probeMarkers,
    recoveryDisabledDuringAutoVerify,
    recoveryHidden: elements["#verify-pending-allowance"].hidden,
    recoveryDisabled: elements["#verify-pending-allowance"].disabled,
    recoveryMessageHidden: elements["#pending-allowance-state"].hidden,
    recoveryMessage: elements["#pending-allowance-state"].textContent,
    pageStatus: elements["#page-status"].textContent,
    polygonState: elements["#polygon-state"].textContent,
    polygonButtonText: polygonButton.textContent,
    polygonButtonHidden: polygonButton.hidden,
    allowanceSetupOpen: elements["#allowance-setup"].open,
    approvalDisabledWhileLocked,
    approvalDisabledDuringReauthentication,
    approvalDisabledAfterReauthentication,
    recoveryHiddenWhileLocked,
    recoveryHiddenAfterReauthentication,
    sendCountAfterMalformedHash,
    sendCountAfterBlockedRetry,
    uncertainApprovalDisabledAfterMalformed,
    uncertainMessageAfterMalformed,
    uncertainApprovalDisabledWhileLocked,
    uncertainApprovalDisabledAfterReauthentication,
    uncertainMessageWhileLocked,
    uncertainMessageAfterReauthentication,
    probeRefreshApprovalDisabled,
    probeRefreshRecoveryMessages,
    verificationCountWhileAutoVerifyDelayed,
    verificationCount
  }));
}, 20);
"""
    result = subprocess.run(
        ["node", "-"],
        input=harness,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


def run_allowance_revoke_console(javascript: str, scenario: str) -> dict:
    prefix, suffix = javascript.rsplit("})();", 1)
    test_javascript = (
        prefix
        + """
globalThis.__clinkTestHooks = {
  revokeAllowance: (allowance) =>
    revokeAllowance(selectedWalletSnapshot(), allowance),
  recoverAllowanceRevocation,
  fullyDisconnectWallet:
    typeof fullyDisconnectWallet === "undefined"
      ? null
      : () => fullyDisconnectWallet("wallet_identity_b")
};
})();"""
        + suffix
    )
    harness = (
        """
const scenario = __SCENARIO__;
const polygon = __POLYGON__;
const token = __TOKEN__;
const spender = __SPENDER__;
const wallet = "0x" + "b".repeat(40);
const transactionHash = "0x" + "4".repeat(64);
const makeElement = (extra = {}) => Object.assign({
  attributes: {},
  classList: {add() {}, toggle() {}},
  className: "",
  dataset: {},
  disabled: true,
  children: [],
  hidden: false,
  href: "",
  innerHTML: "",
  listeners: {},
  open: false,
  src: "",
  tagName: "",
  textContent: "",
  value: "",
  addEventListener(type, listener) { this.listeners[type] = listener; },
  append(...children) { this.children.push(...children); },
  closest() { return null; },
  querySelector() { return makeElement(); },
  removeAttribute(name) { delete this[name]; },
  replaceChildren(...children) { this.children = children; },
  setAttribute(name, value) { this.attributes[name] = String(value); },
  showModal() { this.open = true; },
  close() { this.open = false; }
}, extra);

const permissionButton = makeElement();
const permissionForm = makeElement({
  querySelector() { return permissionButton; }
});
const polygonButton = makeElement({dataset: {approveNetwork: polygon}});
const baseButton = makeElement({dataset: {approveNetwork: "eip155:8453"}});
const elements = {};
for (const selector of [
  "#page-status", "#wallet-state", "#wallet-details", "#permission-state",
  "#grant-details", "#polygon-state", "#base-state", "#polygon-token",
  "#polygon-spender", "#base-token", "#base-spender", "#audit-list",
  "#connect-wallet", "#cancel-wallet-selection", "#refresh-allowances",
  "#resume-wallet-disconnect", "#wallet-disconnect-state",
  "#refresh-audit", "#wallet-provider-options", "#wallet-account-options",
  "#wallet-selection-state", "#total-limit", "#transaction-limit",
  "#hourly-limit", "#daily-limit", "#expiry-days", "#trust-clink",
  "#trust-registry", "#notification-mode", "#permission-editor",
  "#permission-editor-label", "#new-limit-settings", "#permission-submit",
  "#limit-help", "#allowance-setup", "#allowance-setup-label",
  "#network-ledger",
  "#verify-pending-allowance",
  "#pending-allowance-state", "#wallet-session-dialog",
  "#wallet-session-qr", "#wallet-session-open", "#wallet-session-cancel"
]) elements[selector] = makeElement();
elements["#permission-form"] = permissionForm;

global.document = {
  cookie: "clink_account_csrf=test-csrf",
  createElement(tagName) {
    return makeElement({tagName: String(tagName).toUpperCase()});
  },
  querySelector(selector) {
    if (selector === `[data-approve-network="${polygon}"]`) {
      return polygonButton;
    }
    if (selector === '[data-approve-network="eip155:8453"]') {
      return baseButton;
    }
    return elements[selector];
  },
  querySelectorAll(selector) {
    if (selector === "[data-approve-network]") {
      return [polygonButton, baseButton];
    }
    if (selector === "[data-network-state]") {
      return [elements["#polygon-state"], elements["#base-state"]];
    }
    if (selector === "[data-network-token], [data-network-spender]") {
      return [
        elements["#polygon-token"],
        elements["#polygon-spender"],
        elements["#base-token"],
        elements["#base-spender"]
      ];
    }
    return [];
  }
};

const allowance = {
  asset_allowance_id: "asset_allowance_polygon",
  wallet_identity_id: "wallet_identity_b",
  wallet_address: scenario === "wrong_address"
    ? "0x" + "c".repeat(40)
    : wallet,
  network: polygon,
  token_address: token,
  token_symbol: "USDC",
  spender_address: scenario === "wrong_target"
    ? "0x" + "5".repeat(40)
    : spender,
  approved_amount_atomic:
    scenario === "full_disconnect_zero" ? "0" : "25000000",
  observed_allowance_atomic:
    scenario === "full_disconnect_zero" ? "0" : "25000000",
  status: scenario === "full_disconnect_zero" ? "revoked" : "active"
};
const state = {
  wallet_identities: [{
    wallet_identity_id: "wallet_identity_b",
    wallet_address: wallet,
    status: "active",
    verified_at: "now"
  }],
  spending_grants: [{
    spending_grant_id: "spending_grant_b",
    wallet_identity_id: "wallet_identity_b",
    agent_id: "hermes",
    status: "active",
    max_amount_usdc: "25",
    per_transaction_limit_usdc: "0.1",
    hourly_limit_usdc: "1",
    daily_limit_usdc: "5",
    product_scopes: ["marketplace"],
    merchant_trust_scopes: ["clink_verified"],
    notification_mode: "notify_all",
    network_scopes: [polygon],
    asset_scopes: [token]
  }],
  current_spending_mandate: {
    spending_grant_id: "spending_grant_b",
    wallet_identity_id: "wallet_identity_b",
    agent_id: "hermes",
    status: "active",
    max_amount_usdc: "25",
    per_transaction_limit_usdc: "0.1",
    hourly_limit_usdc: "1",
    daily_limit_usdc: "5",
    product_scopes: ["marketplace"],
    merchant_trust_scopes: ["clink_verified"],
    notification_mode: "notify_all",
    network_scopes: [polygon],
    asset_scopes: [token],
    limits_usdc: {
      per_transaction: "0.1",
      rolling_hour: "1",
      daily: "5",
      total: "25"
    },
    used_usdc: {rolling_hour: "0", daily: "0", total: "0"},
    reserved_usdc: {rolling_hour: "0", daily: "0", total: "0"},
    remaining_usdc: {rolling_hour: "1", daily: "5", total: "25"}
  },
  asset_allowances: [allowance],
  approval_targets: {
    [polygon]: {token_address: token, spender_address: spender}
  },
  network_configs: {
    [polygon]: {
      chain_id: 137,
      required_confirmations: 3,
      token_symbol: "USDC",
      token_decimals: 6
    }
  },
  recent_audit_summary: [],
  allowance_recovery: [],
  readiness: {ready: false}
};

const providerCalls = [];
const events = [];
let sentTransaction = null;
let sendCount = 0;
let storagePresentAtRefresh = false;
let exposedAccounts =
  scenario === "full_disconnect_resume" ? [wallet] : [];
let bindDisabledDuringRecovery = null;
const providerListeners = {};
const provider = {
  id: "test-wallet",
  name: "Test Wallet",
  connected() { return exposedAccounts.length > 0; },
  async disconnect() {
    providerCalls.push("disconnect");
    exposedAccounts = [];
  },
  async request(request) {
    providerCalls.push(request.method);
    events.push(request.method);
    if (request.method === "eth_requestAccounts") {
      exposedAccounts = [wallet];
      return exposedAccounts;
    }
    if (request.method === "eth_accounts") return exposedAccounts;
    if (request.method === "wallet_revokePermissions") {
      if (scenario !== "full_disconnect_provider_failure") {
        exposedAccounts = [];
      }
      return null;
    }
    if (request.method === "wallet_switchEthereumChain") return null;
    if (request.method === "eth_chainId") {
      return scenario === "wrong_chain" ? "0x1" : "0x89";
    }
    if (request.method === "eth_sendTransaction") {
      sendCount += 1;
      sentTransaction = request.params[0];
      if (scenario === "full_disconnect_chain_rejected") {
        throw Object.assign(new Error("chain revocation rejected"), {code: 4001});
      }
      if (scenario === "invalid_hash") return "not-a-transaction-hash";
      return transactionHash;
    }
    if (request.method === "eth_getTransactionReceipt") {
      return {blockNumber: "0x64"};
    }
    if (request.method === "eth_blockNumber") return "0x66";
    throw new Error(`Unexpected provider method ${request.method}`);
  },
  on(eventName, listener) {
    (providerListeners[eventName] ||= new Set()).add(listener);
  },
  removeListener(eventName, listener) {
    providerListeners[eventName]?.delete(listener);
  }
};

const revokeStoragePrefix = "clink.account.allowance_revoke.v1.";
const revokeStorageKey =
  revokeStoragePrefix + encodeURIComponent("/account") +
  ".wallet_identity_b." + encodeURIComponent(polygon);
const revokeRecord = {
  operation: "revoke",
  wallet_identity_id: "wallet_identity_b",
  wallet_address: wallet,
  asset_allowance_id: allowance.asset_allowance_id,
  network: polygon,
  token_address: token,
  spender_address: spender,
  allowance_tx_hash: transactionHash
};
const storageValues = new Map();
if (["reload_recovery", "recovery_still_active"].includes(scenario)) {
  storageValues.set(revokeStorageKey, JSON.stringify(revokeRecord));
}
if ([
  "full_disconnect_resume",
  "full_disconnect_resume_site_already_disconnected",
  "full_disconnect_completed_recovery"
].includes(scenario)) {
  const disconnectStorageKey =
    "clink.account.wallet_disconnect.v1." +
    encodeURIComponent("/account") + ".wallet_identity_b";
  const storedPlan = {
    operation: "disconnect",
    wallet_identity_id: "wallet_identity_b",
    wallet_address: wallet,
    provider_uuid: "test-wallet",
    core_disconnected:
      scenario !== "full_disconnect_completed_recovery",
    allowances: [{
      asset_allowance_id: allowance.asset_allowance_id,
      network: polygon,
      token_address: token,
      spender_address: spender,
      observed_allowance_atomic: "25000000"
    }]
  };
  if (scenario === "full_disconnect_completed_recovery") {
    storedPlan.allowances_cleared = true;
  }
  storageValues.set(disconnectStorageKey, JSON.stringify(storedPlan));
}
const sessionStorage = {
  get length() { return storageValues.size; },
  key(index) { return [...storageValues.keys()][index] ?? null; },
  getItem(key) { return storageValues.get(key) ?? null; },
  setItem(key, value) {
    if (scenario === "storage_unavailable") {
      throw new Error("sessionStorage unavailable");
    }
    storageValues.set(key, String(value));
  },
  removeItem(key) {
    if (scenario === "storage_unavailable") {
      throw new Error("sessionStorage unavailable");
    }
    storageValues.delete(key);
  }
};
const windowListeners = {};
global.window = {
  location: {origin: "https://clink.test", pathname: "/account"},
  sessionStorage,
  setTimeout,
  addEventListener(type, listener) {
    (windowListeners[type] ||= []).push(listener);
  },
  dispatchEvent(event) {
    if (event.type !== "eip6963:requestProvider") return;
    for (const listener of windowListeners["eip6963:announceProvider"] || []) {
      listener({detail: {
        info: {
          uuid: "test-wallet",
          name: "Test Wallet",
          icon: "",
          rdns: "test.wallet"
        },
        provider
      }});
    }
  }
};
Object.defineProperty(globalThis, "navigator", {
  configurable: true,
  value: {
    locks: {
      async request(_name, _options, callback) {
        return callback({name: _name});
      }
    }
  }
});

const fetchCalls = [];
let coreDisconnected = [
  "full_disconnect_resume",
  "full_disconnect_resume_site_already_disconnected",
  "full_disconnect_completed_recovery"
].includes(scenario);
let cleanupAuthorized =
  scenario !== "full_disconnect_resume_site_already_disconnected" &&
  scenario !== "full_disconnect_completed_recovery";
let disconnectPrepared = false;
global.fetch = async (url, options = {}) => {
  fetchCalls.push({
    url: String(url),
    method: options.method || "GET",
    body: options.body || null
  });
  events.push(`${options.method || "GET"} ${String(url)}`);
  if (String(url).endsWith(
    "/wallet-identities/wallet_identity_b/prepare-disconnect"
  )) {
    if (!cleanupAuthorized) {
      return {
        ok: false,
        status: 401,
        async json() {
          return {detail: "wallet authentication required"};
        }
      };
    }
    disconnectPrepared = true;
    state.spending_grants[0].status = "revoked";
    return {
      ok: true,
      status: 200,
      async json() {
        return {
          ...state.wallet_identities[0],
          status: "suspended"
        };
      }
    };
  }
  if (String(url).endsWith(
    "/wallet-identities/wallet_identity_b/disconnect-state"
  )) {
    return {
      ok: true,
      status: 200,
      async json() {
        return {
          wallet_identity: {
            ...state.wallet_identities[0],
            status: coreDisconnected
              ? "revoked"
              : disconnectPrepared ? "suspended" : "active"
          },
          disconnect_complete:
            scenario === "full_disconnect_completed_recovery",
          asset_allowances: [allowance],
          approval_targets: state.approval_targets,
          network_configs: state.network_configs
        };
      }
    };
  }
  if (String(url).endsWith(
    "/wallet-identities/wallet_identity_b/disconnect"
  )) {
    coreDisconnected = true;
    cleanupAuthorized = false;
    return {
      ok: true,
      status: 200,
      async json() {
        return {
          wallet_identity_id: "wallet_identity_b",
          wallet_address: wallet,
          status: "revoked"
        };
      }
    };
  }
  if (String(url).endsWith(`/allowances/${allowance.asset_allowance_id}/refresh`)) {
    if (!cleanupAuthorized) {
      return {
        ok: false,
        status: 401,
        async json() {
          return {detail: "wallet authentication required"};
        }
      };
    }
    storagePresentAtRefresh = storageValues.has(revokeStorageKey);
    const chainIsZero =
      scenario !== "recovery_still_active" &&
      (
        scenario === "reload_recovery" ||
        scenario === "full_disconnect_zero" ||
        sendCount > 0
      );
    return {
      ok: true,
      status: 200,
      async json() {
        return {
          ...allowance,
          observed_allowance_atomic: chainIsZero ? 0 : 25000000,
          status: chainIsZero ? "revoked" : "active"
        };
      }
    };
  }
  return {
    ok: true,
    status: 200,
    async json() {
      return coreDisconnected
        ? {
            ...state,
            wallet_identities: [],
            spending_grants: [],
            asset_allowances: []
          }
        : state;
    }
  };
};
"""
        .replace("__SCENARIO__", json.dumps(scenario))
        .replace("__POLYGON__", json.dumps(POLYGON))
        .replace("__TOKEN__", json.dumps(TOKEN))
        .replace("__SPENDER__", json.dumps(SPENDER))
        + test_javascript
        + """
const tick = () => new Promise((resolve) => setTimeout(resolve, 0));
setTimeout(async () => {
  let error = null;
  try {
    if (["reload_recovery", "recovery_still_active"].includes(scenario)) {
      await globalThis.__clinkTestHooks.recoverAllowanceRevocation(
        revokeRecord
      );
    } else if (scenario === "full_disconnect_completed_recovery") {
      await globalThis.__clinkTestHooks.fullyDisconnectWallet();
    } else {
      const providerButton =
        elements["#wallet-provider-options"].children.find(
          (item) => item.dataset.providerUuid === "test-wallet"
        );
      await providerButton.listeners.click();
      await tick();
      const accountButton =
        elements["#wallet-account-options"].children.find(
          (item) => item.textContent === wallet
        );
      accountButton.listeners.click();
      await tick();
      if (scenario.startsWith("full_disconnect_resume")) {
        bindDisabledDuringRecovery =
          elements["#connect-wallet"].disabled;
      }
      if (scenario.startsWith("full_disconnect_")) {
        if (scenario === "full_disconnect_concurrent") {
          await Promise.all([
            globalThis.__clinkTestHooks.fullyDisconnectWallet(),
            globalThis.__clinkTestHooks.fullyDisconnectWallet()
          ]);
        } else {
          await globalThis.__clinkTestHooks.fullyDisconnectWallet();
        }
        if (scenario === "full_disconnect_provider_failure") {
          const freshProviderButton =
            elements["#wallet-provider-options"].children.find(
              (item) => item.dataset.providerUuid === "test-wallet"
            );
          await freshProviderButton.listeners.click();
          await tick();
        }
      } else if (scenario === "invalid_hash") {
        try {
          await globalThis.__clinkTestHooks.revokeAllowance(allowance);
        } catch (caught) {
          error = caught.message;
        }
        try {
          await globalThis.__clinkTestHooks.revokeAllowance(allowance);
        } catch (caught) {
          error = caught.message;
        }
      } else {
        await globalThis.__clinkTestHooks.revokeAllowance(allowance);
      }
    }
  } catch (caught) {
    error = caught.message;
  }
  await tick();
  console.log(JSON.stringify({
    error,
    providerCalls,
    sentTransaction,
    sendCount,
    coreDisconnected,
    events,
    storagePresentAtRefresh,
    fetchCalls,
    storage: Object.fromEntries(storageValues),
    pageStatus: elements["#page-status"].textContent,
    walletSelectionStatus:
      elements["#wallet-selection-state"].textContent,
    accountAddresses: elements["#wallet-account-options"].children
      .filter((item) => item.listeners.click)
      .map((item) => item.textContent),
    bindDisabledDuringRecovery
  }));
}, 20);
"""
    )
    result = subprocess.run(
        ["node", "-"],
        input=harness,
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)


class ASGIClient:
    def __init__(self, app, *, cookies: httpx.Cookies | None = None) -> None:
        self.app = app
        self.cookies = cookies or httpx.Cookies()

    def request(self, method: str, url: str, **kwargs):
        add_csrf = kwargs.pop("add_csrf", True)
        headers = httpx.Headers(kwargs.pop("headers", None))
        if add_csrf and method.upper() not in {"GET", "HEAD", "OPTIONS"}:
            csrf_token = self.cookies.get("clink_account_csrf")
            if csrf_token:
                headers.setdefault("X-CSRF-Token", csrf_token)
        kwargs["headers"] = headers

        async def send():
            transport = httpx.ASGITransport(
                app=self.app, raise_app_exceptions=False
            )
            async with httpx.AsyncClient(
                transport=transport,
                base_url="https://testserver",
                cookies=self.cookies,
            ) as client:
                response = await client.request(method, url, **kwargs)
                self.cookies.update(response.cookies)
                return response

        return anyio.run(send)

    def get(self, url: str, **kwargs):
        return self.request("GET", url, **kwargs)

    def post(self, url: str, **kwargs):
        return self.request("POST", url, **kwargs)


class Clock:
    def __init__(self) -> None:
        self.now = NOW

    def __call__(self) -> datetime:
        return self.now


def identity(user_id: str, suffix: str, *, status: str = "active") -> WalletIdentity:
    wallet = Account.from_key(bytes.fromhex(suffix[-1] * 64))
    return WalletIdentity(
        wallet_identity_id=f"wallet_identity_{suffix}",
        user_id=user_id,
        wallet_address=wallet.address,
        status=status,
        proof_hash=f"proof_{suffix}",
        verified_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )


def grant(owner: WalletIdentity, suffix: str, *, status: str = "active") -> SpendingGrant:
    return SpendingGrant(
        spending_grant_id=f"spending_grant_{suffix}",
        wallet_identity_id=owner.wallet_identity_id,
        user_id=owner.user_id,
        agent_id="hermes",
        status=status,
        max_amount_usdc=Decimal("25"),
        per_transaction_limit_usdc=Decimal("5"),
        daily_limit_usdc=Decimal("10"),
        product_scopes=["prediction_markets", "marketplace"],
        venue_scopes=["polymarket", "clink_marketplace"],
        merchant_scopes=[],
        network_scopes=[POLYGON, BASE],
        asset_scopes=[TOKEN],
        starts_at=NOW,
        expires_at=NOW + timedelta(days=7),
        created_at=NOW,
        updated_at=NOW,
    )


def allowance(owner: WalletIdentity, suffix: str, *, network: str = POLYGON) -> AssetAllowance:
    return AssetAllowance(
        asset_allowance_id=f"asset_allowance_{suffix}",
        wallet_identity_id=owner.wallet_identity_id,
        network=network,
        token_address=TOKEN,
        token_symbol="USDC",
        token_decimals=6,
        spender_address=SPENDER,
        approved_amount_atomic=25_000_000,
        observed_allowance_atomic=25_000_000,
        allowance_tx_hash=TX_HASH,
        status="active",
        confirmed_block=100,
        last_chain_check_at=NOW,
        created_at=NOW,
        updated_at=NOW,
    )


@pytest.fixture
def context(tmp_path):
    repository = AccountRepository(f"sqlite+pysqlite:///{tmp_path / 'account-console.db'}")
    clock = Clock()
    service = AccountService(repository, domain="account.clink.test", clock=clock)
    app = create_app(
        service=service,
        internal_token=INTERNAL_TOKEN,
        clock=clock,
        session_ttl=timedelta(minutes=15),
        audit_summary_reader=lambda _user_id, _limit: [],
        approval_targets={
            POLYGON: {"token_address": TOKEN, "spender_address": SPENDER},
            BASE: {"token_address": TOKEN, "spender_address": SPENDER},
        },
    )
    return ASGIClient(app), service, repository, clock


def internal_headers(token: str = INTERNAL_TOKEN) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


def create_account_link(client: ASGIClient, user_id: str = "user_1") -> str:
    response = client.post(
        "/internal/account-sessions",
        headers=internal_headers(),
        json={"user_id": user_id},
    )
    assert response.status_code == 201
    return response.json()["session_id"]


def create_session(client: ASGIClient, user_id: str = "user_1") -> str:
    session_id = create_account_link(client, user_id)
    preview = client.get(f"/account/{session_id}")
    assert preview.status_code == 200
    exchanged = client.post(f"/account/{session_id}")
    assert exchanged.status_code == 303
    return session_id


def sign_wallet_challenge(client: ASGIClient, wallet) -> httpx.Response:
    challenge_response = client.post(
        "/account/wallet-challenge",
        json={"wallet_address": wallet.address},
    )
    assert challenge_response.status_code == 200
    challenge = challenge_response.json()
    signature = Account.sign_message(
        encode_defunct(text=challenge["message_to_sign"]), wallet.key
    ).signature.hex()
    return client.post(
        "/account/wallet-verify",
        json={
            "challenge_session_id": challenge["session_id"],
            "signed_message": challenge["message_to_sign"],
            "signature": signature,
        },
    )


def create_authenticated_session(
    client: ASGIClient, user_id: str = "user_1", wallet=None
) -> str:
    raw_token = create_session(client, user_id)
    if wallet is None:
        suffix = "b" if user_id == "user_2" else "a"
        wallet = Account.from_key(bytes.fromhex(suffix * 64))
    verified = sign_wallet_challenge(client, wallet)
    assert verified.status_code == 200
    return raw_token


def test_stolen_account_url_cannot_read_state_or_mutate_permissions(context):
    client, _service, repository, _clock = context
    wallet = Account.create()
    owner = WalletIdentity(
        **identity("user_1", "a").model_dump(exclude={"wallet_address"}),
        wallet_address=wallet.address,
    )
    permission = grant(owner, "a")
    repository.save_wallet_identity(owner)
    repository.save_spending_grant(permission)
    create_session(client, "user_1")

    state = client.get("/account", headers={"Accept": "application/json"})
    pause = client.post(f"/account/grants/{permission.spending_grant_id}/pause", json={})
    reduce = client.post(
        f"/account/grants/{permission.spending_grant_id}/reduce",
        json={"max_amount_usdc": "20"},
    )
    revoke = client.post(f"/account/grants/{permission.spending_grant_id}/revoke", json={})
    revoke_identity = client.post(
        f"/account/wallet-identities/{owner.wallet_identity_id}/revoke", json={}
    )

    assert state.status_code == 401
    assert owner.wallet_address not in state.text
    assert permission.spending_grant_id not in state.text
    assert {
        pause.status_code,
        reduce.status_code,
        revoke.status_code,
        revoke_identity.status_code,
    } == {401}
    assert repository.spending_grant(permission.spending_grant_id).status == "active"
    assert repository.wallet_identity(owner.wallet_identity_id).status == "active"


def test_full_disconnect_route_requires_prepare_and_revokes_all_open_grants(
    context,
):
    client, _service, repository, _clock = context
    owner = identity("user_1", "a")
    repository.save_wallet_identity(owner)
    for status in ("active", "pending", "paused"):
        item = grant(owner, status, status=status)
        if status == "paused":
            item = item.model_copy(update={"status_reason": "user_paused"})
        repository.save_spending_grant(item)
    create_authenticated_session(client, "user_1")

    bypass = client.post(
        f"/account/wallet-identities/{owner.wallet_identity_id}/disconnect",
        json={},
    )
    prepare = client.post(
        f"/account/wallet-identities/{owner.wallet_identity_id}/prepare-disconnect",
        json={},
    )
    response = client.post(
        f"/account/wallet-identities/{owner.wallet_identity_id}/disconnect",
        json={},
    )

    assert bypass.status_code == 400
    assert prepare.status_code == 200
    assert response.status_code == 200
    assert repository.wallet_identity(owner.wallet_identity_id).status == "revoked"
    for status in ("active", "pending", "paused"):
        stored = repository.spending_grant(f"spending_grant_{status}")
        assert stored.status == "revoked"
        assert stored.status_reason == "wallet_disconnect_prepared"


def test_unbind_sequence_keeps_wallet_auth_until_allowance_cleanup_finishes(
    context,
):
    client, service, repository, _clock = context
    wallet = Account.create()
    create_authenticated_session(client, "user_1", wallet=wallet)
    state = client.get(
        "/account", headers={"Accept": "application/json"}
    ).json()
    owner = WalletIdentity(**state["wallet_identities"][0])
    permission = grant(owner, "unbind")
    approved = allowance(owner, "unbind")
    historical = identity("user_1", "d", status="revoked")
    historical_allowance = allowance(historical, "historical")
    repository.save_spending_grant(permission)
    repository.save_asset_allowance(approved)
    repository.save_wallet_identity(historical)
    repository.save_asset_allowance(historical_allowance)
    def refresh_asset_allowance(asset_allowance_id):
        item = repository.asset_allowance(asset_allowance_id)
        if asset_allowance_id == approved.asset_allowance_id:
            item = item.model_copy(
                update={
                    "observed_allowance_atomic": 0,
                    "status": "revoked",
                    "last_chain_check_at": NOW,
                    "updated_at": NOW,
                }
            )
            repository.save_asset_allowance(item)
        return item

    service.refresh_asset_allowance = refresh_asset_allowance

    prepare = client.post(
        f"/account/wallet-identities/{owner.wallet_identity_id}/prepare-disconnect",
        json={},
    )
    prepared_identity = repository.wallet_identity(owner.wallet_identity_id)
    prepared_grant = repository.spending_grant(
        permission.spending_grant_id
    )
    locked_for_normal_actions = client.get(
        "/account", headers={"Accept": "application/json"}
    )
    cleanup_state = client.get(
        f"/account/wallet-identities/{owner.wallet_identity_id}/disconnect-state"
    )
    other_cleanup_state = client.get(
        f"/account/wallet-identities/{historical.wallet_identity_id}/disconnect-state"
    )
    other_allowance_refresh = client.post(
        f"/account/allowances/{historical_allowance.asset_allowance_id}/refresh",
        json={},
    )
    refresh_allowance = client.post(
        f"/account/allowances/{approved.asset_allowance_id}/refresh",
        json={},
    )
    create_grant = client.post(
        "/account/grants",
        json={
            "wallet_identity_id": owner.wallet_identity_id,
            "agent_id": "hermes",
            "max_amount_usdc": "1",
            "per_transaction_limit_usdc": "1",
            "daily_limit_usdc": "1",
            "product_scopes": ["marketplace"],
            "network_scopes": [POLYGON],
            "asset_scopes": [TOKEN],
            "starts_at": NOW.isoformat(),
            "expires_at": (NOW + timedelta(days=1)).isoformat(),
        },
    )
    create_challenge = client.post(
        "/account/wallet-challenge",
        json={"wallet_address": owner.wallet_address},
    )
    disconnect = client.post(
        f"/account/wallet-identities/{owner.wallet_identity_id}/disconnect",
        json={},
    )
    completed_state = client.get(
        f"/account/wallet-identities/{owner.wallet_identity_id}/disconnect-state"
    )
    locked = client.get(
        "/account", headers={"Accept": "application/json"}
    )

    assert prepare.status_code == 200
    assert prepare.json()["status"] == "suspended"
    assert prepared_identity.status == "suspended"
    assert prepared_grant.status == "revoked"
    assert locked_for_normal_actions.status_code == 401
    assert cleanup_state.status_code == 200
    assert cleanup_state.json()["wallet_identity"]["status"] == "suspended"
    assert [
        item["asset_allowance_id"]
        for item in cleanup_state.json()["asset_allowances"]
    ] == [approved.asset_allowance_id]
    assert cleanup_state.json()["approval_targets"][POLYGON] == {
        "token_address": TOKEN,
        "spender_address": SPENDER,
    }
    assert other_cleanup_state.status_code == 200
    assert (
        other_cleanup_state.json()["wallet_identity"]["status"]
        == "revoked"
    )
    assert other_allowance_refresh.status_code == 404
    assert refresh_allowance.status_code == 200
    assert create_grant.status_code == 401
    assert create_challenge.status_code == 409
    assert disconnect.status_code == 200
    assert completed_state.status_code == 200
    assert completed_state.json()["disconnect_complete"] is True
    assert locked.status_code == 401


def test_prepare_disconnect_keeps_cleanup_authority_in_one_browser_session(
    context,
):
    first, service, repository, _clock = context
    second = ASGIClient(first.app)
    wallet = Account.create()
    create_authenticated_session(first, "user_1", wallet=wallet)
    create_authenticated_session(second, "user_1", wallet=wallet)
    state = first.get(
        "/account", headers={"Accept": "application/json"}
    ).json()
    owner = WalletIdentity(**state["wallet_identities"][0])
    approved = allowance(owner, "single_cleanup_owner")
    repository.save_asset_allowance(approved)
    service.refresh_asset_allowance = repository.asset_allowance

    prepared = first.post(
        f"/account/wallet-identities/{owner.wallet_identity_id}/prepare-disconnect",
        json={},
    )
    second_prepare = second.post(
        f"/account/wallet-identities/{owner.wallet_identity_id}/prepare-disconnect",
        json={},
    )
    second_refresh = second.post(
        f"/account/allowances/{approved.asset_allowance_id}/refresh",
        json={},
    )
    public_recovery_state = second.get(
        f"/account/wallet-identities/{owner.wallet_identity_id}/disconnect-state"
    )
    cleanup_reauthorization = sign_wallet_challenge(second, wallet)
    first_after_takeover = first.post(
        f"/account/allowances/{approved.asset_allowance_id}/refresh",
        json={},
    )
    second_after_takeover = second.post(
        f"/account/allowances/{approved.asset_allowance_id}/refresh",
        json={},
    )

    assert prepared.status_code == 200
    assert second_prepare.status_code == 401
    assert second_refresh.status_code == 401
    assert public_recovery_state.status_code == 200
    assert (
        public_recovery_state.json()["wallet_identity"]["status"]
        == "suspended"
    )
    assert cleanup_reauthorization.status_code == 200
    assert cleanup_reauthorization.json()["status"] == "suspended"
    assert repository.wallet_identity(owner.wallet_identity_id).status == "suspended"
    assert first_after_takeover.status_code == 401
    assert second_after_takeover.status_code == 200


def test_final_disconnect_requires_fresh_zero_allowance_verification(context):
    client, _service, repository, _clock = context
    wallet = Account.create()
    create_authenticated_session(client, "user_1", wallet=wallet)
    state = client.get(
        "/account", headers={"Accept": "application/json"}
    ).json()
    owner = WalletIdentity(**state["wallet_identities"][0])
    stale_zero = allowance(owner, "stale_zero").model_copy(
        update={
            "observed_allowance_atomic": 0,
            "status": "revoked",
            "last_chain_check_at": NOW - timedelta(seconds=1),
        }
    )
    repository.save_asset_allowance(stale_zero)
    prepared = client.post(
        f"/account/wallet-identities/{owner.wallet_identity_id}/prepare-disconnect",
        json={},
    )

    stale_disconnect = client.post(
        f"/account/wallet-identities/{owner.wallet_identity_id}/disconnect",
        json={},
    )
    repository.save_asset_allowance(
        stale_zero.model_copy(
            update={
                "last_chain_check_at": NOW,
                "updated_at": NOW,
            }
        )
    )
    verified_disconnect = client.post(
        f"/account/wallet-identities/{owner.wallet_identity_id}/disconnect",
        json={},
    )

    assert prepared.status_code == 200
    assert stale_disconnect.status_code == 400
    assert verified_disconnect.status_code == 200


def test_full_disconnect_route_requires_csrf_and_owned_identity(context):
    client, _service, repository, _clock = context
    owner = identity("user_1", "a")
    other = identity("user_2", "b")
    repository.save_wallet_identity(owner)
    repository.save_wallet_identity(other)
    create_authenticated_session(client, "user_1")

    missing_csrf = client.post(
        f"/account/wallet-identities/{owner.wallet_identity_id}/disconnect",
        json={},
        add_csrf=False,
    )
    cross_user = client.post(
        f"/account/wallet-identities/{other.wallet_identity_id}/disconnect",
        json={},
    )

    assert missing_csrf.status_code == 403
    assert cross_user.status_code == 404
    assert repository.wallet_identity(owner.wallet_identity_id).status == "active"
    assert repository.wallet_identity(other.wallet_identity_id).status == "active"


@pytest.mark.parametrize("status", ["active", "suspended"])
def test_locked_wallet_challenge_does_not_disclose_unlock_eligibility(context, status):
    client, _service, repository, _clock = context
    owner_wallet = Account.create()
    attacker_wallet = Account.create()
    repository.save_wallet_identity(
        WalletIdentity(
            **identity("user_1", "a").model_dump(exclude={"wallet_address", "status"}),
            wallet_address=owner_wallet.address,
            status=status,
        )
    )
    create_session(client, "user_1")

    known_wallet_challenge = client.post(
        "/account/wallet-challenge",
        json={"wallet_address": owner_wallet.address},
    )
    attacker_challenge = client.post(
        "/account/wallet-challenge",
        json={"wallet_address": attacker_wallet.address},
    )
    assert known_wallet_challenge.status_code == attacker_challenge.status_code == 200
    assert known_wallet_challenge.json().keys() == attacker_challenge.json().keys()
    challenge = attacker_challenge.json()
    signature = Account.sign_message(
        encode_defunct(text=challenge["message_to_sign"]), attacker_wallet.key
    ).signature.hex()
    verified = client.post(
        "/account/wallet-verify",
        json={
            "challenge_session_id": challenge["session_id"],
            "signed_message": challenge["message_to_sign"],
            "signature": signature,
        },
    )
    state = client.get("/account", headers={"Accept": "application/json"})

    assert verified.status_code == 400
    assert verified.json() == {"detail": "request could not be completed"}
    assert state.status_code == 401


def test_existing_active_wallet_unlocks_same_browser_session_durably(context):
    client, _service, repository, _clock = context
    wallet = Account.create()
    owner = WalletIdentity(
        **identity("user_1", "a").model_dump(exclude={"wallet_address"}),
        wallet_address=wallet.address,
    )
    repository.save_wallet_identity(owner)
    raw_token = create_session(client, "user_1")

    verified = sign_wallet_challenge(client, wallet)
    state = client.get("/account", headers={"Accept": "application/json"})
    persisted = repository.public_account_session(
        hashlib.sha256(raw_token.encode()).hexdigest()
    )

    assert verified.status_code == 200
    assert verified.json()["wallet_identity_id"] == owner.wallet_identity_id
    assert state.status_code == 200
    assert state.json()["user_id"] == "user_1"
    assert persisted.authenticated_wallet_identity_id == owner.wallet_identity_id
    assert persisted.authenticated_at == NOW


def test_first_wallet_signature_bootstraps_identity_and_unlocks_session(context):
    client, _service, repository, _clock = context
    wallet = Account.create()
    create_session(client, "user_1")

    locked_state = client.get("/account", headers={"Accept": "application/json"})
    verified = sign_wallet_challenge(client, wallet)
    unlocked_state = client.get("/account", headers={"Accept": "application/json"})

    assert locked_state.status_code == 401
    assert verified.status_code == 200
    assert unlocked_state.status_code == 200
    assert (
        unlocked_state.json()["wallet_identities"][0]["wallet_address"]
        == wallet.address.lower()
    )
    assert (
        repository.active_wallet_identities("user_1")[0].wallet_address
        == wallet.address.lower()
    )


def test_authenticated_wallet_must_disconnect_before_signing_in_another_address(
    context,
):
    client, _service, repository, _clock = context
    first_wallet = Account.create()
    second_wallet = Account.create()
    create_session(client, "user_1")
    first = sign_wallet_challenge(client, first_wallet)

    second = sign_wallet_challenge(client, second_wallet)
    state = client.get("/account", headers={"Accept": "application/json"})

    assert first.status_code == 200
    assert second.status_code == 400
    assert state.status_code == 200
    assert {
        item["wallet_address"]
        for item in state.json()["wallet_identities"]
    } == {first_wallet.address.lower()}
    assert repository.active_wallet_identities("user_1")[0].wallet_address == (
        first_wallet.address.lower()
    )


def test_first_wallet_challenge_cannot_activate_from_another_browser_session(
    context,
):
    client_a, _service, repository, _clock = context
    wallet = Account.create()
    session_a_token = create_session(client_a, "user_1")
    challenge_response = client_a.post(
        "/account/wallet-challenge", json={"wallet_address": wallet.address}
    )
    assert challenge_response.status_code == 200
    challenge = challenge_response.json()

    client_b = ASGIClient(client_a.app)
    create_session(client_b, "user_1")
    repository.revoke_public_account_session(
        hashlib.sha256(session_a_token.encode()).hexdigest(), NOW
    )
    signature = Account.sign_message(
        encode_defunct(text=challenge["message_to_sign"]), wallet.key
    ).signature.hex()

    verified = client_b.post(
        "/account/wallet-verify",
        json={
            "challenge_session_id": challenge["session_id"],
            "signed_message": challenge["message_to_sign"],
            "signature": signature,
        },
    )

    assert verified.status_code == 404
    assert repository.active_wallet_identities("user_1") == []


def test_additional_wallet_challenge_cannot_activate_from_another_browser_session(
    context,
):
    client_a, _service, repository, _clock = context
    first_wallet = Account.create()
    second_wallet = Account.create()
    session_a_token = create_authenticated_session(client_a, wallet=first_wallet)

    client_b = ASGIClient(client_a.app)
    create_authenticated_session(client_b, wallet=first_wallet)
    challenge_response = client_a.post(
        "/account/wallet-challenge",
        json={"wallet_address": second_wallet.address},
    )
    assert challenge_response.status_code == 200
    challenge = challenge_response.json()
    repository.revoke_public_account_session(
        hashlib.sha256(session_a_token.encode()).hexdigest(), NOW
    )
    signature = Account.sign_message(
        encode_defunct(text=challenge["message_to_sign"]), second_wallet.key
    ).signature.hex()

    verified = client_b.post(
        "/account/wallet-verify",
        json={
            "challenge_session_id": challenge["session_id"],
            "signed_message": challenge["message_to_sign"],
            "signature": signature,
        },
    )

    assert verified.status_code == 404
    assert {
        item.wallet_address for item in repository.active_wallet_identities("user_1")
    } == {first_wallet.address.lower()}


@pytest.mark.parametrize(
    "path,method",
    [
        ("/internal/account-sessions", "post"),
        ("/internal/wallet-identities?user_id=user_1", "get"),
        ("/internal/spending-grants?user_id=user_1&status=active", "get"),
        ("/internal/authorization-resolution", "post"),
        ("/internal/account-readiness?user_id=user_1", "get"),
    ],
)
def test_internal_routes_require_exact_bearer_token(context, path, method):
    client, _service, _repository, _clock = context
    request = getattr(client, method)
    request_kwargs = {"json": {}} if method == "post" else {}

    missing = request(path, **request_kwargs)
    malformed = request(
        path,
        headers={"Authorization": f"Basic {INTERNAL_TOKEN}"},
        **request_kwargs,
    )
    wrong = request(
        path,
        headers=internal_headers("wrong-token"),
        **request_kwargs,
    )

    assert missing.status_code == malformed.status_code == wrong.status_code == 401
    assert INTERNAL_TOKEN not in missing.text + malformed.text + wrong.text


def test_internal_routes_fail_closed_when_token_is_unconfigured(tmp_path):
    repository = AccountRepository(f"sqlite+pysqlite:///{tmp_path / 'closed.db'}")
    service = AccountService(repository, domain="account.clink.test", clock=lambda: NOW)
    client = ASGIClient(create_app(service=service, internal_token="", clock=lambda: NOW))

    response = client.post(
        "/internal/account-sessions",
        headers=internal_headers(),
        json={"user_id": "user_1"},
    )

    assert response.status_code == 503
    assert response.json() == {"detail": "service unavailable"}
    assert INTERNAL_TOKEN not in response.text


def test_internal_bearer_validation_uses_constant_time_compare(context, monkeypatch):
    client, _service, _repository, _clock = context
    calls = []

    def compare(first, second):
        calls.append((first, second))
        return first == second

    monkeypatch.setattr("services.account_service.app.secrets.compare_digest", compare)

    response = client.get(
        "/internal/wallet-identities?user_id=user_1",
        headers=internal_headers(),
    )

    assert response.status_code == 200
    assert calls == [(INTERNAL_TOKEN, INTERNAL_TOKEN)]


def test_internal_account_session_is_high_entropy_and_never_leaks_token(context):
    client, _service, _repository, _clock = context

    first = client.post(
        "/internal/account-sessions",
        headers=internal_headers(),
        json={"user_id": "user_1"},
    )
    second = client.post(
        "/internal/account-sessions",
        headers=internal_headers(),
        json={"user_id": "user_1"},
    )

    assert first.status_code == second.status_code == 201
    assert first.json()["session_id"] != second.json()["session_id"]
    assert len(first.json()["session_id"]) >= 43
    assert first.json()["account_url"] == f"/account/{first.json()['session_id']}"
    assert INTERNAL_TOKEN not in first.text + second.text
    assert INTERNAL_TOKEN not in first.json()["account_url"]


def test_public_session_persists_only_sha256_digest_and_explicit_metadata(context):
    client, _service, repository, _clock = context

    raw_token = create_session(client, "user_1")

    assert "public_account_sessions" in inspect(repository.engine).get_table_names()
    with repository.sessions() as database_session:
        row = database_session.execute(
            text(
                "SELECT token_digest, browser_session_digest, csrf_token_digest, "
                "exchanged_at, user_id, purpose, status, expires_at "
                "FROM public_account_sessions"
            )
        ).mappings().one()
    assert row["token_digest"] == hashlib.sha256(raw_token.encode()).hexdigest()
    assert row["browser_session_digest"] == hashlib.sha256(
        client.cookies.get("clink_account_session").encode()
    ).hexdigest()
    assert row["csrf_token_digest"] == hashlib.sha256(
        client.cookies.get("clink_account_csrf").encode()
    ).hexdigest()
    assert row["exchanged_at"] is not None
    assert row["user_id"] == "user_1"
    assert row["purpose"] == "clink_account_console"
    assert row["status"] == "active"
    assert raw_token not in repr(dict(row))


def test_public_session_works_across_app_instances_and_restart(tmp_path):
    database_url = f"sqlite+pysqlite:///{tmp_path / 'shared-console.db'}"
    clock = Clock()
    first_repository = AccountRepository(database_url)
    first_service = AccountService(
        first_repository, domain="account.clink.test", clock=clock
    )
    first_client = ASGIClient(
        create_app(
            service=first_service,
            internal_token=INTERNAL_TOKEN,
            clock=clock,
        )
    )
    create_authenticated_session(first_client, "user_1")

    second_repository = AccountRepository(database_url)
    second_service = AccountService(
        second_repository, domain="account.clink.test", clock=clock
    )
    second_client = ASGIClient(
        create_app(
            service=second_service,
            internal_token=INTERNAL_TOKEN,
            clock=clock,
        ),
        cookies=first_client.cookies,
    )
    second_response = second_client.get(
        "/account", headers={"Accept": "application/json"}
    )

    restarted_repository = AccountRepository(database_url)
    restarted_service = AccountService(
        restarted_repository, domain="account.clink.test", clock=clock
    )
    restarted_response = ASGIClient(
        create_app(
            service=restarted_service,
            internal_token=INTERNAL_TOKEN,
            clock=clock,
        ),
        cookies=first_client.cookies,
    ).get("/account", headers={"Accept": "application/json"})

    assert second_response.status_code == 200
    assert restarted_response.status_code == 200
    assert second_response.json()["user_id"] == restarted_response.json()["user_id"] == "user_1"


def test_public_session_access_revoke_expiry_and_cleanup_are_persisted(context):
    client, _service, repository, clock = context
    raw_token = create_authenticated_session(client, "user_1")
    digest = hashlib.sha256(raw_token.encode()).hexdigest()

    active = client.get("/account", headers={"Accept": "application/json"})
    accessed = repository.public_account_session(digest)
    revoked = repository.revoke_public_account_session(digest, clock())
    denied = client.get("/account")

    assert active.status_code == 200
    assert accessed.last_accessed_at == NOW
    assert revoked.status == "revoked"
    assert revoked.revoked_at == NOW
    assert denied.status_code == 401

    expiring_token = create_session(client, "user_1")
    expiring_digest = hashlib.sha256(expiring_token.encode()).hexdigest()
    clock.now += timedelta(minutes=16)
    expired = client.get("/account")

    assert expired.status_code == 410
    assert repository.public_account_session(expiring_digest).status == "expired"

    create_session(client, "user_1")
    assert repository.public_account_session(expiring_digest) is None


def test_public_url_token_is_one_time_cookie_exchange_with_strict_attributes(context):
    client, _service, _repository, _clock = context
    raw_token = create_account_link(client, "user_1")

    preview = client.get(f"/account/{raw_token}")
    exchanged = client.post(f"/account/{raw_token}")
    replay = ASGIClient(client.app).post(f"/account/{raw_token}")
    state = client.get("/account", headers={"Accept": "application/json"})
    set_cookies = exchanged.headers.get_list("set-cookie")

    assert preview.status_code == 200
    assert preview.headers.get_list("set-cookie") == []
    assert exchanged.status_code == 303
    assert exchanged.headers["location"] == "/account"
    assert any(
        "clink_account_session=" in value
        and "Secure" in value
        and "HttpOnly" in value
        and "SameSite=strict" in value
        for value in set_cookies
    )
    assert any("clink_account_csrf=" in value and "SameSite=strict" in value for value in set_cookies)
    assert raw_token not in "".join(set_cookies)
    assert replay.status_code == 404
    assert state.status_code == 401
    assert state.json() == {"detail": "wallet authentication required"}


def test_link_preview_get_does_not_consume_public_account_session(context):
    client, _service, _repository, _clock = context
    raw_token = create_account_link(client, "user_1")
    preview_client = ASGIClient(client.app)

    preview = preview_client.get(f"/account/{raw_token}")
    exchanged = client.post(f"/account/{raw_token}")

    assert preview.status_code == 200
    assert "Continue to Clink Account" in preview.text
    assert preview.headers.get_list("set-cookie") == []
    assert exchanged.status_code == 303
    assert exchanged.headers["location"] == "/account"


def test_exchanged_account_link_reopens_only_in_the_bound_browser(context):
    client, _service, _repository, _clock = context
    raw_token = create_session(client, "user_1")

    reopened = client.get(f"/account/{raw_token}")
    stolen = ASGIClient(client.app).get(f"/account/{raw_token}")

    assert reopened.status_code == 303
    assert reopened.headers["location"] == "/account"
    assert stolen.status_code == 404
    assert stolen.json() == {"detail": "account session unavailable"}


def test_public_mutation_requires_cookie_bound_csrf(context):
    client, _service, _repository, _clock = context
    create_session(client, "user_1")
    payload = {"wallet_address": "0x" + "11" * 20}

    missing = client.post(
        "/account/wallet-challenge", json=payload, add_csrf=False
    )
    forged = client.post(
        "/account/wallet-challenge",
        json=payload,
        headers={"X-CSRF-Token": "forged"},
        add_csrf=False,
    )
    accepted = client.post("/account/wallet-challenge", json=payload)

    assert missing.status_code == forged.status_code == 403
    assert accepted.status_code == 200


def test_wallet_login_challenge_cancel_is_csrf_bound_and_owner_only(context):
    client, _service, repository, _clock = context
    wallet = Account.create()
    create_session(client, "user_1")
    challenge = client.post(
        "/account/wallet-challenge",
        json={"wallet_address": wallet.address},
    ).json()

    missing_csrf = client.post(
        f"/account/wallet-challenges/{challenge['session_id']}/cancel",
        json={},
        add_csrf=False,
    )
    other_client = ASGIClient(client.app)
    create_session(other_client, "user_2")
    wrong_owner = other_client.post(
        f"/account/wallet-challenges/{challenge['session_id']}/cancel",
        json={},
    )
    cancelled = client.post(
        f"/account/wallet-challenges/{challenge['session_id']}/cancel",
        json={},
    )
    repeated = client.post(
        f"/account/wallet-challenges/{challenge['session_id']}/cancel",
        json={},
    )

    assert missing_csrf.status_code == 403
    assert wrong_owner.status_code == 404
    assert cancelled.status_code == repeated.status_code == 200
    assert cancelled.json() == repeated.json() == {"cancelled": True}
    with repository.sessions() as session:
        assert session.get(
            AccountSessionRow,
            challenge["session_id"],
        ).consumed_at is not None


def test_internal_session_rejects_control_characters_in_user_binding(context):
    client, _service, _repository, _clock = context

    response = client.post(
        "/internal/account-sessions",
        headers=internal_headers(),
        json={"user_id": "user_1\nforged"},
    )

    assert response.status_code == 422
    assert response.json() == {"detail": "invalid request"}


def test_new_total_limit_is_not_prefilled_with_a_fixed_amount(context):
    client, _service, _repository, _clock = context
    create_session(client)

    html = client.get("/account", headers={"Accept": "text/html"}).text
    total_limit_input = next(
        line for line in html.splitlines() if 'id="total-limit"' in line
    )

    assert 'value="25"' not in total_limit_input
    if "value=" in total_limit_input:
        assert 'value=""' in total_limit_input


@pytest.mark.parametrize(
    ("scenario", "expected_wallet_identity_id"),
    [
        ("same_user_authenticated", "wallet_identity_a"),
        ("different_user", None),
        ("same_user_unauthenticated", None),
        ("expired_existing_session", None),
    ],
)
def test_new_account_session_reuses_only_current_valid_wallet_authentication(
    context, scenario, expected_wallet_identity_id
):
    client, _service, repository, clock = context
    wallet = Account.from_key(bytes.fromhex("a" * 64))
    owner = identity("user_1", "a", status="active")
    repository.save_wallet_identity(owner)

    create_session(client, "user_1")
    if scenario == "same_user_authenticated":
        verified = sign_wallet_challenge(client, wallet)
        assert verified.status_code == 200
    elif scenario == "expired_existing_session":
        verified = sign_wallet_challenge(client, wallet)
        assert verified.status_code == 200
        clock.now += timedelta(minutes=16)

    target_user = "user_2" if scenario == "different_user" else "user_1"
    new_token = create_account_link(client, target_user)
    assert client.get(f"/account/{new_token}").status_code == 200
    exchanged = client.post(f"/account/{new_token}")

    assert exchanged.status_code == 303
    exchanged_row = repository.public_account_session(
        hashlib.sha256(new_token.encode()).hexdigest()
    )
    assert exchanged_row is not None
    assert (
        exchanged_row.authenticated_wallet_identity_id
        == expected_wallet_identity_id
    )

    state = client.get("/account", headers={"Accept": "application/json"})
    if expected_wallet_identity_id is None:
        assert state.status_code == 401
    else:
        assert state.status_code == 200
        assert (
            state.json()["wallet_identities"][0]["wallet_identity_id"]
            == expected_wallet_identity_id
        )


@pytest.mark.parametrize("race", ["revoke", "expire"])
def test_account_session_exchange_rechecks_source_authentication_after_race(
    context, monkeypatch, race
):
    client, _service, repository, clock = context
    wallet = Account.from_key(bytes.fromhex("a" * 64))
    owner = identity("user_1", "a")
    repository.save_wallet_identity(owner)
    source_token = create_authenticated_session(client, "user_1", wallet=wallet)

    source_digest = hashlib.sha256(source_token.encode()).hexdigest()
    source = repository.public_account_session(source_digest)
    assert source is not None
    assert source.authenticated_wallet_identity_id == owner.wallet_identity_id

    new_token = create_account_link(client, "user_1")
    assert client.get(f"/account/{new_token}").status_code == 200

    exchange = repository.exchange_public_account_session

    def race_before_exchange(*args, **kwargs):
        if race == "revoke":
            repository.revoke_public_account_session(source_digest, clock())
        else:
            with repository.sessions.begin() as database_session:
                database_session.execute(
                    text(
                        "UPDATE public_account_sessions "
                        "SET expires_at = :expires_at "
                        "WHERE public_account_session_id = :session_id"
                    ),
                    {
                        "expires_at": clock() - timedelta(seconds=1),
                        "session_id": source.public_account_session_id,
                    },
                )
        return exchange(*args, **kwargs)

    monkeypatch.setattr(
        repository, "exchange_public_account_session", race_before_exchange
    )
    exchanged = client.post(f"/account/{new_token}")

    assert exchanged.status_code == 303
    exchanged_row = repository.public_account_session(
        hashlib.sha256(new_token.encode()).hexdigest()
    )
    assert exchanged_row is not None
    assert exchanged_row.authenticated_wallet_identity_id is None


def test_internal_reads_and_readiness_use_account_domain(context):
    client, _service, repository, _clock = context
    owner = identity("user_1", "a")
    repository.save_wallet_identity(owner)
    repository.save_spending_grant(grant(owner, "a"))
    repository.save_asset_allowance(allowance(owner, "polygon", network=POLYGON))
    repository.save_asset_allowance(allowance(owner, "base", network=BASE))

    identities = client.get(
        "/internal/wallet-identities?user_id=user_1", headers=internal_headers()
    )
    grants = client.get(
        "/internal/spending-grants?user_id=user_1&status=active",
        headers=internal_headers(),
    )
    readiness = client.get(
        "/internal/account-readiness?user_id=user_1", headers=internal_headers()
    )

    assert [item["wallet_identity_id"] for item in identities.json()] == [owner.wallet_identity_id]
    assert [item["spending_grant_id"] for item in grants.json()] == ["spending_grant_a"]
    assert readiness.json() == {
        "user_id": "user_1",
        "wallet_bound": True,
        "wallet_address": owner.wallet_address,
        "wallet_identity_id": owner.wallet_identity_id,
        "spending_grant_active": True,
        "active_spending_mandate": {
            "spending_grant_id": "spending_grant_a",
            "agent_id": "hermes",
            "limits_usdc": {
                "per_transaction": "5",
                "rolling_hour": "10",
                "daily": "10",
                "total": "25",
            },
            "remaining_usdc": {
                "rolling_hour": "10",
                "daily": "10",
                "total": "25",
            },
            "product_scopes": ["marketplace", "prediction_markets"],
            "venue_scopes": ["clink_marketplace", "polymarket"],
            "merchant_scopes": [],
            "merchant_trust_scopes": ["clink_verified"],
            "network_scopes": [POLYGON, BASE],
            "asset_scopes": [TOKEN],
            "notification_mode": "notify_all",
            "expires_at": "2026-07-22T12:00:00Z",
        },
        "chain_allowances": {POLYGON: True, BASE: True},
        "ready": True,
    }
    assert INTERNAL_TOKEN not in identities.text + grants.text + readiness.text


def test_internal_readiness_uses_only_the_configured_amoy_rehearsal_network(
    tmp_path,
):
    repository = AccountRepository(f"sqlite+pysqlite:///{tmp_path / 'amoy-readiness.db'}")
    clock = Clock()
    service = AccountService(
        repository,
        domain="account.clink.test",
        clock=clock,
        network_configs={AMOY_NETWORK: AMOY_NETWORK_CONFIG},
    )
    owner = identity("user_1", "a")
    repository.save_wallet_identity(owner)
    repository.save_spending_grant(
        grant(owner, "amoy").model_copy(
            update={
                "network_scopes": [AMOY_NETWORK],
                "asset_scopes": [AMOY_NETWORK_CONFIG["token_address"]],
            }
        )
    )
    repository.save_asset_allowance(
        allowance(owner, "amoy", network=AMOY_NETWORK).model_copy(
            update={
                "token_address": AMOY_NETWORK_CONFIG["token_address"],
                "spender_address": SPENDER,
                "approved_amount_atomic": 1,
                "observed_allowance_atomic": 1,
            }
        )
    )
    app = create_app(
        service=service,
        internal_token=INTERNAL_TOKEN,
        clock=clock,
        audit_summary_reader=lambda _user_id, _limit: [],
        approval_targets={
            AMOY_NETWORK: {
                "token_address": AMOY_NETWORK_CONFIG["token_address"],
                "spender_address": SPENDER,
            }
        },
    )

    response = ASGIClient(app).get(
        "/internal/account-readiness?user_id=user_1",
        headers=internal_headers(),
    )

    assert response.status_code == 200
    assert response.json()["chain_allowances"] == {AMOY_NETWORK: True}
    assert response.json()["ready"] is True


def test_public_account_state_exposes_only_safe_configured_network_metadata(
    tmp_path,
):
    repository = AccountRepository(
        f"sqlite+pysqlite:///{tmp_path / 'amoy-account-state.db'}"
    )
    clock = Clock()
    service = AccountService(
        repository,
        domain="account.clink.test",
        clock=clock,
        network_configs={AMOY_NETWORK: AMOY_NETWORK_CONFIG},
    )
    owner = identity("user_1", "a")
    repository.save_wallet_identity(owner)
    repository.save_spending_grant(
        grant(owner, "amoy").model_copy(
            update={
                "network_scopes": [AMOY_NETWORK],
                "asset_scopes": [AMOY_NETWORK_CONFIG["token_address"]],
            }
        )
    )
    app = create_app(
        service=service,
        internal_token=INTERNAL_TOKEN,
        clock=clock,
        audit_summary_reader=lambda _user_id, _limit: [],
        approval_targets={
            AMOY_NETWORK: {
                "token_address": AMOY_NETWORK_CONFIG["token_address"],
                "spender_address": SPENDER,
            }
        },
    )
    client = ASGIClient(app)
    wallet = Account.from_key(bytes.fromhex("a" * 64))
    create_authenticated_session(client, "user_1", wallet)

    response = client.get("/account", headers={"Accept": "application/json"})

    assert response.status_code == 200
    assert response.json()["network_configs"] == {
        AMOY_NETWORK: {
            "chain_id": 80002,
            "required_confirmations": 3,
            "token_symbol": "USDC",
            "token_decimals": 6,
        }
    }
    assert "token_address" not in response.json()["network_configs"][AMOY_NETWORK]
    assert "rpc_url" not in response.json()["network_configs"][AMOY_NETWORK]


def test_console_uses_server_network_metadata_instead_of_fixed_chain_set():
    javascript = ACCOUNT_CONSOLE_JS

    assert "const REQUIRED_GRANT_NETWORKS" not in javascript
    assert "network_configs" in javascript
    assert "Object.entries(state.network_configs)" in javascript
    assert "Object.keys(accountState.network_configs)" in javascript
    assert "0x89" not in javascript and "0x2105" not in javascript
    assert "required_confirmations" in javascript


def test_internal_account_balances_reads_real_usdc_balances_per_network(context):
    client, service, repository, _clock = context
    owner = identity("user_1", "a")
    repository.save_wallet_identity(owner)
    repository.save_spending_grant(grant(owner, "a"))
    calls = []

    def rpc(network, method, params):
        calls.append((network, method, params))
        assert method == "eth_call"
        assert params[0]["data"] == (
            "0x70a08231" + ("0" * 24) + owner.wallet_address[2:].lower()
        )
        return hex(1_234_567 if network == POLYGON else 7_000_000)

    service.rpc_transport = rpc

    response = client.get(
        "/internal/account-balances?user_id=user_1",
        headers=internal_headers(),
    )

    assert response.status_code == 200
    assert response.json() == {
        "user_id": "user_1",
        "status": "ready",
        "wallet_bound": True,
        "wallet_address": owner.wallet_address,
        "balances": {
            POLYGON: {
                "status": "ready",
                "network": POLYGON,
                "asset": "USDC",
                "token_address": TOKEN,
                "amount_atomic": "1234567",
                "amount_usdc": "1.234567",
            },
            BASE: {
                "status": "ready",
                "network": BASE,
                "asset": "USDC",
                "token_address": BASE_TOKEN,
                "amount_atomic": "7000000",
                "amount_usdc": "7.000000",
            },
        },
    }
    assert {network for network, _method, _params in calls} == {POLYGON, BASE}


def test_internal_account_balances_never_turns_rpc_failure_into_zero(context):
    client, service, repository, _clock = context
    owner = identity("user_1", "a")
    repository.save_wallet_identity(owner)

    def rpc(network, _method, _params):
        if network == POLYGON:
            raise RuntimeError("private upstream detail")
        return hex(500_000)

    service.rpc_transport = rpc

    response = client.get(
        "/internal/account-balances?user_id=user_1",
        headers=internal_headers(),
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "partial"
    assert payload["balances"][POLYGON]["status"] == "unavailable"
    assert payload["balances"][POLYGON]["amount_atomic"] is None
    assert payload["balances"][POLYGON]["amount_usdc"] is None
    assert payload["balances"][BASE]["amount_usdc"] == "0.500000"
    assert "private upstream detail" not in response.text


def test_readiness_reports_positive_network_allowances_without_using_limit_caps(
    context,
):
    client, _service, repository, _clock = context
    owner = identity("user_1", "a")
    repository.save_wallet_identity(owner)
    repository.save_spending_grant(
        grant(owner, "a").model_copy(
            update={"per_transaction_limit_usdc": Decimal("2")}
        )
    )
    for network, amount in ((POLYGON, 3_000_000), (BASE, 500_000)):
        repository.save_asset_allowance(
            allowance(owner, network, network=network).model_copy(
                update={
                    "approved_amount_atomic": amount,
                    "observed_allowance_atomic": amount,
                }
            )
        )
    create_authenticated_session(client, "user_1")

    internal = client.get(
        "/internal/account-readiness?user_id=user_1",
        headers=internal_headers(),
    )
    public = client.get("/account", headers={"Accept": "application/json"})

    assert internal.json()["chain_allowances"] == {POLYGON: True, BASE: True}
    assert internal.json()["ready"] is True
    assert public.json()["readiness"]["chain_allowances"] == {
        POLYGON: True,
        BASE: True,
    }
    assert public.json()["readiness"]["ready"] is True


def test_readiness_is_false_when_every_network_allowance_is_zero(context):
    client, _service, repository, _clock = context
    owner = identity("user_1", "a")
    repository.save_wallet_identity(owner)
    repository.save_spending_grant(grant(owner, "a"))
    for network in (POLYGON, BASE):
        repository.save_asset_allowance(
            allowance(owner, network, network=network).model_copy(
                update={
                    "approved_amount_atomic": 0,
                    "observed_allowance_atomic": 0,
                }
            )
        )
    create_authenticated_session(client, "user_1")

    internal = client.get(
        "/internal/account-readiness?user_id=user_1",
        headers=internal_headers(),
    )
    public = client.get("/account", headers={"Accept": "application/json"})

    assert internal.json()["chain_allowances"] == {POLYGON: False, BASE: False}
    assert internal.json()["ready"] is False
    assert public.json()["readiness"]["chain_allowances"] == {
        POLYGON: False,
        BASE: False,
    }
    assert public.json()["readiness"]["ready"] is False


def test_public_allowance_atomic_amounts_are_exact_json_strings(context):
    client, _service, repository, _clock = context
    owner = identity("user_1", "a")
    maximum = 2**256 - 1
    repository.save_wallet_identity(owner)
    repository.save_asset_allowance(
        allowance(owner, "max").model_copy(
            update={
                "approved_amount_atomic": maximum,
                "observed_allowance_atomic": maximum,
            }
        )
    )
    create_authenticated_session(client, "user_1")

    response = client.get("/account", headers={"Accept": "application/json"})

    assert response.status_code == 200
    serialized = response.json()["asset_allowances"][0]
    assert serialized["approved_amount_atomic"] == str(maximum)
    assert serialized["observed_allowance_atomic"] == str(maximum)


def test_internal_readiness_returns_null_wallet_identity_when_unbound(context):
    client, _service, _repository, _clock = context

    response = client.get(
        "/internal/account-readiness?user_id=unbound_user",
        headers=internal_headers(),
    )

    assert response.status_code == 200
    assert response.json() == {
        "user_id": "unbound_user",
        "wallet_bound": False,
        "wallet_address": None,
        "wallet_identity_id": None,
        "spending_grant_active": False,
        "active_spending_mandate": None,
        "chain_allowances": {POLYGON: False, BASE: False},
        "ready": False,
    }


def test_internal_readiness_selects_wallet_that_owns_active_spending_grant(context):
    client, _service, repository, _clock = context
    first = identity("user_1", "a", status="revoked")
    funded = identity("user_1", "b")
    repository.save_wallet_identity(first)
    repository.save_wallet_identity(funded)
    repository.save_spending_grant(grant(funded, "b"))
    repository.save_asset_allowance(allowance(funded, "polygon", network=POLYGON))
    repository.save_asset_allowance(allowance(funded, "base", network=BASE))

    response = client.get(
        "/internal/account-readiness?user_id=user_1", headers=internal_headers()
    )

    assert response.status_code == 200
    assert response.json()["wallet_address"] == funded.wallet_address
    assert response.json()["wallet_identity_id"] == funded.wallet_identity_id
    assert response.json()["ready"] is True


def test_internal_authorization_resolution_delegates_to_core(context):
    client, service, _repository, _clock = context
    captured = []

    def resolve(request):
        captured.append(request)
        return {
            "ready": False,
            "reason_code": "WALLET_IDENTITY_REQUIRED",
            "next_action": "configure_wallet_authorization",
        }

    service.resolve_authorization = resolve
    payload = {
        "user_id": "user_1",
        "agent_id": "hermes",
        "product": "marketplace",
        "network": POLYGON,
        "token_address": TOKEN,
        "spender_address": SPENDER,
        "amount_usdc": "1",
        "destination": "0x" + "55" * 20,
        "resource": "purchase_1",
    }

    response = client.post(
        "/internal/authorization-resolution", headers=internal_headers(), json=payload
    )

    assert response.status_code == 200
    assert response.json()["reason_code"] == "WALLET_IDENTITY_REQUIRED"
    assert captured[0].user_id == "user_1"


def test_console_page_has_strict_headers_and_no_inline_or_third_party_assets(context):
    client, _service, _repository, _clock = context
    session_id = create_session(client)

    response = client.get("/account", headers={"Accept": "text/html"})

    assert response.status_code == 200
    assert response.headers["content-security-policy"] == (
        "default-src 'none'; script-src 'self'; style-src 'self'; connect-src 'self'; "
        "img-src 'self' data:; font-src 'self'; object-src 'none'; base-uri 'none'; "
        "frame-ancestors 'none'; form-action 'self'"
    )
    assert response.headers["x-content-type-options"] == "nosniff"
    assert response.headers["cache-control"] == "no-store"
    assert response.headers["referrer-policy"] == "no-referrer"
    assert "<style" not in response.text.lower()
    assert "<script>" not in response.text.lower()
    assert "wallet-session.js" not in response.text
    assert '<script src="/account/static/account.js" defer></script>' in response.text
    assert '<link rel="stylesheet" href="/account/static/account.css">' in response.text
    assert '<dialog id="wallet-session-dialog"' not in response.text
    assert "http://" not in response.text and "https://" not in response.text
    assert INTERNAL_TOKEN not in response.text


def test_removed_wallet_session_assets_are_not_served(context):
    client, _service, _repository, _clock = context

    bundle = client.get("/account/static/wallet-session.js")
    icon = client.get("/account/static/clink.svg")

    assert bundle.status_code == 404
    assert icon.status_code == 404


def test_console_assets_honor_configured_reverse_proxy_base_path(tmp_path, monkeypatch):
    monkeypatch.setenv(
        "CLINK_ACCOUNT_PUBLIC_BASE_URL", "https://account.example.com/core"
    )
    monkeypatch.setenv("CLINK_CORE_INTERNAL_API_TOKEN", INTERNAL_TOKEN)
    monkeypatch.setenv("CLINK_POLYGON_USDC_ADDRESS", TOKEN)
    monkeypatch.setenv("CLINK_POLYGON_SPENDER_ADDRESS", SPENDER)
    monkeypatch.setenv("CLINK_BASE_USDC_ADDRESS", BASE_TOKEN)
    monkeypatch.setenv("CLINK_BASE_SPENDER_ADDRESS", BASE_SPENDER)
    repository = AccountRepository(
        f"sqlite+pysqlite:///{tmp_path / 'prefixed-console.db'}"
    )
    clock = Clock()
    service = AccountService(repository, domain="account.clink.test", clock=clock)
    app = create_app(
        service=service,
        internal_token=INTERNAL_TOKEN,
        clock=clock,
        audit_summary_reader=lambda _user_id, _limit: [],
    )
    client = ASGIClient(app)
    created = client.post(
        "/internal/account-sessions",
        headers=internal_headers(),
        json={"user_id": "user_1"},
    )
    raw_token = created.json()["session_id"]
    preview = client.get(f"/account/{raw_token}")
    exchanged = client.post(f"/account/{raw_token}")
    cookie_header = (
        f"clink_account_session={client.cookies.get('clink_account_session')}; "
        f"clink_account_csrf={client.cookies.get('clink_account_csrf')}"
    )
    page = ASGIClient(app).get("/account", headers={"Cookie": cookie_header})

    assert created.json()["account_url"] == (
        f"https://account.example.com/core/account/{raw_token}"
    )
    assert preview.status_code == 200
    assert '<link rel="stylesheet" href="/core/account/static/account.css">' in preview.text
    assert exchanged.status_code == 303
    assert exchanged.headers["location"] == "/core/account"
    assert "Path=/core/account" in "".join(exchanged.headers.get_list("set-cookie"))
    assert "wallet-session.js" not in page.text
    assert '<script src="/core/account/static/account.js" defer></script>' in page.text
    assert '<link rel="stylesheet" href="/core/account/static/account.css">' in page.text


def test_console_is_clink_account_with_four_focused_sections(context):
    client, _service, _repository, _clock = context
    session_id = create_session(client)

    html = client.get("/account", headers={"Accept": "text/html"}).text

    assert "Clink Account" in html
    assert html.count("<section") == 4
    for heading in ("Wallet", "Spending limit", "Wallet setup", "Recent audit summary"):
        assert f">{heading}<" in html
    assert 'id="network-ledger"' in html
    assert "prediction markets" in html.lower() and "marketplace" in html.lower()
    assert "Polymarket CLOB auth" in html
    assert "one total usdc limit" in html.lower()
    assert "one-time wallet approval" in html.lower()
    assert html.count('id="total-limit"') == 1
    for duplicate_limit_id in (
        "transaction-limit",
        "hourly-limit",
        "daily-limit",
    ):
        assert f'id="{duplicate_limit_id}"' not in html
    for forbidden in ("demo", "trading dashboard"):
        assert forbidden.lower() not in html.lower()
    for forbidden_field in ("private_key", "seed_phrase", "polymarket_credentials", "platform_api_secret"):
        assert f'name="{forbidden_field}"' not in html.lower()


def test_console_renders_only_current_mandate(context):
    client, _service, _repository, _clock = context
    javascript = client.get("/account/static/account.js").text

    result = run_wallet_selection_console(
        javascript, "renders_only_current_mandate"
    )

    assert result["currentCount"] == 1
    assert "spending_grant_active" in result["html"]
    assert "spending_grant_revoked" not in result["html"]
    assert "revoked" not in result["html"].lower()


def test_console_active_mandate_summary_uses_one_total_used_remaining_view(context):
    client, _service, _repository, _clock = context
    javascript = client.get("/account/static/account.js").text

    result = run_wallet_selection_console(
        javascript, "renders_only_current_mandate"
    )

    assert "Total" in result["html"]
    assert "Used" in result["html"]
    assert "Remaining" in result["html"]
    for duplicate_limit_label in (
        "New per transaction",
        "New rolling hour",
        "New daily",
    ):
        assert duplicate_limit_label not in result["html"]
    assert "Existing safeguards" in result["html"]
    assert "1 per purchase" in result["html"]


def test_console_active_mandate_collapses_new_mandate_editor_by_default(context):
    client, _service, _repository, _clock = context
    create_session(client)
    html = client.get("/account", headers={"Accept": "text/html"}).text
    javascript = client.get("/account/static/account.js").text

    result = run_wallet_selection_console(
        javascript, "renders_only_current_mandate"
    )

    assert '<details id="permission-editor"' in html
    assert result["editorOpen"] is False


def test_console_uses_agentonomy_public_brand_without_exposing_internal_agent_name(context):
    client, _service, _repository, _clock = context
    create_session(client)

    html = client.get("/account", headers={"Accept": "text/html"}).text
    javascript = client.get("/account/static/account.js").text

    assert "Agentonomy" in html
    assert "hermes" not in html.lower()
    assert "hermes" not in javascript.lower()


def test_console_clearly_renders_locked_session_and_unlock_action(context):
    client, _service, _repository, _clock = context
    create_session(client)

    html = client.get("/account", headers={"Accept": "text/html"}).text
    javascript = client.get("/account/static/account.js").text

    assert "Sign in with selected address" in html
    assert 'textContent = "Locked"' in javascript
    assert (
        "Wallet proof is required before account details or permission controls are available."
        in javascript
    )
    assert "renderLocked" in javascript
    assert "wallet authentication required" in javascript


def test_console_disables_allowance_refresh_until_authenticated_state_is_loaded(context):
    client, _service, _repository, _clock = context
    create_session(client)

    html = client.get("/account", headers={"Accept": "text/html"}).text
    javascript = client.get("/account/static/account.js").text

    render = javascript.split("const render = (state) => {", 1)[1].split(
        "const renderLocked = () => {", 1
    )[0]
    locked = javascript.split("const renderLocked = () => {", 1)[1].split(
        "const loadState = async", 1
    )[0]
    refresh = javascript.split(
        '$("#refresh-allowances").addEventListener("click", async () => {', 1
    )[1].split('$("#refresh-audit")', 1)[0]

    assert (
        '<button id="refresh-allowances" class="primary-action compact" '
        'type="button" disabled>'
        in html
    )
    assert '$("#refresh-allowances").disabled = false;' in render
    assert '$("#refresh-allowances").disabled = true;' in locked
    assert "if (!accountState || !Array.isArray(accountState.asset_allowances))" in refresh
    assert refresh.index("if (!accountState") < refresh.index("for (const item")


@pytest.mark.parametrize(
    "scenario",
    [
        "locked_account_state",
        "non_array_allowances",
        "malformed_authenticated_state",
        "empty_network_configs",
    ],
)
def test_console_refresh_stays_inert_without_a_valid_authenticated_state(
    context, scenario
):
    client, _service, _repository, _clock = context
    javascript = client.get("/account/static/account.js").text

    result = run_wallet_selection_console(javascript, scenario)

    assert result["allowanceRefreshFetches"] == []
    assert result["refreshFetchCount"] == 0
    assert result["refreshDisabled"] is True
    assert result["walletState"] == "Locked"


def test_newer_locked_state_rejects_an_older_authenticated_response(context):
    client, _service, _repository, _clock = context
    javascript = client.get("/account/static/account.js").text

    result = run_wallet_selection_console(
        javascript, "stale_authenticated_response_after_lock"
    )

    locked_state = {
        "refreshDisabled": True,
        "walletState": "Locked",
        "permissionState": "Locked",
        "polygonState": "Locked",
        "baseState": "Locked",
    }
    assert result["lockedBeforeStaleResponse"] == locked_state
    assert result["stateAfterStaleResponse"] == locked_state
    assert result["allowanceRefreshFetches"] == []
    assert result["refreshFetchCount"] == 0


def test_expired_session_rejects_an_older_authenticated_response(context):
    client, _service, _repository, _clock = context
    javascript = client.get("/account/static/account.js").text

    result = run_wallet_selection_console(
        javascript, "stale_account_session_expired_response"
    )

    locked_state = {
        "refreshDisabled": True,
        "walletState": "Locked",
        "permissionState": "Locked",
        "polygonState": "Locked",
        "baseState": "Locked",
    }
    assert result["lockedBeforeStaleResponse"] == locked_state
    assert result["stateAfterStaleResponse"] == locked_state
    assert result["pageStatus"] == (
        "Account session expired. Open a new account management link and sign in "
        "to continue verification. Your spending authorization is unchanged; do "
        "not approve again."
    )
    assert result["allowanceRefreshFetches"] == []
    assert result["refreshFetchCount"] == 0


def test_console_assets_are_same_origin_wallet_only_and_accessible(context):
    client, _service, _repository, _clock = context

    javascript = client.get("/account/static/account.js")
    stylesheet = client.get("/account/static/account.css")

    assert javascript.status_code == stylesheet.status_code == 200
    assert "window.ethereum" not in javascript.text
    assert "eip6963:announceProvider" in javascript.text
    assert "eip6963:requestProvider" in javascript.text
    assert "window.ClinkWalletSessions" not in javascript.text
    assert "/wallet-session-config" not in javascript.text
    assert "personal_sign" in javascript.text
    assert "eth_sendTransaction" in javascript.text
    assert "waitForConfirmations" in javascript.text
    assert javascript.text.index("await waitForConfirmations") < javascript.text.index(
        'request("/allowances/verify"'
    )
    assert "usdcAtomic" in javascript.text
    assert "Number(" not in javascript.text
    assert "fetch(window.location.pathname" in javascript.text
    assert "Authorization" not in javascript.text
    assert "privateKey" not in javascript.text
    assert "seedPhrase" not in javascript.text
    assert "http://" not in javascript.text and "https://" not in javascript.text
    assert ":focus-visible" in stylesheet.text
    assert "prefers-reduced-motion: reduce" in stylesheet.text
    assert ".wallet-selection" in stylesheet.text
    assert ".wallet-choice" in stylesheet.text
    assert "linear-gradient" not in stylesheet.text and "radial-gradient" not in stylesheet.text
    assert INTERNAL_TOKEN not in javascript.text + stylesheet.text


def test_console_requires_explicit_discovered_wallet_and_account_selection(context):
    client, _service, _repository, _clock = context
    create_session(client)

    html = client.get("/account", headers={"Accept": "text/html"}).text
    javascript = client.get("/account/static/account.js").text

    assert 'id="wallet-provider-options"' in html
    assert 'id="wallet-account-options"' in html
    assert 'id="wallet-selection-state"' in html
    assert 'id="connect-wallet"' in html
    assert 'id="connect-wallet" class="primary-action" type="button" disabled' in html
    assert (
        'id="cancel-wallet-selection" class="row-action" type="button" disabled'
        in html
    )
    assert "eip6963:announceProvider" in javascript
    assert "eip6963:requestProvider" in javascript
    assert "initializeWalletSession" not in javascript
    assert "wallet-session.js" not in html
    assert "selectedProviderUuid" in javascript
    assert "selectedWalletAddress" in javascript
    assert "eth_requestAccounts" in javascript
    assert "wallet_revokePermissions" not in javascript
    assert "still authorizes Clink" not in javascript


def test_eip6963_discovery_does_not_select_or_request_an_account(context):
    client, _service, _repository, _clock = context
    javascript = client.get("/account/static/account.js").text

    result = run_allowance_console(javascript, "discovery")

    assert result["provider_choices"] == 1
    assert result["account_choices"] == 0
    assert result["connect_disabled"] is True
    assert "eth_requestAccounts" not in result["initial_calls"]


def test_wallet_picker_binds_the_explicit_second_provider_and_second_address(context):
    client, _service, _repository, _clock = context
    javascript = client.get("/account/static/account.js").text

    result = run_wallet_selection_console(javascript, "bind_second_account")

    assert result["providerNames"] == ["Alpha Wallet", "Beta Wallet"]
    assert result["providerIcons"] == [
        {
            "imageSource": "data:image/png;base64,AA==",
            "imageHidden": True,
            "fallback": "A",
        },
        {
            "imageSource": None,
            "imageHidden": None,
            "fallback": "B",
        },
    ]
    assert result["accountAddresses"] == [
        ("0x" + "b" * 40),
        ("0x" + "c" * 40),
    ]
    assert result["selectedAddress"] == "0x" + "c" * 40
    assert result["challengeRequests"] == [{"wallet_address": "0x" + "c" * 40}]
    assert result["verifyRequests"][0]["signature"] == "0xsigned-c"
    assert result["providerCalls"]["alpha"] == []
    assert result["providerCalls"]["beta"].count("eth_requestAccounts") == 1
    assert result["providerCalls"]["beta"].count("personal_sign") == 1


def test_suspended_wallet_signature_restores_cleanup_only_recovery(context):
    client, _service, _repository, _clock = context
    javascript = client.get("/account/static/account.js").text

    result = run_wallet_selection_console(
        javascript,
        "suspended_cleanup_reauth",
    )

    assert len(result["challengeRequests"]) == 1
    assert len(result["verifyRequests"]) == 1
    assert len(result["storage"]) == 1
    plan = json.loads(next(iter(result["storage"].values())))
    assert plan["wallet_identity_id"] == "wallet_identity_suspended"
    assert plan["wallet_address"] == "0x" + "c" * 40
    assert plan["provider_uuid"] == "beta"
    assert plan["core_disconnected"] is False
    assert plan["allowances_cleared"] is False
    assert result["recoveryHidden"] is False
    assert "cleanup only" in result["pageStatus"].lower()


def test_wallet_picker_does_not_default_to_the_first_returned_address(context):
    client, _service, _repository, _clock = context
    javascript = client.get("/account/static/account.js").text

    result = run_wallet_selection_console(javascript, "accounts_without_choice")

    assert result["accountAddresses"] == [
        ("0x" + "b" * 40),
        ("0x" + "c" * 40),
    ]
    assert result["selectedAddress"] is None
    assert result["challengeRequests"] == []
    assert result["bindDisabled"] is True


def test_locked_console_accepts_accounts_from_an_existing_plugin_permission(
    context,
):
    client, _service, _repository, _clock = context
    javascript = client.get("/account/static/account.js").text

    result = run_wallet_selection_console(
        javascript,
        "restored_session",
    )

    assert result["providerCalls"]["beta"] == ["eth_requestAccounts"]
    assert result["accountAddresses"] == [
        "0x" + "b" * 40,
        "0x" + "c" * 40,
    ]
    assert result["selectedProvider"] == "beta"
    assert result["selectedAddress"] is None
    assert result["challengeRequests"] == []
    assert result["verifyRequests"] == []
    assert result["bindDisabled"] is True
    assert result["cancelDisabled"] is False
    assert "not signed in" in result["status"].lower()


def test_existing_plugin_permission_can_be_cancelled_back_to_initial_state(
    context,
):
    client, _service, _repository, _clock = context
    javascript = client.get("/account/static/account.js").text

    result = run_wallet_selection_console(
        javascript,
        "restored_session_cancel",
    )

    assert result["providerCalls"]["beta"] == ["eth_requestAccounts"]
    assert result["selectedProvider"] is None
    assert result["selectedAddress"] is None
    assert result["accountAddresses"] == []
    assert result["challengeRequests"] == []
    assert result["verifyRequests"] == []
    assert result["bindDisabled"] is True
    assert result["cancelDisabled"] is True
    assert result["status"] == (
        "Wallet login cancelled. Choose a wallet to start again."
    )


def test_reselecting_an_existing_plugin_permission_requests_accounts_again(
    context,
):
    client, _service, _repository, _clock = context
    javascript = client.get("/account/static/account.js").text

    result = run_wallet_selection_console(
        javascript,
        "restored_session_retry",
    )

    assert result["providerCalls"]["beta"] == [
        "eth_requestAccounts",
        "eth_requestAccounts",
    ]
    assert result["selectedProvider"] == "beta"
    assert result["selectedAddress"] is None
    assert result["accountAddresses"] == [
        "0x" + "b" * 40,
        "0x" + "c" * 40,
    ]
    assert result["challengeRequests"] == []
    assert result["verifyRequests"] == []
    assert result["bindDisabled"] is True
    assert result["cancelDisabled"] is False
    assert "not signed in" in result["status"].lower()


def test_locked_console_requests_plugin_accounts_again_after_wallet_disconnect(
    context,
):
    client, _service, _repository, _clock = context
    javascript = client.get("/account/static/account.js").text

    result = run_wallet_selection_console(
        javascript,
        "restored_then_wallet_disconnected",
    )

    assert result["providerCalls"]["beta"] == [
        "eth_requestAccounts",
        "eth_requestAccounts",
    ]
    assert result["accountAddresses"] == [
        "0x" + "b" * 40,
        "0x" + "c" * 40,
    ]
    assert result["selectedProvider"] == "beta"
    assert result["selectedAddress"] is None
    assert result["challengeRequests"] == []
    assert result["verifyRequests"] == []
    assert result["bindDisabled"] is True
    assert "not signed in" in result["status"].lower()


def test_cancel_wallet_selection_clears_choice_without_core_mutation(context):
    client, _service, _repository, _clock = context
    javascript = client.get("/account/static/account.js").text

    result = run_wallet_selection_console(javascript, "cancel_after_selection")

    assert result["selectedProvider"] is None
    assert result["selectedAddress"] is None
    assert result["accountAddresses"] == []
    assert result["challengeRequests"] == []
    assert result["verifyRequests"] == []
    assert result["bindDisabled"] is True
    assert result["cancelDisabled"] is True
    assert result["status"] == (
        "Wallet login cancelled. Choose a wallet to start again."
    )


def test_cancel_selection_clears_page_state_and_reselection_requests_accounts_again(
    context,
):
    client, _service, _repository, _clock = context
    javascript = client.get("/account/static/account.js").text

    result = run_wallet_selection_console(javascript, "cancel_then_reselect")

    assert result["providerCalls"]["beta"].count("eth_requestAccounts") == 2
    assert "disconnect" not in result["providerCalls"]["beta"]
    assert result["selectedProvider"] == "beta"
    assert result["selectedAddress"] is None
    assert result["accountAddresses"] == [
        "0x" + "b" * 40,
        "0x" + "c" * 40,
    ]
    assert result["verifyRequests"] == []
    assert result["cancelDisabled"] is False
    assert "not signed in" in result["status"].lower()


def test_cancel_wallet_selection_invalidates_pending_account_request(context):
    client, _service, _repository, _clock = context
    javascript = client.get("/account/static/account.js").text

    result = run_wallet_selection_console(javascript, "cancel_pending_provider")

    assert result["selectedProvider"] is None
    assert result["selectedAddress"] is None
    assert result["accountAddresses"] == []
    assert result["challengeRequests"] == []
    assert result["verifyRequests"] == []
    assert result["bindDisabled"] is True
    assert result["cancelDisabled"] is True
    assert result["status"] == (
        "Wallet login cancelled. Choose a wallet to start again."
    )


def test_cancel_wallet_selection_during_signature_blocks_verify(context):
    client, _service, _repository, _clock = context
    javascript = client.get("/account/static/account.js").text

    result = run_wallet_selection_console(javascript, "cancel_during_signature")

    assert result["challengeRequests"] == [
        {"wallet_address": "0x" + "c" * 40}
    ]
    assert result["cancelRequests"] == ["wallet_session"]
    assert result["verifyRequests"] == []
    assert result["selectedProvider"] is None
    assert result["selectedAddress"] is None
    assert result["bindDisabled"] is True
    assert result["cancelDisabled"] is True


@pytest.mark.parametrize(
    "scenario",
    ["account_access_rejected", "empty_accounts", "invalid_accounts"],
)
def test_wallet_account_discovery_failures_do_not_create_challenge(
    context, scenario
):
    client, _service, _repository, _clock = context
    javascript = client.get("/account/static/account.js").text

    result = run_wallet_selection_console(javascript, scenario)

    assert result["selectedAddress"] is None
    assert result["challengeRequests"] == []
    assert result["verifyRequests"] == []
    assert result["bindDisabled"] is True


def test_rejected_wallet_signature_cancels_challenge_and_resets_login(
    context,
):
    client, _service, _repository, _clock = context
    javascript = client.get("/account/static/account.js").text

    result = run_wallet_selection_console(javascript, "signature_rejected")

    assert result["challengeRequests"] == [
        {"wallet_address": "0x" + "c" * 40}
    ]
    assert result["cancelRequests"] == ["wallet_session"]
    assert result["verifyRequests"] == []
    assert result["selectedProvider"] is None
    assert result["selectedAddress"] is None
    assert result["accountAddresses"] == []
    assert result["bindDisabled"] is True
    assert result["cancelDisabled"] is True
    assert result["status"] == (
        "Wallet login failed. No wallet was bound. "
        "Choose a wallet to start again."
    )


def test_verified_wallet_does_not_report_unbound_when_state_refresh_fails(
    context,
):
    client, _service, _repository, _clock = context
    javascript = client.get("/account/static/account.js").text

    result = run_wallet_selection_console(
        javascript,
        "post_verify_refresh_failure",
    )

    assert len(result["verifyRequests"]) == 1
    assert result["cancelRequests"] == []
    assert result["status"] == (
        "Wallet sign-in completed, but account state could not be refreshed. "
        "Reload the page."
    )


@pytest.mark.parametrize(
    "scenario",
    ["accounts_changed", "chain_changed", "disconnected"],
)
def test_wallet_change_invalidates_selection_and_blocks_stale_verify(context, scenario):
    client, _service, _repository, _clock = context
    javascript = client.get("/account/static/account.js").text

    result = run_wallet_selection_console(javascript, scenario)

    assert result["verifyRequests"] == []
    assert result["bindDisabled"] is True
    assert result["selectedProvider"] is None
    assert result["selectedAddress"] is None
    assert result["accountAddresses"] == []
    assert result["status"] == (
        "Wallet login failed. No wallet was bound. "
        "Choose a wallet to start again."
    )


def test_listener_cleanup_failure_cannot_keep_wallet_selection_usable(context):
    client, _service, _repository, _clock = context
    javascript = client.get("/account/static/account.js").text

    result = run_wallet_selection_console(javascript, "listener_cleanup_throws")

    assert result["selectedProvider"] is None
    assert result["selectedAddress"] is None
    assert result["bindDisabled"] is True


def test_selected_address_has_visible_selected_treatment(context):
    client, _service, _repository, _clock = context
    stylesheet = client.get("/account/static/account.css").text

    assert '.wallet-choice[aria-checked="true"]' in stylesheet


def test_console_allowance_refresh_calls_chain_refresh_route(context):
    client, service, repository, _clock = context
    owner = identity("user_1", "a")
    repository.save_wallet_identity(owner)
    repository.save_asset_allowance(allowance(owner, "a"))
    session_id = create_authenticated_session(client, "user_1")
    refreshed = []

    def refresh(asset_allowance_id):
        refreshed.append(asset_allowance_id)
        return repository.asset_allowance(asset_allowance_id)

    service.refresh_asset_allowance = refresh
    response = client.post(
        "/account/allowances/asset_allowance_a/refresh",
        json={},
    )
    javascript = client.get("/account/static/account.js").text

    assert response.status_code == 200
    assert refreshed == ["asset_allowance_a"]
    assert "/allowances/${item.asset_allowance_id}/refresh" in javascript


def test_allowance_actions_preflight_all_prerequisites_before_send(context):
    client, _service, _repository, _clock = context
    session_id = create_session(client)

    html = client.get("/account", headers={"Accept": "text/html"})
    javascript = client.get("/account/static/account.js").text

    assert '<div id="network-ledger"' in html.text
    assert "data-approve-network" in javascript
    assert "const preflightAllowance" in javascript
    assert 'method: "eth_accounts"' in javascript
    assert "Selected wallet does not match the bound wallet" in javascript
    assert "Unsupported allowance target" in javascript
    assert "No active bound wallet" in javascript
    assert "No active permission supports this allowance" in javascript
    assert "canonicalAddress" in javascript
    assert "accountState.approval_targets" in javascript
    assert "const refreshAllowanceReadiness" in javascript
    assert "mandate.wallet_identity_id !== identity.wallet_identity_id" in javascript
    approve_javascript = javascript.split("const approve = async", 1)[1].split(
        "const verifyPendingAllowance", 1
    )[0]
    assert approve_javascript.index(
        "await preflightAllowance"
    ) < approve_javascript.index(
        'method: "eth_sendTransaction"'
    )


def test_allowance_prepare_attempt_precedes_wallet_send_and_submitted_attach(
    context,
):
    client, _service, _repository, _clock = context
    javascript = client.get("/account/static/account.js").text

    result = run_allowance_console(javascript, "durable_attempt")

    assert result["attemptBeginCount"] == 1
    assert result["attemptSubmittedCount"] == 1
    assert result["sendCount"] == 1
    assert result["httpEvents"].index("begin") < result["httpEvents"].index(
        "send"
    )
    assert result["httpEvents"].index("submitted") < result["httpEvents"].index(
        "receipt"
    )
    assert len(result["attemptBeginRequests"][0]["request_key"]) == 64
    assert result["attemptBeginRequests"][0]["request_key"] == result[
        "attemptBeginRequests"
    ][0]["request_key"].lower()
    assert result["attemptRecordReflectedRequestKey"] is False


def test_allowance_session_expiry_during_prepare_blocks_wallet_send(context):
    client, _service, _repository, _clock = context
    javascript = client.get("/account/static/account.js").text

    result = run_allowance_console(
        javascript, "session_expired_during_prepare"
    )

    assert result["attemptBeginCount"] == 1
    assert result["sendCount"] == 0
    assert result["verificationCount"] == 0
    assert result["pageStatus"] == (
        "Account session expired. Open a new account management link and sign in "
        "to continue verification. Your spending authorization is unchanged; do "
        "not approve again."
    )
    assert any(
        key.startswith("clink.account.allowance_attempt.v1.")
        for key in result["storage"]
    )


def test_expired_account_session_requires_wallet_login_before_recovery(context):
    client, _service, _repository, _clock = context
    javascript = client.get("/account/static/account.js").text

    result = run_allowance_console(javascript, "expired_session_reauth")

    assert result["walletVerifyCount"] == 1
    assert result["approvalDisabledAfterReauthentication"] == [False, False]
    assert result["sendCount"] == 0


def test_console_keeps_positive_partial_allowance_ready_without_new_approval(
    context,
):
    client, _service, _repository, _clock = context
    create_session(client)
    html = client.get("/account", headers={"Accept": "text/html"}).text
    javascript = client.get("/account/static/account.js").text

    result = run_allowance_console(javascript, "allowance_insufficient")

    assert '<details id="allowance-setup"' in html
    assert result["allowanceSetupOpen"] is False
    assert "3" in result["polygonState"]
    assert result["polygonButtonHidden"] is True
    assert result["sendCount"] == 0
    assert "setup" not in result["pageStatus"].lower()


def test_console_collapses_ready_allowance_and_prevents_repeat_approval(context):
    client, _service, _repository, _clock = context
    create_session(client)
    html = client.get("/account", headers={"Accept": "text/html"}).text
    javascript = client.get("/account/static/account.js").text

    result = run_allowance_console(javascript, "allowance_sufficient")

    assert '<details id="allowance-setup"' in html
    assert result["allowanceSetupOpen"] is False
    assert any(
        marker in result["polygonState"].lower()
        for marker in ("covered", "ready")
    )
    assert result["sendCount"] == 0
    assert result["approvalDisabled"][0] is True or result["polygonButtonHidden"] is True


def test_console_upgrades_insufficient_allowance_once_then_hides_network_action(context):
    client, _service, _repository, _clock = context
    javascript = client.get("/account/static/account.js").text

    result = run_allowance_console(javascript, "allowance_upgrade")

    assert result["sendCount"] == 1
    assert result["sentTransaction"]["data"] == (
        "0x095ea7b3"
        + SPENDER[2:].rjust(64, "0")
        + hex(5_000_000)[2:].rjust(64, "0")
    )
    assert result["verification"]["network"] == POLYGON
    assert result["polygonButtonHidden"] is True
    assert "ready" in result["polygonState"].lower()


def test_allowance_browser_binds_connected_wallet_to_its_exact_active_grant(context):
    client, _service, _repository, _clock = context
    javascript = client.get("/account/static/account.js").text

    result = run_allowance_console(javascript, "multi_wallet")

    assert result["verification"]["wallet_identity_id"] == "wallet_identity_b"
    assert result["sentTransaction"]["from"] == "0x" + "b" * 40
    assert result["sentTransaction"]["chainId"] == "0x89"
    assert result["calls"][:6] == [
        "eth_accounts",
        "wallet_switchEthereumChain",
        "eth_chainId",
        "eth_accounts",
        "eth_chainId",
        "eth_sendTransaction",
    ]
    assert result["calls"].index("eth_accounts") < result["calls"].index(
        "wallet_switchEthereumChain"
    )
    assert result["calls"].index("wallet_switchEthereumChain") < result[
        "calls"
    ].index("eth_sendTransaction")


def test_mandate_signature_uses_the_explicit_bound_wallet(context):
    client, _service, _repository, _clock = context
    javascript = client.get("/account/static/account.js").text

    result = run_allowance_console(javascript, "grant")

    assert "window.ethereum" not in javascript
    assert result["grantRequests"][0]["wallet_identity_id"] == "wallet_identity_b"
    assert result["grantRequests"][0]["agent_id"] == "hermes"
    assert result["personalSignRequest"]["params"][1] == "0x" + "b" * 40


def test_mandate_rechecks_wallet_after_challenge_before_personal_sign(context):
    client, _service, _repository, _clock = context
    javascript = client.get("/account/static/account.js").text

    result = run_allowance_console(javascript, "mandate_challenge_changed")

    assert len(result["grantRequests"]) == 1
    assert result["personalSignRequest"] is None


def test_allowance_send_uses_the_explicit_bound_wallet(context):
    client, _service, _repository, _clock = context
    javascript = client.get("/account/static/account.js").text

    result = run_allowance_console(javascript, "multi_wallet")

    assert result["sentTransaction"]["from"] == "0x" + "b" * 40
    assert result["verification"]["wallet_identity_id"] == "wallet_identity_b"


def test_allowance_revoke_sends_zero_approval_and_verifies_chain_state(context):
    client, _service, _repository, _clock = context
    javascript = client.get("/account/static/account.js").text

    result = run_allowance_revoke_console(javascript, "success")

    assert result["error"] is None
    assert result["sentTransaction"] == {
        "from": "0x" + "b" * 40,
        "to": TOKEN,
        "data": (
            "0x095ea7b3"
            + SPENDER[2:].rjust(64, "0")
            + "0".rjust(64, "0")
        ),
        "chainId": "0x89",
    }
    assert result["sendCount"] == 1
    assert result["storagePresentAtRefresh"] is True
    assert any(
        call["url"].endswith(
            "/allowances/asset_allowance_polygon/refresh"
        )
        for call in result["fetchCalls"]
    )
    assert result["storage"] == {}


def test_allowance_revoke_recovery_refreshes_without_resending(context):
    client, _service, _repository, _clock = context
    javascript = client.get("/account/static/account.js").text

    result = run_allowance_revoke_console(javascript, "reload_recovery")

    assert result["error"] is None
    assert result["sendCount"] == 0
    assert any(
        call["url"].endswith(
            "/allowances/asset_allowance_polygon/refresh"
        )
        for call in result["fetchCalls"]
    )
    assert result["storage"] == {}


def test_allowance_revoke_requires_recoverable_storage_before_send(context):
    client, _service, _repository, _clock = context
    javascript = client.get("/account/static/account.js").text

    result = run_allowance_revoke_console(javascript, "storage_unavailable")

    assert "recovery storage" in result["error"].lower()
    assert result["sendCount"] == 0
    assert result["sentTransaction"] is None


def test_allowance_revoke_rejects_a_different_selected_address(context):
    client, _service, _repository, _clock = context
    javascript = client.get("/account/static/account.js").text

    result = run_allowance_revoke_console(javascript, "wrong_address")

    assert "does not match" in result["error"].lower()
    assert result["sendCount"] == 0
    assert result["sentTransaction"] is None


@pytest.mark.parametrize(
    ("scenario", "message"),
    [
        ("wrong_target", "target"),
        ("wrong_chain", "network"),
    ],
)
def test_allowance_revoke_blocks_wrong_target_or_chain(
    context, scenario, message
):
    client, _service, _repository, _clock = context
    javascript = client.get("/account/static/account.js").text

    result = run_allowance_revoke_console(javascript, scenario)

    assert message in result["error"].lower()
    assert result["sendCount"] == 0
    assert result["sentTransaction"] is None


def test_allowance_revoke_recovery_keeps_record_while_chain_is_positive(context):
    client, _service, _repository, _clock = context
    javascript = client.get("/account/static/account.js").text

    result = run_allowance_revoke_console(javascript, "recovery_still_active")

    assert "still active" in result["error"].lower()
    assert result["sendCount"] == 0
    assert len(result["storage"]) == 1


def test_allowance_revoke_invalid_hash_blocks_every_retry(context):
    client, _service, _repository, _clock = context
    javascript = client.get("/account/static/account.js").text

    result = run_allowance_revoke_console(javascript, "invalid_hash")

    assert "do not resend" in result["error"].lower()
    assert result["sendCount"] == 1
    assert result["sentTransaction"] is not None


def test_fully_disconnect_revokes_chain_before_closing_core_session(context):
    client, _service, _repository, _clock = context
    javascript = client.get("/account/static/account.js").text

    result = run_allowance_revoke_console(
        javascript, "full_disconnect_success"
    )

    assert result["error"] is None
    assert result["coreDisconnected"] is True
    assert result["sendCount"] == 1
    disconnect_index = next(
        index
        for index, event in enumerate(result["events"])
        if event.endswith(
            "POST /account/wallet-identities/wallet_identity_b/disconnect"
        )
    )
    prepare_index = result["events"].index(
        "POST /account/wallet-identities/wallet_identity_b/prepare-disconnect"
    )
    send_index = result["events"].index("eth_sendTransaction")
    assert prepare_index < send_index < disconnect_index
    assert "wallet_revokePermissions" not in result["events"]
    assert result["storage"] == {}
    assert "signed out" in result["walletSelectionStatus"].lower()
    assert "wallet extension" in result["pageStatus"].lower()


def test_fully_disconnect_chain_failure_keeps_core_session_open_for_retry(context):
    client, _service, _repository, _clock = context
    javascript = client.get("/account/static/account.js").text

    result = run_allowance_revoke_console(
        javascript, "full_disconnect_chain_rejected"
    )

    assert result["coreDisconnected"] is False
    assert result["sendCount"] == 1
    assert "wallet_revokePermissions" not in result["events"]
    assert "chain revocation rejected" in result["error"].lower()
    assert (
        "POST /account/wallet-identities/wallet_identity_b/prepare-disconnect"
        in result["events"]
    )
    assert len(result["storage"]) == 1


def test_fully_disconnect_skips_zero_allowance_and_leaves_plugin_permission(context):
    client, _service, _repository, _clock = context
    javascript = client.get("/account/static/account.js").text

    result = run_allowance_revoke_console(
        javascript, "full_disconnect_zero"
    )

    assert result["error"] is None
    assert result["coreDisconnected"] is True
    assert result["sendCount"] == 0
    assert "wallet_revokePermissions" not in result["events"]
    assert any(
        call["url"].endswith(
            "/allowances/asset_allowance_polygon/refresh"
        )
        for call in result["fetchCalls"]
    )
    assert result["storage"] == {}


def test_fully_disconnect_succeeds_without_revoking_plugin_site_permission(
    context,
):
    client, _service, _repository, _clock = context
    javascript = client.get("/account/static/account.js").text

    result = run_allowance_revoke_console(
        javascript, "full_disconnect_provider_failure"
    )

    assert result["coreDisconnected"] is True
    assert result["sendCount"] == 1
    assert result["error"] is None
    assert "signed out" in result["pageStatus"].lower()
    assert "wallet extension" in result["pageStatus"].lower()
    assert result["storage"] == {}
    assert "wallet_revokePermissions" not in result["providerCalls"]
    assert result["accountAddresses"] == ["0x" + "b" * 40]


def test_fully_disconnect_is_single_flight(context):
    client, _service, _repository, _clock = context
    javascript = client.get("/account/static/account.js").text

    result = run_allowance_revoke_console(
        javascript, "full_disconnect_concurrent"
    )

    disconnect_calls = [
        event
        for event in result["events"]
        if event.endswith(
            "POST /account/wallet-identities/wallet_identity_b/disconnect"
        )
    ]
    assert len(disconnect_calls) == 1
    assert result["sendCount"] == 1


def test_fully_disconnect_resumes_after_reload_without_repeating_core_step(
    context,
):
    client, _service, _repository, _clock = context
    javascript = client.get("/account/static/account.js").text

    result = run_allowance_revoke_console(
        javascript, "full_disconnect_resume"
    )

    disconnect_calls = [
        event
        for event in result["events"]
        if event.endswith(
            "POST /account/wallet-identities/wallet_identity_b/disconnect"
        )
    ]
    assert result["error"] is None
    assert disconnect_calls == []
    assert result["sendCount"] == 1
    assert "wallet_revokePermissions" not in result["events"]
    assert result["providerCalls"].count("eth_requestAccounts") == 1
    assert result["bindDisabledDuringRecovery"] is False
    assert result["storage"] == {}


def test_disconnect_recovery_can_reauthorize_only_for_cleanup(context):
    client, _service, _repository, _clock = context
    javascript = client.get("/account/static/account.js").text

    result = run_allowance_revoke_console(
        javascript,
        "full_disconnect_resume_site_already_disconnected",
    )

    assert "wallet authentication required" in result["error"].lower()
    assert result["coreDisconnected"] is True
    assert result["providerCalls"][0] == "eth_requestAccounts"
    assert result["bindDisabledDuringRecovery"] is False
    assert result["sendCount"] == 0
    assert len(result["storage"]) == 1


def test_completed_disconnect_response_loss_recovers_without_wallet_auth(context):
    client, _service, _repository, _clock = context
    javascript = client.get("/account/static/account.js").text

    result = run_allowance_revoke_console(
        javascript,
        "full_disconnect_completed_recovery",
    )

    assert result["error"] is None
    assert result["coreDisconnected"] is True
    assert result["providerCalls"] == []
    assert result["sendCount"] == 0
    assert not any(
        call["url"].endswith("/refresh")
        for call in result["fetchCalls"]
    )
    assert result["storage"] == {}


def test_chain_change_during_preflight_prevents_transaction_send(context):
    client, _service, _repository, _clock = context
    javascript = client.get("/account/static/account.js").text

    result = run_allowance_console(javascript, "chain_changed_on_switch")

    assert result["sentTransaction"] is None
    assert result["verification"] is None


@pytest.mark.parametrize("scenario", ["wrong_chain", "delayed_chain_changed"])
def test_wrong_or_delayed_chain_change_prevents_allowance_send(context, scenario):
    client, _service, _repository, _clock = context
    javascript = client.get("/account/static/account.js").text

    result = run_allowance_console(javascript, scenario)

    assert result["sendCount"] == 0
    assert result["sentTransaction"] is None
    assert result["verification"] is None


def test_allowance_submission_is_single_flight_across_network_buttons(context):
    client, _service, _repository, _clock = context
    javascript = client.get("/account/static/account.js").text

    result = run_allowance_console(javascript, "concurrent_approve")

    assert result["approvalDisabledBeforeRace"] == [False, False]
    assert (
        result["sendCountWhileFirstDelayed"],
        result["sendCount"],
        result["approvalDisabledAfterFirstClick"],
    ) == (1, 1, [True, True])


def test_automatic_and_manual_pending_verification_are_single_flight(context):
    client, _service, _repository, _clock = context
    javascript = client.get("/account/static/account.js").text

    result = run_allowance_console(javascript, "manual_verify_during_auto_verify")

    assert (
        result["recoveryDisabledDuringAutoVerify"],
        result["verificationCountWhileAutoVerifyDelayed"],
        result["verificationCount"],
    ) == (True, 1, 1)
    assert result["storage"] == {}


def test_selection_change_after_transaction_hash_still_verifies_once(context):
    client, _service, _repository, _clock = context
    javascript = client.get("/account/static/account.js").text

    result = run_allowance_console(javascript, "changed_after_send")

    assert result["sendCount"] == 1
    assert result["verification"]["wallet_identity_id"] == "wallet_identity_b"
    assert result["verification"]["allowance_tx_hash"] == "0x" + "4" * 64


def test_provider_confirmation_failure_does_not_block_core_verification(context):
    client, _service, _repository, _clock = context
    javascript = client.get("/account/static/account.js").text

    result = run_allowance_console(javascript, "provider_confirmation_failure")

    assert result["sendCount"] == 1
    assert result["verification"]["wallet_identity_id"] == "wallet_identity_b"
    assert result["storage"] == {}


@pytest.mark.parametrize(
    ("scenario", "sentinel_persisted"),
    [
        ("invalid_hash_post_send_uncertain", True),
        ("invalid_hash_storage_write_failure", False),
    ],
)
def test_invalid_resolved_hash_blocks_second_send_without_core_verification(
    context, scenario, sentinel_persisted
):
    client, _service, _repository, _clock = context
    javascript = client.get("/account/static/account.js").text

    result = run_allowance_console(javascript, scenario)

    assert result["sendCountAfterMalformedHash"] == 1
    assert result["sendCountAfterBlockedRetry"] == 1
    assert result["sendCount"] == 1
    assert result["verificationCount"] == 0
    assert result["verification"] is None
    storage = result["storage"]
    assert attempt_storage_key("wallet_identity_b") in storage
    uncertain_key = uncertain_storage_key("/account", "wallet_identity_b")
    if sentinel_persisted:
        assert storage[uncertain_key] == UNCERTAIN_STORAGE_LABEL
    else:
        assert not any(
            key.startswith(UNCERTAIN_STORAGE_PREFIX)
            or key.startswith(UNCERTAIN_STORAGE_V2_PREFIX)
            for key in storage
        )
    assert result["uncertainApprovalDisabledAfterMalformed"] == [True, True]
    message = (
        result["uncertainMessageAfterMalformed"] + " " + result["pageStatus"]
    ).lower()
    assert "may have been submitted" in message
    assert "do not retry" in message
    assert "wallet" in message
    assert "support" in message
    assert "malformed-provider-secret-transaction-result" not in json.dumps(result)


def test_invalid_resolved_hash_stays_blocked_across_401_and_reauthentication(
    context,
):
    client, _service, _repository, _clock = context
    javascript = client.get("/account/static/account.js").text

    result = run_allowance_console(javascript, "invalid_hash_lock_reauth")

    assert result["sendCount"] == 1
    assert result["verificationCount"] == 0
    assert result["verification"] is None
    assert result["uncertainApprovalDisabledWhileLocked"] == [True, True]
    assert result["uncertainApprovalDisabledAfterReauthentication"] == [
        True,
        True,
    ]
    for message in (
        result["uncertainMessageWhileLocked"],
        result["uncertainMessageAfterReauthentication"],
    ):
        assert "do not retry" in message.lower()
        assert "support" in message.lower()


def test_invalid_resolved_hash_sentinel_blocks_same_path_reload(context):
    client, _service, _repository, _clock = context
    javascript = client.get("/account/static/account.js").text

    submitted = run_allowance_console(
        javascript, "invalid_hash_post_send_uncertain"
    )
    reloaded = run_allowance_console(javascript, "invalid_hash_same_path_reload")

    expected_uncertain_key = uncertain_storage_key(
        "/account", "wallet_identity_b"
    )
    assert submitted["storage"][expected_uncertain_key] == UNCERTAIN_STORAGE_LABEL
    assert reloaded["storage"] == {
        expected_uncertain_key: UNCERTAIN_STORAGE_LABEL
    }
    assert submitted["sendCount"] + reloaded["sendCount"] == 1
    assert submitted["verificationCount"] + reloaded["verificationCount"] == 0
    assert reloaded["approvalDisabled"] == [True, True]
    assert "do not retry" in reloaded["recoveryMessage"].lower()


def test_uncertain_sentinel_read_failure_blocks_before_wallet_send(context):
    client, _service, _repository, _clock = context
    javascript = client.get("/account/static/account.js").text

    result = run_allowance_console(
        javascript, "invalid_hash_sentinel_read_failure"
    )

    assert result["sendCount"] == 0
    assert result["verificationCount"] == 0
    assert result["approvalDisabled"] == [True, True]
    assert result["storage"] == {
        uncertain_storage_key("/account", "wallet_identity_b"):
            UNCERTAIN_STORAGE_LABEL
    }
    assert "storage" in (
        result["recoveryMessage"] + result["pageStatus"]
    ).lower()


@pytest.mark.parametrize(
    ("scenario", "sentinel_key"),
    [
        (
            "uncertain_cross_path",
            legacy_uncertain_storage_key(
                "/account/other", "wallet_identity_b"
            ),
        ),
        (
            "uncertain_inactive_identity",
            legacy_uncertain_storage_key(
                "/account", "wallet_identity_inactive"
            ),
        ),
    ],
)
def test_out_of_scope_uncertain_sentinel_is_untouched_and_does_not_block_current(
    context, scenario, sentinel_key
):
    client, _service, _repository, _clock = context
    javascript = client.get("/account/static/account.js").text

    result = run_allowance_console(javascript, scenario)

    if scenario == "uncertain_cross_path":
        assert result["sendCount"] == 0
        assert result["verificationCount"] == 0
        assert result["recoveryMessageHidden"] is False
    else:
        assert result["sendCount"] == 1
        assert result["verificationCount"] == 1
        assert result["recoveryMessageHidden"] is True
    assert result["storage"] == {sentinel_key: UNCERTAIN_STORAGE_LABEL}


def test_core_verify_failure_persists_public_tuple_for_reload_verify_only_recovery(
    context,
):
    client, _service, _repository, _clock = context
    javascript = client.get("/account/static/account.js").text

    submitted = run_allowance_console(javascript, "core_verify_failure")
    recovered = run_allowance_console(javascript, "reload_verify")

    assert submitted["sendCount"] == 1
    assert submitted["disabled"] is True
    expected_key = pending_storage_key("/account", "wallet_identity_b")
    expected_attempt_key = attempt_storage_key("wallet_identity_b")
    assert set(submitted["storage"]) == {expected_key, expected_attempt_key}
    stored = json.loads(submitted["storage"][expected_key])
    assert stored == {
        "wallet_identity_id": "wallet_identity_b",
        "network": POLYGON,
        "token_address": TOKEN,
        "spender_address": SPENDER,
        "allowance_tx_hash": "0x" + "4" * 64,
    }
    assert set(stored) == {
        "wallet_identity_id",
        "network",
        "token_address",
        "spender_address",
        "allowance_tx_hash",
    }
    assert "provider" not in json.dumps(stored).lower()
    assert "account" not in json.dumps(stored).lower().replace(
        "wallet_identity_id", ""
    )
    assert "secret" not in json.dumps(stored).lower()
    attempt = json.loads(submitted["storage"][expected_attempt_key])
    assert attempt["wallet_identity_id"] == "wallet_identity_b"
    assert attempt["network"] == POLYGON
    assert attempt["status"] == "pending"
    assert len(attempt["request_key"]) == 64
    assert "allowance_tx_hash" not in attempt

    assert recovered["sendCount"] == 0
    assert recovered["verification"] == stored
    assert recovered["storage"] == {}


def test_core_verify_failure_releases_single_flight_for_same_page_verify_only(
    context,
):
    client, _service, _repository, _clock = context
    javascript = client.get("/account/static/account.js").text

    result = run_allowance_console(javascript, "core_verify_failure_then_retry")

    assert result["sendCount"] == 1
    assert result["verificationCount"] == 2
    assert result["storage"] == {}
    assert result["disabled"] is False


def test_core_success_with_storage_cleanup_failure_remains_blocked(context):
    client, _service, _repository, _clock = context
    javascript = client.get("/account/static/account.js").text

    result = run_allowance_console(javascript, "core_success_cleanup_failure")

    assert result["sendCount"] == 1
    assert result["verificationCount"] == 1
    assert result["approvalDisabled"] == [True, True]
    assert result["recoveryHidden"] is False
    assert result["recoveryDisabled"] is False
    assert len(result["storage"]) == 1
    assert result["removeItemCalls"] >= 1
    assert "storage" in result["recoveryMessage"].lower()
    assert "clear" in result["recoveryMessage"].lower()


def test_storage_write_failure_refresh_and_core_failure_preserve_memory_recovery(
    context,
):
    client, _service, _repository, _clock = context
    javascript = client.get("/account/static/account.js").text

    result = run_allowance_console(
        javascript, "storage_write_failure_refresh_core_failure"
    )

    assert result["sendCount"] == 1
    assert result["verificationCount"] == 1
    assert set(result["storage"]) == {attempt_storage_key("wallet_identity_b")}
    retained_attempt = json.loads(
        result["storage"][attempt_storage_key("wallet_identity_b")]
    )
    assert retained_attempt["status"] == "pending"
    assert result["approvalDisabled"] == [True, True]
    assert result["recoveryHidden"] is False
    assert result["recoveryDisabled"] is False
    assert TX_HASH in result["recoveryMessage"]
    assert "without sending another transaction" in result["recoveryMessage"]


def test_locked_reauthentication_preserves_exact_memory_pending_verify_only_recovery(
    context,
):
    client, _service, _repository, _clock = context
    javascript = client.get("/account/static/account.js").text

    result = run_allowance_console(
        javascript, "storage_write_failure_lock_reauth_core_failure"
    )

    exact_pending = {
        "wallet_identity_id": "wallet_identity_b",
        "network": POLYGON,
        "token_address": TOKEN,
        "spender_address": SPENDER,
        "allowance_tx_hash": TX_HASH,
    }
    assert result["sendCount"] == 1
    assert result["verificationCount"] == 2
    assert result["verification"] == exact_pending
    assert set(result["storage"]) == {attempt_storage_key("wallet_identity_b")}
    retained_attempt = json.loads(
        result["storage"][attempt_storage_key("wallet_identity_b")]
    )
    assert retained_attempt["status"] == "pending"
    assert result["approvalDisabledWhileLocked"] == [True, True]
    assert result["approvalDisabledDuringReauthentication"] == [True, True]
    assert result["approvalDisabledAfterReauthentication"] == [True, True]
    assert result["recoveryHiddenWhileLocked"] is False
    assert result["recoveryHiddenAfterReauthentication"] is False
    assert TX_HASH in result["recoveryMessage"]
    assert "without sending another transaction" in result["recoveryMessage"]


def test_persistent_probe_remove_failure_blocks_every_refresh_before_send(context):
    client, _service, _repository, _clock = context
    javascript = client.get("/account/static/account.js").text

    result = run_allowance_console(javascript, "persistent_probe_remove_failure")

    assert result["sendCount"] == 0
    assert result["verification"] is None
    assert result["probeRefreshApprovalDisabled"] == [
        [True, True],
        [True, True],
    ]
    assert all(
        "storage" in message.lower()
        for message in result["probeRefreshRecoveryMessages"]
    )
    assert result["probeRemoveItemCalls"] >= 3
    assert len(result["probeMarkers"]) >= 3
    assert len(set(result["probeMarkers"])) == len(result["probeMarkers"])
    assert all("secret" not in marker.lower() for marker in result["probeMarkers"])


def test_pre_send_inaccessible_recovery_storage_blocks_every_wallet_send(context):
    client, _service, _repository, _clock = context
    javascript = client.get("/account/static/account.js").text

    result = run_allowance_console(javascript, "pre_send_storage_inaccessible")

    assert result["sendCount"] == 0
    assert result["verification"] is None
    assert result["approvalDisabled"] == [True, True]
    assert result["recoveryMessageHidden"] is False
    assert "storage" in (
        result["recoveryMessage"] + result["pageStatus"]
    ).lower()


def test_reload_malformed_current_scoped_pending_is_preserved_and_blocks_send(
    context,
):
    client, _service, _repository, _clock = context
    javascript = client.get("/account/static/account.js").text

    result = run_allowance_console(javascript, "reload_invalid_storage")

    assert result["sendCount"] == 0
    assert result["verification"] is None
    expected_record = {
        "wallet_identity_id": "wallet_identity_b",
        "network": POLYGON,
        "token_address": TOKEN,
        "spender_address": SPENDER,
        "allowance_tx_hash": TX_HASH,
        "provider": "must-not-load",
    }
    assert result["storage"] == {
        legacy_pending_storage_key("/account", "wallet_identity_b"): json.dumps(
            expected_record, separators=(",", ":")
        )
    }
    assert result["approvalDisabled"] == [True, True]
    assert result["removeItemCalls"] == 0
    assert result["recoveryMessageHidden"] is False
    assert "storage" in result["recoveryMessage"].lower()


def test_cross_path_pending_record_is_untouched_and_does_not_affect_current_path(
    context,
):
    client, _service, _repository, _clock = context
    javascript = client.get("/account/static/account.js").text

    result = run_allowance_console(javascript, "cross_path_record")

    expected_record = {
        "wallet_identity_id": "wallet_identity_b",
        "network": POLYGON,
        "token_address": TOKEN,
        "spender_address": SPENDER,
        "allowance_tx_hash": TX_HASH,
    }
    legacy_key = legacy_pending_storage_key(
        "/account/other", "wallet_identity_b"
    )
    current_key = pending_storage_key("/account", "wallet_identity_b")
    assert result["storage"] == {
        legacy_key: json.dumps(expected_record, separators=(",", ":")),
        current_key: json.dumps(expected_record, separators=(",", ":")),
    }
    assert result["sendCount"] == 0
    assert result["verification"] is None
    assert result["disabled"] is True
    assert result["recoveryHidden"] is False
    assert result["removeItemCalls"] == 0


def test_current_path_inactive_identity_record_is_untouched_and_not_consumed(
    context,
):
    client, _service, _repository, _clock = context
    javascript = client.get("/account/static/account.js").text

    result = run_allowance_console(javascript, "inactive_identity_storage")

    expected_record = {
        "wallet_identity_id": "wallet_identity_inactive",
        "network": POLYGON,
        "token_address": TOKEN,
        "spender_address": SPENDER,
        "allowance_tx_hash": TX_HASH,
    }
    assert result["storage"] == {
        legacy_pending_storage_key(
            "/account", "wallet_identity_inactive"
        ): json.dumps(expected_record, separators=(",", ":"))
    }
    assert result["verification"] is None
    assert result["disabled"] is False
    assert result["recoveryHidden"] is True
    assert result["removeItemCalls"] == 0


def test_current_path_active_identity_key_record_mismatch_blocks_without_delete(
    context,
):
    client, _service, _repository, _clock = context
    javascript = client.get("/account/static/account.js").text

    result = run_allowance_console(javascript, "key_record_mismatch")

    assert result["sendCount"] == 0
    assert result["verification"] is None
    assert result["approvalDisabled"] == [True, True]
    assert result["removeItemCalls"] == 0
    assert set(result["storage"]) == {
        legacy_pending_storage_key("/account", "wallet_identity_b")
    }
    assert result["recoveryMessageHidden"] is False


def test_stale_verification_cleanup_preserves_newer_full_pending_tuple(context):
    client, _service, _repository, _clock = context
    javascript = client.get("/account/static/account.js").text

    result = run_allowance_console(javascript, "stale_verify_cleanup")

    newer = {
        "wallet_identity_id": "wallet_identity_b",
        "network": BASE,
        "token_address": BASE_TOKEN,
        "spender_address": BASE_SPENDER,
        "allowance_tx_hash": TX_HASH,
    }
    expected_storage = {
        legacy_pending_storage_key("/account", "wallet_identity_b"): json.dumps(
            newer, separators=(",", ":")
        ),
        pending_storage_key("/account", "wallet_identity_b"): json.dumps(
            {
                "wallet_identity_id": "wallet_identity_b",
                "network": POLYGON,
                "token_address": TOKEN,
                "spender_address": SPENDER,
                "allowance_tx_hash": TX_HASH,
            },
            separators=(",", ":"),
        ),
    }
    assert result["verification"]["network"] == POLYGON
    assert result["storageBeforeCleanupReload"] == expected_storage
    assert result["pendingMessageHiddenBeforeCleanupReload"] is False
    assert result["storage"] == expected_storage
    assert result["removeItemCalls"] == 0


@pytest.mark.parametrize(
    "scenario",
    ["missing_provider", "mismatch", "unsupported"],
)
def test_allowance_browser_failure_keeps_action_disabled_and_sends_nothing(
    context, scenario
):
    client, _service, _repository, _clock = context
    javascript = client.get("/account/static/account.js").text

    result = run_allowance_console(javascript, scenario)

    assert result["disabled"] is True
    assert result["sentTransaction"] is None
    assert result["verification"] is None


def test_pre_send_failure_releases_operation_and_restores_readiness(context):
    client, _service, _repository, _clock = context
    javascript = client.get("/account/static/account.js").text

    result = run_allowance_console(javascript, "switch_failure")

    assert result["sendCount"] == 0
    assert result["storage"] == {}
    assert result["disabled"] is False


def test_console_grant_flow_signs_polygon_and_base_token_scopes(context):
    client, _service, _repository, _clock = context
    javascript = client.get("/account/static/account.js").text

    result = run_allowance_console(javascript, "grant")

    assert len(result["grantRequests"]) == 2
    for payload in result["grantRequests"]:
        assert payload["network_scopes"] == [POLYGON, BASE]
        assert payload["asset_scopes"] == [TOKEN, BASE_TOKEN]
        assert payload["per_transaction_limit_usdc"] == payload["max_amount_usdc"]
        assert payload["hourly_limit_usdc"] == payload["max_amount_usdc"]
        assert payload["daily_limit_usdc"] == payload["max_amount_usdc"]
        assert payload["merchant_trust_scopes"] == [
            "clink_verified",
            "registry_verified",
        ]
        assert payload["notification_mode"] == "silent_under_limits"


def test_console_amoy_browser_harness_runs_grant_and_approval(context):
    client, _service, _repository, _clock = context
    javascript = client.get("/account/static/account.js").text

    result = run_allowance_console(javascript, "amoy")

    assert "data-network=\"eip155:80002\"" in result["networkLedger"]
    assert "Polygon Amoy" in result["networkLedger"]
    assert len(result["grantRequests"]) == 2
    for payload in result["grantRequests"]:
        assert payload["network_scopes"] == [AMOY_NETWORK]
        assert payload["asset_scopes"] == [AMOY_NETWORK_CONFIG["token_address"]]
    assert result["switchRequests"] == [
        {"chainId": "0x13882"},
    ]
    assert result["sentTransaction"]["chainId"] == "0x13882"
    assert result["verification"]["network"] == AMOY_NETWORK
    assert result["confirmationBlockNumbers"] == ["0x64", "0x65", "0x66"]


def test_console_base_browser_approval_uses_two_confirmations(context):
    client, _service, _repository, _clock = context
    javascript = client.get("/account/static/account.js").text

    result = run_allowance_console(javascript, "base_approval")

    assert result["switchRequests"] == [{"chainId": "0x2105"}]
    assert result["sentTransaction"]["chainId"] == "0x2105"
    assert result["confirmationBlockNumbers"] == ["0x64", "0x65"]


def test_console_lowers_current_total_in_place_without_new_signature(context):
    client, _service, _repository, _clock = context
    javascript = client.get("/account/static/account.js").text

    result = run_allowance_console(javascript, "reduce_total")

    assert result["grantRequests"] == []
    assert result["personalSignRequest"] is None
    assert result["reduceRequests"] == [
        {
            "max_amount_usdc": "8",
            "per_transaction_limit_usdc": "8",
            "hourly_limit_usdc": "8",
            "daily_limit_usdc": "8",
        }
    ]


def test_console_amends_total_in_place_without_resetting_current_budget(context):
    client, _service, _repository, _clock = context
    javascript = client.get("/account/static/account.js").text

    result = run_allowance_console(javascript, "increase_total")

    assert len(result["grantRequests"]) == 2
    unsigned, signed = result["grantRequests"]
    assert unsigned["amends_spending_grant_id"] == "grant_b"
    assert unsigned["max_amount_usdc"] == "20"
    assert unsigned["per_transaction_limit_usdc"] == "20"
    assert unsigned["hourly_limit_usdc"] == "20"
    assert unsigned["daily_limit_usdc"] == "20"
    assert signed["amends_spending_grant_id"] == "grant_b"
    assert signed["challenge_session_id"] == "grant_session"
    assert result["reduceRequests"] == []
    assert result["personalSignRequest"]["params"] == [
        "grant terms",
        "0x" + "b" * 40,
    ]


def test_console_does_not_ask_again_when_total_is_already_set(context):
    client, _service, _repository, _clock = context
    javascript = client.get("/account/static/account.js").text

    result = run_allowance_console(javascript, "unchanged_total")

    assert result["grantRequests"] == []
    assert result["reduceRequests"] == []
    assert result["personalSignRequest"] is None


def test_production_console_fails_closed_when_either_chain_target_is_missing(
    tmp_path, monkeypatch
):
    monkeypatch.setenv(
        "CLINK_ACCOUNT_PUBLIC_BASE_URL", "https://account.example.com/core"
    )
    monkeypatch.setenv("CLINK_LIVE_FUNDING", "true")
    monkeypatch.setenv("CLINK_RISK_PROVIDER", "misttrack")
    monkeypatch.setenv("CLINK_RISK_MODE", "enforce")
    monkeypatch.setenv("MISTTRACK_API_KEY", "dummy-test-key")
    monkeypatch.setenv("CLINK_CORE_INTERNAL_API_TOKEN", INTERNAL_TOKEN)
    monkeypatch.setenv("CLINK_POLYGON_USDC_ADDRESS", TOKEN)
    monkeypatch.setenv("CLINK_POLYGON_SPENDER_ADDRESS", SPENDER)
    monkeypatch.delenv("CLINK_BASE_USDC_ADDRESS", raising=False)
    monkeypatch.delenv("CLINK_BASE_SPENDER_ADDRESS", raising=False)
    repository = AccountRepository(
        f"sqlite+pysqlite:///{tmp_path / 'missing-production-target.db'}"
    )
    service = AccountService(repository, domain="account.clink.test", clock=lambda: NOW)

    with pytest.raises(RuntimeError, match="Base.*approval target"):
        create_app(
            service=service,
            internal_token=INTERNAL_TOKEN,
            clock=lambda: NOW,
            audit_summary_reader=lambda _user_id, _limit: [],
        )


def test_public_read_only_console_allows_missing_chain_targets(
    tmp_path, monkeypatch
):
    monkeypatch.setenv(
        "CLINK_ACCOUNT_PUBLIC_BASE_URL", "https://account.example.com/core"
    )
    monkeypatch.setenv("CLINK_LIVE_FUNDING", "false")
    monkeypatch.setenv("CLINK_CORE_INTERNAL_API_TOKEN", INTERNAL_TOKEN)
    monkeypatch.delenv("CLINK_POLYGON_USDC_ADDRESS", raising=False)
    monkeypatch.delenv("CLINK_POLYGON_SPENDER_ADDRESS", raising=False)
    monkeypatch.delenv("CLINK_BASE_USDC_ADDRESS", raising=False)
    monkeypatch.delenv("CLINK_BASE_SPENDER_ADDRESS", raising=False)
    repository = AccountRepository(
        f"sqlite+pysqlite:///{tmp_path / 'read-only-public-console.db'}"
    )
    service = AccountService(
        repository,
        domain="account.clink.test",
        clock=lambda: NOW,
    )

    app = create_app(
        service=service,
        internal_token=INTERNAL_TOKEN,
        clock=lambda: NOW,
        audit_summary_reader=lambda _user_id, _limit: [],
    )
    client = ASGIClient(app)
    response = client.get("/healthz")

    assert response.status_code == 200


def test_account_api_creates_two_network_grant_and_verifies_independent_allowances(
    tmp_path,
):
    wallet = Account.create()
    polygon_tx_hash = "0x" + "71" * 32
    base_tx_hash = "0x" + "72" * 32
    targets = {
        POLYGON: {
            "token_address": TOKEN,
            "spender_address": SPENDER,
            "tx_hash": polygon_tx_hash,
            "chain_id": 137,
        },
        BASE: {
            "token_address": BASE_TOKEN,
            "spender_address": BASE_SPENDER,
            "tx_hash": base_tx_hash,
            "chain_id": 8453,
        },
    }

    def approve_calldata(spender: str, amount: int) -> str:
        return (
            "0x095ea7b3"
            + ("0" * 24)
            + spender.removeprefix("0x")
            + amount.to_bytes(32, "big").hex()
        )

    def rpc(network, method, params):
        target = targets[network]
        if method == "eth_chainId":
            return hex(target["chain_id"])
        if method == "eth_getTransactionReceipt":
            return {
                "status": "0x1",
                "transactionHash": target["tx_hash"],
                "blockNumber": "0x20",
            }
        if method == "eth_getTransactionByHash":
            return {
                "hash": target["tx_hash"],
                "from": wallet.address,
                "to": target["token_address"],
                "input": approve_calldata(target["spender_address"], 25_000_000),
                "blockNumber": "0x20",
            }
        if method == "eth_blockNumber":
            return "0x20"
        if method == "eth_call":
            return hex(25_000_000)
        raise AssertionError(method)

    database_url = f"sqlite+pysqlite:///{tmp_path / 'two-network-api.db'}"
    repository = AccountRepository(database_url)
    owner = WalletIdentity(
        **identity("user_1", "a").model_dump(exclude={"wallet_address"}),
        wallet_address=wallet.address,
    )
    repository.save_wallet_identity(owner)
    network_configs = {
        network: {
            "chain_id": target["chain_id"],
            "required_confirmations": 1,
            "token_symbol": "USDC",
            "token_decimals": 6,
            "token_address": target["token_address"],
        }
        for network, target in targets.items()
    }
    service = AccountService(
        repository,
        domain="account.clink.test",
        clock=lambda: NOW,
        rpc_transport=rpc,
        network_configs=network_configs,
    )
    app = create_app(
        service=service,
        internal_token=INTERNAL_TOKEN,
        clock=lambda: NOW,
        audit_summary_reader=lambda _user_id, _limit: [],
        approval_targets={
            network: {
                "token_address": target["token_address"],
                "spender_address": target["spender_address"],
            }
            for network, target in targets.items()
        },
    )
    client = ASGIClient(app)
    create_authenticated_session(client, "user_1", wallet)
    grant_payload = {
        "wallet_identity_id": owner.wallet_identity_id,
        "agent_id": "hermes",
        "max_amount_usdc": "25",
        "per_transaction_limit_usdc": "5",
        "daily_limit_usdc": "10",
        "product_scopes": ["prediction_markets", "marketplace"],
        "venue_scopes": ["polymarket", "clink_marketplace"],
        "merchant_scopes": [],
        "network_scopes": [POLYGON, BASE],
        "asset_scopes": [TOKEN, BASE_TOKEN],
        "starts_at": NOW.isoformat(),
        "expires_at": (NOW + timedelta(days=30)).isoformat(),
    }
    challenge = client.post("/account/grants", json=grant_payload).json()
    signature = Account.sign_message(
        encode_defunct(text=challenge["message_to_sign"]), wallet.key
    ).signature.hex()

    created = client.post(
        "/account/grants",
        json={
            **grant_payload,
            "challenge_session_id": challenge["session_id"],
            "signed_message": challenge["message_to_sign"],
            "signature": signature,
        },
    )
    amendment_payload = {
        **grant_payload,
        "amends_spending_grant_id": created.json()["spending_grant_id"],
        "max_amount_usdc": "30",
        "per_transaction_limit_usdc": "30",
        "hourly_limit_usdc": "30",
        "daily_limit_usdc": "30",
    }
    amendment_challenge = client.post(
        "/account/grants", json=amendment_payload
    ).json()
    amendment_signature = Account.sign_message(
        encode_defunct(text=amendment_challenge["message_to_sign"]), wallet.key
    ).signature.hex()
    amended = client.post(
        "/account/grants",
        json={
            **amendment_payload,
            "challenge_session_id": amendment_challenge["session_id"],
            "signed_message": amendment_challenge["message_to_sign"],
            "signature": amendment_signature,
        },
    )
    allowance_responses = [
        client.post(
            "/account/allowances/verify",
            json={
                "wallet_identity_id": owner.wallet_identity_id,
                "network": network,
                "token_address": target["token_address"],
                "spender_address": target["spender_address"],
                "allowance_tx_hash": target["tx_hash"],
            },
        )
        for network, target in targets.items()
    ]

    assert created.status_code == 201
    assert amended.status_code == 201
    assert amended.json()["spending_grant_id"] == created.json()[
        "spending_grant_id"
    ]
    assert amended.json()["max_amount_usdc"] == "30"
    assert len(repository.spending_grants("user_1")) == 1
    assert created.json()["network_scopes"] == [POLYGON, BASE]
    assert created.json()["asset_scopes"] == [TOKEN, BASE_TOKEN]
    assert [response.status_code for response in allowance_responses] == [200, 200]
    assert {
        (item.network, item.token_address, item.spender_address)
        for item in repository.asset_allowances(owner.wallet_identity_id)
    } == {
        (POLYGON, TOKEN, SPENDER),
        (BASE, BASE_TOKEN, BASE_SPENDER),
    }


def test_account_state_exposes_only_canonical_supported_approval_targets(tmp_path):
    repository = AccountRepository(f"sqlite+pysqlite:///{tmp_path / 'targets.db'}")
    clock = Clock()
    service = AccountService(repository, domain="account.clink.test", clock=clock)
    owner = identity("user_1", "a")
    repository.save_wallet_identity(owner)
    repository.save_spending_grant(grant(owner, "a"))
    app = create_app(
        service=service,
        internal_token=INTERNAL_TOKEN,
        clock=clock,
        audit_summary_reader=lambda _user_id, _limit: [],
        approval_targets={
            POLYGON: {
                "token_address": TOKEN.upper().replace("0X", "0x"),
                "spender_address": SPENDER.upper().replace("0X", "0x"),
            }
        },
    )
    client = ASGIClient(app)
    session_id = create_authenticated_session(client, "user_1")

    response = client.get(
        "/account", headers={"Accept": "application/json"}
    )

    assert response.status_code == 200
    assert response.json()["approval_targets"] == {
        POLYGON: {"token_address": TOKEN, "spender_address": SPENDER}
    }


def test_account_state_projects_current_spending_mandate_from_history(context):
    client, _service, repository, _clock = context
    owner = identity("user_1", "a")
    repository.save_wallet_identity(owner)
    history = [
        grant(owner, "superseded").model_copy(
            update={"status": "revoked", "status_reason": "grant_superseded"}
        ),
        grant(owner, "revoked_a", status="revoked"),
        grant(owner, "revoked_b", status="revoked"),
    ]
    active = grant(owner, "active").model_copy(
        update={
            "per_transaction_limit_usdc": Decimal("1"),
            "hourly_limit_usdc": Decimal("2"),
            "daily_limit_usdc": Decimal("5"),
        }
    )
    for item in [*history, active]:
        repository.save_spending_grant(item)
    create_authenticated_session(client, "user_1")

    body = client.get("/account", headers={"Accept": "application/json"}).json()

    assert len(body["spending_grants"]) == 4
    assert body["current_spending_mandate"]["spending_grant_id"] == (
        active.spending_grant_id
    )
    assert body["current_spending_mandate"]["status"] == "active"
    assert body["current_spending_mandate"]["limits_usdc"] == {
        "per_transaction": "1",
        "rolling_hour": "2",
        "daily": "5",
        "total": "25",
    }
    assert body["current_spending_mandate"]["used_usdc"] == {
        "rolling_hour": "0",
        "daily": "0",
        "total": "0",
    }
    assert body["current_spending_mandate"]["reserved_usdc"] == {
        "rolling_hour": "0",
        "daily": "0",
        "total": "0",
    }
    assert body["current_spending_mandate"]["remaining_usdc"] == {
        "rolling_hour": "2",
        "daily": "5",
        "total": "25",
    }


def test_account_state_projects_paused_current_spending_mandate(context):
    client, _service, repository, _clock = context
    owner = identity("user_1", "a")
    repository.save_wallet_identity(owner)
    paused = grant(owner, "paused", status="paused")
    repository.save_spending_grant(paused)
    create_authenticated_session(client, "user_1")

    body = client.get("/account", headers={"Accept": "application/json"}).json()

    assert body["current_spending_mandate"]["spending_grant_id"] == (
        paused.spending_grant_id
    )
    assert body["current_spending_mandate"]["status"] == "paused"


def test_account_state_returns_no_current_spending_mandate_for_closed_history(context):
    client, _service, repository, _clock = context
    owner = identity("user_1", "a")
    repository.save_wallet_identity(owner)
    repository.save_spending_grant(grant(owner, "revoked", status="revoked"))
    repository.save_spending_grant(grant(owner, "expired", status="expired"))
    create_authenticated_session(client, "user_1")

    body = client.get("/account", headers={"Accept": "application/json"}).json()

    assert body["current_spending_mandate"] is None


def test_account_state_fails_closed_for_multiple_current_spending_mandates(context):
    client, _service, repository, _clock = context
    owner = identity("user_1", "a")
    repository.save_wallet_identity(owner)
    repository.save_spending_grant(grant(owner, "active_a"))
    repository.save_spending_grant(grant(owner, "active_b"))
    create_authenticated_session(client, "user_1")

    body = client.get("/account", headers={"Accept": "application/json"}).json()

    assert body["current_spending_mandate"] is None


def test_removed_wallet_session_configuration_is_not_exposed(tmp_path):
    repository = AccountRepository(
        f"sqlite+pysqlite:///{tmp_path / 'wallet-session-config.db'}"
    )
    clock = Clock()
    service = AccountService(repository, domain="account.clink.test", clock=clock)
    app = create_app(
        service=service,
        internal_token=INTERNAL_TOKEN,
        clock=clock,
        audit_summary_reader=lambda _user_id, _limit: [],
    )
    client = ASGIClient(app)
    create_session(client)

    response = client.get("/account/wallet-session-config")

    assert response.status_code == 404


def test_invalid_grant_domain_returns_generic_json_not_internal_500(context):
    client, _service, repository, _clock = context
    owner = identity("user_1", "a")
    repository.save_wallet_identity(owner)
    session_id = create_authenticated_session(client, "user_1")
    payload = {
        "wallet_identity_id": owner.wallet_identity_id,
        "agent_id": "hermes",
        "max_amount_usdc": "5",
        "per_transaction_limit_usdc": "6",
        "daily_limit_usdc": "5",
        "product_scopes": ["prediction_markets", "marketplace"],
        "venue_scopes": ["polymarket", "clink_marketplace"],
        "merchant_scopes": [],
        "network_scopes": [POLYGON, BASE],
        "asset_scopes": [TOKEN],
        "starts_at": NOW.isoformat(),
        "expires_at": (NOW + timedelta(days=7)).isoformat(),
    }

    response = client.post("/account/grants", json=payload)

    assert response.status_code in {400, 422}
    assert response.headers["content-type"].startswith("application/json")
    assert response.json() == {"detail": "request could not be completed"}
    assert "per-transaction" not in response.text


def test_console_parser_handles_non_json_error_responses_without_exposing_body(context):
    client, _service, _repository, _clock = context

    javascript = client.get("/account/static/account.js").text

    assert "const parseResponse" in javascript
    assert "await response.json()" in javascript
    assert "Request could not be completed" in javascript
    assert "await response.text()" not in javascript
    assert javascript.count("await parseResponse(response)") >= 2


def test_console_exposes_one_signed_total_editor_pause_and_revoke_actions(context):
    client, _service, _repository, _clock = context
    create_session(client)

    html = client.get("/account", headers={"Accept": "text/html"}).text
    javascript = client.get("/account/static/account.js").text

    assert "data-grant-action" in javascript
    assert "Review and sign total limit" in html
    assert "Change total limit" in javascript
    assert "Valid until" in javascript
    assert "Reduce limits" not in javascript
    assert "Pause access" in javascript
    assert "Resume access" in javascript
    assert "Revoke access" in javascript
    assert "Unbind wallet from Clink" in javascript
    assert (
        "/wallet-identities/${workingPlan.wallet_identity_id}/disconnect"
        in javascript
    )
    assert "resume-wallet-disconnect" in javascript
    assert "/grants/${grantId}/${action}" in javascript


def test_public_state_is_bound_to_session_user(context):
    client, _service, repository, _clock = context
    owner = identity("user_1", "a")
    other = identity("user_2", "b")
    for item in (owner, other):
        repository.save_wallet_identity(item)
        repository.save_spending_grant(grant(item, item.wallet_identity_id[-1]))
        repository.save_asset_allowance(allowance(item, item.wallet_identity_id[-1]))
    session_id = create_authenticated_session(client, "user_1")

    response = client.get(
        "/account", headers={"Accept": "application/json"}
    )

    assert response.status_code == 200
    body = response.json()
    serialized = response.text
    assert body["user_id"] == "user_1"
    assert [item["wallet_identity_id"] for item in body["wallet_identities"]] == [
        owner.wallet_identity_id
    ]
    assert "spending_grant_a" in serialized and "asset_allowance_a" in serialized
    assert other.wallet_identity_id not in serialized
    assert "spending_grant_b" not in serialized and "asset_allowance_b" not in serialized
    assert INTERNAL_TOKEN not in serialized


def test_public_state_is_scoped_to_the_authenticated_wallet(context):
    client, _service, repository, _clock = context
    first = identity("user_1", "a", status="revoked")
    selected = identity("user_1", "b")
    for item in (first, selected):
        repository.save_wallet_identity(item)
        repository.save_spending_grant(
            grant(
                item,
                item.wallet_identity_id[-1],
                status=(
                    "revoked"
                    if item.status == "revoked"
                    else "active"
                ),
            )
        )
        repository.save_asset_allowance(
            allowance(
                item,
                item.wallet_identity_id[-1],
            ).model_copy(
                update={
                    "status": (
                        "revoked"
                        if item.status == "revoked"
                        else "active"
                    )
                }
            )
        )
    selected_wallet = Account.from_key(bytes.fromhex("b" * 64))
    create_authenticated_session(client, "user_1", selected_wallet)

    response = client.get("/account", headers={"Accept": "application/json"})

    assert response.status_code == 200
    body = response.json()
    assert body["wallet_identities"][0]["wallet_identity_id"] == selected.wallet_identity_id
    assert [item["spending_grant_id"] for item in body["spending_grants"]] == [
        "spending_grant_b"
    ]
    assert [item["asset_allowance_id"] for item in body["asset_allowances"]] == [
        "asset_allowance_b"
    ]
    assert body["readiness"]["ready"] is True


def test_pending_grant_is_not_reported_as_active(context):
    client, _service, repository, _clock = context
    owner = identity("user_1", "a")
    repository.save_wallet_identity(owner)
    pending = grant(owner, "pending", status="pending").model_copy(
        update={"starts_at": NOW + timedelta(days=1)}
    )
    repository.save_spending_grant(pending)
    repository.save_asset_allowance(allowance(owner, "polygon", network=POLYGON))
    repository.save_asset_allowance(allowance(owner, "base", network=BASE))
    create_authenticated_session(client, "user_1")

    response = client.get("/account", headers={"Accept": "application/json"})

    assert response.status_code == 200
    assert response.json()["readiness"]["spending_grant_active"] is False
    assert response.json()["readiness"]["ready"] is False


def test_public_audit_summary_uses_real_exact_user_events_and_safe_fields(tmp_path):
    repository = AccountRepository(f"sqlite+pysqlite:///{tmp_path / 'account.db'}")
    clock = Clock()
    service = AccountService(repository, domain="account.clink.test", clock=clock)
    audit_service = AuditService(
        storage_file=tmp_path / "audit.jsonl",
        clock=clock,
    )
    audit_service.write_event(
        WriteAuditEventRequest(
            event_type="grant_reduced",
            source_service="account_service",
            user_id="user_1",
            action_id="private_action_id",
            payload={"secret": "never-public"},
        )
    )
    audit_service.write_event(
        WriteAuditEventRequest(
            event_type="event_secret_private_key_123",
            source_service="service_secret_seed_phrase_456",
            user_id="user_1",
        )
    )
    audit_service.write_event(
        WriteAuditEventRequest(
            event_type="wallet_revoked",
            source_service="account_service",
            user_id="user_2",
            payload={"other": True},
        )
    )
    app = create_app(
        service=service,
        internal_token=INTERNAL_TOKEN,
        clock=clock,
        audit_summary_reader=audit_service.get_user_summary,
    )
    client = ASGIClient(app)
    session_id = create_authenticated_session(client, "user_1")

    response = client.get(
        "/account", headers={"Accept": "application/json"}
    )

    assert response.status_code == 200
    assert response.json()["recent_audit_summary"] == [
        {
            "event": "Account activity",
            "summary": "Recorded by Clink Core",
            "at": "2026-07-15T12:00:00Z",
        },
        {
            "event": "Grant reduced",
            "summary": "Recorded by account service",
            "at": "2026-07-15T12:00:00Z",
        }
    ]
    assert "never-public" not in response.text
    assert "private_action_id" not in response.text
    assert "private_key" not in response.text
    assert "seed_phrase" not in response.text
    assert "user_2" not in response.text


def test_public_session_rejects_unknown_and_expired_ids(context):
    client, _service, _repository, clock = context
    session_id = create_account_link(client)

    missing = client.get("/account/not-a-real-session")
    clock.now += timedelta(minutes=16)
    expired = client.get(f"/account/{session_id}")

    assert missing.status_code == 404
    assert expired.status_code == 410
    assert missing.json() == {"detail": "account session unavailable"}
    assert expired.json() == {"detail": "account session unavailable"}


def test_wallet_challenge_and_verification_are_bound_to_console_user(context):
    client, _service, repository, _clock = context
    other_client = ASGIClient(client.app)
    wallet = Account.create()
    create_session(client, "user_1")
    create_session(other_client, "user_2")

    challenge_response = client.post(
        "/account/wallet-challenge",
        json={"wallet_address": wallet.address},
    )
    challenge = challenge_response.json()
    signature = Account.sign_message(
        encode_defunct(text=challenge["message_to_sign"]), wallet.key
    ).signature.hex()

    cross_user = other_client.post(
        "/account/wallet-verify",
        json={
            "challenge_session_id": challenge["session_id"],
            "signed_message": challenge["message_to_sign"],
            "signature": signature,
        },
    )
    verified = client.post(
        "/account/wallet-verify",
        json={
            "challenge_session_id": challenge["session_id"],
            "signed_message": challenge["message_to_sign"],
            "signature": signature,
        },
    )

    assert challenge_response.status_code == 200
    assert cross_user.status_code == 404
    assert verified.status_code == 200
    assert verified.json()["user_id"] == "user_1"
    assert repository.active_wallet_identities("user_1")
    assert repository.active_wallet_identities("user_2") == []


def test_grant_challenge_forces_session_user_and_wallet_ownership(context):
    client, _service, repository, _clock = context
    owner = identity("user_1", "a")
    other = identity("user_2", "b")
    repository.save_wallet_identity(owner)
    repository.save_wallet_identity(other)
    session_id = create_authenticated_session(client, "user_1")
    payload = {
        "user_id": "user_2",
        "wallet_identity_id": other.wallet_identity_id,
        "agent_id": "hermes",
        "max_amount_usdc": "25",
        "per_transaction_limit_usdc": "5",
        "daily_limit_usdc": "10",
        "product_scopes": ["prediction_markets", "marketplace"],
        "venue_scopes": ["polymarket", "clink_marketplace"],
        "merchant_scopes": [],
        "network_scopes": [POLYGON, BASE],
        "asset_scopes": [TOKEN],
        "starts_at": NOW.isoformat(),
        "expires_at": (NOW + timedelta(days=7)).isoformat(),
    }

    response = client.post("/account/grants", json=payload)

    assert response.status_code == 404
    assert repository.active_spending_grants("user_1", at=NOW) == []
    assert repository.active_spending_grants("user_2", at=NOW) == []


def test_grant_signature_cannot_be_replayed_through_another_user_session(context):
    client, service, repository, _clock = context
    other_client = ASGIClient(client.app)
    wallet = Account.create()
    owner = WalletIdentity(
        **identity("user_1", "a").model_dump(exclude={"wallet_address"}),
        wallet_address=wallet.address,
    )
    repository.save_wallet_identity(owner)
    create_authenticated_session(client, "user_1", wallet)
    create_authenticated_session(other_client, "user_2")
    payload = {
        "wallet_identity_id": owner.wallet_identity_id,
        "agent_id": "hermes",
        "max_amount_usdc": "25",
        "per_transaction_limit_usdc": "5",
        "daily_limit_usdc": "10",
        "product_scopes": ["prediction_markets", "marketplace"],
        "venue_scopes": ["polymarket", "clink_marketplace"],
        "merchant_scopes": [],
        "network_scopes": [POLYGON, BASE],
        "asset_scopes": [TOKEN],
        "starts_at": NOW.isoformat(),
        "expires_at": (NOW + timedelta(days=7)).isoformat(),
    }
    challenge = client.post("/account/grants", json=payload).json()
    signature = Account.sign_message(
        encode_defunct(text=challenge["message_to_sign"]), wallet.key
    ).signature.hex()
    signed = {
        **payload,
        "challenge_session_id": challenge["session_id"],
        "signed_message": challenge["message_to_sign"],
        "signature": signature,
    }

    cross_user = other_client.post("/account/grants", json=signed)
    created = client.post("/account/grants", json=signed)

    assert cross_user.status_code == 404
    assert created.status_code == 201
    assert created.json()["user_id"] == "user_1"
    assert service.repository.active_spending_grants("user_1", at=NOW)


def test_allowance_verification_refuses_cross_user_identity(context):
    client, service, repository, _clock = context
    owner = identity("user_1", "a")
    other = identity("user_2", "b")
    repository.save_wallet_identity(owner)
    repository.save_wallet_identity(other)
    session_id = create_authenticated_session(client, "user_1")
    called = []

    def verify(**values):
        called.append(values)
        return allowance(owner, "verified")

    service.verify_asset_allowance = verify
    payload = {
        "wallet_identity_id": other.wallet_identity_id,
        "network": POLYGON,
        "token_address": TOKEN,
        "spender_address": SPENDER,
        "allowance_tx_hash": TX_HASH,
    }

    response = client.post("/account/allowances/verify", json=payload)

    assert response.status_code == 404
    assert called == []


@pytest.mark.parametrize("action", ["pause", "resume", "reduce", "revoke"])
def test_every_grant_lifecycle_route_refuses_cross_user_objects(context, action):
    client, _service, repository, _clock = context
    owner = identity("user_1", "a")
    other = identity("user_2", "b")
    repository.save_wallet_identity(owner)
    repository.save_wallet_identity(other)
    foreign_grant = grant(other, "b")
    repository.save_spending_grant(foreign_grant)
    session_id = create_authenticated_session(client, "user_1")
    payload = (
        {"max_amount_usdc": "20", "per_transaction_limit_usdc": "4", "daily_limit_usdc": "8"}
        if action == "reduce"
        else {}
    )

    response = client.post(
        f"/account/grants/{foreign_grant.spending_grant_id}/{action}",
        json=payload,
    )

    assert response.status_code == 404
    assert repository.spending_grant(foreign_grant.spending_grant_id).status == "active"


def test_wallet_revoke_refuses_cross_user_identity(context):
    client, _service, repository, _clock = context
    other = identity("user_2", "b")
    repository.save_wallet_identity(other)
    session_id = create_authenticated_session(client, "user_1")

    response = client.post(
        f"/account/wallet-identities/{other.wallet_identity_id}/revoke"
    )

    assert response.status_code == 404
    assert repository.wallet_identity(other.wallet_identity_id).status == "active"


def test_lifecycle_routes_reject_credential_bearing_extra_bodies(context):
    client, _service, repository, _clock = context
    owner = identity("user_1", "a")
    repository.save_wallet_identity(owner)
    permission = grant(owner, "a")
    repository.save_spending_grant(permission)
    session_id = create_session(client, "user_1")

    grant_response = client.post(
        f"/account/grants/{permission.spending_grant_id}/pause",
        json={"private_key": "secret"},
    )
    wallet_response = client.post(
        f"/account/wallet-identities/{owner.wallet_identity_id}/revoke",
        json={"seed_phrase": "secret"},
    )

    assert grant_response.status_code == wallet_response.status_code == 422
    assert "secret" not in grant_response.text + wallet_response.text
    assert repository.spending_grant(permission.spending_grant_id).status == "active"
    assert repository.wallet_identity(owner.wallet_identity_id).status == "active"


@pytest.mark.parametrize(
    "path,payload",
    [
        ("wallet-challenge", {"wallet_address": "0x" + "11" * 20, "private_key": "secret"}),
        ("wallet-challenge", {"wallet_address": "0x" + "11" * 20, "seed_phrase": "secret"}),
        ("wallet-challenge", {"wallet_address": "0x" + "11" * 20, "polymarket_credentials": "secret"}),
        ("wallet-challenge", {"wallet_address": "0x" + "11" * 20, "platform_api_secret": "secret"}),
    ],
)
def test_public_forms_reject_wallet_and_platform_secrets(context, path, payload):
    client, _service, _repository, _clock = context
    session_id = create_session(client)

    response = client.post(f"/account/{path}", json=payload)

    assert response.status_code == 422
    assert "secret" not in response.text.lower()


def test_public_errors_do_not_expose_internal_exception_details(context):
    client, service, _repository, _clock = context
    session_id = create_session(client)

    def fail(*_args, **_kwargs):
        raise ValueError(f"rpc failed with {INTERNAL_TOKEN} at postgresql://private")

    service.create_wallet_challenge = fail
    response = client.post(
        "/account/wallet-challenge",
        json={"wallet_address": "0x" + "11" * 20},
    )

    assert response.status_code == 400
    assert response.json() == {"detail": "request could not be completed"}
    assert INTERNAL_TOKEN not in response.text
    assert "postgresql" not in response.text
