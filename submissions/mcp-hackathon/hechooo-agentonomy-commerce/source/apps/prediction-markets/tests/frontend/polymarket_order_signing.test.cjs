"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const ROOT = path.resolve(__dirname, "../..");
const SOURCE = path.join(
  ROOT,
  "services/execution_service/frontend/src/order_signing.js",
);
const STATIC_HTML = path.join(
  ROOT,
  "services/execution_service/static/polymarket_order_signing.html",
);

const ACCOUNT = "0x1111111111111111111111111111111111111111";
const SIGNER = "0x2222222222222222222222222222222222222222";
const EXCHANGE = "0xE111180000d2663C0091e4f400237545B87B996B";
const NEG_RISK_EXCHANGE = "0xe2222d279d744050d28e00520010520000310F59";
const PUSD = "0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB";
const CAPABILITY = "browser-capability-token";
const ORDER_FIELDS = [
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
];

function loadModule() {
  const source = fs.readFileSync(SOURCE, "utf8")
    .replace(
      /^import \{ hashDomain, hashStruct \} from "viem";\s*/m,
      "const { hashDomain, hashStruct } = dependencies;\n",
    )
    .replace(/^import[^;]+;\s*/gm, "")
    .replace(/\/\* istanbul ignore next -- browser bootstrap \*\/[\s\S]*$/, "");
  const module = { exports: {} };
  const viem = require(path.join(
    ROOT,
    "services/execution_service/frontend/node_modules/viem",
  ));
  new Function("dependencies", "module", "exports", source)(viem, module, module.exports);
  return module.exports;
}

class FakeElement {
  constructor(id = "") {
    this.id = id;
    this.textContent = "";
    this.disabled = false;
    this.hidden = false;
    this.children = [];
    this.listeners = new Map();
    this.dataset = {};
  }

  addEventListener(type, handler) {
    const handlers = this.listeners.get(type) || [];
    handlers.push(handler);
    this.listeners.set(type, handlers);
  }

  append(...children) {
    this.children.push(...children);
  }

  replaceChildren(...children) {
    this.children = [...children];
  }

  async dispatch(type) {
    for (const handler of this.listeners.get(type) || []) {
      await handler({ type, target: this, preventDefault() {} });
    }
  }
}

class FakeDocument {
  constructor() {
    const ids = [
      "order-title", "order-outcome", "order-side", "order-amount",
      "order-limit-price", "order-worst-price", "order-slippage",
      "order-wallet", "order-exchange", "order-signature-mode",
      "wallet-list", "sign-order", "order-status", "return-link",
    ];
    this.elements = new Map(ids.map((id) => [id, new FakeElement(id)]));
    this.readyState = "complete";
  }

  getElementById(id) {
    return this.elements.get(id) || null;
  }

  createElement() {
    return new FakeElement();
  }
}

class FakeWindow {
  constructor(hash = `#access_token=${CAPABILITY}`) {
    this.location = {
      hash,
      pathname: "/execution/polymarket/order-signing-console/",
      search: "",
      origin: "https://clink.example",
    };
    this.historyCalls = [];
    this.history = {
      replaceState: (...args) => this.historyCalls.push(args),
    };
    this.listeners = new Map();
    this.dispatched = [];
    this.localStorage = forbiddenStorage();
    this.sessionStorage = forbiddenStorage();
  }

  addEventListener(type, handler) {
    const handlers = this.listeners.get(type) || [];
    handlers.push(handler);
    this.listeners.set(type, handlers);
  }

  removeEventListener(type, handler) {
    const handlers = this.listeners.get(type) || [];
    this.listeners.set(type, handlers.filter((candidate) => candidate !== handler));
  }

  dispatchEvent(event) {
    this.dispatched.push(event.type);
    for (const handler of this.listeners.get(event.type) || []) handler(event);
    return true;
  }

  emit(type, detail) {
    this.dispatchEvent({ type, detail });
  }
}

