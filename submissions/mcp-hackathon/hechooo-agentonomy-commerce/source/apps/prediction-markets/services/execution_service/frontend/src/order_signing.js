import { hashDomain, hashStruct } from "viem";

const POLYGON_CHAIN_ID = "0x89";
const SESSION_URL = "/execution/polymarket/browser-order-signing-session";
const STATUS_URL = `${SESSION_URL}/status`;
const COMPLETE_URL = `${SESSION_URL}/complete`;
const STANDARD_EXCHANGE = "0xE111180000d2663C0091e4f400237545B87B996B";
const NEG_RISK_EXCHANGE = "0xe2222d279d744050d28e00520010520000310F59";
const PUSD_COLLATERAL = "0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB";
const ZERO_BYTES32 = `0x${"00".repeat(32)}`;
const ORDER_TYPE_STRING = "Order(uint256 salt,address maker,address signer,uint256 tokenId,uint256 makerAmount,uint256 takerAmount,uint8 side,uint8 signatureType,uint256 timestamp,bytes32 metadata,bytes32 builder)";
const MODE_SIGNATURE_TYPE = Object.freeze({ eoa: 0, proxy: 1, safe: 2, deposit_wallet: 3 });
const ORDER_FIELDS = Object.freeze([
  ["salt", "uint256"],
  ["maker", "address"],
  ["signer", "address"],
  ["tokenId", "uint256"],
  ["makerAmount", "uint256"],
  ["takerAmount", "uint256"],
  ["side", "uint8"],
  ["signatureType", "uint8"],
  ["timestamp", "uint256"],
  ["metadata", "bytes32"],
  ["builder", "bytes32"],
]);
const TYPED_DATA_SIGN_FIELDS = Object.freeze([
  ["contents", "Order"],
  ["name", "string"],
  ["version", "string"],
  ["chainId", "uint256"],
  ["verifyingContract", "address"],
  ["salt", "bytes32"],
]);
const DOMAIN_FIELDS = Object.freeze([
  { name: "name", type: "string" },
  { name: "version", type: "string" },
  { name: "chainId", type: "uint256" },
  { name: "verifyingContract", type: "address" },
]);
const HEX_SIGNATURE = /^0x[0-9a-fA-F]{130}$/;
const HEX_32 = /^0x[0-9a-fA-F]{64}$/;
const SHA256 = /^[0-9a-f]{64}$/;
const ADDRESS = /^0x[0-9a-fA-F]{40}$/;

function extractCapability(window) {
  const raw = String(window.location.hash || "");
  const params = new URLSearchParams(raw.startsWith("#") ? raw.slice(1) : raw);
  const token = params.get("access_token");
  if (!token || params.size !== 1 || token.length > 256) {
    throw new Error("Order signing capability is unavailable.");
  }
  window.history.replaceState(
    null,
    "",
    `${window.location.pathname}${window.location.search || ""}`,
  );
  if (window.location.hash) window.location.hash = "";
  return token;
}

