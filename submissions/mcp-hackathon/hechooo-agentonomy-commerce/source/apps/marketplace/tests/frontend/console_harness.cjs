"use strict";

const fs = require("node:fs");
const path = require("node:path");
const vm = require("node:vm");

class FakeElement {
  constructor(tagName = "div", id = "") {
    this.tagName = tagName.toUpperCase();
    this.id = id;
    this.name = "";
    this.value = "";
    this.textContent = "";
    this.className = "";
    this.type = "";
    this.children = [];
    this.listeners = new Map();
    this.focused = false;
  }

  append(...children) {
    this.children.push(...children);
  }

  prepend(...children) {
    this.children.unshift(...children);
  }

  replaceChildren(...children) {
    this.children = [...children];
  }

  addEventListener(type, handler) {
    const handlers = this.listeners.get(type) || [];
    handlers.push(handler);
    this.listeners.set(type, handlers);
  }

  focus() {
    this.focused = true;
  }

  async dispatch(type, values = {}) {
    const event = {
      target: this,
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
  constructor(ids) {
    this.elements = new Map(ids.map((id) => [id, new FakeElement("div", id)]));
  }

  getElementById(id) {
    return this.elements.get(id) || null;
  }

  createElement(tagName) {
    return new FakeElement(tagName);
  }
}

class FakeSessionStorage {
  constructor() {
    this.values = new Map();
  }

  getItem(key) {
    return this.values.has(key) ? this.values.get(key) : null;
  }

  setItem(key, value) {
    this.values.set(key, String(value));
  }
}

function deepText(element) {
  return [element.textContent, ...element.children.map(deepText)].filter(Boolean).join(" ");
}

function findByText(element, text) {
  if (element.textContent === text) return element;
  for (const child of element.children) {
    const match = findByText(child, text);
    if (match) return match;
  }
  return null;
}

function jsonResponse(body, status = 200) {
  return {
    ok: status >= 200 && status < 300,
    status,
    headers: { get: (name) => name.toLowerCase() === "content-type" ? "application/json" : null },
    async json() {
      return body;
    },
    async text() {
      return JSON.stringify(body);
    },
  };
}

function recordingFetch(route) {
  const calls = [];
  const fetch = async (url, options = {}) => {
    const call = {
      url: String(url),
      method: options.method || "GET",
      headers: options.headers || {},
      body: options.body === undefined ? undefined : JSON.parse(options.body),
    };
    calls.push(call);
    return jsonResponse(await route(call));
  };
  return { calls, fetch };
}

function loadFactory(relativePath, exportName) {
  const filename = path.resolve(__dirname, "../..", relativePath);
  const source = fs.readFileSync(filename, "utf8");
  const module = { exports: {} };
  const context = vm.createContext({
    module,
    exports: module.exports,
    URLSearchParams,
    encodeURIComponent,
    JSON,
    Date,
  });
  new vm.Script(source, { filename }).runInContext(context);
  return module.exports[exportName];
}

function assertAuthorized(call, token) {
  if (!call) throw new Error("expected request was not recorded");
  if (call.headers.Authorization !== `Bearer ${token}`) {
    throw new Error(`missing bearer token for ${call.method} ${call.url}`);
  }
}

module.exports = {
  FakeDocument,
  FakeSessionStorage,
  assertAuthorized,
  deepText,
  findByText,
  loadFactory,
  recordingFetch,
};