function forbiddenStorage() {
  return {
    getItem() { throw new Error("browser capability must not use storage"); },
    setItem() { throw new Error("browser capability must not use storage"); },
    removeItem() { throw new Error("browser capability must not use storage"); },
  };
}

function jsonResponse(body, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    async json() { return body; },
  };
}

function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((yes, no) => { resolve = yes; reject = no; });
  return { promise, resolve, reject };
}

function sessionFixture(updates = {}) {
  const order = {
    salt: 7,
    maker: ACCOUNT,
    signer: ACCOUNT,
    tokenId: "102936",
    makerAmount: "5200000",
    takerAmount: "10000000",
    side: "BUY",
    signatureType: 0,
    timestamp: "1787184000000",
    metadata: `0x${"00".repeat(32)}`,
    builder: `0x${"00".repeat(32)}`,
    expiration: "0",
  };
  const typedOrder = { ...order, side: 0 };
  delete typedOrder.expiration;
  return {
    session_id: "pm_sign_sess_browser",
    status: "pending_browser_signature",
    title: "Will the test pass?",
    outcome: "Yes",
    side: "buy",
    amount_usd: "5.20",
    limit_price: "0.52",
    worst_case_price: "0.52",
    max_slippage_bps: 0,
    wallet_address: ACCOUNT,
    exchange: EXCHANGE,
    wallet_mode: "eoa",
    order_payload: {
      typed_data: {
        domain: {
          name: "Polymarket CTF Exchange",
          version: "2",
          chainId: 137,
          verifyingContract: EXCHANGE,
        },
        types: {
          Order: ORDER_FIELDS.map(([name, type]) => ({ name, type })),
        },
        primaryType: "Order",
        message: typedOrder,
      },
      order,
      orderType: "GTC",
      exchange: EXCHANGE,
      collateral: PUSD,
      tickSize: "0.01",
      minOrderSize: "5",
      negRisk: false,
      provenance: {
        preview_id: "preview-1",
        market_id: "market-1",
        core_action_id: "action-1",
        core_policy_decision_id: "policy-1",
        funding_operation_id: "funding-1",
      },
      projection_sha256: "ab".repeat(32),
    },
    return_url: "/miniapp/",
    ...updates,
  };
}

function depositSessionFixture(updates = {}) {
  const session = sessionFixture({
    wallet_address: SIGNER,
    wallet_mode: "deposit_wallet",
    ...updates,
  });
  const order = session.order_payload.order;
  order.signer = order.maker;
  order.signatureType = 3;
  const contents = { ...order, side: 0 };
  delete contents.expiration;
  const typedData = session.order_payload.typed_data;
  typedData.primaryType = "TypedDataSign";
  typedData.types.TypedDataSign = [
    { name: "contents", type: "Order" },
    { name: "name", type: "string" },
    { name: "version", type: "string" },
    { name: "chainId", type: "uint256" },
    { name: "verifyingContract", type: "address" },
    { name: "salt", type: "bytes32" },
  ];
  typedData.message = {
    contents,
    name: "DepositWallet",
    version: "1",
    chainId: 137,
    verifyingContract: order.maker,
    salt: `0x${"00".repeat(32)}`,
  };
  return session;
}

function providerHarness(options = {}) {
  const calls = [];
  const listeners = new Map();
  const provider = {
    async request(request) {
      calls.push(request);
      if (request.method === "eth_chainId") {
        if (options.chainPromise) return options.chainPromise;
        return options.chainId || "0x89";
      }
      if (request.method === "wallet_switchEthereumChain") return null;
      if (request.method === "eth_requestAccounts") {
        if (options.accountsPromise) return options.accountsPromise;
        return options.accounts || [ACCOUNT];
      }
      if (request.method === "eth_signTypedData_v4") {
        if (options.signaturePromise) return options.signaturePromise;
        return options.signature || `0x${"ab".repeat(65)}`;
      }
      throw new Error(`unexpected wallet method ${request.method}`);
    },
    on(type, handler) {
      const handlers = listeners.get(type) || [];
      handlers.push(handler);
      listeners.set(type, handlers);
    },
    removeListener(type, handler) {
      listeners.set(type, (listeners.get(type) || []).filter((item) => item !== handler));
    },
    emit(type, value) {
      for (const handler of listeners.get(type) || []) handler(value);
    },
  };
  return { calls, provider };
}

