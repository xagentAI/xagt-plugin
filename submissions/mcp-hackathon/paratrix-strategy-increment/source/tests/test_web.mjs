import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";
import vm from "node:vm";

const html = readFileSync(new URL("../web/index.html", import.meta.url), "utf8");
const script = readFileSync(new URL("../web/app.js", import.meta.url), "utf8");

class Node {
  constructor(tag = "div") {
    this.tagName = tag;
    this.children = [];
    this.listeners = new Map();
    this.disabled = false;
    this.hidden = true;
    this.value = "";
    this.classList = { toggle() {} };
  }

  append(...nodes) { this.children.push(...nodes); }
  replaceChildren(...nodes) { this.children = [...nodes]; }
  get firstChild() { return this.children[0]; }
  setAttribute(name, value) { this[name] = value; }
  addEventListener(name, listener) { this.listeners.set(name, listener); }
  querySelectorAll() { return []; }
}

function workbench() {
  const nodes = new Map([...html.matchAll(/<(\w+)[^>]*\bid="([^"]+)"/g)]
    .map(([, tag, id]) => [id, new Node(tag)]));
  const formHtml = html.slice(html.indexOf('<form id="experiment-form"'), html.indexOf("</form>"));
  const controls = [...formHtml.matchAll(/<(button|input|select)[^>]*\bid="([^"]+)"/g)]
    .map(([, , id]) => nodes.get(id));
  const radios = [new Node("input"), new Node("input")];
  radios[0].value = "facts";
  radios[1].value = "criteria";
  nodes.get("experiment-form").querySelectorAll = () => [...controls, ...radios];
  const document = {
    body: new Node("body"),
    getElementById: (id) => nodes.get(id),
    createElement: (tag) => new Node(tag),
    querySelectorAll: () => radios,
  };
  const requests = [];
  const context = vm.createContext({
    document,
    Intl,
    fetch(path, options) {
      return new Promise((resolve, reject) => requests.push({
        path, options, reject,
        respond(payload, ok = true) {
          resolve({ ok, status: ok ? 200 : 422, json: async () => payload });
        },
      }));
    },
  });
  const initialization = vm.runInContext(script, context);
  return { nodes, controls, requests, initialization, context };
}

const nextTurn = () => new Promise((resolve) => setImmediate(resolve));

test("bootstrap blocks writes until the cookie-establishing request and history read finish", async () => {
  const app = workbench();
  assert.equal(app.requests.length, 1);
  assert.equal(app.requests[0].path, "/v1/demo-cases");
  assert.ok(app.controls.every((control) => control.disabled));
  assert.equal(app.nodes.get("refresh-history").disabled, true);

  const upload = app.nodes.get("baseline-file");
  upload.files = [{ size: 2, text: async () => "{}" }];
  await upload.listeners.get("change")({ target: upload });
  await app.nodes.get("experiment-form").listeners.get("submit")({ preventDefault() {} });
  assert.equal(app.requests.length, 1, "interaction must not race first-session establishment");

  app.requests[0].respond({ cases: [] });
  await nextTurn();
  assert.equal(app.requests[1].path, "/v1/experiments");
  assert.ok(app.controls.every((control) => control.disabled));
  app.requests[1].respond({ experiments: [] });
  await app.initialization;
  assert.ok(app.controls.every((control) => !control.disabled));
  assert.equal(app.nodes.get("refresh-history").disabled, false);
});

test("bootstrap failure restores controls and permits an independent JSON import", async () => {
  const app = workbench();
  app.requests[0].reject(new Error("Network disconnected"));
  await app.initialization;
  assert.equal(app.nodes.get("service-message").hidden, false);
  assert.ok(app.nodes.get("service-message").textContent.length > 0);
  assert.ok(app.controls.every((control) => !control.disabled));
  assert.equal(app.requests.length, 1, "do not issue parallel session-minting fallback reads");

  const upload = app.nodes.get("baseline-file");
  upload.files = [{ size: 2, text: async () => "{}" }];
  const importing = upload.listeners.get("change")({ target: upload });
  await nextTurn();
  assert.equal(app.requests[1].path, "/v1/data-snapshots");
  assert.equal(app.requests[1].options.body, '{"curve":{}}');
  app.requests[1].respond({ error: { code: "invalid_input", message: "Missing curve fields." } }, false);
  await importing;
  assert.equal(app.nodes.get("form-error").hidden, false);
  assert.ok(app.controls.every((control) => !control.disabled));
});

test("an older history response cannot replace the result of a newer refresh", async () => {
  const app = workbench();
  app.requests[0].respond({ cases: [] });
  await nextTurn();
  app.requests[1].respond({ experiments: [] });
  await app.initialization;

  const older = vm.runInContext("refreshHistory()", app.context);
  const newer = vm.runInContext("refreshHistory()", app.context);
  const latest = {
    experiment_id: "e_newer",
    created_at: "2026-09-25T00:00:00Z",
    status: "comparison_only",
    baseline_name: "New baseline",
    candidate_name: "New candidate",
    mode: "historical_exploration",
  };
  app.requests[3].respond({ experiments: [latest] });
  await newer;
  const list = app.nodes.get("experiment-history");
  const displayedName = () => list.children[0].children[0].children[0].textContent;
  assert.equal(displayedName(), "New baseline + New candidate");
  app.requests[2].respond({ experiments: [] });
  await older;
  assert.equal(displayedName(), "New baseline + New candidate");

  const staleFailure = vm.runInContext("refreshHistory()", app.context);
  const freshSuccess = vm.runInContext("refreshHistory()", app.context);
  app.requests[5].respond({ experiments: [latest] });
  await freshSuccess;
  app.requests[4].reject(new Error("Stale request disconnected"));
  await staleFailure;
  assert.equal(displayedName(), "New baseline + New candidate");
});
