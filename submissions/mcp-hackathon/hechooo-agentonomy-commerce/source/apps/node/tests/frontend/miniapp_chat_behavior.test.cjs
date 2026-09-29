"use strict";

const assert = require("node:assert/strict");
const fs = require("node:fs");
const path = require("node:path");
const test = require("node:test");

const {
  createMiniApp,
  STORAGE_KEYS,
} = require("../../clink_node/static/miniapp.js");

const STABLE_SCOPE_A = "A".repeat(43);
const STABLE_SCOPE_B = "B".repeat(43);


class FakeClassList {
  constructor() {
    this.values = new Set();
  }

  add(...values) {
    values.forEach((value) => this.values.add(value));
  }

  remove(...values) {
    values.forEach((value) => this.values.delete(value));
  }

  toggle(value, force) {
    if (force === true) this.values.add(value);
    else if (force === false) this.values.delete(value);
    else if (this.values.has(value)) this.values.delete(value);
    else this.values.add(value);
    return this.values.has(value);
  }

  contains(value) {
    return this.values.has(value);
  }
}


class FakeElement {
  constructor(tagName = "div", id = "") {
    this.tagName = tagName.toUpperCase();
    this.id = id;
    this.value = "";
    this.textContent = "";
    this.className = "";
    this.children = [];
    this.listeners = new Map();
    this.dataset = {};
    this.classList = new FakeClassList();
    this.disabled = false;
    this.hidden = false;
    this.scrollTop = 0;
    this.scrollHeight = 500;
    this.attributes = new Map();
    this.focused = false;
  }

  append(...children) {
    this.children.push(...children);
  }

  replaceChildren(...children) {
    this.children = [...children];
  }

  addEventListener(type, handler) {
    const handlers = this.listeners.get(type) || [];
    handlers.push(handler);
    this.listeners.set(type, handlers);
  }

  setAttribute(name, value) {
    this.attributes.set(name, String(value));
  }

  getAttribute(name) {
    return this.attributes.get(name) ?? null;
  }

  focus() {
    this.focused = true;
  }

  async dispatch(type, values = {}) {
    const event = {
      target: this,
      currentTarget: this,
      defaultPrevented: false,
      preventDefault() {
        this.defaultPrevented = true;
      },
      ...values,
    };
    for (const handler of this.listeners.get(type) || []) {
      await handler(event);
    }
    return event;
  }
}


class FakeDocument {
  constructor() {
    const ids = [
      "miniapp-transcript", "miniapp-composer", "miniapp-input",
      "miniapp-send", "miniapp-status", "miniapp-identity",
      "miniapp-tool-progress", "miniapp-tool-progress-toggle",
      "miniapp-tool-progress-summary", "miniapp-tool-progress-list",
      "miniapp-operations", "miniapp-operations-toggle",
      "miniapp-operations-close", "miniapp-logout",
      "polymarket-funding-confirm", "polymarket-funding-amount",
      "polymarket-funding-status", "polymarket-signing-preview",
      "polymarket-signing-open", "polymarket-signing-check",
      "polymarket-signing-status",
    ];
    this.elements = new Map(ids.map((id) => [id, new FakeElement("div", id)]));
    this.elements.get("miniapp-operations").hidden = true;
    this.elements.get("miniapp-composer").tagName = "FORM";
    this.elements.get("miniapp-input").tagName = "TEXTAREA";
    this.operationLinks = [null, "/#marketplace-showcase", null].map((url, index) => {
      const link = new FakeElement("button");
      if (index === 0) link.dataset.operation = "account";
      else if (index === 2) link.dataset.operation = "polymarket";
      else link.dataset.operationUrl = url;
      return link;
    });
    this.readyState = "complete";
    this.visibilityState = "visible";
    this.listeners = new Map();
  }

  getElementById(id) {
    return this.elements.get(id) || null;
  }

  createElement(tagName) {
    return new FakeElement(tagName);
  }

  querySelectorAll(selector) {
    if (
      selector === "[data-operation-url]" ||
      selector === "[data-operation-url], [data-operation]"
    ) return this.operationLinks;
    return [];
  }

  addEventListener(type, handler) {
    const handlers = this.listeners.get(type) || [];
    handlers.push(handler);
    this.listeners.set(type, handlers);
  }

  async dispatch(type, values = {}) {
    const event = { type, target: this, ...values };
    for (const handler of this.listeners.get(type) || []) {
      await handler(event);
    }
  }
}


class FakeStorage {
  constructor(seed = {}) {
    this.values = new Map(Object.entries(seed));
  }

  getItem(key) {
    return this.values.has(key) ? this.values.get(key) : null;
  }

  setItem(key, value) {
    this.values.set(key, String(value));
  }

  removeItem(key) {
    this.values.delete(key);
  }
}


class FakeEventSource {
  static instances = [];

  constructor(url) {
    this.url = url;
    this.listeners = new Map();
    this.closed = false;
    FakeEventSource.instances.push(this);
  }

  addEventListener(type, handler) {
    const handlers = this.listeners.get(type) || [];
    handlers.push(handler);
    this.listeners.set(type, handlers);
  }

  emit(type, data, lastEventId = "") {
    for (const handler of this.listeners.get(type) || []) {
      handler({ data: JSON.stringify(data), lastEventId, type });
    }
  }

  close() {
    this.closed = true;
  }
}


function jsonResponse(body, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    async json() {
      return body;
    },
  };
}


function deferred() {
  let resolve;
  let reject;
  const promise = new Promise((resolvePromise, rejectPromise) => {
    resolve = resolvePromise;
    reject = rejectPromise;
  });
  return { promise, resolve, reject };
}


function createHarness(route, options = {}) {
  FakeEventSource.instances = [];
  const calls = [];
  const document = new FakeDocument();
  const sessionStorage = options.sessionStorage || new FakeStorage();
  const localStorage = options.localStorage || new FakeStorage();
  if (
    options.legacySession !== true &&
    sessionStorage.getItem(STORAGE_KEYS.csrf) &&
    !sessionStorage.getItem(STORAGE_KEYS.scope)
  ) sessionStorage.setItem(STORAGE_KEYS.scope, STABLE_SCOPE_A);
  const externalOpened = [];
  const telegramVersionChecks = [];
  const telegram = options.telegram === false ? undefined : {
    initData: options.initData === undefined
      ? "signed-init-data"
      : options.initData,
    readyCalls: 0,
    expandCalls: 0,
    ready() { this.readyCalls += 1; },
    expand() { this.expandCalls += 1; },
  };
  if (telegram && options.telegramOpenLink === true) {
    telegram.openLink = (url) => externalOpened.push(url);
    telegram.isVersionAtLeast = (version) => {
      telegramVersionChecks.push(version);
      return options.telegramVersionSupported !== false;
    };
  }
  const autoSessionExchange = (
    options.observeSessionExchange !== true &&
    options.legacySession !== true &&
    Boolean(telegram?.initData) &&
    Boolean(sessionStorage.getItem(STORAGE_KEYS.csrf)) &&
    /^[A-Za-z0-9_-]{43}$/.test(
      sessionStorage.getItem(STORAGE_KEYS.scope) || "",
    )
  );
  const windowListeners = new Map();
  const assigned = [];
  const historyReplacements = [];
  const scheduled = new Map();
  let nextTimerId = 1;
  const window = {
    Telegram: telegram ? { WebApp: telegram } : undefined,
    location: {
      origin: options.origin || "https://www.agentonomy.xyz",
      pathname: options.pathname || "/miniapp/",
      search: options.search || "",
      hash: options.hash || "",
      assign(url) { assigned.push(url); },
    },
    history: {
      replaceState(state, title, url) {
        historyReplacements.push({ state, title, url });
        window.location.hash = "";
      },
    },
    addEventListener(type, handler) {
      const handlers = windowListeners.get(type) || [];
      handlers.push(handler);
      windowListeners.set(type, handlers);
    },
  };
  const crypto = {
    randomUUID: options.randomUUID || (() => "11111111-2222-4333-8444-555555555555"),
    getRandomValues(bytes) {
      bytes.set(Array.from({ length: 16 }, (_, index) => index + 1));
      return bytes;
    },
  };
  const fetch = async (url, request = {}) => {
    const call = {
      url: String(url),
      method: request.method || "GET",
      headers: request.headers || {},
      body: request.body === undefined ? undefined : JSON.parse(request.body),
    };
    if (
      autoSessionExchange &&
      call.method === "POST" &&
      call.url === "/miniapp/api/session"
    ) {
      return jsonResponse(
        sessionExchangeBody(
          sessionStorage.getItem(STORAGE_KEYS.csrf),
          sessionStorage.getItem(STORAGE_KEYS.scope),
        ),
        201,
      );
    }
    calls.push(call);
    const result = await route(call, calls);
    return jsonResponse(result.body, result.status || 200);
  };
  const setTimeoutApi = (callback) => {
    const timerId = nextTimerId;
    nextTimerId += 1;
    scheduled.set(timerId, callback);
    return timerId;
  };
  const clearTimeoutApi = (timerId) => {
    scheduled.delete(timerId);
  };
  const app = createMiniApp({
    document,
    window,
    fetch,
    EventSource: FakeEventSource,
    sessionStorage,
    localStorage,
    crypto,
    deriveStorageScope: async (csrf) => `scope:${csrf}`,
    setTimeout: setTimeoutApi,
    clearTimeout: clearTimeoutApi,
  });
  return {
    app, calls, document, sessionStorage, localStorage, telegram, assigned,
    historyReplacements,
    externalOpened, telegramVersionChecks,
    emitWindow(type, values = {}) {
      const event = {
        type,
        defaultPrevented: false,
        preventDefault() {
          this.defaultPrevented = true;
        },
        ...values,
      };
      const results = [];
      for (const handler of windowListeners.get(type) || []) {
        results.push(handler(event));
      }
      return Promise.all(results).then(() => event);
    },
    emitDocument(type, values = {}) {
      return document.dispatch(type, values);
    },
    scheduledCount() {
      return scheduled.size;
    },
    async runScheduled() {
      const batch = [...scheduled.values()];
      scheduled.clear();
      for (const callback of batch) await callback();
    },
  };
}


function scoped(value, scope = STABLE_SCOPE_A) {
  return JSON.stringify({ scope, value: String(value) });
}

function sessionExchangeBody(csrfToken, storageScope, username = "Jeff") {
  return {
    authenticated: true,
    csrf_token: csrfToken,
    storage_scope: storageScope,
    user: { username },
  };
}


function freshSessionRoute(csrfToken, storageScope, username = "Jeff") {
  let authenticated = false;
  return ({ method, url }) => {
    if (method === "GET" && url === "/miniapp/api/chat") {
      return authenticated
        ? { body: chatBody() }
        : { status: 401, body: { detail: "miniapp_unauthorized" } };
    }
    if (method === "POST" && url === "/miniapp/api/session") {
      authenticated = true;
      return {
        status: 201,
        body: sessionExchangeBody(csrfToken, storageScope, username),
      };
    }
    return null;
  };
}


function storedValue(storage, key, scope = STABLE_SCOPE_A) {
  const raw = storage.getItem(key) ?? storage.getItem(`${key}:${scope}`);
  return raw === null ? null : JSON.parse(raw).value;
}


function storedNamespacedValue(storage, key, scope) {
  const raw = storage.getItem(`${key}:${scope}`);
  return raw === null ? null : JSON.parse(raw).value;
}


function chatBody(messages = [], latest = null) {
  return { messages, latest };
}


const LIVE_STORAGE_KEYS = Object.freeze({
  fundingAmount: "agentonomy.miniapp.polymarket.funding_amount",
  fundingIdempotency: "agentonomy.miniapp.polymarket.funding_idempotency_key",
  fundingOperation: "agentonomy.miniapp.polymarket.funding_operation_id",
  signingPreview: "agentonomy.miniapp.polymarket.signing_preview_id",
  signingSession: "agentonomy.miniapp.polymarket.signing_session_id",
  signingSessionPreview: "agentonomy.miniapp.polymarket.signing_session_preview_id",
  signingUnknownPreview: "agentonomy.miniapp.polymarket.signing_unknown_preview_id",
});


function fundingBody(overrides = {}) {
  return {
    operation_id: "pm_funding_1",
    status: "created",
    amount_usdc: "1.250000",
    chain_status: "not_started",
    bridge_status: "not_started",
    buying_power_status: "not_started",
    reason: null,
    next_action: "confirm",
    ...overrides,
  };
}


function signingBody(overrides = {}) {
  return {
    session_id: "pm_sign_sess_123456789abc",
    status: "pending_browser_signature",
    reason: null,
    next_action: "open_polymarket_order_signing_url",
    execution_id: null,
    signing_url: (
      "https://www.agentonomy.xyz/execution/polymarket/" +
      "order-signing-console/#access_token=opaque_browser_capability"
    ),
    ...overrides,
  };
}