function createHarness(options = {}) {
  const { createOrderSigningPage } = loadModule();
  const document = new FakeDocument();
  const window = new FakeWindow(options.hash);
  const wallet = options.wallet || providerHarness(options.providerOptions);
  if (options.fallbackProvider !== false) window.ethereum = wallet.provider;
  const calls = [];
  const fetch = async (url, init = {}) => {
    calls.push({ url, ...init });
    if (options.fetch) return options.fetch(url, init, calls);
    if (String(url).endsWith("/complete")) {
      return jsonResponse({ session_id: "pm_sign_sess_browser", status: "submitted" });
    }
    if (String(url).endsWith("/status")) {
      return jsonResponse({ session_id: "pm_sign_sess_browser", status: "unknown" });
    }
    return jsonResponse(options.session || sessionFixture());
  };
  const controller = createOrderSigningPage({ document, window, fetch });
  return { calls, controller, document, wallet, window };
}

test("fragment capability is read once, removed from history, and sent only as bearer", async () => {
  const harness = createHarness();
  await harness.controller.start();

  assert.equal(harness.window.historyCalls.length, 1);
  assert.equal(harness.window.historyCalls[0][2], "/execution/polymarket/order-signing-console/");
  assert.equal(harness.window.location.hash, "");
  assert.equal(harness.calls[0].url, "/execution/polymarket/browser-order-signing-session");
  assert.equal(harness.calls[0].headers.Authorization, `Bearer ${CAPABILITY}`);
  assert.doesNotMatch(harness.calls[0].url, /capability|access_token/);
});

