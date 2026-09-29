"use strict";

(function () {
function createAdminConsole({ document, window, fetch, sessionStorage }) {
const TOKEN_KEY = "clink.marketplace.session";
const WALLET_KEY = "clink.marketplace.wallet";
const state = {
  token: sessionStorage.getItem(TOKEN_KEY),
  wallet: sessionStorage.getItem(WALLET_KEY),
};
const PROVIDER_OPERATION_PATHS = { suspend: "/suspend", restore: "/restore" };

const byId = (id) => document.getElementById(id);

function log(message, kind = "neutral") {
  const item = document.createElement("li");
  item.className = kind;
  const time = document.createElement("time");
  time.textContent = new Date().toLocaleTimeString([], { hour: "2-digit", minute: "2-digit" });
  const text = document.createElement("span");
  text.textContent = message;
  item.append(time, text);
  byId("operation-log").prepend(item);
}

function report(id, message, kind = "neutral") {
  const target = byId(id);
  target.textContent = message;
  target.className = `result-line ${kind}`;
  log(message, kind);
}

async function request(path, { method = "GET", json: payload, auth = true } = {}) {
  const headers = { Accept: "application/json" };
  if (payload !== undefined) headers["Content-Type"] = "application/json";
  if (auth) {
    if (!state.token) throw new Error("Connect an allowlisted wallet first.");
    headers.Authorization = `Bearer ${state.token}`;
  }
  const response = await fetch(path, {
    method,
    headers,
    body: payload === undefined ? undefined : JSON.stringify(payload),
  });
  const contentType = response.headers.get("content-type") || "";
  const body = contentType.includes("application/json") ? await response.json() : await response.text();
  if (!response.ok) {
    const detail = typeof body === "object" ? body.detail : body;
    throw new Error(`${response.status}: ${detail || "Request failed"}`);
  }
  return body;
}

function walletProvider() {
  if (!window.ethereum) throw new Error("No browser EVM wallet was detected.");
  return window.ethereum;
}

async function connectWallet() {
  report("status-result", "Requesting wallet access...", "pending");
  const ethereum = walletProvider();
  const [wallet] = await ethereum.request({ method: "eth_requestAccounts" });
  if (!wallet) throw new Error("The wallet did not return an account.");
  const config = await request("/auth/siwe/config", { auth: false });
  const domain = [window.location.host, window.location.hostname]
    .find((value) => config.allowed_domains.includes(value)) || config.allowed_domains[0];
  if (!domain) throw new Error("No SIWE domain is configured for this console.");
  const challenge = await request("/auth/siwe/challenge", {
    method: "POST",
    auth: false,
    json: { address: wallet, domain },
  });
  const signature = await ethereum.request({ method: "personal_sign", params: [challenge.message, wallet] });
  const verified = await request("/auth/siwe/verify", {
    method: "POST",
    auth: false,
    json: { address: wallet, nonce: challenge.nonce, message: challenge.message, signature },
  });
  state.token = verified.access_token;
  state.wallet = verified.wallet_address;
  sessionStorage.setItem(TOKEN_KEY, state.token);
  sessionStorage.setItem(WALLET_KEY, state.wallet);
  updateSessionLabel();
  report("status-result", `Admin SIWE session active for ${state.wallet}.`, "success");
  await Promise.all([loadStatus(), loadProviders()]);
}

function updateSessionLabel() {
  byId("wallet-state").textContent = state.wallet
    ? `${state.wallet.slice(0, 8)}...${state.wallet.slice(-6)}`
    : "Admin session required";
}

function runtimeCard(title, value) {
  const card = document.createElement("article");
  card.className = "runtime-card";
  const heading = document.createElement("h3");
  heading.textContent = title;
  const detail = document.createElement("pre");
  detail.textContent = JSON.stringify(value, null, 2);
  card.append(heading, detail);
  return card;
}

async function loadStatus() {
  try {
    report("status-result", "Loading authenticated runtime status...", "pending");
    const status = await request("/admin/status");
    byId("overall-status").textContent = status.status;
    byId("worker-status").textContent = status.worker.status;
    byId("core-status").textContent = status.core.status;
    byId("registry-status").textContent = String(status.registries.length);
    const detail = byId("runtime-detail");
    detail.replaceChildren(
      runtimeCard("Worker", status.worker),
      runtimeCard("Registries", status.registries),
      runtimeCard("Core", status.core),
      runtimeCard("Pilot metrics", status.metrics),
    );
    report("status-result", `Runtime is ${status.status}; authenticated read completed.`, status.status === "ok" ? "success" : "pending");
  } catch (error) {
    report("status-result", error.message, "error");
  }
}

async function syncRegistries() {
  try {
    report("status-result", "Running fenced Registry synchronization...", "pending");
    const result = await request("/admin/registries/sync", { method: "POST" });
    report("status-result", `Registry sync finished for ${result.registries.length} source(s).`, "success");
    await Promise.all([loadStatus(), loadProviders()]);
  } catch (error) {
    report("status-result", error.message, "error");
  }
}

async function loadProviders(event) {
  if (event) event.preventDefault();
  try {
    report("provider-result", "Loading provider controls...", "pending");
    const params = new URLSearchParams();
    const query = byId("provider-query").value.trim();
    const status = byId("provider-status").value;
    if (query) params.set("query", query);
    if (status) params.set("status", status);
    const result = await request(`/admin/providers?${params.toString()}`);
    renderProviders(result.providers);
    byId("provider-count").textContent = String(result.count);
    report("provider-result", `${result.count} provider${result.count === 1 ? "" : "s"} loaded.`, "success");
  } catch (error) {
    report("provider-result", error.message, "error");
  }
}

function operationButton(providerId, status) {
  const operation = status === "suspended" ? "restore" : "suspend";
  const button = document.createElement("button");
  button.type = "button";
  button.className = operation === "suspend" ? "button danger small" : "button primary small";
  button.textContent = operation === "suspend" ? "Suspend" : "Restore";
  button.addEventListener("click", () => updateProvider(providerId, operation));
  return button;
}

function renderProviders(providers) {
  const table = byId("provider-table");
  table.replaceChildren();
  providers.forEach((record) => {
    const provider = record.provider;
    const row = document.createElement("tr");
    const identity = document.createElement("td");
    const name = document.createElement("strong");
    name.textContent = provider.name;
    const domain = document.createElement("code");
    domain.textContent = provider.domain;
    const id = document.createElement("code");
    id.textContent = provider.provider_id;
    identity.append(name, domain, id);
    const owner = document.createElement("td");
    const ownerCode = document.createElement("code");
    ownerCode.textContent = record.owner_wallet_address || "Unclaimed";
    owner.append(ownerCode);
    const status = document.createElement("td");
    status.textContent = provider.status;
    const offerings = document.createElement("td");
    offerings.textContent = `${record.offerings.length} total`;
    const action = document.createElement("td");
    action.append(operationButton(provider.provider_id, provider.status));
    row.append(identity, owner, status, offerings, action);
    table.append(row);
  });
}

async function updateProvider(providerId, operation) {
  try {
    const operationPath = PROVIDER_OPERATION_PATHS[operation];
    if (!operationPath) throw new Error("Unsupported provider operation.");
    report("provider-result", `${operation} requested for ${providerId}...`, "pending");
    const result = await request(`/admin/providers/${encodeURIComponent(providerId)}${operationPath}`, { method: "POST" });
    report("provider-result", `${result.provider_id} is now ${result.status}.`, "success");
    await Promise.all([loadProviders(), loadStatus()]);
  } catch (error) {
    report("provider-result", error.message, "error");
  }
}

byId("connect-wallet").addEventListener("click", () => connectWallet().catch((error) => report("status-result", error.message, "error")));
byId("refresh-status").addEventListener("click", loadStatus);
byId("sync-registry").addEventListener("click", syncRegistries);
byId("provider-filter").addEventListener("submit", loadProviders);

updateSessionLabel();
if (state.token) Promise.all([loadStatus(), loadProviders()]);
}

if (typeof module === "object" && module.exports) {
  module.exports = { createAdminConsole };
} else {
  const initialize = () => createAdminConsole({ document, window, fetch, sessionStorage });
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initialize, { once: true });
  } else {
    initialize();
  }
}
})();