test("wallet control has no direct account URL in the Mini App shell", () => {
  const html = fs.readFileSync(
    path.join(__dirname, "../../clink_node/static/miniapp.html"),
    "utf8",
  );

  assert.match(html, /data-operation="account"/);
  assert.doesNotMatch(html, /data-operation-url="\/account(?:\/|\")/);
});


test("Polymarket control has no direct dashboard URL in the Mini App shell", () => {
  const html = fs.readFileSync(
    path.join(__dirname, "../../clink_node/static/miniapp.html"),
    "utf8",
  );

  assert.match(html, /data-operation="polymarket"/);
  assert.doesNotMatch(html, /data-operation-url="\/polymarket(?:\/|\")/);
});


test("Polymarket drawer is binding-only", () => {
  const html = fs.readFileSync(
    path.join(__dirname, "../../clink_node/static/miniapp.html"),
    "utf8",
  );

  assert.equal(
    (html.match(/data-operation=["']polymarket["']/g) || []).length,
    1,
  );
  assert.doesNotMatch(html, /Fund Polymarket/);
  assert.doesNotMatch(html, /Sign an order/);
  assert.doesNotMatch(
    html,
    /id=["']polymarket-(?:funding|signing)-[^"']+["']/,
  );
  assert.doesNotMatch(
    html,
    /name=["'](?:user_id|binding_id|wallet|destination|reservation_id|audit_event_id|tx|signer|exchange|credentials|metadata)["']/i,
  );
});


test("an account link in an Agentonomy reply becomes one clear Mini App action", async () => {
  const accountUrl = "https://www.agentonomy.xyz/account/session/setup-1";
  const harness = createHarness(({ method, url }) => {
    if (method === "GET" && url === "/miniapp/api/chat") {
      return {
        body: chatBody([
          {
            id: 1,
            role: "assistant",
            content: `还差一步，请完成钱包授权：${accountUrl}`,
            timestamp: 1,
          },
        ]),
      };
    }
    throw new Error(`unexpected ${method} ${url}`);
  }, {
    sessionStorage: new FakeStorage({ [STORAGE_KEYS.csrf]: "csrf" }),
    telegramOpenLink: true,
  });

  await harness.app.start();

  const turn = harness.document.getElementById("miniapp-transcript").children[0];
  assert.equal(turn.children.length, 3);
  assert.doesNotMatch(turn.children[1].textContent, /https?:\/\//);
  assert.equal(
    turn.children[2].textContent,
    "Open Clink spending account",
  );

  await turn.children[2].dispatch("click");

  assert.deepEqual(harness.externalOpened, [accountUrl]);
  assert.deepEqual(harness.assigned, []);
  assert.deepEqual(harness.telegramVersionChecks, ["6.1"]);
});


test("an unsafe account-like reply never becomes a Mini App action", async () => {
  const harness = createHarness(({ method, url }) => {
    if (method === "GET" && url === "/miniapp/api/chat") {
      return {
        body: chatBody([
          {
            id: 1,
            role: "assistant",
            content: (
              "请完成钱包授权：https://www.agentonomy.xyz.evil/account/session/setup-1"
            ),
            timestamp: 1,
          },
        ]),
      };
    }
    throw new Error(`unexpected ${method} ${url}`);
  }, {
    sessionStorage: new FakeStorage({ [STORAGE_KEYS.csrf]: "csrf" }),
  });

  await harness.app.start();

  const turn = harness.document.getElementById("miniapp-transcript").children[0];
  assert.equal(turn.children.length, 2);
  assert.deepEqual(harness.assigned, []);
});


test("a valid funding fragment is consumed before any mutation and opens one action", async () => {
  const harness = createHarness(({ method, url }) => {
    if (method === "GET" && url === "/miniapp/api/chat") {
      return { body: chatBody() };
    }
    throw new Error(`unexpected ${method} ${url}`);
  }, {
    hash: "#funding=1.000000",
    pathname: "/miniapp/",
    search: "?safe=1",
    sessionStorage: new FakeStorage({ [STORAGE_KEYS.csrf]: "csrf" }),
  });

  await harness.app.start();

  assert.deepEqual(harness.historyReplacements, [{
    state: null,
    title: "",
    url: "/miniapp/?safe=1",
  }]);
  assert.equal(
    harness.document.getElementById("polymarket-funding-amount").value,
    "1.000000",
  );
  assert.equal(
    storedValue(harness.localStorage, LIVE_STORAGE_KEYS.fundingAmount),
    "1.000000",
  );
  assert.equal(harness.document.getElementById("miniapp-operations").hidden, false);
  const confirm = harness.document.getElementById("polymarket-funding-confirm");
  assert.equal(confirm.textContent, "Confirm and fund 1 USDC");
  assert.equal(confirm.disabled, false);
  assert.equal(harness.calls.some((call) => call.method === "POST"), false);
});


test("an amount-free funding fragment opens the drawer without enabling a transfer", async () => {
  const harness = createHarness(({ method, url }) => {
    if (method === "GET" && url === "/miniapp/api/chat") {
      return { body: chatBody() };
    }
    throw new Error(`unexpected ${method} ${url}`);
  }, {
    hash: "#funding",
    sessionStorage: new FakeStorage({ [STORAGE_KEYS.csrf]: "csrf" }),
  });

  await harness.app.start();

  assert.equal(harness.historyReplacements.length, 1);
  assert.equal(harness.document.getElementById("miniapp-operations").hidden, false);
  assert.equal(
    harness.document.getElementById("polymarket-funding-amount").value,
    "",
  );
  assert.equal(
    harness.document.getElementById("polymarket-funding-confirm").disabled,
    true,
  );
  assert.equal(harness.calls.some((call) => call.method === "POST"), false);
});


for (const hash of [
  "#funding=1",
  "#funding=0.000000",
  "#funding=-1.000000",
  "#funding=1.0000000",
  "#funding=1.000000&funding=2.000000",
  "#funding=1.000000&extra=value",
]) {
  test(`an unsafe funding fragment is cleared without opening an action: ${hash}`, async () => {
    const harness = createHarness(({ method, url }) => {
      if (method === "GET" && url === "/miniapp/api/chat") {
        return { body: chatBody() };
      }
      throw new Error(`unexpected ${method} ${url}`);
    }, {
      hash,
      sessionStorage: new FakeStorage({ [STORAGE_KEYS.csrf]: "csrf" }),
    });

    await harness.app.start();

    assert.equal(harness.historyReplacements.length, 1);
    assert.equal(harness.historyReplacements[0].url, "/miniapp/");
    assert.equal(
      harness.document.getElementById("polymarket-funding-amount").value,
      "",
    );
    assert.equal(harness.document.getElementById("miniapp-operations").hidden, true);
    assert.equal(
      harness.document.getElementById("polymarket-funding-confirm").disabled,
      true,
    );
    assert.equal(harness.calls.some((call) => call.method === "POST"), false);
  });
}


test("Mini App browser assets use only the Agentonomy public name", () => {
  const assets = ["miniapp.html", "miniapp.css", "miniapp.js"].map((name) => (
    fs.readFileSync(
      path.join(__dirname, "../../clink_node/static", name),
      "utf8",
    )
  ));

  for (const asset of assets) {
    assert.doesNotMatch(asset, /hermes/i);
  }
  assert.match(assets[0], /Continue with Agentonomy\./);
  assert.match(assets[0], /Message Agentonomy/);
});


test("Mini App shell contains one accessible tool progress region", () => {
  const html = fs.readFileSync(
    path.join(__dirname, "../../clink_node/static/miniapp.html"),
    "utf8",
  );
  const css = fs.readFileSync(
    path.join(__dirname, "../../clink_node/static/miniapp.css"),
    "utf8",
  );

  for (const id of [
    "miniapp-tool-progress",
    "miniapp-tool-progress-toggle",
    "miniapp-tool-progress-summary",
    "miniapp-tool-progress-list",
  ]) {
    assert.equal((html.match(new RegExp(`id=["']${id}["']`, "g")) || []).length, 1);
  }
  assert.match(html, /aria-controls="miniapp-tool-progress-list"/);
  assert.match(
    html,
    /id="miniapp-tool-progress-summary"\s+class="tool-progress-summary"/,
  );
  assert.match(css, /\.tool-progress-summary\s*\{[^}]*overflow-wrap:\s*anywhere/s);
});


test("Telegram bootstrap never persists or renders initData and keeps nonce stable after failure", async () => {
  let exchangeAttempts = 0;
  const harness = createHarness(({ method, url }) => {
    if (method === "GET" && url === "/miniapp/api/chat") {
      if (exchangeAttempts === 2) return { body: chatBody() };
      return { status: 401, body: { detail: "miniapp_unauthorized" } };
    }
    if (method === "POST" && url === "/miniapp/api/session") {
      exchangeAttempts += 1;
      if (exchangeAttempts === 1) {
        return { status: 503, body: { detail: "miniapp_unavailable" } };
      }
      return {
        status: 201,
        body: sessionExchangeBody("csrf-1", STABLE_SCOPE_A),
      };
    }
    throw new Error(`unexpected ${method} ${url}`);
  }, { initData: "private-signed-init-data" });

  await harness.app.start();
  const firstExchange = harness.calls.find((call) => call.method === "POST");
  const nonce = firstExchange.body.client_nonce;
  assert.equal(nonce.length, 22);
  assert.deepEqual(
    [...Buffer.from(nonce, "base64url")],
    Array.from({ length: 16 }, (_, index) => index + 1),
  );
  assert.equal(harness.sessionStorage.getItem(STORAGE_KEYS.clientNonce), nonce);

  await harness.app.start();
  const exchanges = harness.calls.filter((call) => call.method === "POST");
  assert.equal(exchanges[1].body.client_nonce, nonce);
  assert.equal(exchanges[1].body.init_data, "private-signed-init-data");
  assert.equal(harness.sessionStorage.getItem("init_data"), null);
  assert.equal(harness.localStorage.getItem("init_data"), null);
  assert.equal([...harness.sessionStorage.values.values()].includes("private-signed-init-data"), false);
  assert.equal([...harness.localStorage.values.values()].includes("private-signed-init-data"), false);
  assert.doesNotMatch(harness.document.getElementById("miniapp-status").textContent, /private-signed/);
  assert.equal(harness.telegram.readyCalls, 2);
  assert.equal(harness.telegram.expandCalls, 2);
});


test("Telegram identity exchange precedes a chat outage on every start", async () => {
  const harness = createHarness(({ method, url }) => {
    if (method === "POST" && url === "/miniapp/api/session") {
      return {
        status: 201,
        body: sessionExchangeBody("csrf-current", STABLE_SCOPE_A),
      };
    }
    if (method === "GET" && url === "/miniapp/api/chat") {
      return { status: 503, body: { detail: "miniapp_unavailable" } };
    }
    throw new Error(`unexpected ${method} ${url}`);
  }, { sessionStorage: new FakeStorage(), observeSessionExchange: true });

  await harness.app.start();

  assert.deepEqual(
    harness.calls.map((call) => `${call.method} ${call.url}`),
    ["POST /miniapp/api/session", "GET /miniapp/api/chat"],
  );
  assert.equal(
    harness.sessionStorage.getItem(STORAGE_KEYS.scope),
    STABLE_SCOPE_A,
  );
});


test("successful exchange stores CSRF in sessionStorage and hard refresh reuses it", async () => {
  const sessionStorage = new FakeStorage();
  const first = createHarness(({ method, url }) => {
    if (method === "GET" && url === "/miniapp/api/chat") {
      if (sessionStorage.getItem(STORAGE_KEYS.csrf)) return { body: chatBody() };
      return { status: 401, body: { detail: "miniapp_unauthorized" } };
    }
    if (method === "POST" && url === "/miniapp/api/session") {
      return {
        status: 201,
        body: sessionExchangeBody("csrf-kept", STABLE_SCOPE_A),
      };
    }
    throw new Error(`unexpected ${method} ${url}`);
  }, { sessionStorage });
  await first.app.start();
  assert.equal(sessionStorage.getItem(STORAGE_KEYS.csrf), "csrf-kept");

  const refreshed = createHarness(({ method, url }) => {
    assert.equal(method, "GET");
    assert.equal(url, "/miniapp/api/chat");
    return { body: chatBody() };
  }, { sessionStorage });
  await refreshed.app.start();
  assert.equal(
    refreshed.calls.filter((call) => call.url === "/miniapp/api/session").length,
    0,
  );
  assert.equal(sessionStorage.getItem(STORAGE_KEYS.csrf), "csrf-kept");
});


test("an existing cookie can recover missing CSRF with current Telegram proof and nonce", async () => {
  const nonce = "AQIDBAUGBwgJCgsMDQ4PEA";
  const sessionStorage = new FakeStorage({ [STORAGE_KEYS.clientNonce]: nonce });
  const harness = createHarness(({ method, url }) => {
    if (method === "GET" && url === "/miniapp/api/chat") {
      return { body: chatBody([{ id: 1, role: "assistant", content: "Still here", timestamp: 1 }]) };
    }
    if (method === "POST" && url === "/miniapp/api/session") {
      return {
        status: 201,
        body: sessionExchangeBody("csrf-restored", STABLE_SCOPE_A),
      };
    }
    throw new Error(`unexpected ${method} ${url}`);
  }, { sessionStorage, initData: "fresh-telegram-proof" });

  await harness.app.start();

  const exchange = harness.calls.find((call) => call.method === "POST");
  assert.deepEqual(exchange.body, {
    init_data: "fresh-telegram-proof",
    client_nonce: nonce,
  });
  assert.equal(sessionStorage.getItem(STORAGE_KEYS.csrf), "csrf-restored");
});


test("chat history uses textContent and never interprets remote markup", async () => {
  const payload = '<img src=x onerror="steal()">';
  const harness = createHarness(({ method, url }) => {
    if (method === "GET" && url === "/miniapp/api/chat") {
      return { body: chatBody([{ id: 1, role: "assistant", content: payload, timestamp: 1 }]) };
    }
    throw new Error(`unexpected ${method} ${url}`);
  }, { sessionStorage: new FakeStorage({ [STORAGE_KEYS.csrf]: "csrf" }) });

  await harness.app.start();
  const transcript = harness.document.getElementById("miniapp-transcript");
  assert.equal(transcript.children[0].children[1].textContent, payload);
  assert.equal(transcript.children[0].children.length, 2);
});


test("local conversation state is unreadable from another browser session scope", async () => {
  const localStorage = new FakeStorage({
    [STORAGE_KEYS.draft]: scoped("private draft", "scope:old-csrf"),
    [STORAGE_KEYS.currentClientMessage]: scoped(
      "11111111-2222-4333-8444-555555555555",
      "scope:old-csrf",
    ),
  });
  const harness = createHarness(({ method, url }) => {
    if (method === "GET" && url === "/miniapp/api/chat") return { body: chatBody() };
    throw new Error(`unexpected ${method} ${url}`);
  }, {
    localStorage,
    sessionStorage: new FakeStorage({ [STORAGE_KEYS.csrf]: "new-csrf" }),
  });

  await harness.app.start();

  assert.equal(harness.document.getElementById("miniapp-input").value, "");
  assert.equal(
    harness.calls.filter((call) => call.url.endsWith("/run")).length,
    0,
  );
});


test("CSRF scope replacement clears prepared funding evidence", async () => {
  const clientId = "11111111-2222-4333-8444-555555555555";
  const sessionStorage = new FakeStorage({ [STORAGE_KEYS.csrf]: "old-csrf" });
  const localStorage = new FakeStorage({
    [STORAGE_KEYS.fundingPreparedMessage]: scoped(clientId, "scope:old-csrf"),
    [STORAGE_KEYS.fundingMessageAmount]: scoped(
      JSON.stringify({ client_message_id: clientId, amount: "1.000000" }),
      "scope:old-csrf",
    ),
  });
  let chatLoads = 0;
  const harness = createHarness(({ method, url }) => {
    if (method === "GET" && url === "/miniapp/api/chat") {
      chatLoads += 1;
      return chatLoads === 1
        ? { status: 401, body: { detail: "miniapp_unauthorized" } }
        : { body: chatBody() };
    }
    if (method === "POST" && url === "/miniapp/api/session") {
      return {
        status: 201,
        body: {
          authenticated: true,
          csrf_token: "new-csrf",
          storage_scope: STABLE_SCOPE_A,
          user: { username: "Jeff" },
        },
      };
    }
    throw new Error(`unexpected ${method} ${url}`);
  }, { sessionStorage, localStorage, legacySession: true });

  await harness.app.start();

  assert.equal(
    localStorage.getItem(STORAGE_KEYS.fundingPreparedMessage),
    null,
  );
  assert.equal(
    localStorage.getItem(STORAGE_KEYS.fundingMessageAmount),
    null,
  );
});


test("server storage scope restores one subject's funding across a new CSRF", async () => {
  const localStorage = new FakeStorage({
    [STORAGE_KEYS.fundingAmount]: scoped("1.000000", STABLE_SCOPE_A),
    [STORAGE_KEYS.fundingIdempotency]: scoped("stable-intent", STABLE_SCOPE_A),
    [STORAGE_KEYS.fundingOperation]: scoped("pm_funding_1", STABLE_SCOPE_A),
  });
  const authenticate = freshSessionRoute("new-csrf", STABLE_SCOPE_A);
  let statusGets = 0;
  const harness = createHarness((call) => {
    const authenticated = authenticate(call);
    if (authenticated) return authenticated;
    const { method, url } = call;
    if (
      method === "GET" &&
      url === "/miniapp/api/operations/polymarket/funding/pm_funding_1"
    ) {
      statusGets += 1;
      return {
        body: fundingBody({
          amount_usdc: "1.000000",
          status: "manual_review",
          next_action: "manual_review",
        }),
      };
    }
    throw new Error(`unexpected ${method} ${url}`);
  }, { localStorage, sessionStorage: new FakeStorage() });

  await harness.app.start();

  assert.equal(statusGets, 1);
  assert.equal(
    harness.document.getElementById("polymarket-funding-amount").value,
    "1.000000",
  );
  assert.equal(
    harness.calls.some((call) =>
      call.method === "POST" &&
      call.url.startsWith("/miniapp/api/operations/polymarket/funding")
    ),
    false,
  );
});


test("server storage scope isolates a different Telegram subject", async () => {
  const localStorage = new FakeStorage({
    [STORAGE_KEYS.fundingAmount]: scoped("1.000000", STABLE_SCOPE_A),
    [STORAGE_KEYS.fundingIdempotency]: scoped("stable-intent", STABLE_SCOPE_A),
    [STORAGE_KEYS.fundingOperation]: scoped("pm_funding_1", STABLE_SCOPE_A),
  });
  const authenticate = freshSessionRoute("other-csrf", STABLE_SCOPE_B, "Other");
  const harness = createHarness((call) => {
    const authenticated = authenticate(call);
    if (authenticated) return authenticated;
    const { method, url } = call;
    throw new Error(`unexpected ${method} ${url}`);
  }, { localStorage, sessionStorage: new FakeStorage() });

  await harness.app.start();

  assert.equal(
    harness.document.getElementById("polymarket-funding-amount").value,
    "",
  );
  assert.equal(
    harness.calls.some((call) =>
      call.url.startsWith("/miniapp/api/operations/polymarket/funding")
    ),
    false,
  );
});


test("invalid server storage scope never falls back to a new CSRF namespace", async () => {
  const localStorage = new FakeStorage({
    [STORAGE_KEYS.fundingAmount]: scoped("1.000000", "scope:new-csrf"),
    [STORAGE_KEYS.fundingOperation]: scoped("pm_funding_1", "scope:new-csrf"),
  });
  const authenticate = freshSessionRoute("new-csrf", "scope:new-csrf");
  const harness = createHarness((call) => {
    const authenticated = authenticate(call);
    if (authenticated) return authenticated;
    const { method, url } = call;
    if (url.startsWith("/miniapp/api/operations/polymarket/funding")) {
      return { body: fundingBody({ amount_usdc: "1.000000" }) };
    }
    throw new Error(`unexpected ${method} ${url}`);
  }, { localStorage, sessionStorage: new FakeStorage() });

  await harness.app.start();

  assert.equal(
    harness.calls.some((call) =>
      call.url.startsWith("/miniapp/api/operations/polymarket/funding")
    ),
    false,
  );
  assert.equal(harness.sessionStorage.getItem(STORAGE_KEYS.csrf), null);
});


test("legacy CSRF cannot fund before a forced stable-scope exchange completes", async () => {
  const exchangeGate = deferred();
  const sessionStorage = new FakeStorage({ [STORAGE_KEYS.csrf]: "legacy-csrf" });
  const harness = createHarness(({ method, url }) => {
    if (method === "POST" && url === "/miniapp/api/session") {
      return exchangeGate.promise;
    }
    if (method === "GET" && url === "/miniapp/api/chat") {
      return { body: chatBody() };
    }
    if (method === "POST" && url === "/miniapp/api/operations/polymarket/funding") {
      return { status: 400, body: { detail: "miniapp_invalid_request" } };
    }
    throw new Error(`unexpected ${method} ${url}`);
  }, { sessionStorage, legacySession: true });

  const starting = harness.app.start();
  for (let index = 0; index < 5; index += 1) await Promise.resolve();

  assert.equal(
    harness.calls.filter((call) => call.url === "/miniapp/api/session").length,
    1,
  );
  await harness.document.getElementById(
    "polymarket-funding-confirm",
  ).dispatch("click");
  assert.equal(
    harness.calls.some((call) =>
      call.url.startsWith("/miniapp/api/operations/polymarket/funding")
    ),
    false,
  );

  exchangeGate.resolve({
    status: 201,
    body: sessionExchangeBody("stable-csrf", STABLE_SCOPE_A),
  });
  await starting;
  const amount = harness.document.getElementById("polymarket-funding-amount");
  amount.value = "1";
  await amount.dispatch("input");
  await harness.document.getElementById(
    "polymarket-funding-confirm",
  ).dispatch("click");

  assert.equal(
    harness.calls.filter((call) =>
      call.method === "POST" &&
      call.url === "/miniapp/api/operations/polymarket/funding"
    ).length,
    1,
  );
});


test("failed identity exchange leaves legacy funding recovery untouched", async () => {
  const legacyScope = "scope:legacy-csrf";
  const legacyEnvelope = scoped("legacy-intent", legacyScope);
  const localStorage = new FakeStorage({
    [STORAGE_KEYS.fundingIdempotency]: legacyEnvelope,
  });
  const sessionStorage = new FakeStorage({ [STORAGE_KEYS.csrf]: "legacy-csrf" });
  const harness = createHarness(({ method, url }) => {
    if (method === "POST" && url === "/miniapp/api/session") {
      return { status: 503, body: { detail: "miniapp_unavailable" } };
    }
    throw new Error(`unexpected ${method} ${url}`);
  }, {
    localStorage,
    sessionStorage,
    legacySession: true,
    initData: "subject-b-init-data",
  });

  await harness.app.start();

  assert.equal(
    localStorage.getItem(STORAGE_KEYS.fundingIdempotency),
    legacyEnvelope,
  );
  assert.equal(
    localStorage.getItem(`${STORAGE_KEYS.fundingIdempotency}:${legacyScope}`),
    null,
  );
});


test("legacy funding recovery becomes a stable reconciliation block", async () => {
  const legacyScope = "scope:legacy-csrf";
  const localStorage = new FakeStorage({
    [STORAGE_KEYS.fundingAmount]: scoped("1.000000", legacyScope),
    [STORAGE_KEYS.fundingIdempotency]: scoped("legacy-intent", legacyScope),
    [STORAGE_KEYS.fundingOperation]: scoped("pm_legacy", legacyScope),
  });
  const sessionStorage = new FakeStorage({ [STORAGE_KEYS.csrf]: "legacy-csrf" });
  const harness = createHarness(({ method, url }) => {
    if (method === "POST" && url === "/miniapp/api/session") {
      return {
        status: 201,
        body: sessionExchangeBody("stable-csrf", STABLE_SCOPE_A),
      };
    }
    if (method === "GET" && url === "/miniapp/api/chat") {
      return { body: chatBody() };
    }
    throw new Error(`unexpected ${method} ${url}`);
  }, { localStorage, sessionStorage, legacySession: true });

  await harness.app.start();
  const amount = harness.document.getElementById("polymarket-funding-amount");
  amount.value = "2";
  await amount.dispatch("input");
  await harness.document.getElementById(
    "polymarket-funding-confirm",
  ).dispatch("click");

  assert.equal(
    harness.calls.filter((call) => call.url === "/miniapp/api/session").length,
    1,
  );
  assert.equal(
    harness.calls.some((call) =>
      call.url.startsWith("/miniapp/api/operations/polymarket/funding")
    ),
    false,
  );
  assert.equal(
    storedNamespacedValue(
      localStorage,
      STORAGE_KEYS.fundingCreateUncertain,
      STABLE_SCOPE_A,
    ),
    "true",
  );
  assert.equal(
    storedNamespacedValue(
      localStorage,
      STORAGE_KEYS.fundingRecoveryStatus,
      STABLE_SCOPE_A,
    ),
    "legacy_scope_unresolved",
  );
  assert.equal(
    harness.document.getElementById("polymarket-funding-status").textContent,
    "A previous funding request needs reconciliation. No new funding was started.",
  );
});


test("a legacy amount-only draft does not block stable funding", async () => {
  const legacyScope = "scope:legacy-csrf";
  const localStorage = new FakeStorage({
    [STORAGE_KEYS.fundingAmount]: scoped("1.000000", legacyScope),
  });
  const sessionStorage = new FakeStorage({ [STORAGE_KEYS.csrf]: "legacy-csrf" });
  const harness = createHarness(({ method, url }) => {
    if (method === "POST" && url === "/miniapp/api/session") {
      return {
        status: 201,
        body: sessionExchangeBody("stable-csrf", STABLE_SCOPE_A),
      };
    }
    if (method === "GET" && url === "/miniapp/api/chat") {
      return { body: chatBody() };
    }
    if (method === "POST" && url === "/miniapp/api/operations/polymarket/funding") {
      return { status: 400, body: { detail: "miniapp_invalid_request" } };
    }
    throw new Error(`unexpected ${method} ${url}`);
  }, { localStorage, sessionStorage, legacySession: true });

  await harness.app.start();
  const amount = harness.document.getElementById("polymarket-funding-amount");
  amount.value = "2";
  await amount.dispatch("input");
  await harness.document.getElementById(
    "polymarket-funding-confirm",
  ).dispatch("click");

  assert.equal(
    harness.calls.filter((call) =>
      call.method === "POST" &&
      call.url === "/miniapp/api/operations/polymarket/funding"
    ).length,
    1,
  );
});


test("cached scope waits for the current Telegram subject exchange", async () => {
  const exchangeGate = deferred();
  const localStorage = new FakeStorage({
    [`${STORAGE_KEYS.fundingAmount}:${STABLE_SCOPE_A}`]: scoped(
      "1.000000",
      STABLE_SCOPE_A,
    ),
    [`${STORAGE_KEYS.fundingIdempotency}:${STABLE_SCOPE_A}`]: scoped(
      "intent-a",
      STABLE_SCOPE_A,
    ),
    [`${STORAGE_KEYS.fundingOperation}:${STABLE_SCOPE_A}`]: scoped(
      "pm_funding_a",
      STABLE_SCOPE_A,
    ),
  });
  const sessionStorage = new FakeStorage({
    [STORAGE_KEYS.csrf]: "csrf-a",
    [STORAGE_KEYS.scope]: STABLE_SCOPE_A,
  });
  const harness = createHarness(({ method, url }) => {
    if (method === "POST" && url === "/miniapp/api/session") {
      return exchangeGate.promise;
    }
    if (method === "GET" && url === "/miniapp/api/chat") {
      return { body: chatBody() };
    }
    if (
      method === "GET" &&
      url === "/miniapp/api/operations/polymarket/funding/pm_funding_a"
    ) {
      return {
        body: fundingBody({
          operation_id: "pm_funding_a",
          status: "manual_review",
          next_action: "manual_review",
        }),
      };
    }
    if (method === "POST" && url === "/miniapp/api/operations/polymarket/funding") {
      return { status: 400, body: { detail: "miniapp_invalid_request" } };
    }
    throw new Error(`unexpected ${method} ${url}`);
  }, {
    localStorage,
    sessionStorage,
    initData: "subject-b-init-data",
    observeSessionExchange: true,
  });

  const starting = harness.app.start();
  for (let index = 0; index < 5; index += 1) await Promise.resolve();

  assert.equal(
    harness.calls.filter((call) => call.url === "/miniapp/api/session").length,
    1,
  );
  await harness.document.getElementById(
    "polymarket-funding-confirm",
  ).dispatch("click");
  assert.equal(
    harness.calls.some((call) =>
      call.url.startsWith("/miniapp/api/operations/polymarket/funding")
    ),
    false,
  );

  exchangeGate.resolve({
    status: 201,
    body: sessionExchangeBody("csrf-b", STABLE_SCOPE_B, "Subject B"),
  });
  await starting;
  const amount = harness.document.getElementById("polymarket-funding-amount");
  amount.value = "2";
  await amount.dispatch("input");
  await harness.document.getElementById(
    "polymarket-funding-confirm",
  ).dispatch("click");

  assert.equal(
    harness.calls.filter((call) =>
      call.method === "POST" &&
      call.url === "/miniapp/api/operations/polymarket/funding"
    ).length,
    1,
  );
  assert.equal(
    storedNamespacedValue(
      localStorage,
      STORAGE_KEYS.fundingOperation,
      STABLE_SCOPE_A,
    ),
    "pm_funding_a",
  );
  assert.equal(
    storedNamespacedValue(
      localStorage,
      STORAGE_KEYS.fundingIdempotency,
      STABLE_SCOPE_A,
    ),
    "intent-a",
  );
});


test("logout invalidates an in-flight Telegram subject exchange", async () => {
  const exchangeGate = deferred();
  const sessionStorage = new FakeStorage({
    [STORAGE_KEYS.csrf]: "csrf-a",
    [STORAGE_KEYS.scope]: STABLE_SCOPE_A,
  });
  const localStorage = new FakeStorage({
    [STORAGE_KEYS.draft]: scoped("subject A private draft", STABLE_SCOPE_A),
    [`${STORAGE_KEYS.fundingOperation}:${STABLE_SCOPE_A}`]: scoped(
      "pm_funding_a",
      STABLE_SCOPE_A,
    ),
  });
  const harness = createHarness(({ method, url }) => {
    if (method === "POST" && url === "/miniapp/api/session") {
      return exchangeGate.promise;
    }
    if (method === "DELETE" && url === "/miniapp/api/session") {
      return { status: 204, body: null };
    }
    if (method === "GET" && url === "/miniapp/api/chat") {
      return { body: chatBody() };
    }
    if (url.startsWith("/miniapp/api/operations/polymarket/funding")) {
      return { status: 400, body: { detail: "miniapp_invalid_request" } };
    }
    throw new Error(`unexpected ${method} ${url}`);
  }, {
    localStorage,
    sessionStorage,
    initData: "subject-b-init-data",
    observeSessionExchange: true,
  });

  const starting = harness.app.start();
  for (let index = 0; index < 5; index += 1) await Promise.resolve();
  await harness.app.logout();

  exchangeGate.resolve({
    status: 201,
    body: sessionExchangeBody("csrf-b", STABLE_SCOPE_B, "Subject B"),
  });
  await starting;

  assert.equal(sessionStorage.getItem(STORAGE_KEYS.csrf), null);
  assert.equal(sessionStorage.getItem(STORAGE_KEYS.scope), null);
  assert.equal(
    harness.calls.some((call) => call.url === "/miniapp/api/chat"),
    false,
  );
  assert.equal(
    harness.calls.some((call) =>
      call.url.startsWith("/miniapp/api/operations/polymarket/funding")
    ),
    false,
  );
  const revocations = harness.calls.filter((call) =>
    call.method === "DELETE" && call.url === "/miniapp/api/session"
  );
  assert.deepEqual(
    revocations.map((call) => call.headers["X-Agentonomy-CSRF"]),
    ["csrf-a", "csrf-b"],
  );
  assert.equal(harness.document.getElementById("miniapp-input").value, "");
  assert.equal(
    harness.document.getElementById("miniapp-transcript").children.length,
    0,
  );
});


test("a stale subject capability cannot cross a new Telegram bootstrap", async () => {
  const oldCapability = deferred();
  let exchanges = 0;
  let accountPosts = 0;
  const harness = createHarness(({ method, url }) => {
    if (method === "POST" && url === "/miniapp/api/session") {
      exchanges += 1;
      return {
        status: 201,
        body: sessionExchangeBody(
          `csrf-${exchanges}`,
          exchanges === 1 ? STABLE_SCOPE_A : STABLE_SCOPE_B,
          exchanges === 1 ? "Subject A" : "Subject B",
        ),
      };
    }
    if (method === "GET" && url === "/miniapp/api/chat") {
      return { body: chatBody() };
    }
    if (method === "POST" && url === "/miniapp/api/operations/account") {
      accountPosts += 1;
      if (accountPosts === 1) return oldCapability.promise;
      return {
        body: { url: "https://www.agentonomy.xyz/account/session/subject-b" },
      };
    }
    throw new Error(`unexpected ${method} ${url}`);
  }, {
    sessionStorage: new FakeStorage(),
    observeSessionExchange: true,
    telegramOpenLink: true,
  });

  await harness.app.start();
  const oldClick = harness.document.operationLinks[0].dispatch("click");
  for (let index = 0; index < 5; index += 1) await Promise.resolve();

  harness.telegram.initData = "subject-b-init-data";
  await harness.app.start();
  oldCapability.resolve({
    body: { url: "https://www.agentonomy.xyz/account/session/subject-a" },
  });
  await oldClick;

  assert.deepEqual(harness.externalOpened, []);
  await harness.document.operationLinks[0].dispatch("click");
  assert.equal(accountPosts, 2);
  assert.deepEqual(harness.externalOpened, [
    "https://www.agentonomy.xyz/account/session/subject-b",
  ]);
  assert.deepEqual(harness.assigned, []);
});


test("a prepared signing capability cannot cross a new Telegram bootstrap", async () => {
  let exchanges = 0;
  let signingPosts = 0;
  const signingUrl = (subject) => (
    "https://www.agentonomy.xyz/execution/polymarket/" +
    `order-signing-console/#access_token=subject_${subject}_capability`
  );
  const harness = createHarness(({ method, url }) => {
    if (method === "POST" && url === "/miniapp/api/session") {
      exchanges += 1;
      return {
        status: 201,
        body: sessionExchangeBody(
          `csrf-${exchanges}`,
          exchanges === 1 ? STABLE_SCOPE_A : STABLE_SCOPE_B,
          exchanges === 1 ? "Subject A" : "Subject B",
        ),
      };
    }
    if (method === "GET" && url === "/miniapp/api/chat") {
      return { body: chatBody() };
    }
    if (
      method === "POST" &&
      url === "/miniapp/api/operations/polymarket/order-signing"
    ) {
      signingPosts += 1;
      const subject = signingPosts === 1 ? "a" : "b";
      return {
        status: 201,
        body: signingBody({
          session_id: `pm_sign_${subject}`,
          signing_url: signingUrl(subject),
        }),
      };
    }
    throw new Error(`unexpected ${method} ${url}`);
  }, {
    sessionStorage: new FakeStorage(),
    observeSessionExchange: true,
    telegramOpenLink: true,
  });

  await harness.app.start();
  const preview = harness.document.getElementById("polymarket-signing-preview");
  const open = harness.document.getElementById("polymarket-signing-open");
  preview.value = "preview-shared";
  await preview.dispatch("input");
  await open.dispatch("click");
  assert.equal(signingPosts, 1);
  assert.deepEqual(harness.externalOpened, []);

  harness.telegram.initData = "subject-b-init-data";
  await harness.app.start();
  preview.value = "preview-shared";
  await preview.dispatch("input");
  await open.dispatch("click");

  assert.equal(signingPosts, 2);
  assert.deepEqual(harness.externalOpened, []);
  await open.dispatch("click");
  assert.deepEqual(harness.externalOpened, [signingUrl("b")]);
});


test("a first Telegram visit exchanges a session before loading chat", async () => {
  const harness = createHarness(({ method, url }) => {
    if (method === "POST" && url === "/miniapp/api/session") {
      return {
        status: 201,
        body: sessionExchangeBody("fresh-csrf", STABLE_SCOPE_A),
      };
    }
    if (method === "GET" && url === "/miniapp/api/chat") {
      return { body: chatBody() };
    }
    throw new Error(`unexpected ${method} ${url}`);
  }, {
    sessionStorage: new FakeStorage(),
    observeSessionExchange: true,
  });

  await harness.app.start();

  assert.deepEqual(
    harness.calls.map(({ method, url }) => `${method} ${url}`),
    ["POST /miniapp/api/session", "GET /miniapp/api/chat"],
  );
  assert.equal(
    harness.sessionStorage.getItem(STORAGE_KEYS.csrf),
    "fresh-csrf",
  );
  assert.equal(
    harness.sessionStorage.getItem(STORAGE_KEYS.scope),
    STABLE_SCOPE_A,
  );
});


test("cached subject state stays unreadable when current exchange fails", async () => {
  const sessionStorage = new FakeStorage({
    [STORAGE_KEYS.csrf]: "csrf-a",
    [STORAGE_KEYS.scope]: STABLE_SCOPE_A,
  });
  const localStorage = new FakeStorage({
    [STORAGE_KEYS.draft]: scoped("subject A private draft", STABLE_SCOPE_A),
    [STORAGE_KEYS.signingPreview]: scoped("preview-a", STABLE_SCOPE_A),
    [STORAGE_KEYS.signingSession]: scoped("signing-a", STABLE_SCOPE_A),
    [STORAGE_KEYS.signingSessionPreview]: scoped("preview-a", STABLE_SCOPE_A),
  });
  const harness = createHarness(({ method, url }) => {
    if (method === "POST" && url === "/miniapp/api/session") {
      return { status: 503, body: { detail: "miniapp_unavailable" } };
    }
    if (method === "GET" && url === "/miniapp/api/chat") {
      return {
        body: chatBody([
          { role: "assistant", content: "subject A private history" },
        ]),
      };
    }
    if (method === "POST" && url === "/miniapp/api/chat/messages") {
      return {
        status: 202,
        body: {
          client_message_id: "11111111-2222-4333-8444-555555555555",
          status: "accepted",
        },
      };
    }
    if (
      method === "POST" &&
      [
        "/miniapp/api/operations/account",
        "/miniapp/api/operations/polymarket",
        "/miniapp/api/operations/polymarket/order-signing",
      ].includes(url)
    ) {
      return { status: 503, body: { detail: "miniapp_unavailable" } };
    }
    if (
      method === "GET" &&
      url === "/miniapp/api/operations/polymarket/order-signing/signing-a"
    ) {
      return { status: 503, body: { detail: "miniapp_unavailable" } };
    }
    if (method === "POST" && url === "/miniapp/api/operations/polymarket/funding") {
      return { status: 400, body: { detail: "miniapp_invalid_request" } };
    }
    throw new Error(`unexpected ${method} ${url}`);
  }, {
    localStorage,
    sessionStorage,
    initData: "subject-b-init-data",
    observeSessionExchange: true,
  });

  await harness.app.start();
  const amount = harness.document.getElementById("polymarket-funding-amount");
  amount.value = "1";
  await amount.dispatch("input");
  await harness.document.getElementById(
    "polymarket-funding-confirm",
  ).dispatch("click");
  await harness.document.operationLinks[0].dispatch("click");
  await harness.document.operationLinks[2].dispatch("click");
  const preview = harness.document.getElementById("polymarket-signing-preview");
  preview.value = "preview-b";
  await preview.dispatch("input");
  await harness.document.getElementById("polymarket-signing-open").dispatch("click");
  await harness.document.getElementById("polymarket-signing-check").dispatch("click");

  assert.equal(
    harness.calls.filter((call) => call.url === "/miniapp/api/session").length,
    1,
  );
  assert.equal(
    harness.calls.some((call) => call.url === "/miniapp/api/chat"),
    false,
  );
  assert.equal(harness.document.getElementById("miniapp-input").value, "");
  assert.equal(
    harness.document.getElementById("miniapp-transcript").children.length,
    0,
  );
  const input = harness.document.getElementById("miniapp-input");
  input.value = "subject B message";
  await input.dispatch("input");
  await harness.app.sendCurrentMessage();
  assert.equal(
    harness.calls.some((call) => call.url === "/miniapp/api/chat/messages"),
    false,
  );
  assert.equal(
    localStorage.getItem(STORAGE_KEYS.draft),
    scoped("subject A private draft", STABLE_SCOPE_A),
  );
  input.value = "";
  await harness.emitWindow("pageshow");
  assert.equal(input.value, "");
  assert.equal(
    harness.calls.some((call) => call.url === "/miniapp/api/chat"),
    false,
  );
  assert.equal(
    harness.calls.some((call) =>
      call.url.startsWith("/miniapp/api/operations/")
    ),
    false,
  );
  assert.equal(localStorage.getItem(STORAGE_KEYS.returnMarker), null);
  assert.equal(
    localStorage.getItem(STORAGE_KEYS.signingPreview),
    scoped("preview-a", STABLE_SCOPE_A),
  );
});


test("cached scope without Telegram initData stays funding-closed", async () => {
  const sessionStorage = new FakeStorage({
    [STORAGE_KEYS.csrf]: "csrf-a",
    [STORAGE_KEYS.scope]: STABLE_SCOPE_A,
  });
  const harness = createHarness(({ method, url }) => {
    if (method === "GET" && url === "/miniapp/api/chat") {
      return { body: chatBody() };
    }
    if (method === "POST" && url === "/miniapp/api/operations/polymarket/funding") {
      return { status: 400, body: { detail: "miniapp_invalid_request" } };
    }
    throw new Error(`unexpected ${method} ${url}`);
  }, { sessionStorage, telegram: false });

  await harness.app.start();
  const amount = harness.document.getElementById("polymarket-funding-amount");
  amount.value = "1";
  await amount.dispatch("input");
  await harness.document.getElementById(
    "polymarket-funding-confirm",
  ).dispatch("click");

  assert.equal(
    harness.calls.some((call) =>
      call.url.startsWith("/miniapp/api/operations/polymarket/funding")
    ),
    false,
  );
});


test("logout during funding continuation reopens the same operation with GET only", async () => {
  const continueGate = deferred();
  const localStorage = new FakeStorage();
  const authenticateFirst = freshSessionRoute("csrf-a1", STABLE_SCOPE_A);
  const first = createHarness((call) => {
    const authenticated = authenticateFirst(call);
    if (authenticated) return authenticated;
    const { method, url } = call;
    if (method === "POST" && url === "/miniapp/api/operations/polymarket/funding") {
      return {
        status: 201,
        body: fundingBody({ amount_usdc: "1.000000" }),
      };
    }
    if (
      method === "POST" &&
      url === "/miniapp/api/operations/polymarket/funding/pm_funding_1/continue"
    ) return continueGate.promise;
    if (method === "DELETE" && url === "/miniapp/api/session") {
      return { status: 204, body: null };
    }
    throw new Error(`unexpected ${method} ${url}`);
  }, { localStorage, sessionStorage: new FakeStorage() });
  await first.app.start();
  const amount = first.document.getElementById("polymarket-funding-amount");
  amount.value = "1";
  await amount.dispatch("input");
  const continuing = first.document.getElementById(
    "polymarket-funding-confirm",
  ).dispatch("click");
  for (let index = 0; index < 5; index += 1) await Promise.resolve();
  assert.equal(
    first.calls.some((call) => call.url.endsWith("/continue")),
    true,
  );

  await first.app.logout();

  assert.equal(
    storedNamespacedValue(localStorage, STORAGE_KEYS.fundingOperation, STABLE_SCOPE_A),
    "pm_funding_1",
  );
  continueGate.resolve({
    body: fundingBody({
      amount_usdc: "1.000000",
      status: "confirmed",
      next_action: "processing",
    }),
  });
  await continuing;

  const authenticateSecond = freshSessionRoute("csrf-a2", STABLE_SCOPE_A);
  let statusGets = 0;
  const second = createHarness((call) => {
    const authenticated = authenticateSecond(call);
    if (authenticated) return authenticated;
    const { method, url } = call;
    if (
      method === "GET" &&
      url === "/miniapp/api/operations/polymarket/funding/pm_funding_1"
    ) {
      statusGets += 1;
      return {
        body: fundingBody({
          amount_usdc: "1.000000",
          status: "manual_review",
          next_action: "manual_review",
        }),
      };
    }
    throw new Error(`unexpected ${method} ${url}`);
  }, { localStorage, sessionStorage: new FakeStorage() });

  await second.app.start();

  assert.equal(statusGets, 1);
  assert.equal(
    second.calls.some((call) =>
      call.method === "POST" &&
      call.url.startsWith("/miniapp/api/operations/polymarket/funding")
    ),
    false,
  );
});


test("logout terminal proof cannot delete a newer shared funding operation", async () => {
  const localStorage = new FakeStorage({
    [`${STORAGE_KEYS.fundingAmount}:${STABLE_SCOPE_A}`]: scoped(
      "1.000000",
      STABLE_SCOPE_A,
    ),
    [`${STORAGE_KEYS.fundingIdempotency}:${STABLE_SCOPE_A}`]: scoped(
      "old-intent",
      STABLE_SCOPE_A,
    ),
    [`${STORAGE_KEYS.fundingOperation}:${STABLE_SCOPE_A}`]: scoped(
      "pm_old",
      STABLE_SCOPE_A,
    ),
  });
  const first = createHarness(({ method, url }) => {
    if (method === "GET" && url === "/miniapp/api/chat") {
      return { body: chatBody() };
    }
    if (
      method === "GET" &&
      url === "/miniapp/api/operations/polymarket/funding/pm_old"
    ) {
      return {
        body: fundingBody({
          operation_id: "pm_old",
          status: "finalized",
          next_action: "complete",
        }),
      };
    }
    if (method === "DELETE" && url === "/miniapp/api/session") {
      return { status: 204, body: null };
    }
    throw new Error(`unexpected ${method} ${url}`);
  }, {
    localStorage,
    sessionStorage: new FakeStorage({
      [STORAGE_KEYS.csrf]: "csrf-old",
      [STORAGE_KEYS.scope]: STABLE_SCOPE_A,
    }),
  });
  await first.app.start();

  localStorage.setItem(
    `${STORAGE_KEYS.fundingAmount}:${STABLE_SCOPE_A}`,
    scoped("2.000000", STABLE_SCOPE_A),
  );
  localStorage.setItem(
    `${STORAGE_KEYS.fundingIdempotency}:${STABLE_SCOPE_A}`,
    scoped("new-intent", STABLE_SCOPE_A),
  );
  localStorage.setItem(
    `${STORAGE_KEYS.fundingOperation}:${STABLE_SCOPE_A}`,
    scoped("pm_new", STABLE_SCOPE_A),
  );

  await first.document.getElementById("miniapp-logout").dispatch("click");

  let newOperationGets = 0;
  const reopened = createHarness(({ method, url }) => {
    if (method === "GET" && url === "/miniapp/api/chat") {
      return { body: chatBody() };
    }
    if (
      method === "GET" &&
      url === "/miniapp/api/operations/polymarket/funding/pm_new"
    ) {
      newOperationGets += 1;
      return {
        body: fundingBody({
          operation_id: "pm_new",
          amount_usdc: "2.000000",
          status: "manual_review",
          next_action: "manual_review",
        }),
      };
    }
    if (method === "POST" && url === "/miniapp/api/operations/polymarket/funding") {
      throw new Error("new funding create must not run");
    }
    throw new Error(`unexpected ${method} ${url}`);
  }, {
    localStorage,
    sessionStorage: new FakeStorage({
      [STORAGE_KEYS.csrf]: "csrf-new",
      [STORAGE_KEYS.scope]: STABLE_SCOPE_A,
    }),
  });
  await reopened.app.start();

  assert.equal(newOperationGets, 1);
  assert.equal(
    storedNamespacedValue(
      localStorage,
      STORAGE_KEYS.fundingOperation,
      STABLE_SCOPE_A,
    ),
    "pm_new",
  );
  assert.equal(
    reopened.calls.some((call) =>
      call.method === "POST" &&
      call.url === "/miniapp/api/operations/polymarket/funding"
    ),
    false,
  );
});


test("logout during an unanswered funding create preserves its tombstone", async () => {
  const createGate = deferred();
  const localStorage = new FakeStorage();
  const authenticateFirst = freshSessionRoute("csrf-create-a1", STABLE_SCOPE_A);
  const first = createHarness((call) => {
    const authenticated = authenticateFirst(call);
    if (authenticated) return authenticated;
    const { method, url } = call;
    if (method === "POST" && url === "/miniapp/api/operations/polymarket/funding") {
      return createGate.promise;
    }
    if (method === "DELETE" && url === "/miniapp/api/session") {
      return { status: 204, body: null };
    }
    throw new Error(`unexpected ${method} ${url}`);
  }, { localStorage, sessionStorage: new FakeStorage() });
  await first.app.start();
  const amount = first.document.getElementById("polymarket-funding-amount");
  amount.value = "1";
  await amount.dispatch("input");
  const creating = first.document.getElementById(
    "polymarket-funding-confirm",
  ).dispatch("click");
  await Promise.resolve();

  await first.app.logout();

  assert.equal(
    storedNamespacedValue(localStorage, STORAGE_KEYS.fundingAmount, STABLE_SCOPE_A),
    "1.000000",
  );
  assert.equal(
    storedNamespacedValue(
      localStorage,
      STORAGE_KEYS.fundingCreateUncertain,
      STABLE_SCOPE_A,
    ),
    "true",
  );
  assert.equal(
    storedNamespacedValue(
      localStorage,
      STORAGE_KEYS.fundingIdempotency,
      STABLE_SCOPE_A,
    ),
    "11111111-2222-4333-8444-555555555555",
  );

  const authenticateSecond = freshSessionRoute("csrf-create-a2", STABLE_SCOPE_A);
  const second = createHarness((call) => {
    const authenticated = authenticateSecond(call);
    if (authenticated) return authenticated;
    const { method, url } = call;
    throw new Error(`unexpected ${method} ${url}`);
  }, { localStorage, sessionStorage: new FakeStorage() });

  await second.app.start();

  assert.equal(
    second.calls.some((call) =>
      call.method === "POST" &&
      call.url.startsWith("/miniapp/api/operations/polymarket/funding")
    ),
    false,
  );
  createGate.resolve({
    status: 201,
    body: fundingBody({ amount_usdc: "1.000000" }),
  });
  await creating;
});


test("another subject cannot overwrite or delete preserved funding recovery", async () => {
  const localStorage = new FakeStorage({
    [STORAGE_KEYS.fundingAmount]: scoped("1.000000", STABLE_SCOPE_A),
    [STORAGE_KEYS.fundingIdempotency]: scoped("intent-a", STABLE_SCOPE_A),
    [STORAGE_KEYS.fundingOperation]: scoped("pm_funding_a", STABLE_SCOPE_A),
  });
  const firstA = createHarness(({ method, url }) => {
    if (method === "GET" && url === "/miniapp/api/chat") return { body: chatBody() };
    if (
      method === "GET" &&
      url === "/miniapp/api/operations/polymarket/funding/pm_funding_a"
    ) {
      return {
        body: fundingBody({
          operation_id: "pm_funding_a",
          amount_usdc: "1.000000",
          status: "manual_review",
          next_action: "manual_review",
        }),
      };
    }
    if (method === "DELETE" && url === "/miniapp/api/session") {
      return { status: 204, body: null };
    }
    throw new Error(`unexpected ${method} ${url}`);
  }, {
    localStorage,
    sessionStorage: new FakeStorage({
      [STORAGE_KEYS.csrf]: "csrf-a1",
      [STORAGE_KEYS.scope]: STABLE_SCOPE_A,
    }),
  });
  await firstA.app.start();
  await firstA.app.logout();

  const bCreateGate = deferred();
  const subjectB = createHarness(({ method, url }) => {
    if (method === "GET" && url === "/miniapp/api/chat") return { body: chatBody() };
    if (method === "POST" && url === "/miniapp/api/operations/polymarket/funding") {
      return bCreateGate.promise;
    }
    if (method === "DELETE" && url === "/miniapp/api/session") {
      return { status: 204, body: null };
    }
    throw new Error(`unexpected ${method} ${url}`);
  }, {
    localStorage,
    sessionStorage: new FakeStorage({
      [STORAGE_KEYS.csrf]: "csrf-b",
      [STORAGE_KEYS.scope]: STABLE_SCOPE_B,
    }),
  });
  await subjectB.app.start();
  const bAmount = subjectB.document.getElementById("polymarket-funding-amount");
  bAmount.value = "2";
  await bAmount.dispatch("input");
  const bCreating = subjectB.document.getElementById(
    "polymarket-funding-confirm",
  ).dispatch("click");
  await Promise.resolve();
  await subjectB.app.logout();
  bCreateGate.resolve({
    status: 201,
    body: fundingBody({ amount_usdc: "2.000000" }),
  });
  await bCreating;

  let aStatusGets = 0;
  const secondA = createHarness(({ method, url }) => {
    if (method === "GET" && url === "/miniapp/api/chat") return { body: chatBody() };
    if (
      method === "GET" &&
      url === "/miniapp/api/operations/polymarket/funding/pm_funding_a"
    ) {
      aStatusGets += 1;
      return {
        body: fundingBody({
          operation_id: "pm_funding_a",
          amount_usdc: "1.000000",
          status: "manual_review",
          next_action: "manual_review",
        }),
      };
    }
    throw new Error(`unexpected ${method} ${url}`);
  }, {
    localStorage,
    sessionStorage: new FakeStorage({
      [STORAGE_KEYS.csrf]: "csrf-a2",
      [STORAGE_KEYS.scope]: STABLE_SCOPE_A,
    }),
  });

  await secondA.app.start();

  assert.equal(aStatusGets, 1);
  assert.equal(
    secondA.document.getElementById("polymarket-funding-amount").value,
    "1.000000",
  );
  assert.equal(
    secondA.calls.some((call) =>
      call.method === "POST" &&
      call.url.startsWith("/miniapp/api/operations/polymarket/funding")
    ),
    false,
  );
});


test("send lock reuses one client id only when the user explicitly retries a definite failure", async () => {
  let postCount = 0;
  const harness = createHarness(({ method, url }) => {
    if (method === "GET" && url === "/miniapp/api/chat") return { body: chatBody() };
    if (method === "POST" && url === "/miniapp/api/chat/messages") {
      postCount += 1;
      return { status: 503, body: { detail: "miniapp_unavailable" } };
    }
    throw new Error(`unexpected ${method} ${url}`);
  }, { sessionStorage: new FakeStorage({ [STORAGE_KEYS.csrf]: "csrf" }) });
  await harness.app.start();
  const input = harness.document.getElementById("miniapp-input");
  input.value = "Pay attention to idempotency";

  const first = harness.app.sendCurrentMessage();
  const second = harness.app.sendCurrentMessage();
  await Promise.all([first, second]);
  assert.equal(postCount, 1);
  assert.equal(
    storedValue(harness.localStorage, STORAGE_KEYS.currentClientMessage),
    "11111111-2222-4333-8444-555555555555",
  );

  await harness.app.sendCurrentMessage();
  const posts = harness.calls.filter((call) => call.method === "POST" && call.url === "/miniapp/api/chat/messages");
  assert.equal(posts.length, 2);
  assert.equal(posts[0].body.client_message_id, "11111111-2222-4333-8444-555555555555");
  assert.equal(posts[1].body.client_message_id, posts[0].body.client_message_id);
  assert.deepEqual(Object.keys(posts[0].body).sort(), ["client_message_id", "text"]);
});


test("a message conflict keeps the draft but discards the stale id before explicit retry", async () => {
  const clientIds = [
    "11111111-2222-4333-8444-555555555555",
    "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee",
  ];
  let uuidIndex = 0;
  let postCount = 0;
  const harness = createHarness(({ method, url, body }) => {
    if (method === "GET" && url === "/miniapp/api/chat") return { body: chatBody() };
    if (method === "POST" && url === "/miniapp/api/chat/messages") {
      postCount += 1;
      if (postCount === 1) {
        assert.equal(body.client_message_id, clientIds[0]);
        return { status: 409, body: { detail: "miniapp_conflict" } };
      }
      assert.equal(body.client_message_id, clientIds[1]);
      return {
        status: 202,
        body: { client_message_id: clientIds[1], status: "accepted" },
      };
    }
    throw new Error(`unexpected ${method} ${url}`);
  }, {
    randomUUID: () => {
      const value = clientIds[uuidIndex];
      uuidIndex += 1;
      return value;
    },
    sessionStorage: new FakeStorage({ [STORAGE_KEYS.csrf]: "csrf" }),
  });
  await harness.app.start();
  const input = harness.document.getElementById("miniapp-input");
  input.value = "keep this draft";

  await harness.app.sendCurrentMessage();

  assert.equal(postCount, 1);
  assert.equal(input.value, "keep this draft");
  assert.equal(
    harness.localStorage.getItem(STORAGE_KEYS.currentClientMessage),
    null,
  );
  assert.equal(
    harness.document.getElementById("miniapp-status").textContent,
    "This message changed before it was accepted. Your draft is safe. Tap Send again to create a new request.",
  );

  await harness.app.sendCurrentMessage();

  assert.equal(postCount, 2);
  assert.equal(input.value, "");
  const posts = harness.calls.filter((call) => (
    call.method === "POST" && call.url === "/miniapp/api/chat/messages"
  ));
  assert.notEqual(posts[0].body.client_message_id, posts[1].body.client_message_id);
});


test("definite send rejections show safe specific guidance and never auto-post", async () => {
  const cases = [
    {
      status: 409,
      reason: "miniapp_run_active",
      message: "Another response is still running. Wait for it to finish, then tap Send again. Nothing was resent.",
    },
    {
      status: 429,
      reason: "miniapp_rate_limited",
      message: "Too many requests. Wait a moment, then tap Send again. Nothing was resent.",
    },
    {
      status: 401,
      reason: "miniapp_unauthorized",
      message: "Your session expired. Reopen Agentonomy from Telegram. Your draft is safe.",
    },
    {
      status: 403,
      reason: "miniapp_forbidden",
      message: "This request could not be verified. Reopen Agentonomy from Telegram. Your draft is safe.",
    },
    {
      status: 503,
      reason: "miniapp_unavailable",
      message: "Agentonomy is temporarily unavailable. Your draft is safe. Nothing was resent.",
    },
  ];

  for (const item of cases) {
    const harness = createHarness(({ method, url }) => {
      if (method === "GET" && url === "/miniapp/api/chat") return { body: chatBody() };
      if (method === "POST" && url === "/miniapp/api/chat/messages") {
        return { status: item.status, body: { detail: item.reason } };
      }
      throw new Error(`unexpected ${method} ${url}`);
    }, { sessionStorage: new FakeStorage({ [STORAGE_KEYS.csrf]: "csrf" }) });
    await harness.app.start();
    harness.document.getElementById("miniapp-input").value = "one attempt";

    await harness.app.sendCurrentMessage();

    assert.equal(
      harness.calls.filter((call) => call.method === "POST").length,
      1,
      item.reason,
    );
    assert.equal(
      harness.document.getElementById("miniapp-status").textContent,
      item.message,
      item.reason,
    );
    assert.doesNotMatch(
      harness.document.getElementById("miniapp-status").textContent,
      /miniapp_/,
    );
  }
});


test("an ambiguous send checks run status and never automatically posts again", async () => {
  const clientId = "11111111-2222-4333-8444-555555555555";
  const harness = createHarness(({ method, url }) => {
    if (method === "GET" && url === "/miniapp/api/chat") return { body: chatBody() };
    if (method === "POST" && url === "/miniapp/api/chat/messages") {
      return { status: 503, body: { detail: "miniapp_message_unknown" } };
    }
    if (method === "GET" && url === `/miniapp/api/chat/messages/${clientId}/run`) {
      return { body: { client_message_id: clientId, status: "running" } };
    }
    throw new Error(`unexpected ${method} ${url}`);
  }, { sessionStorage: new FakeStorage({ [STORAGE_KEYS.csrf]: "csrf" }) });
  await harness.app.start();
  harness.document.getElementById("miniapp-input").value = "one safe attempt";

  await harness.app.sendCurrentMessage();

  assert.equal(
    harness.calls.filter((call) => call.method === "POST").length,
    1,
  );
  assert.equal(
    harness.calls.filter((call) => call.method === "GET" && call.url.endsWith("/run")).length,
    1,
  );
  assert.equal(FakeEventSource.instances.length, 0);
  assert.equal(harness.scheduledCount(), 1);

  await harness.app.sendCurrentMessage();
  assert.equal(
    harness.calls.filter((call) => call.method === "POST").length,
    1,
  );
  assert.equal(
    storedValue(harness.localStorage, STORAGE_KEYS.currentClientMessage),
    clientId,
  );
});


test("an unknown message keeps its id status-only even when lookup returns not found", async () => {
  const clientId = "11111111-2222-4333-8444-555555555555";
  const harness = createHarness(({ method, url }) => {
    if (method === "GET" && url === "/miniapp/api/chat") return { body: chatBody() };
    if (method === "POST" && url === "/miniapp/api/chat/messages") {
      return { status: 503, body: { detail: "miniapp_message_unknown" } };
    }
    if (method === "GET" && url.endsWith("/run")) {
      return { status: 404, body: { detail: "miniapp_message_unknown" } };
    }
    throw new Error(`unexpected ${method} ${url}`);
  }, { sessionStorage: new FakeStorage({ [STORAGE_KEYS.csrf]: "csrf" }) });
  await harness.app.start();
  harness.document.getElementById("miniapp-input").value = "status only";

  await harness.app.sendCurrentMessage();
  await harness.app.sendCurrentMessage();
  await harness.app.sendCurrentMessage();

  assert.equal(
    harness.calls.filter((call) => call.method === "POST").length,
    1,
  );
  assert.equal(
    harness.calls.filter((call) => call.method === "GET" && call.url.endsWith("/run")).length,
    3,
  );
  assert.equal(
    storedValue(harness.localStorage, STORAGE_KEYS.currentClientMessage),
    clientId,
  );
});


test("startup clears a lease-less run id but preserves draft until one explicit fresh send", async () => {
  const staleId = "11111111-2222-4333-8444-555555555555";
  const freshId = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee";
  let uuidCalls = 0;
  const localStorage = new FakeStorage({
    [STORAGE_KEYS.currentClientMessage]: scoped(staleId),
    [STORAGE_KEYS.draft]: scoped("preserve this draft"),
  });
  const harness = createHarness(({ method, url }) => {
    if (method === "GET" && url === "/miniapp/api/chat") {
      return { body: chatBody() };
    }
    if (method === "GET" && url === `/miniapp/api/chat/messages/${staleId}/run`) {
      return { status: 404, body: { detail: "miniapp_not_found" } };
    }
    if (method === "POST" && url === "/miniapp/api/chat/messages") {
      return {
        status: 202,
        body: { client_message_id: freshId, status: "accepted" },
      };
    }
    throw new Error(`unexpected ${method} ${url}`);
  }, {
    localStorage,
    randomUUID: () => {
      uuidCalls += 1;
      return freshId;
    },
    sessionStorage: new FakeStorage({ [STORAGE_KEYS.csrf]: "csrf" }),
  });

  await harness.app.start();

  assert.equal(
    harness.calls.filter((call) => call.method === "POST").length,
    0,
  );
  assert.equal(
    harness.calls.filter((call) => call.method === "GET" && call.url.endsWith("/run")).length,
    1,
  );
  assert.equal(localStorage.getItem(STORAGE_KEYS.currentClientMessage), null);
  assert.equal(
    harness.document.getElementById("miniapp-input").value,
    "preserve this draft",
  );
  assert.equal(uuidCalls, 0);

  await harness.app.sendCurrentMessage();

  const posts = harness.calls.filter((call) => (
    call.method === "POST" && call.url === "/miniapp/api/chat/messages"
  ));
  assert.equal(posts.length, 1);
  assert.equal(posts[0].body.client_message_id, freshId);
  assert.equal(uuidCalls, 1);
});


test("run lookup 503 keeps the scoped id and every explicit retry remains GET-only", async () => {
  const clientId = "11111111-2222-4333-8444-555555555555";
  const localStorage = new FakeStorage({
    [STORAGE_KEYS.currentClientMessage]: scoped(clientId),
    [STORAGE_KEYS.draft]: scoped("do not resend this draft"),
  });
  const harness = createHarness(({ method, url }) => {
    if (method === "GET" && url === "/miniapp/api/chat") {
      return { body: chatBody() };
    }
    if (method === "GET" && url === `/miniapp/api/chat/messages/${clientId}/run`) {
      return { status: 503, body: { detail: "miniapp_unavailable" } };
    }
    throw new Error(`unexpected ${method} ${url}`);
  }, {
    localStorage,
    sessionStorage: new FakeStorage({ [STORAGE_KEYS.csrf]: "csrf" }),
  });

  await harness.app.start();
  await harness.app.sendCurrentMessage();
  await harness.app.sendCurrentMessage();

  assert.equal(
    harness.calls.filter((call) => call.method === "POST").length,
    0,
  );
  assert.equal(
    harness.calls.filter((call) => call.method === "GET" && call.url.endsWith("/run")).length,
    3,
  );
  assert.equal(
    storedValue(localStorage, STORAGE_KEYS.currentClientMessage),
    clientId,
  );
  assert.equal(
    harness.document.getElementById("miniapp-input").value,
    "do not resend this draft",
  );
  assert.equal(harness.scheduledCount(), 1);
});


test("blank deltas create no turn and visible deltas share one streaming turn", async () => {
  const clientId = "11111111-2222-4333-8444-555555555555";
  const harness = createHarness(({ method, url }) => {
    if (method === "GET" && url === "/miniapp/api/chat") return { body: chatBody() };
    if (method === "POST" && url === "/miniapp/api/chat/messages") {
      return {
        status: 202,
        body: { client_message_id: clientId, status: "accepted" },
      };
    }
    throw new Error(`unexpected ${method} ${url}`);
  }, { sessionStorage: new FakeStorage({ [STORAGE_KEYS.csrf]: "csrf" }) });
  await harness.app.start();
  harness.document.getElementById("miniapp-input").value = "question";
  await harness.app.sendCurrentMessage();
  const transcript = harness.document.getElementById("miniapp-transcript");
  const countBeforeDelta = transcript.children.length;
  const source = FakeEventSource.instances[0];

  source.emit("message.delta", { delta: "" });
  source.emit("message.delta", { delta: "   " });
  assert.equal(transcript.children.length, countBeforeDelta);

  source.emit("message.delta", { delta: "Hello" });
  source.emit("message.delta", { delta: " world" });

  assert.equal(transcript.children.length, countBeforeDelta + 1);
  assert.equal(
    transcript.children.at(-1).children[1].textContent,
    "Hello world",
  );
});


test("tool events update one deduplicated progress region and collapse at terminal state", async () => {
  const clientIds = [
    "11111111-2222-4333-8444-555555555555",
    "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee",
  ];
  let chatLoads = 0;
  let postCount = 0;
  const harness = createHarness(({ method, url }) => {
    if (method === "GET" && url === "/miniapp/api/chat") {
      chatLoads += 1;
      return {
        body: chatLoads === 1
          ? chatBody()
          : chatBody([
            { id: 1, role: "user", content: "question", timestamp: 1 },
            { id: 2, role: "assistant", content: "answer", timestamp: 2 },
          ]),
      };
    }
    if (method === "POST" && url === "/miniapp/api/chat/messages") {
      const clientMessageId = clientIds[postCount];
      postCount += 1;
      return {
        status: 202,
        body: { client_message_id: clientMessageId, status: "accepted" },
      };
    }
    if (method === "GET" && url.endsWith("/run")) {
      return {
        body: { client_message_id: clientIds[0], status: "completed" },
      };
    }
    throw new Error(`unexpected ${method} ${url}`);
  }, {
    randomUUID: () => clientIds[postCount],
    sessionStorage: new FakeStorage({ [STORAGE_KEYS.csrf]: "csrf" }),
  });
  await harness.app.start();
  harness.document.getElementById("miniapp-input").value = "question";
  await harness.app.sendCurrentMessage();
  const transcript = harness.document.getElementById("miniapp-transcript");
  const transcriptCount = transcript.children.length;
  const source = FakeEventSource.instances[0];
  const progress = harness.document.getElementById("miniapp-tool-progress");
  const toggle = harness.document.getElementById("miniapp-tool-progress-toggle");
  const summary = harness.document.getElementById("miniapp-tool-progress-summary");
  const list = harness.document.getElementById("miniapp-tool-progress-list");

  source.emit("tool.started", { tool: "account_status" });
  source.emit("tool.started", { tool: "account_status" });
  source.emit("tool.completed", { tool: "account_status" });
  source.emit("tool.started", { tool: "market_scan" });

  assert.equal(transcript.children.length, transcriptCount);
  assert.equal(progress.hidden, false);
  assert.equal(toggle.getAttribute("aria-expanded"), "true");
  assert.equal(list.hidden, false);
  assert.equal(list.children.length, 2);
  assert.match(list.children[0].textContent, /account_status.*Completed/);
  assert.match(list.children[1].textContent, /market_scan.*Running/);
  assert.equal(summary.textContent, "Working · 2 operations");

  await harness.app.handleStreamDisconnect(clientIds[0]);

  assert.equal(summary.textContent, "Run completed · 2 operations");
  assert.equal(toggle.getAttribute("aria-expanded"), "false");
  assert.equal(list.hidden, true);
  await toggle.dispatch("click");
  assert.equal(toggle.getAttribute("aria-expanded"), "true");
  assert.equal(list.hidden, false);

  harness.document.getElementById("miniapp-input").value = "next question";
  await harness.app.sendCurrentMessage();

  assert.equal(progress.hidden, true);
  assert.equal(list.children.length, 0);
});


for (const toolName of [
  "prepare_polymarket_funding_ui",
  "mcp__clink_node__prepare_polymarket_funding_ui",
]) {
  test(`exact ${toolName} completion records this message without funding`, async () => {
    const clientId = "11111111-2222-4333-8444-555555555555";
    const harness = createHarness(({ method, url }) => {
      if (method === "GET" && url === "/miniapp/api/chat") {
        return { body: chatBody() };
      }
      if (method === "POST" && url === "/miniapp/api/chat/messages") {
        return {
          status: 202,
          body: { client_message_id: clientId, status: "accepted" },
        };
      }
      throw new Error(`unexpected ${method} ${url}`);
    }, { sessionStorage: new FakeStorage({ [STORAGE_KEYS.csrf]: "csrf" }) });
    await harness.app.start();
    harness.document.getElementById("miniapp-input").value = "fund 1 USDC";
    await harness.app.sendCurrentMessage();

    FakeEventSource.instances[0].emit("tool.completed", { tool: toolName });

    assert.equal(
      storedValue(harness.localStorage, STORAGE_KEYS.fundingPreparedMessage),
      clientId,
    );
    assert.equal(
      harness.calls.some((call) =>
        call.url.startsWith("/miniapp/api/operations/polymarket/funding")
      ),
      false,
    );
  });
}


for (const [message, expectedAmount] of [
  ["充值3u", "3.000000"],
  ["充值 1 USDC", "1.000000"],
  ["确认充值 1 USDC", "1.000000"],
  ["给 Polymarket 充值 1 USDC", "1.000000"],
  ["fund 1 USDC", "1.000000"],
  ["please fund 1 USDC", "1.000000"],
  ["确认创建并执行本次 1 USDC Polymarket funding operation", "1.000000"],
  ["不要充值 1 USDC", null],
  ["禁止充值 1 USDC", null],
  ["勿充值 1 USDC", null],
  ["避免 fund 1 USDC", null],
  ["do not fund 1 USDC", null],
  ["balance is 1 USDC", null],
  ["怎么充值 1 USDC？", null],
  ["如何充值 1 USDC", null],
  ["how do I fund 1 USDC?", null],
  ["充值 -1 USDC", null],
  ["充值 - 1 USDC", null],
  ["充值 −1 USDC", null],
  ["充值 －1 USDC", null],
  ["充值 ﹣1 USDC", null],
  ["充值﹣1 USDC", null],
  ["充值 ‐1 USDC", null],
  ["充值 ‑1 USDC", null],
  ["充值 –1 USDC", null],
  ["充值 —1 USDC", null],
  ["充值 ﹘1 USDC", null],
  ["充值 1e3 USDC", null],
  ["充值 1,500 USDC", null],
  ["充值 1，500 USDC", null],
  ["充值 1 500 USDC", null],
  ["充值 1'500 USDC", null],
  ["充值 1,5 USDC", null],
  ["充值 1 USDC 再充值 2u", null],
  ["充值 1 USDC 再充值 −2u", null],
  ["充值 1.0000000 USDC", null],
  ["充值 1USDC2", null],
  ["充值 1", null],
]) {
  test(`funding amount binding is exact for message: ${message}`, async () => {
    const clientId = "11111111-2222-4333-8444-555555555555";
    const harness = createHarness(({ method, url }) => {
      if (method === "GET" && url === "/miniapp/api/chat") {
        return { body: chatBody() };
      }
      if (method === "POST" && url === "/miniapp/api/chat/messages") {
        return {
          status: 202,
          body: { client_message_id: clientId, status: "accepted" },
        };
      }
      throw new Error(`unexpected ${method} ${url}`);
    }, { sessionStorage: new FakeStorage({ [STORAGE_KEYS.csrf]: "csrf" }) });
    await harness.app.start();
    harness.document.getElementById("miniapp-input").value = message;

    await harness.app.sendCurrentMessage();

    const stored = storedValue(
      harness.localStorage,
      STORAGE_KEYS.fundingMessageAmount,
    );
    assert.deepEqual(
      stored === null ? null : JSON.parse(stored),
      expectedAmount === null
        ? null
        : { client_message_id: clientId, amount: expectedAmount },
    );
  });
}


test("completed current funding intent executes once without a second click", async () => {
  const clientId = "11111111-2222-4333-8444-555555555555";
  let chatLoads = 0;
  const harness = createHarness(({ method, url, body }) => {
    if (method === "GET" && url === "/miniapp/api/chat") {
      chatLoads += 1;
      return chatLoads === 1
        ? { body: chatBody() }
        : { status: 503, body: { detail: "miniapp_unavailable" } };
    }
    if (method === "POST" && url === "/miniapp/api/chat/messages") {
      return {
        status: 202,
        body: { client_message_id: clientId, status: "accepted" },
      };
    }
    if (method === "GET" && url === `/miniapp/api/chat/messages/${clientId}/run`) {
      return {
        body: {
          client_message_id: clientId,
          status: "completed",
          has_output: true,
          has_error: false,
          output: (
            "充值入口：`" +
            "https://www.agentonomy.xyz/miniapp/#funding=3.000000`）"
          ),
        },
      };
    }
    if (method === "POST" && url === "/miniapp/api/operations/polymarket/funding") {
      assert.deepEqual(body, {
        amount_usdc: "3.000000",
        idempotency_key: clientId,
      });
      return {
        status: 201,
        body: fundingBody({ amount_usdc: "3.000000" }),
      };
    }
    if (
      method === "POST" &&
      url === "/miniapp/api/operations/polymarket/funding/pm_funding_1/continue"
    ) {
      return {
        body: fundingBody({
          status: "finalized",
          amount_usdc: "3.000000",
          chain_status: "confirmed",
          bridge_status: "credited",
          buying_power_status: "credited",
          next_action: "complete",
        }),
      };
    }
    throw new Error(`unexpected ${method} ${url}`);
  }, { sessionStorage: new FakeStorage({ [STORAGE_KEYS.csrf]: "csrf" }) });
  await harness.app.start();
  harness.document.getElementById("miniapp-input").value = "充值3u";
  await harness.app.sendCurrentMessage();
  FakeEventSource.instances[0].emit("tool.completed", {
    tool: "prepare_polymarket_funding_ui",
  });

  assert.equal(
    harness.calls.filter((call) =>
      call.url.startsWith("/miniapp/api/operations/polymarket/funding")
    ).length,
    0,
  );

  await harness.app.handleStreamDisconnect(clientId);

  assert.deepEqual(
    harness.calls.filter((call) =>
      call.url.startsWith("/miniapp/api/operations/polymarket/funding")
    ).map((call) => `${call.method} ${call.url}`),
    [
      "POST /miniapp/api/operations/polymarket/funding",
      "POST /miniapp/api/operations/polymarket/funding/pm_funding_1/continue",
    ],
  );
  assert.equal(
    harness.document.getElementById("miniapp-operations").hidden,
    false,
  );
  assert.equal(
    storedValue(harness.localStorage, STORAGE_KEYS.fundingPreparedMessage),
    null,
  );
});


test("lookalike, generic, and stale tool events never prepare funding", async () => {
  const clientId = "11111111-2222-4333-8444-555555555555";
  const harness = createHarness(({ method, url }) => {
    if (method === "GET" && url === "/miniapp/api/chat") {
      return { body: chatBody() };
    }
    if (method === "POST" && url === "/miniapp/api/chat/messages") {
      return {
        status: 202,
        body: { client_message_id: clientId, status: "accepted" },
      };
    }
    throw new Error(`unexpected ${method} ${url}`);
  }, { sessionStorage: new FakeStorage({ [STORAGE_KEYS.csrf]: "csrf" }) });
  await harness.app.start();
  harness.document.getElementById("miniapp-input").value = "fund 1 USDC";
  await harness.app.sendCurrentMessage();
  const source = FakeEventSource.instances[0];

  for (const tool of [
    "xprepare_polymarket_funding_ui",
    "prepare_polymarket_funding_ui_suffix",
    "mcp__other__prepare_polymarket_funding_ui",
    " prepare_polymarket_funding_ui",
  ]) source.emit("tool.completed", { tool });
  source.emit("tool.started", { tool: "prepare_polymarket_funding_ui" });
  source.emit("tool", {
    tool: "prepare_polymarket_funding_ui",
    status: "completed",
  });
  assert.equal(
    storedValue(harness.localStorage, STORAGE_KEYS.fundingPreparedMessage),
    null,
  );

  harness.localStorage.removeItem(STORAGE_KEYS.currentClientMessage);
  source.emit("tool.completed", { tool: "prepare_polymarket_funding_ui" });
  assert.equal(
    storedValue(harness.localStorage, STORAGE_KEYS.fundingPreparedMessage),
    null,
  );
});


async function completeRejectedFundingIntent({
  messages,
  emitPrepare = true,
  runStatus = "completed",
  hasOutput = true,
  hasError = false,
  inputText = "fund 1 USDC",
  reportedClientId = null,
}) {
  const clientId = "11111111-2222-4333-8444-555555555555";
  let chatLoads = 0;
  const harness = createHarness(({ method, url }) => {
    if (method === "GET" && url === "/miniapp/api/chat") {
      chatLoads += 1;
      return { body: chatLoads === 1 ? chatBody() : chatBody(messages) };
    }
    if (method === "POST" && url === "/miniapp/api/chat/messages") {
      return {
        status: 202,
        body: { client_message_id: clientId, status: "accepted" },
      };
    }
    if (method === "GET" && url === `/miniapp/api/chat/messages/${clientId}/run`) {
      const assistantOutput = [...messages].reverse().find(
        (message) => message.role === "assistant",
      )?.content;
      return {
        body: {
          client_message_id: reportedClientId || clientId,
          status: runStatus,
          has_output: hasOutput,
          has_error: hasError,
          output: hasOutput ? assistantOutput : null,
        },
      };
    }
    throw new Error(`unexpected ${method} ${url}`);
  }, { sessionStorage: new FakeStorage({ [STORAGE_KEYS.csrf]: "csrf" }) });
  await harness.app.start();
  harness.document.getElementById("miniapp-input").value = inputText;
  await harness.app.sendCurrentMessage();
  if (emitPrepare) {
    FakeEventSource.instances[0].emit("tool.completed", {
      tool: "prepare_polymarket_funding_ui",
    });
  }
  await harness.app.handleStreamDisconnect(clientId);
  return harness;
}


for (const rejected of [
  {
    name: "completed run carrying an error",
    hasError: true,
    messages: [
      {
        role: "assistant",
        content: "https://www.agentonomy.xyz/miniapp/#funding=1.000000",
      },
    ],
  },
  {
    name: "URL without prepare evidence",
    emitPrepare: false,
    messages: [
      { role: "user", content: "fund 1", timestamp: 1 },
      {
        role: "assistant",
        content: "https://www.agentonomy.xyz/miniapp/#funding=1.000000",
        timestamp: 2,
      },
    ],
  },
  {
    name: "prepare evidence without a URL",
    messages: [
      { role: "user", content: "fund 1", timestamp: 1 },
      { role: "assistant", content: "Funding is ready.", timestamp: 2 },
    ],
  },
  {
    name: "two URLs",
    messages: [
      { role: "user", content: "fund 1", timestamp: 1 },
      {
        role: "assistant",
        content: (
          "https://www.agentonomy.xyz/miniapp/#funding=1.000000 " +
          "https://www.agentonomy.xyz/miniapp/#funding=1.000000"
        ),
        timestamp: 2,
      },
    ],
  },
  {
    name: "mixed-case extra URL scheme",
    messages: [
      {
        role: "assistant",
        content: (
          "https://www.agentonomy.xyz/miniapp/#funding=1.000000 " +
          "HTTPS://extra.example/path"
        ),
      },
    ],
  },
  {
    name: "HTML link",
    messages: [
      {
        role: "assistant",
        content: (
          "<a href=\"https://www.agentonomy.xyz/miniapp/" +
          "#funding=1.000000\">fund</a>"
        ),
      },
    ],
  },
  {
    name: "cross-origin URL",
    messages: [
      { role: "user", content: "fund 1", timestamp: 1 },
      {
        role: "assistant",
        content: "https://evil.example/miniapp/#funding=1.000000",
        timestamp: 2,
      },
    ],
  },
  {
    name: "credential URL",
    messages: [
      { role: "user", content: "fund 1", timestamp: 1 },
      {
        role: "assistant",
        content: "https://user@www.agentonomy.xyz/miniapp/#funding=1.000000",
        timestamp: 2,
      },
    ],
  },
  {
    name: "empty userinfo URL",
    messages: [
      { role: "user", content: "fund 1", timestamp: 1 },
      {
        role: "assistant",
        content: "https://@www.agentonomy.xyz/miniapp/#funding=1.000000",
        timestamp: 2,
      },
    ],
  },
  {
    name: "query URL",
    messages: [
      { role: "user", content: "fund 1", timestamp: 1 },
      {
        role: "assistant",
        content: "https://www.agentonomy.xyz/miniapp/?x=1#funding=1.000000",
        timestamp: 2,
      },
    ],
  },
  {
    name: "empty query delimiter",
    messages: [
      { role: "user", content: "fund 1", timestamp: 1 },
      {
        role: "assistant",
        content: "https://www.agentonomy.xyz/miniapp/?#funding=1.000000",
        timestamp: 2,
      },
    ],
  },
  {
    name: "wrong path URL",
    messages: [
      { role: "user", content: "fund 1", timestamp: 1 },
      {
        role: "assistant",
        content: "https://www.agentonomy.xyz/miniapp#funding=1.000000",
        timestamp: 2,
      },
    ],
  },
  {
    name: "extra fragment key",
    messages: [
      { role: "user", content: "fund 1", timestamp: 1 },
      {
        role: "assistant",
        content: (
          "https://www.agentonomy.xyz/miniapp/" +
          "#funding=1.000000&extra=true"
        ),
        timestamp: 2,
      },
    ],
  },
  {
    name: "percent-encoded amount",
    messages: [
      { role: "user", content: "fund 1", timestamp: 1 },
      {
        role: "assistant",
        content: "https://www.agentonomy.xyz/miniapp/#funding=1%2E000000",
        timestamp: 2,
      },
    ],
  },
  ...[
    "0.000000", "-1.000000", "1e0", "1", "1.00000", "1.0000000", "01.000000",
  ].map((amount) => ({
    name: `noncanonical amount ${amount}`,
    messages: [
      { role: "user", content: "fund 1", timestamp: 1 },
      {
        role: "assistant",
        content: `https://www.agentonomy.xyz/miniapp/#funding=${amount}`,
        timestamp: 2,
      },
    ],
  })),
  {
    name: "URL only belongs to an older assistant turn",
    messages: [
      {
        role: "assistant",
        content: "https://www.agentonomy.xyz/miniapp/#funding=1.000000",
        timestamp: 1,
      },
      { role: "user", content: "new request", timestamp: 2 },
      { role: "assistant", content: "No funding link for this turn.", timestamp: 3 },
    ],
  },
  {
    name: "completed run without authoritative output",
    hasOutput: false,
    messages: [
      { role: "user", content: "fund 1", timestamp: 1 },
      {
        role: "assistant",
        content: "https://www.agentonomy.xyz/miniapp/#funding=1.000000",
        timestamp: 2,
      },
    ],
  },
  {
    name: "failed run",
    runStatus: "failed",
    messages: [
      { role: "user", content: "fund 1", timestamp: 1 },
      {
        role: "assistant",
        content: "https://www.agentonomy.xyz/miniapp/#funding=1.000000",
        timestamp: 2,
      },
    ],
  },
  {
    name: "output amount differs from the user message",
    inputText: "fund 2 USDC",
    messages: [
      {
        role: "assistant",
        content: "https://www.agentonomy.xyz/miniapp/#funding=1.000000",
      },
    ],
  },
  {
    name: "output reported for another client message id",
    reportedClientId: "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee",
    messages: [
      {
        role: "assistant",
        content: "https://www.agentonomy.xyz/miniapp/#funding=1.000000",
      },
    ],
  },
  ...[
    "fund -1 USDC",
    "fund 1e3 USDC",
    "fund 1 USDC and 2u",
    "fund 1.0000000 USDC",
    "fund 1",
  ].map((inputText) => ({
    name: `unsafe user amount ${inputText}`,
    inputText,
    messages: [
      {
        role: "assistant",
        content: "https://www.agentonomy.xyz/miniapp/#funding=1.000000",
      },
    ],
  })),
]) {
  test(`completed funding intent rejects ${rejected.name}`, async () => {
    const harness = await completeRejectedFundingIntent(rejected);
    assert.equal(
      harness.calls.some((call) =>
        call.url.startsWith("/miniapp/api/operations/polymarket/funding")
      ),
      false,
    );
    assert.equal(
      storedValue(harness.localStorage, STORAGE_KEYS.fundingPreparedMessage),
      null,
    );
  });
}


test("run 404 clears matching prepared funding evidence", async () => {
  const clientId = "11111111-2222-4333-8444-555555555555";
  const harness = createHarness(({ method, url }) => {
    if (method === "GET" && url === "/miniapp/api/chat") {
      return { body: chatBody() };
    }
    if (method === "POST" && url === "/miniapp/api/chat/messages") {
      return {
        status: 202,
        body: { client_message_id: clientId, status: "accepted" },
      };
    }
    if (method === "GET" && url === `/miniapp/api/chat/messages/${clientId}/run`) {
      return { status: 404, body: { detail: "miniapp_not_found" } };
    }
    throw new Error(`unexpected ${method} ${url}`);
  }, { sessionStorage: new FakeStorage({ [STORAGE_KEYS.csrf]: "csrf" }) });
  await harness.app.start();
  harness.document.getElementById("miniapp-input").value = "fund 1 USDC";
  await harness.app.sendCurrentMessage();
  FakeEventSource.instances[0].emit("tool.completed", {
    tool: "prepare_polymarket_funding_ui",
  });

  await harness.app.handleStreamDisconnect(clientId);

  assert.equal(
    storedValue(harness.localStorage, STORAGE_KEYS.fundingPreparedMessage),
    null,
  );
  assert.equal(
    storedValue(harness.localStorage, STORAGE_KEYS.fundingMessageAmount),
    null,
  );
  assert.equal(
    harness.calls.some((call) =>
      call.url.startsWith("/miniapp/api/operations/polymarket/funding")
    ),
    false,
  );
});


test("completed run without safe output clears prepared funding evidence", async () => {
  const clientId = "11111111-2222-4333-8444-555555555555";
  let chatLoads = 0;
  const harness = createHarness(({ method, url }) => {
    if (method === "GET" && url === "/miniapp/api/chat") {
      chatLoads += 1;
      return chatLoads === 1
        ? { body: chatBody() }
        : { status: 503, body: { detail: "miniapp_unavailable" } };
    }
    if (method === "POST" && url === "/miniapp/api/chat/messages") {
      return {
        status: 202,
        body: { client_message_id: clientId, status: "accepted" },
      };
    }
    if (method === "GET" && url.endsWith("/run")) {
      return {
        body: {
          client_message_id: clientId,
          status: "completed",
          has_output: true,
          has_error: false,
        },
      };
    }
    throw new Error(`unexpected ${method} ${url}`);
  }, { sessionStorage: new FakeStorage({ [STORAGE_KEYS.csrf]: "csrf" }) });
  await harness.app.start();
  harness.document.getElementById("miniapp-input").value = "fund 1 USDC";
  await harness.app.sendCurrentMessage();
  FakeEventSource.instances[0].emit("tool.completed", {
    tool: "prepare_polymarket_funding_ui",
  });

  await harness.app.handleStreamDisconnect(clientId);

  assert.equal(
    storedValue(harness.localStorage, STORAGE_KEYS.fundingPreparedMessage),
    null,
  );
  assert.equal(
    storedValue(harness.localStorage, STORAGE_KEYS.fundingMessageAmount),
    null,
  );
});


test("duplicate recovery of one prepared message creates only one operation", async () => {
  const clientId = "11111111-2222-4333-8444-555555555555";
  const runGate = deferred();
  let chatLoads = 0;
  let createPosts = 0;
  let continuePosts = 0;
  const harness = createHarness(({ method, url }) => {
    if (method === "GET" && url === "/miniapp/api/chat") {
      chatLoads += 1;
      return {
        body: chatLoads === 1
          ? chatBody()
          : chatBody([
            { role: "user", content: "fund 1", timestamp: 1 },
            {
              role: "assistant",
              content: "https://www.agentonomy.xyz/miniapp/#funding=1.000000",
              timestamp: 2,
            },
          ]),
      };
    }
    if (method === "POST" && url === "/miniapp/api/chat/messages") {
      return {
        status: 202,
        body: { client_message_id: clientId, status: "accepted" },
      };
    }
    if (method === "GET" && url.endsWith("/run")) return runGate.promise;
    if (method === "POST" && url === "/miniapp/api/operations/polymarket/funding") {
      createPosts += 1;
      return { status: 201, body: fundingBody({ amount_usdc: "1.000000" }) };
    }
    if (method === "POST" && url.endsWith("/pm_funding_1/continue")) {
      continuePosts += 1;
      return {
        body: fundingBody({
          status: "finalized",
          amount_usdc: "1.000000",
          next_action: "complete",
        }),
      };
    }
    throw new Error(`unexpected ${method} ${url}`);
  }, { sessionStorage: new FakeStorage({ [STORAGE_KEYS.csrf]: "csrf" }) });
  await harness.app.start();
  harness.document.getElementById("miniapp-input").value = "fund 1 USDC";
  await harness.app.sendCurrentMessage();
  const source = FakeEventSource.instances[0];
  source.emit("tool.completed", { tool: "prepare_polymarket_funding_ui" });
  source.emit("tool.completed", { tool: "prepare_polymarket_funding_ui" });

  const first = harness.app.handleStreamDisconnect(clientId);
  const duplicate = harness.app.handleStreamDisconnect(clientId);
  runGate.resolve({
    body: {
      client_message_id: clientId,
      status: "completed",
      has_output: true,
      has_error: false,
      output: "https://www.agentonomy.xyz/miniapp/#funding=1.000000",
    },
  });
  await Promise.all([first, duplicate]);
  await harness.app.handleStreamDisconnect(clientId);

  assert.equal(createPosts, 1);
  assert.equal(continuePosts, 1);
});


test("prepared funding resumes an existing nonterminal operation without replacing intent", async () => {
  const clientId = "11111111-2222-4333-8444-555555555555";
  const localStorage = new FakeStorage({
    [STORAGE_KEYS.fundingAmount]: scoped("0.500000"),
    [STORAGE_KEYS.fundingIdempotency]: scoped("existing-intent"),
    [STORAGE_KEYS.fundingOperation]: scoped("pm_funding_existing"),
  });
  let chatLoads = 0;
  let statusGets = 0;
  let continuePosts = 0;
  const harness = createHarness(({ method, url }) => {
    if (method === "GET" && url === "/miniapp/api/chat") {
      chatLoads += 1;
      return {
        body: chatLoads === 1
          ? chatBody()
          : chatBody([
            { role: "user", content: "fund 2", timestamp: 1 },
            {
              role: "assistant",
              content: "https://www.agentonomy.xyz/miniapp/#funding=2.000000",
              timestamp: 2,
            },
          ]),
      };
    }
    if (method === "POST" && url === "/miniapp/api/chat/messages") {
      return {
        status: 202,
        body: { client_message_id: clientId, status: "accepted" },
      };
    }
    if (method === "GET" && url.endsWith("/run")) {
      return {
        body: {
          client_message_id: clientId,
          status: "completed",
          has_output: true,
          has_error: false,
          output: "https://www.agentonomy.xyz/miniapp/#funding=2.000000",
        },
      };
    }
    if (
      method === "GET" &&
      url === "/miniapp/api/operations/polymarket/funding/pm_funding_existing"
    ) {
      statusGets += 1;
      return {
        body: fundingBody({
          operation_id: "pm_funding_existing",
          amount_usdc: "0.500000",
          status: statusGets === 1 ? "manual_review" : "created",
          next_action: statusGets === 1 ? "manual_review" : "confirm",
        }),
      };
    }
    if (
      method === "POST" &&
      url === "/miniapp/api/operations/polymarket/funding/pm_funding_existing/continue"
    ) {
      continuePosts += 1;
      return {
        body: fundingBody({
          operation_id: "pm_funding_existing",
          amount_usdc: "0.500000",
          status: "finalized",
          next_action: "complete",
        }),
      };
    }
    throw new Error(`unexpected ${method} ${url}`);
  }, {
    localStorage,
    sessionStorage: new FakeStorage({ [STORAGE_KEYS.csrf]: "csrf" }),
  });
  await harness.app.start();
  harness.document.getElementById("miniapp-input").value = "fund 2 USDC";
  await harness.app.sendCurrentMessage();
  FakeEventSource.instances[0].emit("tool.completed", {
    tool: "prepare_polymarket_funding_ui",
  });

  await harness.app.handleStreamDisconnect(clientId);

  assert.equal(statusGets, 2);
  assert.equal(continuePosts, 1);
  assert.equal(
    harness.calls.some((call) =>
      call.method === "POST" &&
      call.url === "/miniapp/api/operations/polymarket/funding"
    ),
    false,
  );
  assert.equal(
    storedValue(localStorage, STORAGE_KEYS.fundingAmount),
    "0.500000",
  );
  assert.equal(
    storedValue(localStorage, STORAGE_KEYS.fundingIdempotency),
    "existing-intent",
  );
});


test("a fresh GET-confirmed terminal operation is replaced by the new message intent", async () => {
  const clientId = "11111111-2222-4333-8444-555555555555";
  const localStorage = new FakeStorage({
    [STORAGE_KEYS.fundingAmount]: scoped("0.500000"),
    [STORAGE_KEYS.fundingIdempotency]: scoped("old-message"),
    [STORAGE_KEYS.fundingOperation]: scoped("pm_funding_old"),
  });
  let chatLoads = 0;
  let oldStatusGets = 0;
  let createPosts = 0;
  let continuePosts = 0;
  const harness = createHarness(({ method, url, body }) => {
    if (method === "GET" && url === "/miniapp/api/chat") {
      chatLoads += 1;
      return {
        body: chatLoads === 1
          ? chatBody()
          : chatBody([
            { role: "user", content: "fund 2", timestamp: 1 },
            {
              role: "assistant",
              content: "https://www.agentonomy.xyz/miniapp/#funding=2.000000",
              timestamp: 2,
            },
          ]),
      };
    }
    if (method === "POST" && url === "/miniapp/api/chat/messages") {
      return {
        status: 202,
        body: { client_message_id: clientId, status: "accepted" },
      };
    }
    if (method === "GET" && url.endsWith("/run")) {
      return {
        body: {
          client_message_id: clientId,
          status: "completed",
          has_output: true,
          has_error: false,
          output: "https://www.agentonomy.xyz/miniapp/#funding=2.000000",
        },
      };
    }
    if (
      method === "GET" &&
      url === "/miniapp/api/operations/polymarket/funding/pm_funding_old"
    ) {
      oldStatusGets += 1;
      return {
        body: fundingBody({
          operation_id: "pm_funding_old",
          amount_usdc: "0.500000",
          status: "finalized",
          next_action: "complete",
        }),
      };
    }
    if (method === "POST" && url === "/miniapp/api/operations/polymarket/funding") {
      createPosts += 1;
      assert.deepEqual(body, {
        amount_usdc: "2.000000",
        idempotency_key: clientId,
      });
      return {
        status: 201,
        body: fundingBody({
          operation_id: "pm_funding_new",
          amount_usdc: "2.000000",
        }),
      };
    }
    if (
      method === "POST" &&
      url === "/miniapp/api/operations/polymarket/funding/pm_funding_new/continue"
    ) {
      continuePosts += 1;
      return {
        body: fundingBody({
          operation_id: "pm_funding_new",
          amount_usdc: "2.000000",
          status: "finalized",
          next_action: "complete",
        }),
      };
    }
    throw new Error(`unexpected ${method} ${url}`);
  }, {
    localStorage,
    sessionStorage: new FakeStorage({ [STORAGE_KEYS.csrf]: "csrf" }),
  });
  await harness.app.start();
  harness.document.getElementById("miniapp-input").value = "fund 2 USDC";
  await harness.app.sendCurrentMessage();
  FakeEventSource.instances[0].emit("tool.completed", {
    tool: "prepare_polymarket_funding_ui",
  });

  await harness.app.handleStreamDisconnect(clientId);

  assert.equal(oldStatusGets, 2);
  assert.equal(createPosts, 1);
  assert.equal(continuePosts, 1);
  assert.equal(
    storedValue(localStorage, STORAGE_KEYS.fundingOperation),
    "pm_funding_new",
  );
  assert.equal(
    storedValue(localStorage, STORAGE_KEYS.fundingIdempotency),
    clientId,
  );
});


test("terminal next_action without its legal status never replaces an operation", async () => {
  const clientId = "11111111-2222-4333-8444-555555555555";
  const localStorage = new FakeStorage({
    [STORAGE_KEYS.fundingAmount]: scoped("0.500000"),
    [STORAGE_KEYS.fundingIdempotency]: scoped("old-message"),
    [STORAGE_KEYS.fundingOperation]: scoped("pm_funding_old"),
  });
  let statusGets = 0;
  const harness = createHarness(({ method, url }) => {
    if (method === "GET" && url === "/miniapp/api/chat") {
      return { body: chatBody() };
    }
    if (method === "POST" && url === "/miniapp/api/chat/messages") {
      return {
        status: 202,
        body: { client_message_id: clientId, status: "accepted" },
      };
    }
    if (method === "GET" && url.endsWith("/run")) {
      return {
        body: {
          client_message_id: clientId,
          status: "completed",
          has_output: true,
          has_error: false,
          output: "https://www.agentonomy.xyz/miniapp/#funding=2.000000",
        },
      };
    }
    if (
      method === "GET" &&
      url === "/miniapp/api/operations/polymarket/funding/pm_funding_old"
    ) {
      statusGets += 1;
      return {
        body: fundingBody({
          operation_id: "pm_funding_old",
          amount_usdc: "0.500000",
          status: "confirmed",
          next_action: "complete",
        }),
      };
    }
    throw new Error(`unexpected ${method} ${url}`);
  }, {
    localStorage,
    sessionStorage: new FakeStorage({ [STORAGE_KEYS.csrf]: "csrf" }),
  });
  await harness.app.start();
  harness.document.getElementById("miniapp-input").value = "fund 2 USDC";
  await harness.app.sendCurrentMessage();
  FakeEventSource.instances[0].emit("tool.completed", {
    tool: "prepare_polymarket_funding_ui",
  });

  await harness.app.handleStreamDisconnect(clientId);

  assert.equal(statusGets, 2);
  assert.equal(
    harness.calls.some((call) =>
      call.method === "POST" &&
      call.url.startsWith("/miniapp/api/operations/polymarket/funding")
    ),
    false,
  );
  assert.equal(
    storedValue(localStorage, STORAGE_KEYS.fundingOperation),
    "pm_funding_old",
  );
  assert.equal(
    storedValue(localStorage, STORAGE_KEYS.fundingIdempotency),
    "old-message",
  );
});


test("a terminal operation from the same message is not created again", async () => {
  const clientId = "11111111-2222-4333-8444-555555555555";
  const localStorage = new FakeStorage({
    [STORAGE_KEYS.fundingAmount]: scoped("1.000000"),
    [STORAGE_KEYS.fundingIdempotency]: scoped(clientId),
    [STORAGE_KEYS.fundingOperation]: scoped("pm_funding_same"),
  });
  let chatLoads = 0;
  let statusGets = 0;
  const harness = createHarness(({ method, url }) => {
    if (method === "GET" && url === "/miniapp/api/chat") {
      chatLoads += 1;
      return {
        body: chatLoads === 1
          ? chatBody()
          : chatBody([
            { role: "user", content: "fund 1", timestamp: 1 },
            {
              role: "assistant",
              content: "https://www.agentonomy.xyz/miniapp/#funding=1.000000",
              timestamp: 2,
            },
          ]),
      };
    }
    if (method === "POST" && url === "/miniapp/api/chat/messages") {
      return {
        status: 202,
        body: { client_message_id: clientId, status: "accepted" },
      };
    }
    if (method === "GET" && url.endsWith("/run")) {
      return {
        body: {
          client_message_id: clientId,
          status: "completed",
          has_output: true,
          has_error: false,
          output: "https://www.agentonomy.xyz/miniapp/#funding=1.000000",
        },
      };
    }
    if (
      method === "GET" &&
      url === "/miniapp/api/operations/polymarket/funding/pm_funding_same"
    ) {
      statusGets += 1;
      return {
        body: fundingBody({
          operation_id: "pm_funding_same",
          amount_usdc: "1.000000",
          status: "finalized",
          next_action: "complete",
        }),
      };
    }
    throw new Error(`unexpected ${method} ${url}`);
  }, {
    localStorage,
    sessionStorage: new FakeStorage({ [STORAGE_KEYS.csrf]: "csrf" }),
  });
  await harness.app.start();
  harness.document.getElementById("miniapp-input").value = "fund 1 USDC";
  await harness.app.sendCurrentMessage();
  FakeEventSource.instances[0].emit("tool.completed", {
    tool: "prepare_polymarket_funding_ui",
  });

  await harness.app.handleStreamDisconnect(clientId);

  assert.equal(statusGets, 2);
  assert.equal(
    harness.calls.some((call) =>
      call.method === "POST" &&
      call.url.startsWith("/miniapp/api/operations/polymarket/funding")
    ),
    false,
  );
  assert.equal(
    storedValue(localStorage, STORAGE_KEYS.fundingOperation),
    "pm_funding_same",
  );
});


test("a create-uncertain tombstone blocks conversational funding replay", async () => {
  const clientId = "11111111-2222-4333-8444-555555555555";
  const localStorage = new FakeStorage({
    [STORAGE_KEYS.fundingAmount]: scoped("0.500000"),
    [STORAGE_KEYS.fundingIdempotency]: scoped("old-unresolved-intent"),
    [STORAGE_KEYS.fundingCreateUncertain]: scoped("true"),
  });
  let chatLoads = 0;
  const harness = createHarness(({ method, url }) => {
    if (method === "GET" && url === "/miniapp/api/chat") {
      chatLoads += 1;
      return {
        body: chatLoads === 1
          ? chatBody()
          : chatBody([
            { role: "user", content: "fund 1", timestamp: 1 },
            {
              role: "assistant",
              content: "https://www.agentonomy.xyz/miniapp/#funding=1.000000",
              timestamp: 2,
            },
          ]),
      };
    }
    if (method === "POST" && url === "/miniapp/api/chat/messages") {
      return {
        status: 202,
        body: { client_message_id: clientId, status: "accepted" },
      };
    }
    if (method === "GET" && url.endsWith("/run")) {
      return {
        body: {
          client_message_id: clientId,
          status: "completed",
          has_output: true,
          has_error: false,
          output: "https://www.agentonomy.xyz/miniapp/#funding=1.000000",
        },
      };
    }
    throw new Error(`unexpected ${method} ${url}`);
  }, {
    localStorage,
    sessionStorage: new FakeStorage({ [STORAGE_KEYS.csrf]: "csrf" }),
  });
  await harness.app.start();
  harness.document.getElementById("miniapp-input").value = "fund 1 USDC";
  await harness.app.sendCurrentMessage();
  FakeEventSource.instances[0].emit("tool.completed", {
    tool: "prepare_polymarket_funding_ui",
  });

  await harness.app.handleStreamDisconnect(clientId);

  assert.equal(
    storedValue(localStorage, STORAGE_KEYS.fundingCreateUncertain),
    "true",
  );
  assert.equal(
    storedValue(localStorage, STORAGE_KEYS.fundingAmount),
    "0.500000",
  );
  assert.equal(
    storedValue(localStorage, STORAGE_KEYS.fundingIdempotency),
    "old-unresolved-intent",
  );
  assert.equal(
    harness.calls.some((call) =>
      call.method === "POST" &&
      call.url.startsWith("/miniapp/api/operations/polymarket/funding")
    ),
    false,
  );
});


test("an unresolved prior funding idempotency cannot be replaced by a new chat message", async () => {
  const clientId = "11111111-2222-4333-8444-555555555555";
  const localStorage = new FakeStorage({
    [STORAGE_KEYS.fundingAmount]: scoped("0.500000"),
    [STORAGE_KEYS.fundingIdempotency]: scoped("old-unresolved-intent"),
  });
  let createPosts = 0;
  const harness = createHarness(({ method, url }) => {
    if (method === "GET" && url === "/miniapp/api/chat") {
      return { body: chatBody() };
    }
    if (method === "POST" && url === "/miniapp/api/chat/messages") {
      return {
        status: 202,
        body: { client_message_id: clientId, status: "accepted" },
      };
    }
    if (method === "GET" && url.endsWith("/run")) {
      return {
        body: {
          client_message_id: clientId,
          status: "completed",
          has_output: true,
          has_error: false,
          output: "https://www.agentonomy.xyz/miniapp/#funding=1.000000",
        },
      };
    }
    if (method === "POST" && url === "/miniapp/api/operations/polymarket/funding") {
      createPosts += 1;
      return {
        status: 201,
        body: fundingBody({
          amount_usdc: "1.000000",
          status: "manual_review",
          next_action: "manual_review",
        }),
      };
    }
    throw new Error(`unexpected ${method} ${url}`);
  }, {
    localStorage,
    sessionStorage: new FakeStorage({ [STORAGE_KEYS.csrf]: "csrf" }),
  });
  await harness.app.start();
  harness.document.getElementById("miniapp-input").value = "fund 1 USDC";
  await harness.app.sendCurrentMessage();
  FakeEventSource.instances[0].emit("tool.completed", {
    tool: "prepare_polymarket_funding_ui",
  });

  await harness.app.handleStreamDisconnect(clientId);

  assert.equal(createPosts, 0);
  assert.equal(
    storedValue(localStorage, STORAGE_KEYS.fundingAmount),
    "0.500000",
  );
  assert.equal(
    storedValue(localStorage, STORAGE_KEYS.fundingIdempotency),
    "old-unresolved-intent",
  );
});


test("logout while final history loads prevents late conversational funding", async () => {
  const clientId = "11111111-2222-4333-8444-555555555555";
  const historyGate = deferred();
  let chatLoads = 0;
  const harness = createHarness(({ method, url }) => {
    if (method === "GET" && url === "/miniapp/api/chat") {
      chatLoads += 1;
      if (chatLoads === 1) return { body: chatBody() };
      return historyGate.promise;
    }
    if (method === "POST" && url === "/miniapp/api/chat/messages") {
      return {
        status: 202,
        body: { client_message_id: clientId, status: "accepted" },
      };
    }
    if (method === "GET" && url.endsWith("/run")) {
      return {
        body: {
          client_message_id: clientId,
          status: "completed",
          has_output: true,
          has_error: false,
        },
      };
    }
    if (method === "DELETE" && url === "/miniapp/api/session") {
      return { status: 204, body: null };
    }
    throw new Error(`unexpected ${method} ${url}`);
  }, { sessionStorage: new FakeStorage({ [STORAGE_KEYS.csrf]: "csrf" }) });
  await harness.app.start();
  harness.document.getElementById("miniapp-input").value = "fund 1 USDC";
  await harness.app.sendCurrentMessage();
  FakeEventSource.instances[0].emit("tool.completed", {
    tool: "prepare_polymarket_funding_ui",
  });
  const recovery = harness.app.handleStreamDisconnect(clientId);
  for (let index = 0; index < 4 && chatLoads < 2; index += 1) {
    await Promise.resolve();
  }
  assert.equal(chatLoads, 2);

  await harness.app.logout();
  historyGate.resolve({
    body: chatBody([
      { role: "user", content: "fund 1", timestamp: 1 },
      {
        role: "assistant",
        content: "https://www.agentonomy.xyz/miniapp/#funding=1.000000",
        timestamp: 2,
      },
    ]),
  });
  await recovery;

  assert.equal(
    harness.calls.some((call) =>
      call.method === "POST" &&
      call.url.startsWith("/miniapp/api/operations/polymarket/funding")
    ),
    false,
  );
  assert.equal(
    harness.localStorage.getItem(STORAGE_KEYS.fundingPreparedMessage),
    null,
  );
});


test("conversational funding waits for a busy live action and retains its intent", async () => {
  const clientId = "11111111-2222-4333-8444-555555555555";
  const signingGate = deferred();
  let chatLoads = 0;
  let createPosts = 0;
  const harness = createHarness(({ method, url }) => {
    if (method === "GET" && url === "/miniapp/api/chat") {
      chatLoads += 1;
      return {
        body: chatLoads === 1
          ? chatBody()
          : chatBody([
            { role: "user", content: "fund 1", timestamp: 1 },
            {
              role: "assistant",
              content: "https://www.agentonomy.xyz/miniapp/#funding=1.000000",
              timestamp: 2,
            },
          ]),
      };
    }
    if (method === "POST" && url === "/miniapp/api/chat/messages") {
      return {
        status: 202,
        body: { client_message_id: clientId, status: "accepted" },
      };
    }
    if (method === "GET" && url.endsWith("/run")) {
      return {
        body: {
          client_message_id: clientId,
          status: "completed",
          has_output: true,
          has_error: false,
          output: "https://www.agentonomy.xyz/miniapp/#funding=1.000000",
        },
      };
    }
    if (
      method === "POST" &&
      url === "/miniapp/api/operations/polymarket/order-signing"
    ) return signingGate.promise;
    if (method === "POST" && url === "/miniapp/api/operations/polymarket/funding") {
      createPosts += 1;
      return { status: 201, body: fundingBody({ amount_usdc: "1.000000" }) };
    }
    if (method === "POST" && url.endsWith("/pm_funding_1/continue")) {
      return {
        body: fundingBody({
          amount_usdc: "1.000000",
          status: "finalized",
          next_action: "complete",
        }),
      };
    }
    throw new Error(`unexpected ${method} ${url}`);
  }, { sessionStorage: new FakeStorage({ [STORAGE_KEYS.csrf]: "csrf" }) });
  await harness.app.start();
  const preview = harness.document.getElementById("polymarket-signing-preview");
  preview.value = "preview-busy";
  await preview.dispatch("input");
  const signing = harness.document.getElementById("polymarket-signing-open").dispatch("click");
  await Promise.resolve();
  harness.document.getElementById("miniapp-input").value = "fund 1 USDC";
  await harness.app.sendCurrentMessage();
  FakeEventSource.instances[0].emit("tool.completed", {
    tool: "prepare_polymarket_funding_ui",
  });
  const recovery = harness.app.handleStreamDisconnect(clientId);
  await Promise.resolve();

  assert.equal(createPosts, 0);
  assert.equal(
    storedValue(harness.localStorage, STORAGE_KEYS.fundingPreparedMessage),
    clientId,
  );

  signingGate.resolve({ status: 201, body: signingBody() });
  await Promise.all([signing, recovery]);

  assert.equal(createPosts, 1);
  assert.equal(
    storedValue(harness.localStorage, STORAGE_KEYS.fundingPreparedMessage),
    null,
  );
});


test("logout while conversational funding waits on a live action prevents mutation", async () => {
  const clientId = "11111111-2222-4333-8444-555555555555";
  const signingGate = deferred();
  let chatLoads = 0;
  let createPosts = 0;
  const harness = createHarness(({ method, url }) => {
    if (method === "GET" && url === "/miniapp/api/chat") {
      chatLoads += 1;
      return {
        body: chatLoads === 1
          ? chatBody()
          : chatBody([
            { role: "user", content: "fund 1", timestamp: 1 },
            {
              role: "assistant",
              content: "https://www.agentonomy.xyz/miniapp/#funding=1.000000",
              timestamp: 2,
            },
          ]),
      };
    }
    if (method === "POST" && url === "/miniapp/api/chat/messages") {
      return {
        status: 202,
        body: { client_message_id: clientId, status: "accepted" },
      };
    }
    if (method === "GET" && url.endsWith("/run")) {
      return {
        body: {
          client_message_id: clientId,
          status: "completed",
          has_output: true,
          has_error: false,
          output: "https://www.agentonomy.xyz/miniapp/#funding=1.000000",
        },
      };
    }
    if (
      method === "POST" &&
      url === "/miniapp/api/operations/polymarket/order-signing"
    ) return signingGate.promise;
    if (method === "POST" && url === "/miniapp/api/operations/polymarket/funding") {
      createPosts += 1;
      return { status: 201, body: fundingBody({ amount_usdc: "1.000000" }) };
    }
    if (method === "DELETE" && url === "/miniapp/api/session") {
      return { status: 204, body: null };
    }
    throw new Error(`unexpected ${method} ${url}`);
  }, { sessionStorage: new FakeStorage({ [STORAGE_KEYS.csrf]: "csrf" }) });
  await harness.app.start();
  const preview = harness.document.getElementById("polymarket-signing-preview");
  preview.value = "preview-busy-logout";
  await preview.dispatch("input");
  const signing = harness.document.getElementById("polymarket-signing-open").dispatch("click");
  await Promise.resolve();
  harness.document.getElementById("miniapp-input").value = "fund 1 USDC";
  await harness.app.sendCurrentMessage();
  FakeEventSource.instances[0].emit("tool.completed", {
    tool: "prepare_polymarket_funding_ui",
  });
  const recovery = harness.app.handleStreamDisconnect(clientId);
  for (let index = 0; index < 4; index += 1) await Promise.resolve();
  assert.equal(
    storedValue(harness.localStorage, STORAGE_KEYS.fundingPreparedMessage),
    clientId,
  );

  await harness.app.logout();
  signingGate.resolve({ status: 201, body: signingBody() });
  await Promise.all([signing, recovery]);

  assert.equal(createPosts, 0);
  assert.equal(
    harness.localStorage.getItem(STORAGE_KEYS.fundingPreparedMessage),
    null,
  );
});


test("a completed run says Completed only when every tool completed", async () => {
  const clientId = "11111111-2222-4333-8444-555555555555";
  let chatLoads = 0;
  const harness = createHarness(({ method, url }) => {
    if (method === "GET" && url === "/miniapp/api/chat") {
      chatLoads += 1;
      return { body: chatBody() };
    }
    if (method === "POST" && url === "/miniapp/api/chat/messages") {
      return {
        status: 202,
        body: { client_message_id: clientId, status: "accepted" },
      };
    }
    if (method === "GET" && url.endsWith("/run")) {
      return { body: { client_message_id: clientId, status: "completed" } };
    }
    throw new Error(`unexpected ${method} ${url}`);
  }, { sessionStorage: new FakeStorage({ [STORAGE_KEYS.csrf]: "csrf" }) });
  await harness.app.start();
  harness.document.getElementById("miniapp-input").value = "complete every operation";
  await harness.app.sendCurrentMessage();
  const source = FakeEventSource.instances[0];
  source.emit("tool.started", { tool: "account_status" });
  source.emit("tool.completed", { tool: "account_status" });

  await harness.app.handleStreamDisconnect(clientId);

  assert.equal(chatLoads, 2);
  assert.equal(
    harness.document.getElementById("miniapp-tool-progress-summary").textContent,
    "Completed 1 operation",
  );
  assert.match(
    harness.document.getElementById("miniapp-tool-progress-list").children[0].textContent,
    /account_status.*Completed/,
  );
});


test("an SSE terminal hint waits for authoritative failure before finalizing progress", async () => {
  const clientId = "11111111-2222-4333-8444-555555555555";
  const runResult = deferred();
  let chatLoads = 0;
  let runChecks = 0;
  const harness = createHarness(({ method, url }) => {
    if (method === "GET" && url === "/miniapp/api/chat") {
      chatLoads += 1;
      return { body: chatBody() };
    }
    if (method === "POST" && url === "/miniapp/api/chat/messages") {
      return {
        status: 202,
        body: { client_message_id: clientId, status: "accepted" },
      };
    }
    if (method === "GET" && url.endsWith("/run")) {
      runChecks += 1;
      return runResult.promise;
    }
    throw new Error(`unexpected ${method} ${url}`);
  }, { sessionStorage: new FakeStorage({ [STORAGE_KEYS.csrf]: "csrf" }) });
  await harness.app.start();
  harness.document.getElementById("miniapp-input").value = "question";
  await harness.app.sendCurrentMessage();
  const source = FakeEventSource.instances[0];
  source.emit("tool.started", { tool: "account_status" });
  source.emit("run.completed", {});
  await Promise.resolve();
  const pendingSummary = harness.document.getElementById(
    "miniapp-tool-progress-summary",
  ).textContent;
  const pendingRow = harness.document.getElementById(
    "miniapp-tool-progress-list",
  ).children[0].textContent;
  const recovery = harness.app.handleStreamDisconnect(clientId);

  runResult.resolve({
    body: { client_message_id: clientId, status: "failed" },
  });
  await recovery;

  assert.equal(runChecks, 1);
  assert.equal(pendingSummary, "Working · 1 operation");
  assert.match(pendingRow, /Running/);
  assert.equal(
    harness.document.getElementById("miniapp-tool-progress-summary").textContent,
    "Run failed · 1 operation",
  );
  assert.match(
    harness.document.getElementById("miniapp-tool-progress-list").children[0].textContent,
    /Interrupted/,
  );
  assert.equal(
    harness.document.getElementById("miniapp-status").textContent,
    "Response failed. Nothing was resent.",
  );
  assert.equal(chatLoads, 2);
});


test("authoritative terminal states preserve incomplete tool outcomes", async () => {
  const cases = [
    {
      status: "completed",
      summary: "Run completed · 1 operation",
      row: "No completion received",
      message: "Response completed.",
    },
    {
      status: "stopped",
      summary: "Run stopped · 1 operation",
      row: "Stopped",
      message: "Response stopped. Nothing was resent.",
    },
    {
      status: "cancelled",
      summary: "Run cancelled · 1 operation",
      row: "Cancelled",
      message: "Response cancelled. Nothing was resent.",
    },
  ];

  for (const item of cases) {
    const clientId = "11111111-2222-4333-8444-555555555555";
    let chatLoads = 0;
    const harness = createHarness(({ method, url }) => {
      if (method === "GET" && url === "/miniapp/api/chat") {
        chatLoads += 1;
        return { body: chatBody() };
      }
      if (method === "POST" && url === "/miniapp/api/chat/messages") {
        return {
          status: 202,
          body: { client_message_id: clientId, status: "accepted" },
        };
      }
      if (method === "GET" && url.endsWith("/run")) {
        return { body: { client_message_id: clientId, status: item.status } };
      }
      throw new Error(`unexpected ${method} ${url}`);
    }, { sessionStorage: new FakeStorage({ [STORAGE_KEYS.csrf]: "csrf" }) });
    await harness.app.start();
    harness.document.getElementById("miniapp-input").value = item.status;
    await harness.app.sendCurrentMessage();
    FakeEventSource.instances[0].emit("tool.started", { tool: "pending_tool" });

    await harness.app.handleStreamDisconnect(clientId);

    assert.equal(
      harness.document.getElementById("miniapp-tool-progress-summary").textContent,
      item.summary,
      item.status,
    );
    assert.match(
      harness.document.getElementById("miniapp-tool-progress-list").children[0].textContent,
      new RegExp(item.row),
      item.status,
    );
    assert.equal(
      harness.document.getElementById("miniapp-status").textContent,
      item.message,
      item.status,
    );
    assert.equal(chatLoads, 2);
  }
});


test("all recovery triggers share one in-flight run lookup for the same message", async () => {
  const clientId = "11111111-2222-4333-8444-555555555555";
  const runResult = deferred();
  let runChecks = 0;
  const harness = createHarness(({ method, url }) => {
    if (method === "GET" && url === "/miniapp/api/chat") return { body: chatBody() };
    if (method === "POST" && url === "/miniapp/api/chat/messages") {
      return {
        status: 202,
        body: { client_message_id: clientId, status: "accepted" },
      };
    }
    if (method === "GET" && url.endsWith("/run")) {
      runChecks += 1;
      return runResult.promise;
    }
    throw new Error(`unexpected ${method} ${url}`);
  }, { sessionStorage: new FakeStorage({ [STORAGE_KEYS.csrf]: "csrf" }) });
  await harness.app.start();
  harness.document.getElementById("miniapp-input").value = "question";
  await harness.app.sendCurrentMessage();

  const disconnect = harness.app.handleStreamDisconnect(clientId);
  harness.emitWindow("pageshow");
  const visibility = harness.emitDocument("visibilitychange");
  await Promise.resolve();

  assert.equal(runChecks, 1);
  runResult.resolve({
    body: { client_message_id: clientId, status: "running" },
  });
  await Promise.all([disconnect, visibility]);
  assert.equal(runChecks, 1);
});


test("a late old terminal lookup cannot clear or repaint a newly started run", async () => {
  const oldId = "11111111-2222-4333-8444-555555555555";
  const newId = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee";
  const oldRun = deferred();
  let postCount = 0;
  let chatLoads = 0;
  const harness = createHarness(({ method, url }) => {
    if (method === "GET" && url === "/miniapp/api/chat") {
      chatLoads += 1;
      return {
        body: chatBody([
          { id: 1, role: "assistant", content: "stale old answer", timestamp: 1 },
        ]),
      };
    }
    if (method === "POST" && url === "/miniapp/api/chat/messages") {
      const id = postCount === 0 ? oldId : newId;
      postCount += 1;
      return { status: 202, body: { client_message_id: id, status: "accepted" } };
    }
    if (method === "GET" && url.includes(oldId) && url.endsWith("/run")) {
      return oldRun.promise;
    }
    throw new Error(`unexpected ${method} ${url}`);
  }, {
    randomUUID: () => postCount === 0 ? oldId : newId,
    sessionStorage: new FakeStorage({ [STORAGE_KEYS.csrf]: "csrf" }),
  });
  await harness.app.start();
  harness.document.getElementById("miniapp-input").value = "old question";
  await harness.app.sendCurrentMessage();
  const recovery = harness.app.handleStreamDisconnect(oldId);
  await Promise.resolve();

  harness.localStorage.removeItem(STORAGE_KEYS.currentClientMessage);
  harness.document.getElementById("miniapp-input").value = "new question";
  await harness.app.sendCurrentMessage();
  const newSource = FakeEventSource.instances.at(-1);
  newSource.emit("tool.started", { tool: "new_operation" });
  newSource.emit("message.delta", { delta: "new answer" });

  oldRun.resolve({ body: { client_message_id: oldId, status: "completed" } });
  await recovery;

  assert.equal(
    storedValue(harness.localStorage, STORAGE_KEYS.currentClientMessage),
    newId,
  );
  assert.equal(chatLoads, 1);
  assert.equal(newSource.closed, false);
  assert.equal(
    harness.document.getElementById("miniapp-transcript").children.at(-1).children[1].textContent,
    "new answer",
  );
  assert.equal(
    harness.document.getElementById("miniapp-tool-progress-summary").textContent,
    "Working · 1 operation",
  );
  assert.match(
    harness.document.getElementById("miniapp-tool-progress-list").children[0].textContent,
    /new_operation.*Running/,
  );
});


test("a stale terminal history response cannot overwrite a newer optimistic run", async () => {
  const oldId = "11111111-2222-4333-8444-555555555555";
  const newId = "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee";
  const staleHistory = deferred();
  let postCount = 0;
  let chatLoads = 0;
  let newRunChecks = 0;
  const harness = createHarness(({ method, url }) => {
    if (method === "GET" && url === "/miniapp/api/chat") {
      chatLoads += 1;
      if (chatLoads === 1) return { body: chatBody() };
      return staleHistory.promise;
    }
    if (method === "POST" && url === "/miniapp/api/chat/messages") {
      const id = postCount === 0 ? oldId : newId;
      postCount += 1;
      return { status: 202, body: { client_message_id: id, status: "accepted" } };
    }
    if (method === "GET" && url.includes(oldId) && url.endsWith("/run")) {
      return { body: { client_message_id: oldId, status: "completed" } };
    }
    if (method === "GET" && url.includes(newId) && url.endsWith("/run")) {
      newRunChecks += 1;
      return { body: { client_message_id: newId, status: "running" } };
    }
    throw new Error(`unexpected ${method} ${url}`);
  }, {
    randomUUID: () => postCount === 0 ? oldId : newId,
    sessionStorage: new FakeStorage({ [STORAGE_KEYS.csrf]: "csrf" }),
  });
  await harness.app.start();
  harness.document.getElementById("miniapp-input").value = "old question";
  await harness.app.sendCurrentMessage();
  const recovery = harness.app.handleStreamDisconnect(oldId);
  for (let index = 0; index < 4 && chatLoads < 2; index += 1) {
    await Promise.resolve();
  }
  assert.equal(chatLoads, 2);

  harness.document.getElementById("miniapp-input").value = "new question";
  await harness.app.sendCurrentMessage();
  const newSource = FakeEventSource.instances.at(-1);
  newSource.emit("tool.started", { tool: "new_operation" });
  newSource.emit("message.delta", { delta: "new answer" });

  staleHistory.resolve({
    body: chatBody([
      { id: 9, role: "assistant", content: "stale old answer", timestamp: 9 },
    ]),
  });
  await recovery;

  assert.equal(
    storedValue(harness.localStorage, STORAGE_KEYS.currentClientMessage),
    newId,
  );
  assert.equal(newSource.closed, false);
  assert.equal(newRunChecks, 0);
  assert.equal(
    harness.document.getElementById("miniapp-transcript").children.at(-1).children[1].textContent,
    "new answer",
  );
  assert.equal(
    harness.document.getElementById("miniapp-tool-progress-summary").textContent,
    "Working · 1 operation",
  );
});


test("SSE disconnect polls authoritative run state and reloads final history without reconnecting", async () => {
  const clientId = "11111111-2222-4333-8444-555555555555";
  let chatLoads = 0;
  let runChecks = 0;
  const harness = createHarness(({ method, url }) => {
    if (method === "GET" && url === "/miniapp/api/chat") {
      chatLoads += 1;
      return {
        body: chatLoads === 1
          ? chatBody()
          : chatBody([
            { id: 1, role: "user", content: "question", timestamp: 1 },
            { id: 2, role: "assistant", content: "final answer", timestamp: 2 },
          ]),
      };
    }
    if (method === "POST" && url === "/miniapp/api/chat/messages") {
      return {
        status: 202,
        body: { client_message_id: clientId, status: "accepted" },
      };
    }
    if (method === "GET" && url === `/miniapp/api/chat/messages/${clientId}/run`) {
      runChecks += 1;
      return {
        body: {
          client_message_id: clientId,
          status: runChecks === 1 ? "running" : "completed",
          has_output: runChecks > 1,
          has_error: false,
        },
      };
    }
    throw new Error(`unexpected ${method} ${url}`);
  }, {
    sessionStorage: new FakeStorage({ [STORAGE_KEYS.csrf]: "csrf" }),
  });
  await harness.app.start();
  harness.document.getElementById("miniapp-input").value = "question";
  await harness.app.sendCurrentMessage();
  const source = FakeEventSource.instances[0];
  assert.equal(source.url, `/miniapp/api/chat/messages/${clientId}/events`);
  source.emit("token", { token: "Hello" }, "event-7");
  source.emit("tool", { name: "clink_node_status", status: "running" }, "event-8");
  assert.equal(Object.hasOwn(STORAGE_KEYS, "lastEvent"), false);
  assert.match(harness.document.getElementById("miniapp-transcript").children.at(-1).children[1].textContent, /Hello/);
  assert.match(
    harness.document.getElementById("miniapp-tool-progress-list").children[0].textContent,
    /clink_node_status.*Running/,
  );

  await harness.app.handleStreamDisconnect();
  assert.equal(source.closed, true);
  assert.equal(runChecks, 1);
  assert.equal(FakeEventSource.instances.length, 1);
  assert.equal(harness.scheduledCount(), 1);
  assert.equal(
    harness.calls.filter((call) => call.method === "POST").length,
    1,
  );
  assert.equal(chatLoads, 1);

  await harness.runScheduled();

  assert.equal(runChecks, 2);
  assert.equal(FakeEventSource.instances.length, 1);
  assert.equal(chatLoads, 2);
  assert.equal(harness.localStorage.getItem(STORAGE_KEYS.currentClientMessage), null);
  assert.equal(harness.scheduledCount(), 0);
  assert.equal(
    harness.document.getElementById("miniapp-transcript").children.at(-1).children[1].textContent,
    "final answer",
  );
});


test("status polling survives CSRF scope establishment during cookie recovery", async () => {
  const clientId = "11111111-2222-4333-8444-555555555555";
  let chatLoads = 0;
  let runChecks = 0;
  const harness = createHarness(({ method, url }) => {
    if (method === "GET" && url === "/miniapp/api/chat") {
      chatLoads += 1;
      return {
        body: chatLoads === 1
          ? chatBody([], { client_message_id: clientId, status: "accepted" })
          : chatBody([
            { id: 2, role: "assistant", content: "restored final", timestamp: 2 },
          ]),
      };
    }
    if (method === "GET" && url.endsWith("/run")) {
      runChecks += 1;
      return {
        body: {
          client_message_id: clientId,
          status: runChecks === 1 ? "running" : "completed",
        },
      };
    }
    if (method === "POST" && url === "/miniapp/api/session") {
      return {
        status: 201,
        body: {
          authenticated: true,
          csrf_token: "csrf-restored",
          storage_scope: STABLE_SCOPE_A,
          user: { username: "Jeff" },
        },
      };
    }
    throw new Error(`unexpected ${method} ${url}`);
  }, { sessionStorage: new FakeStorage() });

  await harness.app.start();
  assert.equal(runChecks, 1);
  assert.equal(harness.scheduledCount(), 1);
  assert.equal(FakeEventSource.instances.length, 0);

  await harness.runScheduled();

  assert.equal(runChecks, 2);
  assert.equal(chatLoads, 2);
  assert.equal(FakeEventSource.instances.length, 0);
  assert.equal(
    harness.document.getElementById("miniapp-transcript").children.at(-1).children[1].textContent,
    "restored final",
  );
});


test("draft scroll and operation return state survive top-level navigation", async () => {
  const localStorage = new FakeStorage();
  const harness = createHarness(({ method, url }) => {
    if (method === "GET" && url === "/miniapp/api/chat") return { body: chatBody() };
    throw new Error(`unexpected ${method} ${url}`);
  }, {
    localStorage,
    sessionStorage: new FakeStorage({ [STORAGE_KEYS.csrf]: "csrf" }),
    telegramOpenLink: true,
  });
  await harness.app.start();
  const input = harness.document.getElementById("miniapp-input");
  const transcript = harness.document.getElementById("miniapp-transcript");
  input.value = "unfinished message";
  await input.dispatch("input");
  transcript.scrollTop = 321;
  await transcript.dispatch("scroll");
  await harness.document.operationLinks[1].dispatch("click");

  assert.equal(storedValue(localStorage, STORAGE_KEYS.draft), "unfinished message");
  assert.equal(storedValue(localStorage, STORAGE_KEYS.scroll), "321");
  assert.ok(storedValue(localStorage, STORAGE_KEYS.returnMarker));
  assert.deepEqual(harness.assigned, ["/#marketplace-showcase"]);
  assert.deepEqual(harness.externalOpened, []);

  const returned = createHarness(({ method, url }) => {
    if (method === "GET" && url === "/miniapp/api/chat") return { body: chatBody() };
    throw new Error(`unexpected ${method} ${url}`);
  }, { localStorage, sessionStorage: harness.sessionStorage });
  await returned.app.start();
  assert.equal(returned.document.getElementById("miniapp-input").value, "unfinished message");
  assert.equal(returned.document.getElementById("miniapp-transcript").scrollTop, 321);
  returned.document.getElementById("miniapp-input").value = "";
  returned.document.getElementById("miniapp-transcript").scrollTop = 0;
  returned.emitWindow("pageshow");
  assert.equal(returned.document.getElementById("miniapp-input").value, "unfinished message");
  assert.equal(returned.document.getElementById("miniapp-transcript").scrollTop, 321);
});


test("wallet operation navigates from Telegram on the first click", async () => {
  const localStorage = new FakeStorage();
  const harness = createHarness(({ method, url, headers, body }) => {
    if (method === "GET" && url === "/miniapp/api/chat") {
      return { body: chatBody() };
    }
    if (method === "POST" && url === "/miniapp/api/operations/account") {
      assert.equal(headers["Content-Type"], "application/json");
      assert.equal(headers["X-Agentonomy-CSRF"], "csrf");
      assert.deepEqual(body, {});
      return {
        body: {
          url: "https://www.agentonomy.xyz/account/session/safe?return=miniapp#done",
        },
      };
    }
    throw new Error(`unexpected ${method} ${url}`);
  }, {
    localStorage,
    sessionStorage: new FakeStorage({ [STORAGE_KEYS.csrf]: "csrf" }),
    telegramOpenLink: true,
  });
  await harness.app.start();
  const input = harness.document.getElementById("miniapp-input");
  const transcript = harness.document.getElementById("miniapp-transcript");
  input.value = "unfinished wallet note";
  transcript.scrollTop = 144;

  await harness.document.operationLinks[0].dispatch("click");

  assert.equal(storedValue(localStorage, STORAGE_KEYS.draft), "unfinished wallet note");
  assert.equal(storedValue(localStorage, STORAGE_KEYS.scroll), "144");
  assert.ok(storedValue(localStorage, STORAGE_KEYS.returnMarker));
  assert.deepEqual(harness.externalOpened, [
    "https://www.agentonomy.xyz/account/session/safe?return=miniapp#done",
  ]);
  assert.deepEqual(harness.assigned, []);
  for (const raw of localStorage.values.values()) {
    assert.doesNotMatch(raw, /account\/session\/safe/);
  }

  assert.equal(
    harness.calls.filter((call) =>
      call.method === "POST" && call.url === "/miniapp/api/operations/account"
    ).length,
    1,
  );
  assert.deepEqual(harness.telegramVersionChecks, ["6.1"]);
});


test("subject-bound operations share one in-flight request and navigation", async () => {
  let resolveOperation;
  const operationResponse = new Promise((resolve) => {
    resolveOperation = resolve;
  });
  const harness = createHarness(({ method, url }) => {
    if (method === "GET" && url === "/miniapp/api/chat") {
      return { body: chatBody() };
    }
    if (method === "POST" && url.startsWith("/miniapp/api/operations/")) {
      return operationResponse;
    }
    throw new Error(`unexpected ${method} ${url}`);
  }, {
    sessionStorage: new FakeStorage({ [STORAGE_KEYS.csrf]: "csrf" }),
  });
  await harness.app.start();

  const first = harness.document.operationLinks[0].dispatch("click");
  await Promise.resolve();
  const duplicate = harness.document.operationLinks[0].dispatch("click");
  const competing = harness.document.operationLinks[2].dispatch("click");
  await Promise.resolve();

  assert.equal(
    harness.calls.filter((call) =>
      call.method === "POST" && call.url.startsWith("/miniapp/api/operations/")
    ).length,
    1,
  );

  resolveOperation({
    body: { url: "https://www.agentonomy.xyz/account/session/safe" },
  });
  await Promise.all([first, duplicate, competing]);
  assert.deepEqual(harness.assigned, [
    "https://www.agentonomy.xyz/account/session/safe",
  ]);

  await harness.document.operationLinks[2].dispatch("click");
  assert.equal(
    harness.calls.filter((call) =>
      call.method === "POST" && call.url.startsWith("/miniapp/api/operations/")
    ).length,
    1,
  );
  assert.equal(harness.assigned.length, 1);

  harness.emitWindow("pageshow", { persisted: true });
  await harness.document.operationLinks[2].dispatch("click");
  assert.equal(
    harness.calls.filter((call) =>
      call.method === "POST" && call.url.startsWith("/miniapp/api/operations/")
    ).length,
    2,
  );
  assert.equal(harness.assigned.length, 2);

  harness.emitWindow("pageshow");
  await harness.document.operationLinks[0].dispatch("click");
  assert.equal(
    harness.calls.filter((call) =>
      call.method === "POST" && call.url.startsWith("/miniapp/api/operations/")
    ).length,
    3,
  );
  assert.equal(harness.assigned.length, 3);
});


test("returning from one subject surface enables another one-click navigation", async () => {
  const harness = createHarness(({ method, url }) => {
    if (method === "GET" && url === "/miniapp/api/chat") {
      return { body: chatBody() };
    }
    if (method === "POST" && url === "/miniapp/api/operations/account") {
      return {
        body: { url: "https://www.agentonomy.xyz/account/session/release" },
      };
    }
    if (method === "POST" && url === "/miniapp/api/operations/polymarket") {
      return {
        body: { url: "https://www.agentonomy.xyz/polymarket/binding-console/release" },
      };
    }
    throw new Error(`unexpected ${method} ${url}`);
  }, {
    sessionStorage: new FakeStorage({ [STORAGE_KEYS.csrf]: "csrf" }),
    telegramOpenLink: true,
  });
  await harness.app.start();

  await harness.document.operationLinks[0].dispatch("click");
  harness.emitWindow("pageshow");
  await harness.document.operationLinks[2].dispatch("click");

  assert.deepEqual(harness.externalOpened, [
    "https://www.agentonomy.xyz/account/session/release",
    "https://www.agentonomy.xyz/polymarket/binding-console/release",
  ]);
  assert.deepEqual(harness.assigned, []);
  assert.equal(
    harness.calls.filter((call) =>
      call.method === "POST" && call.url === "/miniapp/api/operations/account"
    ).length,
    1,
  );
  assert.equal(
    harness.calls.filter((call) =>
      call.method === "POST" && call.url === "/miniapp/api/operations/polymarket"
    ).length,
    1,
  );
});


test("wallet operation failure is not auto-retried and permits manual retry", async () => {
  let attempts = 0;
  const localStorage = new FakeStorage();
  const harness = createHarness(({ method, url }) => {
    if (method === "GET" && url === "/miniapp/api/chat") {
      return { body: chatBody() };
    }
    if (method === "POST" && url === "/miniapp/api/operations/account") {
      attempts += 1;
      return { status: 503, body: { detail: "miniapp_unavailable" } };
    }
    throw new Error(`unexpected ${method} ${url}`);
  }, {
    localStorage,
    sessionStorage: new FakeStorage({ [STORAGE_KEYS.csrf]: "csrf" }),
  });
  await harness.app.start();
  harness.document.getElementById("miniapp-input").value = "keep me";
  harness.document.getElementById("miniapp-transcript").scrollTop = 55;

  await harness.document.operationLinks[0].dispatch("click");

  assert.equal(attempts, 1);
  assert.deepEqual(harness.assigned, []);
  assert.equal(storedValue(localStorage, STORAGE_KEYS.draft), "keep me");
  assert.equal(storedValue(localStorage, STORAGE_KEYS.scroll), "55");
  assert.ok(storedValue(localStorage, STORAGE_KEYS.returnMarker));
  assert.match(
    harness.document.getElementById("miniapp-status").textContent,
    /unavailable/i,
  );

  await harness.document.operationLinks[0].dispatch("click");
  assert.equal(attempts, 2);
  assert.deepEqual(harness.assigned, []);
});


test("logout prevents another subject-bound wallet navigation", async () => {
  let operationPosts = 0;
  const harness = createHarness(({ method, url }) => {
    if (method === "GET" && url === "/miniapp/api/chat") {
      return { body: chatBody() };
    }
    if (method === "POST" && url === "/miniapp/api/operations/account") {
      operationPosts += 1;
      return {
        body: { url: "https://www.agentonomy.xyz/account/session/logout" },
      };
    }
    if (method === "DELETE" && url === "/miniapp/api/session") {
      return { body: { revoked: true } };
    }
    throw new Error(`unexpected ${method} ${url}`);
  }, {
    sessionStorage: new FakeStorage({ [STORAGE_KEYS.csrf]: "csrf" }),
    telegramOpenLink: true,
  });
  await harness.app.start();
  await harness.document.operationLinks[0].dispatch("click");
  assert.deepEqual(harness.externalOpened, [
    "https://www.agentonomy.xyz/account/session/logout",
  ]);
  assert.deepEqual(harness.assigned, []);

  await harness.app.logout();
  await harness.document.operationLinks[0].dispatch("click");

  assert.deepEqual(harness.externalOpened, [
    "https://www.agentonomy.xyz/account/session/logout",
  ]);
  assert.equal(operationPosts, 1);
});


test("Polymarket operation navigates from Telegram on the first click", async () => {
  const localStorage = new FakeStorage();
  const harness = createHarness(({ method, url, headers, body }) => {
    if (method === "GET" && url === "/miniapp/api/chat") {
      return { body: chatBody() };
    }
    if (method === "POST" && url === "/miniapp/api/operations/polymarket") {
      assert.equal(headers["Content-Type"], "application/json");
      assert.equal(headers["X-Agentonomy-CSRF"], "csrf");
      assert.deepEqual(body, {});
      return {
        body: {
          url: (
            "https://www.agentonomy.xyz/polymarket/binding-console/" +
            "pm_bind_sess_a1b2c3d4e5f6?access_token=console-secret"
          ),
        },
      };
    }
    throw new Error(`unexpected ${method} ${url}`);
  }, {
    localStorage,
    sessionStorage: new FakeStorage({ [STORAGE_KEYS.csrf]: "csrf" }),
    telegramOpenLink: true,
  });
  await harness.app.start();
  const input = harness.document.getElementById("miniapp-input");
  const transcript = harness.document.getElementById("miniapp-transcript");
  input.value = "unfinished market note";
  transcript.scrollTop = 233;

  await harness.document.operationLinks[2].dispatch("click");

  assert.equal(
    storedValue(localStorage, STORAGE_KEYS.draft),
    "unfinished market note",
  );
  assert.equal(storedValue(localStorage, STORAGE_KEYS.scroll), "233");
  assert.ok(storedValue(localStorage, STORAGE_KEYS.returnMarker));
  assert.deepEqual(harness.externalOpened, [
    (
      "https://www.agentonomy.xyz/polymarket/binding-console/" +
      "pm_bind_sess_a1b2c3d4e5f6?access_token=console-secret"
    ),
  ]);
  assert.deepEqual(harness.assigned, []);
  for (const raw of localStorage.values.values()) {
    assert.doesNotMatch(raw, /console-secret|binding-console/);
  }

  assert.equal(
    harness.calls.filter((call) =>
      call.method === "POST" &&
      call.url === "/miniapp/api/operations/polymarket"
    ).length,
    1,
  );
  assert.deepEqual(harness.telegramVersionChecks, ["6.1"]);
});


test("Polymarket operation failure keeps state and is never retried", async () => {
  let attempts = 0;
  const localStorage = new FakeStorage();
  const harness = createHarness(({ method, url }) => {
    if (method === "GET" && url === "/miniapp/api/chat") {
      return { body: chatBody() };
    }
    if (method === "POST" && url === "/miniapp/api/operations/polymarket") {
      attempts += 1;
      return { status: 503, body: { detail: "miniapp_unavailable" } };
    }
    throw new Error(`unexpected ${method} ${url}`);
  }, {
    localStorage,
    sessionStorage: new FakeStorage({ [STORAGE_KEYS.csrf]: "csrf" }),
  });
  await harness.app.start();
  harness.document.getElementById("miniapp-input").value = (
    "keep this market note"
  );
  harness.document.getElementById("miniapp-transcript").scrollTop = 89;

  await harness.document.operationLinks[2].dispatch("click");

  assert.equal(attempts, 1);
  assert.deepEqual(harness.assigned, []);
  assert.equal(
    storedValue(localStorage, STORAGE_KEYS.draft),
    "keep this market note",
  );
  assert.equal(storedValue(localStorage, STORAGE_KEYS.scroll), "89");
  assert.ok(storedValue(localStorage, STORAGE_KEYS.returnMarker));
  assert.match(
    harness.document.getElementById("miniapp-status").textContent,
    /unavailable/i,
  );
});


test("one funding click creates once and advances only the returned operation", async () => {
  const createGate = deferred();
  let continuePosts = 0;
  const forbiddenFields = [
    "user_id", "binding_id", "wallet", "destination", "reservation_id",
    "audit_event_id", "tx", "signer", "exchange", "credentials", "metadata",
  ];
  const harness = createHarness(({ method, url, headers, body }) => {
    if (method === "GET" && url === "/miniapp/api/chat") {
      return { body: chatBody() };
    }
    if (
      method === "POST" &&
      url === "/miniapp/api/operations/polymarket/funding"
    ) {
      assert.equal(headers["Content-Type"], "application/json");
      assert.equal(headers["X-Agentonomy-CSRF"], "csrf");
      assert.deepEqual(body, {
        amount_usdc: "1.250000",
        idempotency_key: "11111111-2222-4333-8444-555555555555",
      });
      for (const field of forbiddenFields) assert.equal(field in body, false);
      return createGate.promise;
    }
    if (
      method === "POST" &&
      url === "/miniapp/api/operations/polymarket/funding/pm_funding_1/continue"
    ) {
      continuePosts += 1;
      assert.equal(headers["X-Agentonomy-CSRF"], "csrf");
      assert.deepEqual(body, {});
      return {
        body: fundingBody({
          status: "finalized",
          amount_usdc: "1.250000",
          chain_status: "confirmed",
          bridge_status: "credited",
          buying_power_status: "credited",
          next_action: "complete",
        }),
      };
    }
    throw new Error(`unexpected ${method} ${url}`);
  }, {
    localStorage: new FakeStorage(),
    sessionStorage: new FakeStorage({ [STORAGE_KEYS.csrf]: "csrf" }),
  });
  await harness.app.start();
  const amount = harness.document.getElementById("polymarket-funding-amount");
  const confirm = harness.document.getElementById("polymarket-funding-confirm");
  amount.value = "1.25";
  await amount.dispatch("input");

  const first = confirm.dispatch("click");
  await Promise.resolve();
  const duplicate = confirm.dispatch("click");
  await Promise.resolve();
  assert.equal(
    harness.calls.filter((call) =>
      call.method === "POST" &&
      call.url === "/miniapp/api/operations/polymarket/funding"
    ).length,
    1,
  );
  assert.equal(confirm.disabled, true);

  createGate.resolve({
    status: 201,
    body: fundingBody({ amount_usdc: "1.250000" }),
  });
  await Promise.all([first, duplicate]);

  assert.deepEqual(
    harness.calls.filter((call) => call.method === "POST").map((call) => call.url),
    [
      "/miniapp/api/operations/polymarket/funding",
      "/miniapp/api/operations/polymarket/funding/pm_funding_1/continue",
    ],
  );
  assert.equal(continuePosts, 1);
  assert.equal(
    storedValue(harness.localStorage, LIVE_STORAGE_KEYS.fundingAmount),
    "1.250000",
  );
  assert.equal(
    storedValue(harness.localStorage, LIVE_STORAGE_KEYS.fundingIdempotency),
    "11111111-2222-4333-8444-555555555555",
  );
  assert.equal(
    storedValue(harness.localStorage, LIVE_STORAGE_KEYS.fundingOperation),
    "pm_funding_1",
  );
  assert.equal(confirm.textContent, "Funding complete");
  assert.equal(confirm.disabled, true);
});


test("funding create is tombstoned before POST settles and clears after a valid projection", async () => {
  const createGate = deferred();
  const harness = createHarness(({ method, url }) => {
    if (method === "GET" && url === "/miniapp/api/chat") {
      return { body: chatBody() };
    }
    if (method === "POST" && url === "/miniapp/api/operations/polymarket/funding") {
      return createGate.promise;
    }
    throw new Error(`unexpected ${method} ${url}`);
  }, { sessionStorage: new FakeStorage({ [STORAGE_KEYS.csrf]: "csrf" }) });
  await harness.app.start();
  const amount = harness.document.getElementById("polymarket-funding-amount");
  amount.value = "1";
  await amount.dispatch("input");

  const creating = harness.document.getElementById(
    "polymarket-funding-confirm",
  ).dispatch("click");
  await Promise.resolve();

  assert.equal(
    storedValue(harness.localStorage, STORAGE_KEYS.fundingCreateUncertain),
    "true",
  );
  assert.equal(
    storedValue(harness.localStorage, STORAGE_KEYS.fundingIdempotency),
    "11111111-2222-4333-8444-555555555555",
  );

  createGate.resolve({
    status: 201,
    body: fundingBody({
      amount_usdc: "1.000000",
      status: "manual_review",
      next_action: "manual_review",
    }),
  });
  await creating;

  assert.equal(
    storedValue(harness.localStorage, STORAGE_KEYS.fundingCreateUncertain),
    null,
  );
  assert.equal(
    storedValue(harness.localStorage, STORAGE_KEYS.fundingOperation),
    "pm_funding_1",
  );
});


test("safe automatic funding progress is serialized on the same operation", async () => {
  let continuePosts = 0;
  const harness = createHarness(({ method, url }) => {
    if (method === "GET" && url === "/miniapp/api/chat") {
      return { body: chatBody() };
    }
    if (
      method === "POST" &&
      url === "/miniapp/api/operations/polymarket/funding"
    ) return { status: 201, body: fundingBody({ amount_usdc: "1.000000" }) };
    if (
      method === "POST" &&
      url === "/miniapp/api/operations/polymarket/funding/pm_funding_1/continue"
    ) {
      continuePosts += 1;
      return {
        body: continuePosts === 1
          ? fundingBody({
            status: "submitted",
            amount_usdc: "1.000000",
            chain_status: "pending",
            next_action: "processing",
          })
          : fundingBody({
            status: "chain_confirmed",
            amount_usdc: "1.000000",
            chain_status: "confirmed",
            next_action: "check_bridge_status",
          }),
      };
    }
    throw new Error(`unexpected ${method} ${url}`);
  }, { sessionStorage: new FakeStorage({ [STORAGE_KEYS.csrf]: "csrf" }) });
  await harness.app.start();
  const amount = harness.document.getElementById("polymarket-funding-amount");
  amount.value = "1";
  await amount.dispatch("input");

  await harness.document.getElementById("polymarket-funding-confirm").dispatch("click");

  assert.equal(continuePosts, 1);
  assert.equal(harness.scheduledCount(), 1);
  await harness.runScheduled();
  assert.equal(continuePosts, 2);
  assert.equal(
    harness.calls.filter((call) =>
      call.method === "POST" && call.url.endsWith("/continue")
    ).every((call) => call.url.includes("/pm_funding_1/")),
    true,
  );
  assert.equal(harness.scheduledCount(), 1);
});


test("automatic funding progress stops at its attempt bound", async () => {
  let continuePosts = 0;
  const harness = createHarness(({ method, url }) => {
    if (method === "GET" && url === "/miniapp/api/chat") {
      return { body: chatBody() };
    }
    if (
      method === "POST" &&
      url === "/miniapp/api/operations/polymarket/funding"
    ) return { status: 201, body: fundingBody({ amount_usdc: "1.000000" }) };
    if (
      method === "POST" &&
      url === "/miniapp/api/operations/polymarket/funding/pm_funding_1/continue"
    ) {
      continuePosts += 1;
      return {
        body: fundingBody({
          status: "submitted",
          amount_usdc: "1.000000",
          chain_status: "pending",
          next_action: "processing",
        }),
      };
    }
    throw new Error(`unexpected ${method} ${url}`);
  }, { sessionStorage: new FakeStorage({ [STORAGE_KEYS.csrf]: "csrf" }) });
  await harness.app.start();
  const amount = harness.document.getElementById("polymarket-funding-amount");
  amount.value = "1";
  await amount.dispatch("input");

  await harness.document.getElementById("polymarket-funding-confirm").dispatch("click");
  for (let step = 0; step < 40 && harness.scheduledCount() > 0; step += 1) {
    await harness.runScheduled();
  }

  assert.equal(continuePosts, 25);
  assert.equal(harness.scheduledCount(), 0);
  assert.match(
    harness.document.getElementById("polymarket-funding-status").textContent,
    /Automatic progress paused/i,
  );
  assert.equal(
    harness.document.getElementById("polymarket-funding-confirm").textContent,
    "Continue funding",
  );
});


test("logout cancels scheduled funding progress before another mutation", async () => {
  let continuePosts = 0;
  const harness = createHarness(({ method, url }) => {
    if (method === "GET" && url === "/miniapp/api/chat") {
      return { body: chatBody() };
    }
    if (
      method === "POST" &&
      url === "/miniapp/api/operations/polymarket/funding"
    ) return { status: 201, body: fundingBody({ amount_usdc: "1.000000" }) };
    if (
      method === "POST" &&
      url === "/miniapp/api/operations/polymarket/funding/pm_funding_1/continue"
    ) {
      continuePosts += 1;
      return {
        body: fundingBody({
          status: "submitted",
          amount_usdc: "1.000000",
          chain_status: "pending",
          next_action: "processing",
        }),
      };
    }
    if (method === "DELETE" && url === "/miniapp/api/session") {
      return { status: 204, body: null };
    }
    throw new Error(`unexpected ${method} ${url}`);
  }, { sessionStorage: new FakeStorage({ [STORAGE_KEYS.csrf]: "csrf" }) });
  await harness.app.start();
  const amount = harness.document.getElementById("polymarket-funding-amount");
  amount.value = "1";
  await amount.dispatch("input");
  await harness.document.getElementById("polymarket-funding-confirm").dispatch("click");
  assert.equal(harness.scheduledCount(), 1);

  await harness.app.logout();
  assert.equal(harness.scheduledCount(), 0);
  await harness.runScheduled();
  assert.equal(continuePosts, 1);
});


test("a saved funding operation is read before progress and never replaced", async () => {
  const localStorage = new FakeStorage({
    [LIVE_STORAGE_KEYS.fundingAmount]: scoped("1.000000"),
    [LIVE_STORAGE_KEYS.fundingIdempotency]: scoped("stable-funding-key"),
    [LIVE_STORAGE_KEYS.fundingOperation]: scoped("pm_funding_1"),
  });
  let statusGets = 0;
  let continuePosts = 0;
  const harness = createHarness(({ method, url }) => {
    if (method === "GET" && url === "/miniapp/api/chat") {
      return { body: chatBody() };
    }
    if (
      method === "GET" &&
      url === "/miniapp/api/operations/polymarket/funding/pm_funding_1"
    ) {
      statusGets += 1;
      return { body: fundingBody({ amount_usdc: "1.000000" }) };
    }
    if (
      method === "POST" &&
      url === "/miniapp/api/operations/polymarket/funding/pm_funding_1/continue"
    ) {
      continuePosts += 1;
      return {
        body: fundingBody({
          status: "finalized",
          amount_usdc: "1.000000",
          next_action: "complete",
        }),
      };
    }
    throw new Error(`unexpected ${method} ${url}`);
  }, {
    localStorage,
    sessionStorage: new FakeStorage({ [STORAGE_KEYS.csrf]: "csrf" }),
  });

  await harness.app.start();

  assert.equal(statusGets, 1);
  assert.equal(continuePosts, 0);
  assert.equal(
    harness.calls.some((call) =>
      call.method === "POST" &&
      call.url === "/miniapp/api/operations/polymarket/funding"
    ),
    false,
  );
  assert.equal(harness.scheduledCount(), 1);
  await harness.runScheduled();
  assert.equal(continuePosts, 1);
});


test("a delayed old funding GET cannot revive a cleared shared operation", async () => {
  const statusGate = deferred();
  const localStorage = new FakeStorage({
    [`${STORAGE_KEYS.fundingAmount}:${STABLE_SCOPE_A}`]: scoped(
      "1.000000",
      STABLE_SCOPE_A,
    ),
    [`${STORAGE_KEYS.fundingIdempotency}:${STABLE_SCOPE_A}`]: scoped(
      "old-intent",
      STABLE_SCOPE_A,
    ),
    [`${STORAGE_KEYS.fundingOperation}:${STABLE_SCOPE_A}`]: scoped(
      "pm_old",
      STABLE_SCOPE_A,
    ),
  });
  const harness = createHarness(({ method, url }) => {
    if (method === "GET" && url === "/miniapp/api/chat") {
      return { body: chatBody() };
    }
    if (
      method === "GET" &&
      url === "/miniapp/api/operations/polymarket/funding/pm_old"
    ) return statusGate.promise;
    throw new Error(`unexpected ${method} ${url}`);
  }, {
    localStorage,
    sessionStorage: new FakeStorage({
      [STORAGE_KEYS.csrf]: "csrf",
      [STORAGE_KEYS.scope]: STABLE_SCOPE_A,
    }),
  });

  const starting = harness.app.start();
  for (let index = 0; index < 20; index += 1) {
    if (harness.calls.some((call) => call.url.endsWith("/pm_old"))) break;
    await Promise.resolve();
  }
  assert.equal(
    harness.calls.filter((call) => call.url.endsWith("/pm_old")).length,
    1,
  );
  localStorage.removeItem(
    `${STORAGE_KEYS.fundingOperation}:${STABLE_SCOPE_A}`,
  );
  localStorage.setItem(
    `${STORAGE_KEYS.fundingAmount}:${STABLE_SCOPE_A}`,
    scoped("2.000000", STABLE_SCOPE_A),
  );
  localStorage.setItem(
    `${STORAGE_KEYS.fundingIdempotency}:${STABLE_SCOPE_A}`,
    scoped("new-intent", STABLE_SCOPE_A),
  );
  localStorage.setItem(
    `${STORAGE_KEYS.fundingCreateUncertain}:${STABLE_SCOPE_A}`,
    scoped("true", STABLE_SCOPE_A),
  );
  statusGate.resolve({
    body: fundingBody({
      operation_id: "pm_old",
      status: "manual_review",
      next_action: "manual_review",
    }),
  });
  await starting;

  assert.equal(
    storedNamespacedValue(
      localStorage,
      STORAGE_KEYS.fundingOperation,
      STABLE_SCOPE_A,
    ),
    null,
  );
  assert.equal(
    storedNamespacedValue(
      localStorage,
      STORAGE_KEYS.fundingIdempotency,
      STABLE_SCOPE_A,
    ),
    "new-intent",
  );
  assert.equal(
    storedNamespacedValue(
      localStorage,
      STORAGE_KEYS.fundingCreateUncertain,
      STABLE_SCOPE_A,
    ),
    "true",
  );
});


test("a delayed create cannot overwrite another tab's idempotency", async () => {
  const createGate = deferred();
  const localStorage = new FakeStorage();
  const harness = createHarness(({ method, url }) => {
    if (method === "GET" && url === "/miniapp/api/chat") {
      return { body: chatBody() };
    }
    if (method === "POST" && url === "/miniapp/api/operations/polymarket/funding") {
      return createGate.promise;
    }
    throw new Error(`unexpected ${method} ${url}`);
  }, {
    localStorage,
    sessionStorage: new FakeStorage({
      [STORAGE_KEYS.csrf]: "csrf",
      [STORAGE_KEYS.scope]: STABLE_SCOPE_A,
    }),
  });
  await harness.app.start();
  const amount = harness.document.getElementById("polymarket-funding-amount");
  amount.value = "1";
  await amount.dispatch("input");
  const creating = harness.document.getElementById(
    "polymarket-funding-confirm",
  ).dispatch("click");
  for (let index = 0; index < 5; index += 1) await Promise.resolve();

  localStorage.setItem(
    `${STORAGE_KEYS.fundingIdempotency}:${STABLE_SCOPE_A}`,
    scoped("new-intent", STABLE_SCOPE_A),
  );
  localStorage.setItem(
    `${STORAGE_KEYS.fundingCreateUncertain}:${STABLE_SCOPE_A}`,
    scoped("true", STABLE_SCOPE_A),
  );
  createGate.resolve({
    status: 201,
    body: fundingBody({ operation_id: "pm_old" }),
  });
  await creating;

  assert.equal(
    storedNamespacedValue(
      localStorage,
      STORAGE_KEYS.fundingOperation,
      STABLE_SCOPE_A,
    ),
    null,
  );
  assert.equal(
    storedNamespacedValue(
      localStorage,
      STORAGE_KEYS.fundingIdempotency,
      STABLE_SCOPE_A,
    ),
    "new-intent",
  );
  assert.equal(
    storedNamespacedValue(
      localStorage,
      STORAGE_KEYS.fundingCreateUncertain,
      STABLE_SCOPE_A,
    ),
    "true",
  );
});


for (const rejection of [
  {
    status: 400,
    detail: "miniapp_invalid_request",
    message: /correct.*amount/i,
  },
  {
    status: 401,
    detail: "miniapp_unauthorized",
    message: /reopen.*Telegram/i,
  },
  {
    status: 403,
    detail: "miniapp_forbidden",
    message: /reopen.*Telegram/i,
  },
  {
    status: 404,
    detail: "miniapp_not_found",
    message: /unavailable/i,
  },
  {
    status: 422,
    detail: "miniapp_invalid_request",
    message: /correct.*amount/i,
  },
  {
    status: 429,
    detail: "miniapp_rate_limited",
    message: /not accepted/i,
  },
]) {
  test(`funding create ${rejection.status} is deterministic, not uncertain`, async () => {
    const harness = createHarness(({ method, url }) => {
      if (method === "GET" && url === "/miniapp/api/chat") {
        return { body: chatBody() };
      }
      if (
        method === "POST" &&
        url === "/miniapp/api/operations/polymarket/funding"
      ) {
        return { status: rejection.status, body: { detail: rejection.detail } };
      }
      throw new Error(`unexpected ${method} ${url}`);
    }, { sessionStorage: new FakeStorage({ [STORAGE_KEYS.csrf]: "csrf" }) });
    await harness.app.start();
    const amount = harness.document.getElementById("polymarket-funding-amount");
    amount.value = "1";
    await amount.dispatch("input");

    await harness.document.getElementById("polymarket-funding-confirm").dispatch("click");

    const statusText = harness.document.getElementById(
      "polymarket-funding-status",
    ).textContent;
    assert.match(statusText, rejection.message);
    assert.doesNotMatch(statusText, /uncertain/i);
    assert.equal(
      harness.calls.filter((call) => call.method === "POST").length,
      1,
    );
    assert.equal(
      storedValue(harness.localStorage, STORAGE_KEYS.fundingCreateUncertain),
      null,
    );
    assert.equal(
      storedValue(harness.localStorage, STORAGE_KEYS.fundingIdempotency),
      null,
    );
    assert.equal(
      storedValue(harness.localStorage, STORAGE_KEYS.fundingAmount),
      null,
    );
    assert.equal(harness.scheduledCount(), 0);
  });
}


test("a definite create rejection permits one fresh funding intent", async () => {
  const ids = [
    "11111111-2222-4333-8444-555555555555",
    "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee",
  ];
  let createPosts = 0;
  const harness = createHarness(({ method, url }) => {
    if (method === "GET" && url === "/miniapp/api/chat") {
      return { body: chatBody() };
    }
    if (method === "POST" && url === "/miniapp/api/operations/polymarket/funding") {
      createPosts += 1;
      return createPosts === 1
        ? { status: 400, body: { detail: "miniapp_invalid_request" } }
        : {
            status: 201,
            body: fundingBody({
              amount_usdc: "2.000000",
              status: "manual_review",
              next_action: "manual_review",
            }),
          };
    }
    throw new Error(`unexpected ${method} ${url}`);
  }, {
    randomUUID: () => ids.shift(),
    sessionStorage: new FakeStorage({ [STORAGE_KEYS.csrf]: "csrf" }),
  });
  await harness.app.start();
  const amount = harness.document.getElementById("polymarket-funding-amount");
  const confirm = harness.document.getElementById("polymarket-funding-confirm");
  amount.value = "1";
  await amount.dispatch("input");
  await confirm.dispatch("click");

  amount.value = "2";
  await amount.dispatch("input");
  await confirm.dispatch("click");

  const creates = harness.calls.filter((call) =>
    call.method === "POST" &&
    call.url === "/miniapp/api/operations/polymarket/funding"
  );
  assert.deepEqual(creates.map((call) => call.body), [
    {
      amount_usdc: "1.000000",
      idempotency_key: "11111111-2222-4333-8444-555555555555",
    },
    {
      amount_usdc: "2.000000",
      idempotency_key: "aaaaaaaa-bbbb-4ccc-8ddd-eeeeeeeeeeee",
    },
  ]);
});


for (const ambiguousStatus of [409, 503]) {
test(`funding create ${ambiguousStatus} remains uncertain and cannot be replayed`, async () => {
  let createPosts = 0;
  const harness = createHarness(({ method, url }) => {
    if (method === "GET" && url === "/miniapp/api/chat") {
      return { body: chatBody() };
    }
    if (
      method === "POST" &&
      url === "/miniapp/api/operations/polymarket/funding"
    ) {
      createPosts += 1;
      return {
        status: ambiguousStatus,
        body: {
          detail: ambiguousStatus === 409
            ? "miniapp_conflict"
            : "miniapp_unavailable",
        },
      };
    }
    throw new Error(`unexpected ${method} ${url}`);
  }, { sessionStorage: new FakeStorage({ [STORAGE_KEYS.csrf]: "csrf" }) });
  await harness.app.start();
  const amount = harness.document.getElementById("polymarket-funding-amount");
  const confirm = harness.document.getElementById("polymarket-funding-confirm");
  amount.value = "1";
  await amount.dispatch("input");

  await confirm.dispatch("click");
  await confirm.dispatch("click");

  assert.equal(createPosts, 1);
  assert.match(
    harness.document.getElementById("polymarket-funding-status").textContent,
    /uncertain.*not repeated/i,
  );
  assert.equal(confirm.disabled, true);
  assert.equal(
    storedValue(harness.localStorage, STORAGE_KEYS.fundingCreateUncertain),
    "true",
  );
  assert.equal(
    storedValue(harness.localStorage, STORAGE_KEYS.fundingIdempotency),
    "11111111-2222-4333-8444-555555555555",
  );
});
}


test("a lost funding create response is tombstoned and never replayed automatically", async () => {
  let createPosts = 0;
  const harness = createHarness(({ method, url }) => {
    if (method === "GET" && url === "/miniapp/api/chat") {
      return { body: chatBody() };
    }
    if (
      method === "POST" &&
      url === "/miniapp/api/operations/polymarket/funding"
    ) {
      createPosts += 1;
      throw new TypeError("response lost");
    }
    throw new Error(`unexpected ${method} ${url}`);
  }, { sessionStorage: new FakeStorage({ [STORAGE_KEYS.csrf]: "csrf" }) });
  await harness.app.start();
  const amount = harness.document.getElementById("polymarket-funding-amount");
  const confirm = harness.document.getElementById("polymarket-funding-confirm");
  amount.value = "1";
  await amount.dispatch("input");

  await confirm.dispatch("click");
  await confirm.dispatch("click");
  await harness.emitWindow("pageshow", { persisted: true });

  assert.equal(createPosts, 1);
  assert.match(
    harness.document.getElementById("polymarket-funding-status").textContent,
    /uncertain.*not repeated/i,
  );
  assert.equal(confirm.disabled, true);
  assert.equal(
    storedValue(harness.localStorage, STORAGE_KEYS.fundingCreateUncertain),
    "true",
  );
  assert.equal(
    storedValue(harness.localStorage, STORAGE_KEYS.fundingIdempotency),
    "11111111-2222-4333-8444-555555555555",
  );
});


test("an invalid successful create projection is uncertain and never replayed", async () => {
  let createPosts = 0;
  const harness = createHarness(({ method, url }) => {
    if (method === "GET" && url === "/miniapp/api/chat") {
      return { body: chatBody() };
    }
    if (
      method === "POST" &&
      url === "/miniapp/api/operations/polymarket/funding"
    ) {
      createPosts += 1;
      return {
        status: 201,
        body: fundingBody({ operation_id: "", next_action: "confirm" }),
      };
    }
    throw new Error(`unexpected ${method} ${url}`);
  }, { sessionStorage: new FakeStorage({ [STORAGE_KEYS.csrf]: "csrf" }) });
  await harness.app.start();
  const amount = harness.document.getElementById("polymarket-funding-amount");
  const confirm = harness.document.getElementById("polymarket-funding-confirm");
  amount.value = "1";
  await amount.dispatch("input");

  await confirm.dispatch("click");
  await confirm.dispatch("click");

  assert.equal(createPosts, 1);
  assert.match(
    harness.document.getElementById("polymarket-funding-status").textContent,
    /uncertain.*not repeated/i,
  );
  assert.equal(confirm.disabled, true);
  assert.equal(
    storedValue(harness.localStorage, STORAGE_KEYS.fundingCreateUncertain),
    "true",
  );
});


test("funding confirmation persists stable recovery ids before a manual state", async () => {
  const createGate = deferred();
  const forbiddenFields = [
    "user_id", "binding_id", "wallet", "destination", "reservation_id",
    "audit_event_id", "tx", "signer", "exchange", "credentials", "metadata",
  ];
  const harness = createHarness(({ method, url, headers, body }) => {
    if (method === "GET" && url === "/miniapp/api/chat") {
      return { body: chatBody() };
    }
    if (
      method === "POST" &&
      url === "/miniapp/api/operations/polymarket/funding"
    ) {
      assert.equal(headers["Content-Type"], "application/json");
      assert.equal(headers["X-Agentonomy-CSRF"], "csrf");
      assert.deepEqual(body, {
        amount_usdc: "1.250000",
        idempotency_key: "11111111-2222-4333-8444-555555555555",
      });
      for (const field of forbiddenFields) assert.equal(field in body, false);
      return createGate.promise;
    }
    throw new Error(`unexpected ${method} ${url}`);
  }, {
    localStorage: new FakeStorage(),
    sessionStorage: new FakeStorage({ [STORAGE_KEYS.csrf]: "csrf" }),
  });
  await harness.app.start();
  const amount = harness.document.getElementById("polymarket-funding-amount");
  const confirm = harness.document.getElementById("polymarket-funding-confirm");
  amount.value = "1.25";
  await amount.dispatch("input");

  const first = confirm.dispatch("click");
  await Promise.resolve();
  const duplicate = confirm.dispatch("click");
  await Promise.resolve();
  assert.equal(
    harness.calls.filter((call) =>
      call.method === "POST" &&
      call.url === "/miniapp/api/operations/polymarket/funding"
    ).length,
    1,
  );
  assert.equal(confirm.disabled, true);

  createGate.resolve({
    body: fundingBody({
      status: "manual_review",
      amount_usdc: "1.250000",
      next_action: "manual_review",
    }),
  });
  await Promise.all([first, duplicate]);

  assert.equal(
    storedValue(harness.localStorage, LIVE_STORAGE_KEYS.fundingAmount),
    "1.250000",
  );
  assert.equal(
    storedValue(harness.localStorage, LIVE_STORAGE_KEYS.fundingIdempotency),
    "11111111-2222-4333-8444-555555555555",
  );
  assert.equal(
    storedValue(harness.localStorage, LIVE_STORAGE_KEYS.fundingOperation),
    "pm_funding_1",
  );
  assert.match(
    harness.document.getElementById("polymarket-funding-status").textContent,
    /Funding manual review.*Chain not started.*Bridge not started.*Buying power not started/i,
  );
});


test("ambiguous funding continuation recovers with GET only and never mutates on page return", async () => {
  let continuePosts = 0;
  let statusGets = 0;
  const harness = createHarness(({ method, url, headers, body }) => {
    if (method === "GET" && url === "/miniapp/api/chat") {
      return { body: chatBody() };
    }
    if (
      method === "POST" &&
      url === "/miniapp/api/operations/polymarket/funding"
    ) {
      return { status: 201, body: fundingBody() };
    }
    if (
      method === "POST" &&
      url === "/miniapp/api/operations/polymarket/funding/pm_funding_1/continue"
    ) {
      continuePosts += 1;
      assert.equal(headers["X-Agentonomy-CSRF"], "csrf");
      assert.deepEqual(body, {});
      return { status: 503, body: { detail: "miniapp_unavailable" } };
    }
    if (
      method === "GET" &&
      url === "/miniapp/api/operations/polymarket/funding/pm_funding_1"
    ) {
      statusGets += 1;
      assert.equal("Origin" in headers, false);
      assert.equal("X-Agentonomy-CSRF" in headers, false);
      return {
        body: fundingBody({
          status: "created",
          chain_status: "not_started",
          bridge_status: "not_started",
          buying_power_status: "not_started",
          next_action: "confirm",
        }),
      };
    }
    throw new Error(`unexpected ${method} ${url}`);
  }, {
    sessionStorage: new FakeStorage({ [STORAGE_KEYS.csrf]: "csrf" }),
  });
  await harness.app.start();
  harness.document.getElementById("polymarket-funding-amount").value = "1.25";
  await harness.document.getElementById("polymarket-funding-confirm").dispatch("click");

  assert.equal(continuePosts, 1);
  assert.equal(statusGets, 1);
  assert.match(
    harness.document.getElementById("polymarket-funding-status").textContent,
    /created.*Chain not started/i,
  );

  await harness.emitWindow("pageshow", { persisted: true });
  assert.equal(harness.scheduledCount(), 0);
  await harness.document.getElementById("polymarket-funding-confirm").dispatch("click");
  assert.equal(continuePosts, 1);
  assert.equal(statusGets, 3);
});


test("an ambiguous continuation unlocks only after GET verifies a changed status", async () => {
  let continuePosts = 0;
  let statusGets = 0;
  const harness = createHarness(({ method, url }) => {
    if (method === "GET" && url === "/miniapp/api/chat") {
      return { body: chatBody() };
    }
    if (
      method === "POST" &&
      url === "/miniapp/api/operations/polymarket/funding"
    ) return { status: 201, body: fundingBody() };
    if (
      method === "POST" &&
      url === "/miniapp/api/operations/polymarket/funding/pm_funding_1/continue"
    ) {
      continuePosts += 1;
      if (continuePosts === 1) {
        return { status: 503, body: { detail: "miniapp_unavailable" } };
      }
      return {
        body: fundingBody({
          status: "finalized",
          chain_status: "confirmed",
          bridge_status: "credited",
          buying_power_status: "credited",
          next_action: "complete",
        }),
      };
    }
    if (
      method === "GET" &&
      url === "/miniapp/api/operations/polymarket/funding/pm_funding_1"
    ) {
      statusGets += 1;
      return {
        body: fundingBody({
          status: "submitted",
          chain_status: "pending",
          next_action: "processing",
        }),
      };
    }
    throw new Error(`unexpected ${method} ${url}`);
  }, { sessionStorage: new FakeStorage({ [STORAGE_KEYS.csrf]: "csrf" }) });
  await harness.app.start();
  harness.document.getElementById("polymarket-funding-amount").value = "1";

  await harness.document.getElementById("polymarket-funding-confirm").dispatch("click");

  assert.equal(continuePosts, 1);
  assert.equal(statusGets, 1);
  assert.equal(harness.scheduledCount(), 0);
  assert.equal(
    storedValue(harness.localStorage, STORAGE_KEYS.fundingRecoveryStatus),
    null,
  );

  await harness.document.getElementById("polymarket-funding-confirm").dispatch("click");

  assert.equal(statusGets, 2);
  assert.equal(continuePosts, 2);
  assert.equal(harness.scheduledCount(), 0);
  assert.equal(
    harness.document.getElementById("polymarket-funding-confirm").textContent,
    "Funding complete",
  );
});


test("pageshow restores both live drafts and checks saved ids without POST", async () => {
  const localStorage = new FakeStorage({
    [LIVE_STORAGE_KEYS.fundingAmount]: scoped("2.50"),
    [LIVE_STORAGE_KEYS.fundingIdempotency]: scoped("stable-funding-key"),
    [LIVE_STORAGE_KEYS.fundingOperation]: scoped("pm_funding_1"),
    [LIVE_STORAGE_KEYS.signingPreview]: scoped("preview-1"),
    [LIVE_STORAGE_KEYS.signingSession]: scoped("pm_sign_sess_123456789abc"),
    [LIVE_STORAGE_KEYS.signingSessionPreview]: scoped("preview-1"),
  });
  let fundingGets = 0;
  let signingGets = 0;
  const harness = createHarness(({ method, url, headers }) => {
    if (method === "GET" && url === "/miniapp/api/chat") {
      return { body: chatBody() };
    }
    if (
      method === "GET" &&
      url === "/miniapp/api/operations/polymarket/funding/pm_funding_1"
    ) {
      fundingGets += 1;
      assert.equal("Origin" in headers, false);
      assert.equal("X-Agentonomy-CSRF" in headers, false);
      return { body: fundingBody({ status: "bridge_pending", bridge_status: "pending" }) };
    }
    if (
      method === "GET" &&
      url === (
        "/miniapp/api/operations/polymarket/order-signing/" +
        "pm_sign_sess_123456789abc"
      )
    ) {
      signingGets += 1;
      assert.equal("Origin" in headers, false);
      assert.equal("X-Agentonomy-CSRF" in headers, false);
      return {
        body: signingBody({
          status: "submitted",
          execution_id: "pm_execution_1",
          signing_url: undefined,
          next_action: "check_status",
        }),
      };
    }
    throw new Error(`unexpected ${method} ${url}`);
  }, {
    localStorage,
    sessionStorage: new FakeStorage({ [STORAGE_KEYS.csrf]: "csrf" }),
  });

  await harness.app.start();
  assert.equal(
    harness.document.getElementById("polymarket-funding-amount").value,
    "2.50",
  );
  assert.equal(
    harness.document.getElementById("polymarket-signing-preview").value,
    "preview-1",
  );
  assert.equal(fundingGets, 1);
  assert.equal(signingGets, 1);
  assert.match(
    harness.document.getElementById("polymarket-signing-status").textContent,
    /submitted.*pm_execution_1/i,
  );

  harness.document.getElementById("polymarket-funding-amount").value = "";
  harness.document.getElementById("polymarket-signing-preview").value = "";
  await harness.emitWindow("pageshow");

  assert.equal(
    harness.document.getElementById("polymarket-funding-amount").value,
    "2.50",
  );
  assert.equal(
    harness.document.getElementById("polymarket-signing-preview").value,
    "preview-1",
  );
  assert.equal(fundingGets, 2);
  assert.equal(signingGets, 2);
  assert.equal(harness.calls.some((call) => call.method === "POST"), false);
});


test("order signing opens outside Telegram once without storing the capability", async () => {
  const createGate = deferred();
  const localStorage = new FakeStorage();
  const harness = createHarness(({ method, url, headers, body }) => {
    if (method === "GET" && url === "/miniapp/api/chat") {
      return { body: chatBody() };
    }
    if (
      method === "POST" &&
      url === "/miniapp/api/operations/polymarket/order-signing"
    ) {
      assert.equal(headers["Content-Type"], "application/json");
      assert.equal(headers["X-Agentonomy-CSRF"], "csrf");
      assert.deepEqual(body, { preview_id: "preview-1" });
      return createGate.promise;
    }
    throw new Error(`unexpected ${method} ${url}`);
  }, {
    localStorage,
    sessionStorage: new FakeStorage({ [STORAGE_KEYS.csrf]: "csrf" }),
    telegramOpenLink: true,
  });
  await harness.app.start();
  const preview = harness.document.getElementById("polymarket-signing-preview");
  const open = harness.document.getElementById("polymarket-signing-open");
  preview.value = "preview-1";
  await preview.dispatch("input");

  const first = open.dispatch("click");
  await Promise.resolve();
  const duplicate = open.dispatch("click");
  await Promise.resolve();
  assert.equal(
    harness.calls.filter((call) =>
      call.method === "POST" &&
      call.url === "/miniapp/api/operations/polymarket/order-signing"
    ).length,
    1,
  );
  assert.equal(open.disabled, true);

  createGate.resolve({ status: 201, body: signingBody() });
  await Promise.all([first, duplicate]);
  assert.deepEqual(harness.externalOpened, []);
  assert.deepEqual(harness.assigned, []);
  assert.equal(open.disabled, false);
  assert.match(
    harness.document.getElementById("polymarket-signing-status").textContent,
    /ready.*tap again.*browser/i,
  );
  for (const raw of localStorage.values.values()) {
    assert.doesNotMatch(raw, /opaque_browser_capability|signing_url/);
  }

  const opening = open.dispatch("click");
  assert.deepEqual(harness.externalOpened, [signingBody().signing_url]);
  assert.deepEqual(harness.assigned, []);
  await opening;
  assert.equal(
    harness.calls.filter((call) =>
      call.method === "POST" &&
      call.url === "/miniapp/api/operations/polymarket/order-signing"
    ).length,
    1,
  );
  assert.equal(
    storedValue(localStorage, LIVE_STORAGE_KEYS.signingSession),
    "pm_sign_sess_123456789abc",
  );
  assert.equal(
    storedValue(localStorage, LIVE_STORAGE_KEYS.signingSessionPreview),
    "preview-1",
  );
  for (const raw of localStorage.values.values()) {
    assert.doesNotMatch(raw, /opaque_browser_capability|signing_url/);
  }
  assert.deepEqual(harness.telegramVersionChecks, ["6.1", "6.1"]);
});


test("changing the preview discards an in-memory prepared signing capability", async () => {
  let posts = 0;
  const harness = createHarness(({ method, url }) => {
    if (method === "GET" && url === "/miniapp/api/chat") {
      return { body: chatBody() };
    }
    if (
      method === "POST" &&
      url === "/miniapp/api/operations/polymarket/order-signing"
    ) {
      posts += 1;
      return {
        status: 201,
        body: signingBody({ session_id: `pm_sign_sess_preview_${posts}` }),
      };
    }
    throw new Error(`unexpected ${method} ${url}`);
  }, {
    sessionStorage: new FakeStorage({ [STORAGE_KEYS.csrf]: "csrf" }),
    telegramOpenLink: true,
  });
  await harness.app.start();
  const preview = harness.document.getElementById("polymarket-signing-preview");
  const open = harness.document.getElementById("polymarket-signing-open");

  preview.value = "preview-a";
  await preview.dispatch("input");
  await open.dispatch("click");
  preview.value = "preview-b";
  await preview.dispatch("input");
  preview.value = "preview-a";
  await preview.dispatch("input");

  const reopening = open.dispatch("click");
  assert.deepEqual(harness.externalOpened, []);
  await reopening;
  assert.equal(posts, 2);
  assert.deepEqual(harness.externalOpened, []);
});


test("wallet surfaces use same-window navigation without Telegram openLink", async () => {
  const cases = [
    {
      endpoint: "/miniapp/api/operations/account",
      url: "https://www.agentonomy.xyz/account/session/fallback",
      operationIndex: 0,
      options: {
        telegramOpenLink: true,
        telegramVersionSupported: false,
      },
    },
    {
      endpoint: "/miniapp/api/operations/polymarket",
      url: "https://www.agentonomy.xyz/polymarket/binding-console/fallback",
      operationIndex: 2,
      options: { telegram: false },
    },
    {
      endpoint: "/miniapp/api/operations/polymarket/order-signing",
      url: signingBody().signing_url,
      previewId: "preview-fallback",
      options: {},
    },
  ];

  for (const scenario of cases) {
    const harness = createHarness(({ method, url }) => {
      if (method === "GET" && url === "/miniapp/api/chat") {
        return { body: chatBody() };
      }
      if (method === "POST" && url === scenario.endpoint) {
        return scenario.previewId
          ? { status: 201, body: signingBody({ signing_url: scenario.url }) }
          : { body: { url: scenario.url } };
      }
      throw new Error(`unexpected ${method} ${url}`);
    }, {
      ...scenario.options,
      sessionStorage: new FakeStorage({ [STORAGE_KEYS.csrf]: "csrf" }),
    });
    await harness.app.start();

    if (scenario.previewId) {
      const preview = harness.document.getElementById("polymarket-signing-preview");
      preview.value = scenario.previewId;
      await preview.dispatch("input");
      await harness.document.getElementById("polymarket-signing-open").dispatch("click");
    } else {
      await harness.document.operationLinks[scenario.operationIndex].dispatch("click");
    }

    assert.deepEqual(harness.assigned, [scenario.url]);
    assert.deepEqual(harness.externalOpened, []);
    if (scenario.options.telegramOpenLink) {
      assert.deepEqual(harness.telegramVersionChecks, ["6.1"]);
    }
  }
});


test("order signing rejects every non-exact same-origin signing URL", async () => {
  const unsafeUrls = [
    "https://attacker.invalid/execution/polymarket/order-signing-console/#access_token=x",
    "https://www.agentonomy.xyz/execution/polymarket/order-signing-sessions/x#access_token=x",
    "https://www.agentonomy.xyz/execution/polymarket/order-signing-console/?x=1#access_token=x",
    "https://www.agentonomy.xyz/execution/polymarket/order-signing-console/#access_token=x&extra=1",
    "https://www.agentonomy.xyz/execution/polymarket/order-signing-console/#missing=x",
    "https://user@www.agentonomy.xyz/execution/polymarket/order-signing-console/#access_token=x",
  ];
  for (const [index, signingUrl] of unsafeUrls.entries()) {
    const harness = createHarness(({ method, url }) => {
      if (method === "GET" && url === "/miniapp/api/chat") {
        return { body: chatBody() };
      }
      if (
        method === "POST" &&
        url === "/miniapp/api/operations/polymarket/order-signing"
      ) {
        return {
          status: 201,
          body: signingBody({
            session_id: `pm_sign_sess_unsafe_${index}`,
            signing_url: signingUrl,
          }),
        };
      }
      throw new Error(`unexpected ${method} ${url}`);
    }, { sessionStorage: new FakeStorage({ [STORAGE_KEYS.csrf]: "csrf" }) });
    await harness.app.start();
    const preview = harness.document.getElementById("polymarket-signing-preview");
    preview.value = `preview-${index}`;
    await preview.dispatch("input");
    await harness.document.getElementById("polymarket-signing-open").dispatch("click");

    assert.deepEqual(harness.assigned, []);
    assert.match(
      harness.document.getElementById("polymarket-signing-status").textContent,
      /invalid.*signing link|signing link.*invalid/i,
    );
    assert.equal(
      harness.calls.filter((call) => call.method === "POST").length,
      1,
    );
  }
});


test("unknown order creation tombstones that preview until the user enters a new one", async () => {
  let createPosts = 0;
  const harness = createHarness(({ method, url }) => {
    if (method === "GET" && url === "/miniapp/api/chat") {
      return { body: chatBody() };
    }
    if (
      method === "POST" &&
      url === "/miniapp/api/operations/polymarket/order-signing"
    ) {
      createPosts += 1;
      return {
        status: 503,
        body: {
          detail: "miniapp_order_signing_outcome_unknown",
          next_action: "create_new_preview_or_manual_reconcile",
        },
      };
    }
    throw new Error(`unexpected ${method} ${url}`);
  }, { sessionStorage: new FakeStorage({ [STORAGE_KEYS.csrf]: "csrf" }) });
  await harness.app.start();
  const preview = harness.document.getElementById("polymarket-signing-preview");
  const open = harness.document.getElementById("polymarket-signing-open");
  preview.value = "preview-unknown";
  await preview.dispatch("input");
  await open.dispatch("click");

  assert.equal(createPosts, 1);
  assert.equal(
    storedValue(harness.localStorage, LIVE_STORAGE_KEYS.signingUnknownPreview),
    "preview-unknown",
  );
  assert.match(
    harness.document.getElementById("polymarket-signing-status").textContent,
    /new preview.*manual/i,
  );

  await harness.emitWindow("pageshow", { persisted: true });
  await open.dispatch("click");
  assert.equal(createPosts, 1);

  preview.value = "preview-new";
  await preview.dispatch("input");
  await open.dispatch("click");
  assert.equal(createPosts, 2);
});


test("a live-operation 404 disables both cards and performs no later I/O", async () => {
  const harness = createHarness(({ method, url }) => {
    if (method === "GET" && url === "/miniapp/api/chat") {
      return { body: chatBody() };
    }
    if (
      method === "POST" &&
      url === "/miniapp/api/operations/polymarket/funding"
    ) {
      return { status: 404, body: { detail: "miniapp_not_found" } };
    }
    throw new Error(`unexpected ${method} ${url}`);
  }, { sessionStorage: new FakeStorage({ [STORAGE_KEYS.csrf]: "csrf" }) });
  await harness.app.start();
  harness.document.getElementById("polymarket-funding-amount").value = "1.25";
  await harness.document.getElementById("polymarket-funding-confirm").dispatch("click");

  const callsAfter404 = harness.calls.length;
  for (const id of [
    "polymarket-funding-confirm",
    "polymarket-signing-open",
    "polymarket-signing-check",
  ]) {
    assert.equal(harness.document.getElementById(id).disabled, true);
    await harness.document.getElementById(id).dispatch("click");
  }
  await harness.emitWindow("pageshow");
  assert.equal(harness.calls.length, callsAfter404);
  assert.match(
    harness.document.getElementById("polymarket-funding-status").textContent,
    /unavailable/i,
  );
  assert.match(
    harness.document.getElementById("polymarket-signing-status").textContent,
    /unavailable/i,
  );
});


test("pageshow cannot unlock a deferred funding mutation", async () => {
  const createGate = deferred();
  let createPosts = 0;
  let continuePosts = 0;
  const harness = createHarness(({ method, url }) => {
    if (method === "GET" && url === "/miniapp/api/chat") {
      return { body: chatBody() };
    }
    if (
      method === "POST" &&
      url === "/miniapp/api/operations/polymarket/funding"
    ) {
      createPosts += 1;
      return createGate.promise;
    }
    if (
      method === "POST" &&
      url === "/miniapp/api/operations/polymarket/funding/pm_funding_1/continue"
    ) {
      continuePosts += 1;
      return { body: fundingBody({ status: "confirmed", next_action: "processing" }) };
    }
    throw new Error(`unexpected ${method} ${url}`);
  }, { sessionStorage: new FakeStorage({ [STORAGE_KEYS.csrf]: "csrf" }) });
  await harness.app.start();
  const amount = harness.document.getElementById("polymarket-funding-amount");
  amount.value = "1.25";
  await amount.dispatch("input");

  const creating = harness.document.getElementById("polymarket-funding-confirm").dispatch("click");
  await Promise.resolve();
  const returning = harness.emitWindow("pageshow", { persisted: true });
  await Promise.resolve();
  const duplicate = harness.document.getElementById("polymarket-funding-confirm").dispatch("click");
  await Promise.resolve();
  const postsWhileDeferred = createPosts;

  createGate.resolve({ status: 201, body: fundingBody() });
  await Promise.all([creating, returning, duplicate]);
  assert.equal(postsWhileDeferred, 1);
  assert.equal(createPosts, 1);

  assert.equal(continuePosts, 1);
});


test("pageshow cannot unlock a deferred signing mutation", async () => {
  const signingGate = deferred();
  let createPosts = 0;
  const harness = createHarness(({ method, url, body }) => {
    if (method === "GET" && url === "/miniapp/api/chat") {
      return { body: chatBody() };
    }
    if (
      method === "POST" &&
      url === "/miniapp/api/operations/polymarket/order-signing"
    ) {
      createPosts += 1;
      if (body.preview_id === "preview-a") return signingGate.promise;
      return {
        status: 201,
        body: signingBody({
          session_id: "pm_sign_sess_for_preview_b",
          signing_url: (
            "https://www.agentonomy.xyz/execution/polymarket/" +
            "order-signing-console/#access_token=preview_b_capability"
          ),
        }),
      };
    }
    throw new Error(`unexpected ${method} ${url}`);
  }, { sessionStorage: new FakeStorage({ [STORAGE_KEYS.csrf]: "csrf" }) });
  await harness.app.start();
  const preview = harness.document.getElementById("polymarket-signing-preview");
  const open = harness.document.getElementById("polymarket-signing-open");
  preview.value = "preview-a";
  await preview.dispatch("input");

  const creating = open.dispatch("click");
  await Promise.resolve();
  const disabledWhileDeferred = preview.disabled;
  const returning = harness.emitWindow("pageshow", { persisted: true });
  await Promise.resolve();
  const duplicate = open.dispatch("click");
  await Promise.resolve();
  const postsWhileDeferred = createPosts;

  signingGate.resolve({ status: 201, body: signingBody() });
  await Promise.all([creating, returning, duplicate]);
  assert.equal(disabledWhileDeferred, true);
  assert.equal(postsWhileDeferred, 1);
  assert.equal(createPosts, 1);
  assert.equal(preview.disabled, false);

  preview.value = "preview-b";
  await preview.dispatch("input");
  await open.dispatch("click");
  assert.equal(createPosts, 2);
});


test("a late signing response cannot replace a newly selected preview", async () => {
  const signingGate = deferred();
  const localStorage = new FakeStorage();
  const harness = createHarness(({ method, url }) => {
    if (method === "GET" && url === "/miniapp/api/chat") {
      return { body: chatBody() };
    }
    if (
      method === "POST" &&
      url === "/miniapp/api/operations/polymarket/order-signing"
    ) return signingGate.promise;
    throw new Error(`unexpected ${method} ${url}`);
  }, {
    localStorage,
    sessionStorage: new FakeStorage({ [STORAGE_KEYS.csrf]: "csrf" }),
  });
  await harness.app.start();
  const preview = harness.document.getElementById("polymarket-signing-preview");
  preview.value = "preview-a";
  await preview.dispatch("input");
  const creating = harness.document.getElementById("polymarket-signing-open").dispatch("click");
  await Promise.resolve();
  const disabledWhileDeferred = preview.disabled;

  preview.value = "preview-b";
  await preview.dispatch("input");
  const stateAfterChange = harness.document.getElementById(
    "polymarket-signing-status",
  ).textContent;
  signingGate.resolve({ status: 201, body: signingBody() });
  await creating;

  assert.equal(disabledWhileDeferred, true);
  assert.equal(
    storedValue(localStorage, LIVE_STORAGE_KEYS.signingPreview),
    "preview-b",
  );
  assert.equal(localStorage.getItem(LIVE_STORAGE_KEYS.signingSession), null);
  assert.equal(localStorage.getItem(LIVE_STORAGE_KEYS.signingSessionPreview), null);
  assert.deepEqual(harness.assigned, []);
  assert.match(stateAfterChange, /preview changed/i);
  assert.equal(
    harness.document.getElementById("polymarket-signing-status").textContent,
    stateAfterChange,
  );
});


test("logout invalidates deferred funding and signing responses before revocation returns", async () => {
  for (const operation of ["funding", "signing"]) {
    const mutationGate = deferred();
    const logoutGate = deferred();
    const localStorage = new FakeStorage();
    const harness = createHarness(({ method, url }) => {
      if (method === "GET" && url === "/miniapp/api/chat") {
        return { body: chatBody() };
      }
      if (method === "DELETE" && url === "/miniapp/api/session") {
        return logoutGate.promise;
      }
      if (
        operation === "funding" &&
        method === "POST" &&
        url === "/miniapp/api/operations/polymarket/funding"
      ) return mutationGate.promise;
      if (
        operation === "signing" &&
        method === "POST" &&
        url === "/miniapp/api/operations/polymarket/order-signing"
      ) return mutationGate.promise;
      throw new Error(`unexpected ${method} ${url}`);
    }, {
      localStorage,
      sessionStorage: new FakeStorage({ [STORAGE_KEYS.csrf]: "csrf" }),
    });
    await harness.app.start();
    let mutation;
    if (operation === "funding") {
      const amount = harness.document.getElementById("polymarket-funding-amount");
      amount.value = "1.25";
      await amount.dispatch("input");
      mutation = harness.document.getElementById("polymarket-funding-confirm").dispatch("click");
    } else {
      const preview = harness.document.getElementById("polymarket-signing-preview");
      preview.value = "preview-logout";
      await preview.dispatch("input");
      mutation = harness.document.getElementById("polymarket-signing-open").dispatch("click");
    }
    await Promise.resolve();

    const loggingOut = harness.app.logout();
    await Promise.resolve();
    mutationGate.resolve({
      status: 201,
      body: operation === "funding" ? fundingBody() : signingBody(),
    });
    await mutation;

    for (const key of Object.values(STORAGE_KEYS)) {
      assert.equal(harness.sessionStorage.getItem(key), null);
      assert.equal(localStorage.getItem(key), null);
    }
    for (const id of [
      "polymarket-funding-confirm",
      "polymarket-signing-open",
      "polymarket-signing-check",
    ]) assert.equal(harness.document.getElementById(id).disabled, true);
    assert.deepEqual(harness.assigned, []);
    assert.doesNotMatch(
      harness.document.getElementById("polymarket-funding-status").textContent,
      /Funding created/i,
    );
    assert.doesNotMatch(
      harness.document.getElementById("polymarket-signing-status").textContent,
      /Signing pending/i,
    );

    logoutGate.resolve({ status: 204, body: null });
    await loggingOut;
  }
});


test("operation drawer closes on Escape and restores focus to its toggle", async () => {
  const harness = createHarness(({ method, url }) => {
    if (method === "GET" && url === "/miniapp/api/chat") return { body: chatBody() };
    throw new Error(`unexpected ${method} ${url}`);
  }, { sessionStorage: new FakeStorage({ [STORAGE_KEYS.csrf]: "csrf" }) });
  await harness.app.start();

  const drawer = harness.document.getElementById("miniapp-operations");
  const toggle = harness.document.getElementById("miniapp-operations-toggle");
  await toggle.dispatch("click");
  assert.equal(drawer.hidden, false);
  assert.equal(toggle.getAttribute("aria-expanded"), "true");

  harness.emitWindow("keydown", { key: "Escape" });

  assert.equal(drawer.hidden, true);
  assert.equal(toggle.getAttribute("aria-expanded"), "false");
  assert.equal(toggle.focused, true);
});


test("document visibility disconnect closes once and switches to status polling", async () => {
  const clientId = "11111111-2222-4333-8444-555555555555";
  let runChecks = 0;
  const harness = createHarness(({ method, url }) => {
    if (method === "GET" && url === "/miniapp/api/chat") {
      return { body: chatBody() };
    }
    if (method === "POST" && url === "/miniapp/api/chat/messages") {
      return {
        status: 202,
        body: { client_message_id: clientId, status: "accepted" },
      };
    }
    if (method === "GET" && url.endsWith("/run")) {
      runChecks += 1;
      return {
        body: { client_message_id: clientId, status: "running" },
      };
    }
    throw new Error(`unexpected ${method} ${url}`);
  }, { sessionStorage: new FakeStorage({ [STORAGE_KEYS.csrf]: "csrf" }) });
  await harness.app.start();
  harness.document.getElementById("miniapp-input").value = "question";
  await harness.app.sendCurrentMessage();

  const firstStream = FakeEventSource.instances[0];
  harness.document.visibilityState = "hidden";
  await harness.emitDocument("visibilitychange");
  assert.equal(firstStream.closed, true);
  assert.equal(runChecks, 1);
  assert.equal(FakeEventSource.instances.length, 1);

  harness.document.visibilityState = "visible";
  await harness.emitDocument("visibilitychange");
  assert.equal(runChecks, 2);
  assert.equal(FakeEventSource.instances.length, 1);
});


test("logout revokes session and clears every Mini App browser state item", async () => {
  const clientId = "11111111-2222-4333-8444-555555555555";
  const sessionStorage = new FakeStorage({
    [STORAGE_KEYS.csrf]: "csrf",
    [STORAGE_KEYS.clientNonce]: "nonce",
  });
  const localStorage = new FakeStorage({
    [STORAGE_KEYS.draft]: "draft",
    [STORAGE_KEYS.currentClientMessage]: clientId,
    [STORAGE_KEYS.scroll]: "22",
    [STORAGE_KEYS.returnMarker]: "marker",
    [STORAGE_KEYS.fundingPreparedMessage]: scoped(clientId),
    [STORAGE_KEYS.fundingMessageAmount]: scoped(JSON.stringify({
      client_message_id: clientId,
      amount: "1.000000",
    })),
  });
  const harness = createHarness(({ method, url, headers }) => {
    if (method === "GET" && url === "/miniapp/api/chat") return { body: chatBody() };
    if (method === "DELETE" && url === "/miniapp/api/session") {
      assert.equal(headers["X-Agentonomy-CSRF"], "csrf");
      return { status: 204, body: null };
    }
    throw new Error(`unexpected ${method} ${url}`);
  }, { sessionStorage, localStorage });
  await harness.app.start();
  await harness.app.logout();

  for (const key of Object.values(STORAGE_KEYS)) {
    assert.equal(sessionStorage.getItem(key), null);
    assert.equal(localStorage.getItem(key), null);
  }
  assert.equal(harness.document.getElementById("miniapp-transcript").children.length, 0);
});


test("standalone mode safely loads an existing cookie and never fabricates Telegram identity", async () => {
  const harness = createHarness(({ method, url }) => {
    assert.equal(method, "GET");
    assert.equal(url, "/miniapp/api/chat");
    return { body: chatBody([{ id: 1, role: "assistant", content: "Welcome back", timestamp: 1 }]) };
  }, { telegram: false, sessionStorage: new FakeStorage({ [STORAGE_KEYS.csrf]: "csrf" }) });
  await harness.app.start();
  assert.equal(harness.calls.length, 1);
  assert.equal(harness.document.getElementById("miniapp-identity").textContent, "Secure browser session");
  assert.match(harness.document.getElementById("miniapp-transcript").children[0].children[1].textContent, /Welcome back/);
});


test("Telegram SDK without initData remains a standalone browser session", async () => {
  const harness = createHarness(({ method, url }) => {
    assert.equal(method, "GET");
    assert.equal(url, "/miniapp/api/chat");
    return { body: chatBody() };
  }, {
    initData: "",
    sessionStorage: new FakeStorage({ [STORAGE_KEYS.csrf]: "csrf" }),
  });

  await harness.app.start();

  assert.equal(harness.telegram.readyCalls, 1);
  assert.equal(harness.telegram.expandCalls, 1);
  assert.equal(
    harness.document.getElementById("miniapp-identity").textContent,
    "Secure browser session",
  );
  assert.equal(
    harness.calls.filter((call) => call.url === "/miniapp/api/session").length,
    0,
  );
});