test("generic shell contains no session or token material and loads only local assets", () => {
  const html = fs.readFileSync(STATIC_HTML, "utf8");
  assert.doesNotMatch(html, /access_token|pm_sign_sess_|signed_order/);
  assert.match(html, /polymarket_order_signing\.css/);
  assert.match(html, /polymarket_order_signing\.bundle\.js/);
  assert.doesNotMatch(html, /https?:\/\//);
});

test("immutable server order details render with textContent", async () => {
  const harness = createHarness();
  await harness.controller.start();
  const get = (id) => harness.document.getElementById(id).textContent;
  assert.equal(get("order-title"), "Will the test pass?");
  assert.equal(get("order-outcome"), "Yes");
  assert.equal(get("order-side"), "BUY");
  assert.equal(get("order-amount"), "5.20 pUSD");
  assert.equal(get("order-limit-price"), "0.52");
  assert.equal(get("order-worst-price"), "0.52");
  assert.equal(get("order-wallet"), ACCOUNT);
  assert.equal(get("order-exchange"), EXCHANGE);
  assert.equal(get("order-signature-mode"), "EOA");
});

test("EIP-6963 provider discovery is requested and announced provider can sign", async () => {
  const wallet = providerHarness();
  const harness = createHarness({ wallet, fallbackProvider: false });
  const start = harness.controller.start();
  harness.window.emit("eip6963:announceProvider", {
    info: { uuid: "wallet-1", name: "Test Wallet", icon: "data:image/svg+xml,<svg/>" },
    provider: wallet.provider,
  });
  await start;
  assert.ok(harness.window.dispatched.includes("eip6963:requestProvider"));
  assert.equal(harness.document.getElementById("wallet-list").children.length, 1);
  await harness.document.getElementById("wallet-list").children[0].dispatch("click");
  await harness.document.getElementById("sign-order").dispatch("click");
  assert.equal(wallet.calls.filter((call) => call.method === "eth_signTypedData_v4").length, 1);
});

test("one explicit click signs once and completes once", async () => {
  const harness = createHarness();
  await harness.controller.start();
  assert.equal(harness.wallet.calls.length, 0);

  await harness.document.getElementById("sign-order").dispatch("click");

  assert.equal(harness.wallet.calls.filter((call) => call.method === "eth_signTypedData_v4").length, 1);
  assert.equal(harness.calls.filter((call) => String(call.url).endsWith("/complete")).length, 1);
  const completion = harness.calls.find((call) => String(call.url).endsWith("/complete"));
  assert.equal(completion.headers.Authorization, `Bearer ${CAPABILITY}`);
  assert.equal(JSON.parse(completion.body).signed_order.order.signature, `0x${"ab".repeat(65)}`);
});

test("pending state disables duplicate clicks", async () => {
  const signature = deferred();
  const harness = createHarness({
    wallet: providerHarness({ signaturePromise: signature.promise }),
  });
  await harness.controller.start();
  const first = harness.document.getElementById("sign-order").dispatch("click");
  assert.equal(harness.document.getElementById("sign-order").disabled, true);
  await harness.document.getElementById("sign-order").dispatch("click");
  signature.resolve(`0x${"ab".repeat(65)}`);
  await first;
  assert.equal(harness.wallet.calls.filter((call) => call.method === "eth_signTypedData_v4").length, 1);
});

test("completion timeout polls the same capability without signing or posting again", async () => {
  const harness = createHarness({
    fetch: async (url) => {
      if (String(url).endsWith("/complete")) throw new TypeError("network timeout");
      if (String(url).endsWith("/status")) {
        return jsonResponse({ session_id: "pm_sign_sess_browser", status: "unknown" });
      }
      return jsonResponse(sessionFixture());
    },
  });
  await harness.controller.start();
  await harness.document.getElementById("sign-order").dispatch("click");

  assert.equal(harness.wallet.calls.filter((call) => call.method === "eth_signTypedData_v4").length, 1);
  assert.equal(harness.calls.filter((call) => String(call.url).endsWith("/complete")).length, 1);
  assert.equal(harness.calls.filter((call) => String(call.url).endsWith("/status")).length, 1);
});

test("completion and status failures permanently lock the signed capability", async () => {
  const harness = createHarness({
    fetch: async (url) => {
      if (String(url).endsWith("/complete")) {
        return { ok: true, status: 200, async json() { throw new SyntaxError("bad json"); } };
      }
      if (String(url).endsWith("/status")) return jsonResponse({}, 503);
      return jsonResponse(sessionFixture());
    },
  });
  await harness.controller.start();
  await harness.document.getElementById("sign-order").dispatch("click");
  assert.equal(harness.document.getElementById("sign-order").disabled, true);
  await harness.document.getElementById("sign-order").dispatch("click");
  assert.equal(harness.wallet.calls.filter((call) => call.method === "eth_signTypedData_v4").length, 1);
  assert.equal(harness.calls.filter((call) => String(call.url).endsWith("/complete")).length, 1);
});

test("wrong account refuses before typed-data signing", async () => {
  const harness = createHarness({ providerOptions: { accounts: [`0x${"22".repeat(20)}`] } });
  await harness.controller.start();
  await harness.document.getElementById("sign-order").dispatch("click");
  assert.equal(harness.wallet.calls.filter((call) => call.method === "eth_signTypedData_v4").length, 0);
  assert.match(harness.document.getElementById("order-status").textContent, /bound wallet/i);
});

test("wrong Polygon chain refuses before typed-data signing", async () => {
  const harness = createHarness({ providerOptions: { chainId: "0x1" } });
  await harness.controller.start();
  await harness.document.getElementById("sign-order").dispatch("click");
  assert.equal(harness.wallet.calls.filter((call) => call.method === "eth_signTypedData_v4").length, 0);
  assert.match(harness.document.getElementById("order-status").textContent, /Polygon/i);
});

test("any redundant server projection field drift refuses before wallet signing", async () => {
  for (const [field, value] of [
    ["salt", 8],
    ["side", 1],
    ["timestamp", "1787184000001"],
    ["metadata", `0x${"11".repeat(32)}`],
    ["builder", `0x${"22".repeat(32)}`],
  ]) {
    const session = sessionFixture();
    session.order_payload.typed_data.message[field] = value;
    const harness = createHarness({ session });
    await harness.controller.start();
    await harness.document.getElementById("sign-order").dispatch("click");
    assert.equal(
      harness.wallet.calls.filter((call) => call.method === "eth_signTypedData_v4").length,
      0,
      field,
    );
  }
  const reordered = sessionFixture();
  reordered.order_payload.typed_data.types.Order.reverse();
  const harness = createHarness({ session: reordered });
  await harness.controller.start();
  await harness.document.getElementById("sign-order").dispatch("click");
  assert.equal(
    harness.wallet.calls.filter((call) => call.method === "eth_signTypedData_v4").length,
    0,
    "ordered types",
  );
});

test("account or chain change aborts a late signature before completion POST", async () => {
  for (const [event, value] of [
    ["accountsChanged", [`0x${"22".repeat(20)}`]],
    ["chainChanged", "0x1"],
  ]) {
    const signature = deferred();
    const wallet = providerHarness({ signaturePromise: signature.promise });
    const harness = createHarness({ wallet });
    await harness.controller.start();
    const signing = harness.document.getElementById("sign-order").dispatch("click");
    wallet.provider.emit(event, value);
    signature.resolve(`0x${"ab".repeat(65)}`);
    await signing;
    assert.equal(harness.calls.filter((call) => String(call.url).endsWith("/complete")).length, 0);
  }
});

test("switching providers during deferred wallet requests never mixes providers", async () => {
  for (const phase of ["chain", "accounts", "signature"]) {
    const wait = deferred();
    const first = providerHarness({
      ...(phase === "chain" ? { chainPromise: wait.promise } : {}),
      ...(phase === "accounts" ? { accountsPromise: wait.promise } : {}),
      ...(phase === "signature" ? { signaturePromise: wait.promise } : {}),
    });
    const second = providerHarness();
    const harness = createHarness({ wallet: first, fallbackProvider: false });
    const start = harness.controller.start();
    harness.window.emit("eip6963:announceProvider", {
      info: { uuid: `first-${phase}`, name: "First" },
      provider: first.provider,
    });
    harness.window.emit("eip6963:announceProvider", {
      info: { uuid: `second-${phase}`, name: "Second" },
      provider: second.provider,
    });
    await start;
    const signing = harness.document.getElementById("sign-order").dispatch("click");
    for (let turn = 0; turn < 5 && !first.calls.some((call) => call.method === {
      chain: "eth_chainId",
      accounts: "eth_requestAccounts",
      signature: "eth_signTypedData_v4",
    }[phase]); turn += 1) await Promise.resolve();
    await harness.document.getElementById("wallet-list").children[1].dispatch("click");
    assert.equal(harness.document.getElementById("sign-order").disabled, true, phase);
    wait.resolve({ chain: "0x89", accounts: [ACCOUNT], signature: `0x${"ab".repeat(65)}` }[phase]);
    await signing;
    assert.equal(second.calls.length, 0, phase);
    assert.equal(harness.calls.filter((call) => String(call.url).endsWith("/complete")).length, 0, phase);
    await harness.document.getElementById("sign-order").dispatch("click");
    assert.equal(second.calls.length, 0, `${phase} replay`);
  }
});

test("exit aborts late response and clears the in-memory capability", async () => {
  const response = deferred();
  const harness = createHarness({ fetch: () => response.promise });
  const start = harness.controller.start();
  harness.controller.exit();
  response.resolve(jsonResponse(sessionFixture()));
  await start;
  assert.equal(harness.document.getElementById("order-title").textContent, "");
  await assert.rejects(() => harness.controller.pollStatus(), /capability is unavailable/i);
});

test("Deposit signature wrapper concatenates official ERC-7739 parts exactly", () => {
  const { wrapDepositWalletSignatureParts, ORDER_TYPE_STRING } = loadModule();
  const raw = `0x${"ab".repeat(65)}`;
  const domain = `0x${"11".repeat(32)}`;
  const contents = `0x${"22".repeat(32)}`;
  const wrapped = wrapDepositWalletSignatureParts(raw, domain, contents);
  assert.equal(
    wrapped,
    `${raw}${domain.slice(2)}${contents.slice(2)}`
      + Buffer.from(ORDER_TYPE_STRING, "utf8").toString("hex")
      + Buffer.from(ORDER_TYPE_STRING, "utf8").length.toString(16).padStart(4, "0"),
  );
});

test("Deposit wrapper uses real viem hashes and matches the Python golden vector", () => {
  const { finalizeWalletSignature, ORDER_TYPE_STRING } = loadModule();
  const session = depositSessionFixture();
  session.order_payload.order.salt = 479249096354;
  session.order_payload.typed_data.message.contents.salt = "479249096354";
  const raw = `0x${"ab".repeat(65)}`;
  const wrapped = finalizeWalletSignature(raw, session);
  assert.equal(
    wrapped,
    raw
      + "3264e159346253e26a64e00b69032db0e7d32f94628de3e6eecb50304d7af3d2"
      + "a93eff65aa806653f335e1a463afcc9b1633b2a409a61459e02cb19908d9fcf7"
      + Buffer.from(ORDER_TYPE_STRING, "utf8").toString("hex")
      + "00ba",
  );
});

test("a signed session stays single-flight after success or unknown status", async () => {
  for (const state of ["success", "unknown"]) {
    const first = providerHarness();
    const second = providerHarness();
    const harness = createHarness({
      wallet: first,
      fetch: async (url) => {
        if (String(url).endsWith("/complete")) {
          if (state === "unknown") throw new TypeError("timeout");
          return jsonResponse({ session_id: "pm_sign_sess_browser", status: "submitted" });
        }
        if (String(url).endsWith("/status")) {
          return jsonResponse({ session_id: "pm_sign_sess_browser", status: "unknown" });
        }
        return jsonResponse(sessionFixture());
      },
    });
    await harness.controller.start();
    harness.window.emit("eip6963:announceProvider", {
      info: { uuid: `second-${state}`, name: "Second" },
      provider: second.provider,
    });
    await harness.document.getElementById("sign-order").dispatch("click");
    await harness.document.getElementById("wallet-list").children[1].dispatch("click");
    assert.equal(harness.document.getElementById("sign-order").disabled, true, state);
    await harness.document.getElementById("sign-order").dispatch("click");
    assert.equal(first.calls.filter((call) => call.method === "eth_signTypedData_v4").length, 1, state);
    assert.equal(harness.calls.filter((call) => String(call.url).endsWith("/complete")).length, 1, state);
  }
});

test("invalid venue projection or raw EOA signature is rejected before POST", async () => {
  for (const mutate of [
    (session) => {
      session.order_payload.exchange = "0x3333333333333333333333333333333333333333";
      session.order_payload.typed_data.domain.verifyingContract = session.order_payload.exchange;
    },
    (session) => { session.order_payload.collateral = ACCOUNT; },
    (session) => { session.order_payload.negRisk = true; },
  ]) {
    const session = sessionFixture();
    mutate(session);
    const harness = createHarness({ session });
    await harness.controller.start();
    await harness.document.getElementById("sign-order").dispatch("click");
    assert.equal(harness.calls.filter((call) => String(call.url).endsWith("/complete")).length, 0);
  }
  const badSignature = createHarness({ providerOptions: { signature: "0xdead" } });
  await badSignature.controller.start();
  await badSignature.document.getElementById("sign-order").dispatch("click");
  assert.equal(badSignature.calls.filter((call) => String(call.url).endsWith("/complete")).length, 0);
});

test("frontend source is memory-only and never renders remote values as HTML", () => {
  const source = fs.readFileSync(SOURCE, "utf8");
  assert.doesNotMatch(source, /localStorage|sessionStorage|innerHTML|document\.write/);
  assert.match(source, /textContent/);
  assert.doesNotMatch(source, /access_token=.*[?&]|\?access_token/);
});
