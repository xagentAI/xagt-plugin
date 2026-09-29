"use strict";

(function () {
function createMerchantConsole({ document, window, fetch, sessionStorage }) {
const TOKEN_KEY = "clink.marketplace.session";
const WALLET_KEY = "clink.marketplace.wallet";
const state = {
  token: sessionStorage.getItem(TOKEN_KEY),
  wallet: sessionStorage.getItem(WALLET_KEY),
  manifestId: null,
  providerId: null,
};

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
    if (!state.token) throw new Error("Connect and sign in before continuing.");
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
  report("auth-result", "Requesting wallet access...", "pending");
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
  const signature = await ethereum.request({
    method: "personal_sign",
    params: [challenge.message, wallet],
  });
  const verified = await request("/auth/siwe/verify", {
    method: "POST",
    auth: false,
    json: {
      address: wallet,
      nonce: challenge.nonce,
      message: challenge.message,
      signature,
    },
  });
  state.token = verified.access_token;
  state.wallet = verified.wallet_address;
  sessionStorage.setItem(TOKEN_KEY, state.token);
  sessionStorage.setItem(WALLET_KEY, state.wallet);
  updateSessionLabel();
  report("auth-result", `SIWE session active for ${state.wallet}.`, "success");
  await refreshPortfolio();
}

function updateSessionLabel() {
  byId("wallet-state").textContent = state.wallet
    ? `${state.wallet.slice(0, 8)}...${state.wallet.slice(-6)}`
    : "Wallet disconnected";
}

function actionButton(label, handler, className = "button small") {
  const button = document.createElement("button");
  button.type = "button";
  button.className = className;
  button.textContent = label;
  button.addEventListener("click", handler);
  return button;
}

function statusChip(value) {
  const chip = document.createElement("span");
  const good = ["active", "verified", "domain_verified", "wallet_verified"].includes(value);
  const bad = ["disabled", "rejected", "suspended", "stale"].includes(value);
  chip.className = `status-chip ${good ? "success" : bad ? "error" : "neutral"}`;
  chip.textContent = value || "unknown";
  return chip;
}

async function searchCandidates(event) {
  event.preventDefault();
  try {
    report("candidate-result", "Searching Bazaar candidate records...", "pending");
    const params = new URLSearchParams();
    for (const id of ["candidate-query", "candidate-domain", "candidate-pay-to"]) {
      const input = byId(id);
      if (input.value.trim()) params.set(input.name, input.value.trim());
    }
    const result = await request(`/merchant/candidates?${params.toString()}`);
    renderCandidates(result.candidates);
    report("candidate-result", `${result.count} candidate${result.count === 1 ? "" : "s"} found.`, "success");
  } catch (error) {
    report("candidate-result", error.message, "error");
  }
}

function renderCandidates(candidates) {
  const list = byId("candidate-list");
  list.replaceChildren();
  candidates.forEach(({ provider, offering }) => {
    const card = document.createElement("article");
    card.className = "record";
    const head = document.createElement("div");
    head.className = "record-head";
    const title = document.createElement("h3");
    title.textContent = offering.name;
    head.append(title, statusChip(offering.status));
    const domain = document.createElement("p");
    domain.textContent = `${provider.domain} · ${offering.method} ${offering.endpoint}`;
    const id = document.createElement("p");
    id.className = "mono";
    id.textContent = offering.offering_id;
    const claim = actionButton("Claim draft", () => claimDraft(offering.offering_id), "button primary small");
    card.append(head, domain, id, claim);
    list.append(card);
  });
}

async function claimDraft(offeringId) {
  try {
    report("candidate-result", "Creating a canonical claim draft...", "pending");
    const result = await request(`/merchant/candidates/${encodeURIComponent(offeringId)}/claim-draft`, { method: "POST" });
    byId("manifest-editor").value = JSON.stringify(result.manifest, null, 2);
    byId("manifest-editor").focus();
    report("candidate-result", "Draft loaded into the Manifest editor. Review every payment field.", "success");
  } catch (error) {
    report("candidate-result", error.message, "error");
  }
}

async function submitManifest() {
  try {
    report("manifest-result", "Validating and submitting Manifest JSON...", "pending");
    const manifest = JSON.parse(byId("manifest-editor").value);
    const result = await request("/merchant/manifests", { method: "POST", json: manifest });
    state.manifestId = result.manifest_id;
    state.providerId = result.provider_id;
    report("manifest-result", `Manifest ${result.manifest_id} is ${result.status}.`, "success");
    await refreshPortfolio();
  } catch (error) {
    report("manifest-result", error instanceof SyntaxError ? `Invalid JSON: ${error.message}` : error.message, "error");
  }
}

async function signClaim() {
  try {
    if (!state.manifestId) throw new Error("Submit a Manifest in this session first.");
    report("claim-result", "Requesting an EIP-712 ManifestClaim signature...", "pending");
    const challenge = await request(`/merchant/manifests/${encodeURIComponent(state.manifestId)}/claim-challenge`, { method: "POST" });
    const signature = await walletProvider().request({
      method: "eth_signTypedData_v4",
      params: [state.wallet, JSON.stringify(challenge.typed_data)],
    });
    const result = await request(`/merchant/manifests/${encodeURIComponent(state.manifestId)}/submit-claim`, {
      method: "POST",
      json: { claim: challenge.claim, signature, wallet_address: state.wallet },
    });
    state.providerId = result.provider_id;
    report("claim-result", `ManifestClaim accepted. Provider is ${result.status}.`, "success");
    await refreshPortfolio();
  } catch (error) {
    report("claim-result", error.message, "error");
  }
}

async function verifyDomain() {
  try {
    if (!state.providerId) throw new Error("Submit and sign a Manifest in this session first.");
    report("domain-result", "Checking the public domain proof...", "pending");
    const result = await request(`/merchant/providers/${encodeURIComponent(state.providerId)}/verify-domain`, { method: "POST" });
    report("domain-result", `Domain proof accepted. Provider is ${result.status}.`, "success");
    await refreshProvider(state.providerId);
  } catch (error) {
    report("domain-result", error.message, "error");
  }
}

async function verifyOffering(offeringId) {
  try {
    report("portfolio-result", `Running live x402 verification for ${offeringId}...`, "pending");
    const result = await request(`/merchant/offerings/${encodeURIComponent(offeringId)}/verify`, { method: "POST" });
    report("portfolio-result", `${offeringId} is ${result.status}; live 402 fields matched.`, "success");
    await refreshPortfolio();
  } catch (error) {
    report("portfolio-result", error.message, "error");
  }
}

async function disableOffering(offeringId) {
  try {
    report("portfolio-result", `Disabling ${offeringId}...`, "pending");
    const result = await request(`/merchant/offerings/${encodeURIComponent(offeringId)}/disable`, { method: "POST" });
    report("portfolio-result", `${result.offering_id} is ${result.status}.`, "success");
    await refreshPortfolio();
  } catch (error) {
    report("portfolio-result", error.message, "error");
  }
}

async function refreshProvider(providerId) {
  const record = await request(`/merchant/providers/${encodeURIComponent(providerId)}/status`);
  state.providerId = providerId;
  renderProviders([record]);
  byId("provider-count").textContent = "1";
  report("portfolio-result", `Loaded current status for ${providerId}.`, "success");
}

async function refreshPortfolio() {
  try {
    const [providers, manifests] = await Promise.all([
      request("/merchant/providers"),
      request("/merchant/manifests"),
    ]);
    renderProviders(providers.providers);
    renderManifests(manifests.manifests);
    byId("provider-count").textContent = String(providers.count);
    report("portfolio-result", `${providers.count} provider${providers.count === 1 ? "" : "s"} and ${manifests.count} Manifest${manifests.count === 1 ? "" : "s"} loaded.`, "success");
  } catch (error) {
    report("portfolio-result", error.message, "error");
  }
}

function renderManifests(manifests) {
  const list = byId("manifest-list");
  list.replaceChildren();
  manifests.forEach((manifest) => {
    const card = document.createElement("article");
    card.className = "record";
    const head = document.createElement("div");
    head.className = "record-head";
    const title = document.createElement("h3");
    title.textContent = manifest.provider_name;
    head.append(title, statusChip(manifest.status));
    const domain = document.createElement("p");
    domain.textContent = `${manifest.domain} · ${manifest.offering_count} offering${manifest.offering_count === 1 ? "" : "s"}`;
    const id = document.createElement("p");
    id.className = "mono";
    id.textContent = manifest.manifest_id;
    const use = actionButton("Continue Manifest", () => {
      state.manifestId = manifest.manifest_id;
      state.providerId = manifest.provider_id;
      report("claim-result", `Selected ${manifest.manifest_id}; continue signing or domain verification.`, "success");
    }, "button primary small");
    card.append(head, domain, id, use);
    list.append(card);
  });
}

function renderProviders(providers) {
  const list = byId("provider-list");
  list.replaceChildren();
  providers.forEach((record) => {
    const provider = record.provider;
    const card = document.createElement("article");
    card.className = "record";
    const head = document.createElement("div");
    head.className = "record-head";
    const title = document.createElement("h3");
    title.textContent = provider.name;
    head.append(title, statusChip(provider.status));
    const domain = document.createElement("p");
    domain.textContent = provider.domain;
    const id = document.createElement("p");
    id.className = "mono";
    id.textContent = provider.provider_id;
    const refresh = actionButton("Exact status", () => refreshProvider(provider.provider_id));
    const offerings = document.createElement("div");
    offerings.className = "offering-list";
    record.offerings.forEach((offering) => {
      const row = document.createElement("div");
      row.className = "offering-row";
      const label = document.createElement("p");
      label.textContent = `${offering.name} · ${offering.status}`;
      const actions = document.createElement("div");
      actions.className = "offering-actions";
      actions.append(
        actionButton("Verify live x402", () => verifyOffering(offering.offering_id), "button primary small"),
        actionButton("Disable", () => disableOffering(offering.offering_id), "button danger small"),
      );
      row.append(label, actions);
      offerings.append(row);
    });
    card.append(head, domain, id, refresh, offerings);
    list.append(card);
  });
}

byId("connect-wallet").addEventListener("click", () => connectWallet().catch((error) => report("auth-result", error.message, "error")));
byId("candidate-form").addEventListener("submit", searchCandidates);
byId("submit-manifest").addEventListener("click", submitManifest);
byId("sign-claim").addEventListener("click", signClaim);
byId("verify-domain").addEventListener("click", verifyDomain);
byId("refresh-portfolio").addEventListener("click", refreshPortfolio);

updateSessionLabel();
if (state.token) refreshPortfolio();
}

if (typeof module === "object" && module.exports) {
  module.exports = { createMerchantConsole };
} else {
  const initialize = () => createMerchantConsole({ document, window, fetch, sessionStorage });
  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", initialize, { once: true });
  } else {
    initialize();
  }
}
})();