function utf8Hex(value) {
  return Array.from(new TextEncoder().encode(value), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

function wrapDepositWalletSignatureParts(rawSignature, domainSeparator, contentsHash) {
  if (!HEX_SIGNATURE.test(rawSignature) || !HEX_32.test(domainSeparator) || !HEX_32.test(contentsHash)) {
    throw new Error("Wallet signature is invalid.");
  }
  const orderTypeHex = utf8Hex(ORDER_TYPE_STRING);
  const lengthHex = (orderTypeHex.length / 2).toString(16).padStart(4, "0");
  return `${rawSignature}${domainSeparator.slice(2)}${contentsHash.slice(2)}${orderTypeHex}${lengthHex}`;
}

function finalizeWalletSignature(rawSignature, session) {
  if (!HEX_SIGNATURE.test(rawSignature)) {
    throw new Error("Wallet signature is invalid.");
  }
  const signatureType = session.order_payload.order.signatureType;
  if (signatureType !== 3) return rawSignature;
  const typedData = session.order_payload.typed_data;
  const domainSeparator = hashDomain({
    domain: typedData.domain,
    types: { EIP712Domain: DOMAIN_FIELDS },
  });
  const contentsHash = hashStruct({
    data: typedData.message.contents,
    primaryType: "Order",
    types: typedData.types,
  });
  return wrapDepositWalletSignatureParts(
    rawSignature,
    domainSeparator,
    contentsHash,
  );
}

function assertSessionProjection(session) {
  if (!session || typeof session !== "object" || session.status !== "pending_browser_signature") {
    throw new Error("This order is not waiting for a wallet signature.");
  }
  const payload = session.order_payload;
  const typedData = payload && payload.typed_data;
  const order = payload && payload.order;
  const domain = typedData && typedData.domain;
  const walletMode = String(session.wallet_mode || "").toLowerCase();
  const expectedSignatureType = MODE_SIGNATURE_TYPE[walletMode];
  const exactKeys = (value, expected) => Boolean(
    value
    && typeof value === "object"
    && !Array.isArray(value)
    && JSON.stringify(Object.keys(value).sort()) === JSON.stringify([...expected].sort()),
  );
  const typeEntries = (value) => Array.isArray(value)
    ? value.map((field) => [field && field.name, field && field.type])
    : [];
  const sameTypes = (actual, expected) => JSON.stringify(typeEntries(actual)) === JSON.stringify(expected);
  const typeKeys = typedData && typedData.types
    ? Object.keys(typedData.types).sort()
    : [];
  const expectedTypeKeys = walletMode === "deposit_wallet"
    ? ["Order", "TypedDataSign"]
    : ["Order"];
  const orderKeys = order && typeof order === "object"
    ? Object.keys(order).sort()
    : [];
  const expectedOrderKeys = [
    ...ORDER_FIELDS.map(([name]) => name),
    "expiration",
  ].sort();
  const payloadKeys = [
    "typed_data", "order", "orderType", "exchange", "collateral",
    "tickSize", "minOrderSize", "negRisk", "provenance", "projection_sha256",
  ];
  const provenanceKeys = [
    "preview_id", "market_id", "core_action_id", "core_policy_decision_id",
    "funding_operation_id",
  ];
  const expectedExchange = payload && payload.negRisk === true
    ? NEG_RISK_EXCHANGE
    : STANDARD_EXCHANGE;
  const messageKeys = walletMode === "deposit_wallet"
    ? ["contents", "name", "version", "chainId", "verifyingContract", "salt"]
    : ORDER_FIELDS.map(([name]) => name);
  if (
    !payload
    || !typedData
    || !order
    || !domain
    || !ADDRESS.test(String(session.wallet_address || ""))
    || !ADDRESS.test(String(payload.exchange || ""))
    || typeof session.session_id !== "string"
    || !session.session_id.startsWith("pm_sign_sess_")
    || session.session_id.length > 128
    || domain.name !== "Polymarket CTF Exchange"
    || domain.version !== "2"
    || Number(domain.chainId) !== 137
    || String(domain.verifyingContract).toLowerCase() !== String(payload.exchange).toLowerCase()
    || !exactKeys(payload, payloadKeys)
    || !exactKeys(typedData, ["domain", "types", "primaryType", "message"])
    || !exactKeys(domain, ["name", "version", "chainId", "verifyingContract"])
    || !exactKeys(typedData.message, messageKeys)
    || !exactKeys(payload.provenance, provenanceKeys)
    || Object.values(payload.provenance).some((value) => typeof value !== "string" || !value)
    || typeof payload.negRisk !== "boolean"
    || String(payload.exchange).toLowerCase() !== expectedExchange.toLowerCase()
    || String(session.exchange).toLowerCase() !== expectedExchange.toLowerCase()
    || String(payload.collateral).toLowerCase() !== PUSD_COLLATERAL.toLowerCase()
    || !SHA256.test(String(payload.projection_sha256 || ""))
    || expectedSignatureType === undefined
    || order.signatureType !== expectedSignatureType
    || typedData.primaryType !== (walletMode === "deposit_wallet" ? "TypedDataSign" : "Order")
    || JSON.stringify(typeKeys) !== JSON.stringify(expectedTypeKeys.sort())
    || !sameTypes(typedData.types.Order, ORDER_FIELDS)
    || (walletMode === "deposit_wallet" && !sameTypes(typedData.types.TypedDataSign, TYPED_DATA_SIGN_FIELDS))
    || JSON.stringify(orderKeys) !== JSON.stringify(expectedOrderKeys)
    || !["GTC", "GTD"].includes(payload.orderType)
    || String(order.side) !== String(session.side || "").toUpperCase()
  ) {
    throw new Error("The server order projection is invalid.");
  }
  const typedOrder = walletMode === "deposit_wallet"
    ? typedData.message && typedData.message.contents
    : typedData.message;
  if (
    !typedOrder
    || !exactKeys(typedOrder, ORDER_FIELDS.map(([name]) => name))
    || String(typedOrder.maker).toLowerCase() !== String(order.maker).toLowerCase()
    || String(typedOrder.signer).toLowerCase() !== String(order.signer).toLowerCase()
    || String(typedOrder.salt) !== String(order.salt)
    || String(typedOrder.tokenId) !== String(order.tokenId)
    || String(typedOrder.makerAmount) !== String(order.makerAmount)
    || String(typedOrder.takerAmount) !== String(order.takerAmount)
    || Number(typedOrder.side) !== (order.side === "BUY" ? 0 : order.side === "SELL" ? 1 : -1)
    || Number(typedOrder.signatureType) !== Number(order.signatureType)
    || String(typedOrder.timestamp) !== String(order.timestamp)
    || String(typedOrder.metadata) !== String(order.metadata)
    || String(typedOrder.builder) !== String(order.builder)
  ) {
    throw new Error("The server order projection has changed.");
  }
  const wallet = String(session.wallet_address).toLowerCase();
  const maker = String(order.maker).toLowerCase();
  const signer = String(order.signer).toLowerCase();
  if (
    (walletMode === "deposit_wallet" ? maker !== signer : signer !== wallet)
    || (walletMode === "eoa" && maker !== wallet)
    || ((walletMode === "proxy" || walletMode === "safe") && maker === wallet)
  ) {
    throw new Error("The order signer does not match the bound wallet.");
  }
  if (walletMode === "deposit_wallet") {
    const outer = typedData.message;
    if (
      outer.name !== "DepositWallet"
      || outer.version !== "1"
      || Number(outer.chainId) !== 137
      || String(outer.verifyingContract).toLowerCase() !== signer
      || outer.salt !== ZERO_BYTES32
    ) {
      throw new Error("The Deposit Wallet projection is invalid.");
    }
  }
  return session;
}

function createOrderSigningPage({ document, window, fetch }) {
  const elements = {
    title: document.getElementById("order-title"),
    outcome: document.getElementById("order-outcome"),
    side: document.getElementById("order-side"),
    amount: document.getElementById("order-amount"),
    limit: document.getElementById("order-limit-price"),
    worst: document.getElementById("order-worst-price"),
    slippage: document.getElementById("order-slippage"),
    wallet: document.getElementById("order-wallet"),
    exchange: document.getElementById("order-exchange"),
    mode: document.getElementById("order-signature-mode"),
    walletList: document.getElementById("wallet-list"),
    sign: document.getElementById("sign-order"),
    status: document.getElementById("order-status"),
    returnLink: document.getElementById("return-link"),
  };
  let capability = null;
  let session = null;
  let selectedProvider = null;
  let pending = false;
  let submissionAttempted = false;
  let providerSwitchLocked = false;
  let exited = false;
  let generation = 0;
  const providers = new Map();
  const providerListeners = new Map();

  function setStatus(message) {
    elements.status.textContent = message;
  }

  function headers(json = false) {
    if (!capability) throw new Error("Order signing capability is unavailable.");
    return {
      Authorization: `Bearer ${capability}`,
      "X-Clink-Origin": window.location.origin,
      ...(json ? { "Content-Type": "application/json" } : {}),
    };
  }

  async function api(url, init = {}) {
    const response = await fetch(url, {
      ...init,
      headers: { ...headers(Boolean(init.body)), ...(init.headers || {}) },
      credentials: "omit",
      referrerPolicy: "no-referrer",
      cache: "no-store",
    });
    if (!response.ok) throw new Error("Order signing request was rejected.");
    return response.json();
  }

  function renderSession(value) {
    elements.title.textContent = String(value.title || "Unknown market");
    elements.outcome.textContent = String(value.outcome || "—");
    elements.side.textContent = String(value.side || "—").toUpperCase();
    elements.amount.textContent = `${String(value.amount_usd || "—")} pUSD`;
    elements.limit.textContent = String(value.limit_price ?? "—");
    elements.worst.textContent = String(value.worst_case_price ?? "—");
    elements.slippage.textContent = `${String(value.max_slippage_bps ?? 0)} bps`;
    elements.wallet.textContent = String(value.wallet_address || "—");
    elements.exchange.textContent = String(value.exchange || "—");
    elements.mode.textContent = value.wallet_mode === "deposit_wallet"
      ? "Deposit Wallet"
      : String(value.wallet_mode || "—").toUpperCase();
    elements.returnLink.setAttribute?.("href", String(value.return_url || "/"));
  }

  function detachProvider() {
    if (!selectedProvider) return;
    const listeners = providerListeners.get(selectedProvider);
    if (listeners && typeof selectedProvider.removeListener === "function") {
      selectedProvider.removeListener("accountsChanged", listeners.accountsChanged);
      selectedProvider.removeListener("chainChanged", listeners.chainChanged);
    }
    providerListeners.delete(selectedProvider);
  }

  function invalidateWallet(message) {
    generation += 1;
    pending = false;
    elements.sign.disabled = true;
    setStatus(message);
  }

  function selectProvider(provider, button) {
    if (pending && selectedProvider && selectedProvider !== provider) {
      generation += 1;
      pending = false;
      providerSwitchLocked = true;
    }
    detachProvider();
    selectedProvider = provider;
    for (const candidate of elements.walletList.children) {
      candidate.dataset.selected = candidate === button ? "true" : "false";
    }
    if (typeof provider.on === "function") {
      const listeners = {
        accountsChanged: () => invalidateWallet("Wallet account changed. Reopen this order."),
        chainChanged: () => invalidateWallet("Wallet network changed. Reopen this order."),
      };
      provider.on("accountsChanged", listeners.accountsChanged);
      provider.on("chainChanged", listeners.chainChanged);
      providerListeners.set(provider, listeners);
    }
    elements.sign.disabled = !session || pending || submissionAttempted || providerSwitchLocked;
    setStatus(
      providerSwitchLocked
        ? "Wallet changed during this attempt. Reopen the order to continue."
        : "Ready. Confirm once to request the wallet signature.",
    );
  }

  function addProvider(detail) {
    const provider = detail && detail.provider;
    if (!provider || typeof provider.request !== "function") return;
    const key = String((detail.info && detail.info.uuid) || `provider-${providers.size}`);
    if (providers.has(key)) return;
    providers.set(key, provider);
    const button = document.createElement("button");
    button.type = "button";
    button.textContent = String((detail.info && detail.info.name) || "Browser wallet");
    button.addEventListener("click", () => selectProvider(provider, button));
    elements.walletList.append(button);
    if (providers.size === 1) selectProvider(provider, button);
  }

  const announceProvider = (event) => addProvider(event.detail);

  async function pollStatus() {
    const status = await api(STATUS_URL);
    if (exited) return null;
    if (status.status === "submitted") {
      setStatus("Order submitted. Return to Agentonomy to monitor it.");
      elements.returnLink.hidden = false;
    } else {
      setStatus("Submission status is uncertain. No second order was sent.");
    }
    elements.sign.disabled = true;
    return status;
  }

  async function signOnce() {
    if (
      pending
      || submissionAttempted
      || providerSwitchLocked
      || exited
      || !session
      || !selectedProvider
    ) return;
    pending = true;
    elements.sign.disabled = true;
    const attempt = generation;
    const provider = selectedProvider;
    try {
      assertSessionProjection(session);
      const chainId = await provider.request({ method: "eth_chainId" });
      if (attempt !== generation || exited) return;
      if (String(chainId).toLowerCase() !== POLYGON_CHAIN_ID) {
        throw new Error("Switch your wallet to Polygon before signing.");
      }
      const accounts = await provider.request({ method: "eth_requestAccounts" });
      const account = String((accounts && accounts[0]) || "");
      if (account.toLowerCase() !== String(session.wallet_address).toLowerCase()) {
        throw new Error("Select the bound wallet before signing.");
      }
      if (attempt !== generation || exited) return;
      submissionAttempted = true;
      const rawSignature = await provider.request({
        method: "eth_signTypedData_v4",
        params: [account, JSON.stringify(session.order_payload.typed_data)],
      });
      if (attempt !== generation || exited) return;
      const signature = finalizeWalletSignature(rawSignature, session);
      const signedOrder = {
        order: { ...session.order_payload.order, signature },
        orderType: session.order_payload.orderType,
      };
      try {
        const completed = await api(COMPLETE_URL, {
          method: "POST",
          body: JSON.stringify({
            signed_order: signedOrder,
            wallet_address: account,
            order_type: session.order_payload.orderType,
          }),
        });
        if (attempt !== generation || exited) return;
        setStatus(
          completed.status === "submitted"
            ? "Order submitted. Return to Agentonomy to monitor it."
            : "Order was not submitted. Return to Agentonomy for status.",
        );
        elements.returnLink.hidden = false;
        elements.sign.disabled = true;
      } catch (error) {
        if (attempt !== generation || exited) return;
        elements.sign.disabled = true;
        try {
          await pollStatus();
        } catch (_statusError) {
          if (attempt !== generation || exited) return;
          setStatus("Submission status is uncertain. No second order will be sent.");
          elements.sign.disabled = true;
        }
        return;
      }
    } catch (error) {
      if (attempt !== generation || exited) return;
      pending = false;
      elements.sign.disabled = submissionAttempted || providerSwitchLocked;
      setStatus(String(error && error.message ? error.message : "Wallet signing failed."));
    }
  }

  async function start() {
    const startGeneration = generation;
    try {
      capability = extractCapability(window);
      window.addEventListener("eip6963:announceProvider", announceProvider);
      window.dispatchEvent(new Event("eip6963:requestProvider"));
      if (window.ethereum) {
        addProvider({
          info: { uuid: "window-ethereum", name: "Browser wallet" },
          provider: window.ethereum,
        });
      }
      const loaded = await api(SESSION_URL);
      if (exited || startGeneration !== generation) return;
      session = assertSessionProjection(loaded);
      renderSession(session);
      elements.sign.disabled = !selectedProvider || submissionAttempted || providerSwitchLocked;
      setStatus(
        selectedProvider
          ? "Ready. Confirm once to request the wallet signature."
          : "Choose a browser wallet to continue.",
      );
    } catch (error) {
      if (!exited) {
        elements.sign.disabled = true;
        setStatus(String(error && error.message ? error.message : "Order could not be loaded."));
      }
    }
  }

  function exit() {
    exited = true;
    generation += 1;
    pending = false;
    capability = null;
    session = null;
    elements.sign.disabled = true;
    detachProvider();
    window.removeEventListener("eip6963:announceProvider", announceProvider);
    window.removeEventListener("pagehide", exit);
  }

  elements.sign.addEventListener("click", signOnce);
  window.addEventListener("pagehide", exit);
  return { exit, pollStatus, signOnce, start };
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = {
    ORDER_TYPE_STRING,
    assertSessionProjection,
    createOrderSigningPage,
    extractCapability,
    finalizeWalletSignature,
    wrapDepositWalletSignatureParts,
  };
}

/* istanbul ignore next -- browser bootstrap */
if (typeof document !== "undefined" && typeof window !== "undefined") {
  createOrderSigningPage({ document, window, fetch: window.fetch.bind(window) }).start();
}
