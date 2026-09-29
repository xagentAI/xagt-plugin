"use strict";

const assert = require("node:assert/strict");
const test = require("node:test");

const {
  FakeDocument,
  FakeSessionStorage,
  assertAuthorized,
  deepText,
  findByText,
  loadFactory,
  recordingFetch,
} = require("./console_harness.cjs");

const WALLET = "0x1111111111111111111111111111111111111111";
const TOKEN = "console-session-token";

function callFor(calls, method, url) {
  return calls.find((call) => call.method === method && call.url === url);
}

function plain(value) {
  return JSON.parse(JSON.stringify(value));
}

function walletHarness() {
  const calls = [];
  const ethereum = {
    async request(request) {
      calls.push(request);
      if (request.method === "eth_requestAccounts") return [WALLET];
      if (request.method === "personal_sign") return "0xpersonal-signature";
      if (request.method === "eth_signTypedData_v4") return "0xtyped-signature";
      throw new Error(`unexpected wallet method ${request.method}`);
    },
  };
  return { calls, ethereum };
}

test("merchant console executes the complete wallet and offering workflow", async () => {
  const createMerchantConsole = loadFactory("web/assets/merchant.js", "createMerchantConsole");
  assert.equal(typeof createMerchantConsole, "function");

  const ids = [
    "operation-log", "auth-result", "wallet-state", "connect-wallet",
    "candidate-form", "candidate-query", "candidate-domain", "candidate-pay-to",
    "candidate-result", "candidate-list", "manifest-editor", "submit-manifest",
    "manifest-result", "sign-claim", "claim-result", "verify-domain", "domain-result",
    "refresh-portfolio", "provider-list", "manifest-list", "provider-count", "portfolio-result",
  ];
  const document = new FakeDocument(ids);
  document.getElementById("candidate-query").name = "query";
  document.getElementById("candidate-domain").name = "domain";
  document.getElementById("candidate-pay-to").name = "pay_to";
  const sessionStorage = new FakeSessionStorage();
  const wallet = walletHarness();
  let offeringStatus = "active";
  const manifest = {
    manifest_version: "1",
    provider: { name: "Example merchant", domain: "merchant.example" },
    offerings: [{ offering_id: "offering-1", name: "Checkout" }],
  };
  const providerRecord = () => ({
    provider: {
      provider_id: "provider-1",
      name: "Example merchant",
      domain: "merchant.example",
      status: "active",
    },
    offerings: [{ offering_id: "offering-1", name: "Checkout", status: offeringStatus }],
  });
  const manifestRecord = {
    manifest_id: "manifest-1",
    provider_id: "provider-1",
    provider_name: "Example merchant",
    domain: "merchant.example",
    offering_count: 1,
    status: "pending_claim",
  };
  const api = recordingFetch(async ({ method, url }) => {
    if (method === "GET" && url === "/auth/siwe/config") {
      return { allowed_domains: ["marketplace.example"] };
    }
    if (method === "POST" && url === "/auth/siwe/challenge") {
      return { nonce: "nonce-1", message: "Sign in to Clink Marketplace" };
    }
    if (method === "POST" && url === "/auth/siwe/verify") {
      return { access_token: TOKEN, wallet_address: WALLET };
    }
    if (method === "GET" && url === "/merchant/providers") {
      return { count: 1, providers: [providerRecord()] };
    }
    if (method === "GET" && url === "/merchant/manifests") {
      return { count: 1, manifests: [manifestRecord] };
    }
    if (method === "GET" && url === "/merchant/candidates?query=checkout&domain=merchant.example&pay_to=0x2222") {
      return {
        count: 1,
        candidates: [{
          provider: { domain: "merchant.example" },
          offering: {
            offering_id: "offering-1",
            name: "Checkout",
            method: "POST",
            endpoint: "/pay",
            status: "candidate",
          },
        }],
      };
    }
    if (method === "POST" && url === "/merchant/candidates/offering-1/claim-draft") {
      return { manifest };
    }
    if (method === "POST" && url === "/merchant/manifests") {
      return { manifest_id: "manifest-1", provider_id: "provider-1", status: "pending_claim" };
    }
    if (method === "POST" && url === "/merchant/manifests/manifest-1/claim-challenge") {
      return { claim: { manifest_id: "manifest-1" }, typed_data: { primaryType: "ManifestClaim" } };
    }
    if (method === "POST" && url === "/merchant/manifests/manifest-1/submit-claim") {
      return { provider_id: "provider-1", status: "pending_domain" };
    }
    if (method === "POST" && url === "/merchant/providers/provider-1/verify-domain") {
      return { provider_id: "provider-1", status: "active" };
    }
    if (method === "GET" && url === "/merchant/providers/provider-1/status") {
      return providerRecord();
    }
    if (method === "POST" && url === "/merchant/offerings/offering-1/verify") {
      offeringStatus = "verified";
      return { offering_id: "offering-1", status: offeringStatus };
    }
    if (method === "POST" && url === "/merchant/offerings/offering-1/disable") {
      offeringStatus = "disabled";
      return { offering_id: "offering-1", status: offeringStatus };
    }
    throw new Error(`unexpected API request ${method} ${url}`);
  });
  const window = {
    ethereum: wallet.ethereum,
    location: { host: "marketplace.example", hostname: "marketplace.example" },
  };

  createMerchantConsole({ document, window, fetch: api.fetch, sessionStorage });

  await document.getElementById("connect-wallet").dispatch("click");
  assert.match(document.getElementById("auth-result").textContent, /SIWE session active/);
  assert.equal(sessionStorage.getItem("clink.marketplace.session"), TOKEN);
  assert.deepEqual(plain(wallet.calls[0]), { method: "eth_requestAccounts" });
  assert.deepEqual(plain(wallet.calls[1]), {
    method: "personal_sign",
    params: ["Sign in to Clink Marketplace", WALLET],
  });
  assert.deepEqual(callFor(api.calls, "POST", "/auth/siwe/challenge").body, {
    address: WALLET,
    domain: "marketplace.example",
  });
  assert.deepEqual(callFor(api.calls, "POST", "/auth/siwe/verify").body, {
    address: WALLET,
    nonce: "nonce-1",
    message: "Sign in to Clink Marketplace",
    signature: "0xpersonal-signature",
  });
  assert.equal(callFor(api.calls, "POST", "/auth/siwe/verify").headers.Authorization, undefined);
  assertAuthorized(callFor(api.calls, "GET", "/merchant/providers"), TOKEN);

  document.getElementById("candidate-query").value = "checkout";
  document.getElementById("candidate-domain").value = "merchant.example";
  document.getElementById("candidate-pay-to").value = "0x2222";
  const searchEvent = await document.getElementById("candidate-form").dispatch("submit");
  assert.equal(searchEvent.defaultPrevented, true);
  const candidateCall = callFor(
    api.calls,
    "GET",
    "/merchant/candidates?query=checkout&domain=merchant.example&pay_to=0x2222",
  );
  assertAuthorized(candidateCall, TOKEN);
  assert.equal(document.getElementById("candidate-result").textContent, "1 candidate found.");

  await findByText(document.getElementById("candidate-list"), "Claim draft").dispatch("click");
  const draftCall = callFor(api.calls, "POST", "/merchant/candidates/offering-1/claim-draft");
  assertAuthorized(draftCall, TOKEN);
  assert.deepEqual(JSON.parse(document.getElementById("manifest-editor").value), manifest);
  assert.equal(document.getElementById("manifest-editor").focused, true);

  await document.getElementById("submit-manifest").dispatch("click");
  const manifestCall = callFor(api.calls, "POST", "/merchant/manifests");
  assertAuthorized(manifestCall, TOKEN);
  assert.deepEqual(manifestCall.body, manifest);
  assert.equal(manifestCall.headers["Content-Type"], "application/json");
  assert.match(document.getElementById("manifest-result").textContent, /manifest-1 is pending_claim/);

  await document.getElementById("sign-claim").dispatch("click");
  assert.deepEqual(plain(wallet.calls[2]), {
    method: "eth_signTypedData_v4",
    params: [WALLET, JSON.stringify({ primaryType: "ManifestClaim" })],
  });
  const claimCall = callFor(api.calls, "POST", "/merchant/manifests/manifest-1/submit-claim");
  assertAuthorized(claimCall, TOKEN);
  assert.deepEqual(claimCall.body, {
    claim: { manifest_id: "manifest-1" },
    signature: "0xtyped-signature",
    wallet_address: WALLET,
  });
  assert.match(document.getElementById("claim-result").textContent, /ManifestClaim accepted/);

  await document.getElementById("verify-domain").dispatch("click");
  assertAuthorized(callFor(api.calls, "POST", "/merchant/providers/provider-1/verify-domain"), TOKEN);
  assertAuthorized(callFor(api.calls, "GET", "/merchant/providers/provider-1/status"), TOKEN);
  assert.match(document.getElementById("domain-result").textContent, /Domain proof accepted/);

  await findByText(document.getElementById("provider-list"), "Verify live x402").dispatch("click");
  assertAuthorized(callFor(api.calls, "POST", "/merchant/offerings/offering-1/verify"), TOKEN);
  assert.match(deepText(document.getElementById("provider-list")), /Checkout .* verified/);
  assert.match(deepText(document.getElementById("operation-log")), /live 402 fields matched/);

  await findByText(document.getElementById("provider-list"), "Disable").dispatch("click");
  assertAuthorized(callFor(api.calls, "POST", "/merchant/offerings/offering-1/disable"), TOKEN);
  assert.match(deepText(document.getElementById("provider-list")), /Checkout .* disabled/);
  assert.match(deepText(document.getElementById("operation-log")), /offering-1 is disabled/);
});

test("admin console executes allowlisted SIWE and provider operations", async () => {
  const createAdminConsole = loadFactory("web/assets/admin.js", "createAdminConsole");
  assert.equal(typeof createAdminConsole, "function");

  const ids = [
    "operation-log", "status-result", "wallet-state", "connect-wallet", "refresh-status",
    "sync-registry", "overall-status", "worker-status", "core-status", "registry-status",
    "runtime-detail", "provider-result", "provider-filter", "provider-query", "provider-status",
    "provider-table", "provider-count",
  ];
  const document = new FakeDocument(ids);
  const sessionStorage = new FakeSessionStorage();
  const wallet = walletHarness();
  let providerStatus = "active";
  const providerRecord = () => ({
    provider: {
      provider_id: "provider-1",
      name: "Example merchant",
      domain: "merchant.example",
      status: providerStatus,
    },
    owner_wallet_address: WALLET,
    offerings: [{ offering_id: "offering-1" }],
  });
  const runtimeStatus = {
    status: "ok",
    worker: { status: "healthy" },
    core: { status: "reachable" },
    registries: [{ name: "bazaar", status: "ok" }],
    metrics: { active_providers: 1 },
  };
  const api = recordingFetch(async ({ method, url }) => {
    if (method === "GET" && url === "/auth/siwe/config") {
      return { allowed_domains: ["marketplace.example"] };
    }
    if (method === "POST" && url === "/auth/siwe/challenge") {
      return { nonce: "admin-nonce", message: "Admin sign in" };
    }
    if (method === "POST" && url === "/auth/siwe/verify") {
      return { access_token: TOKEN, wallet_address: WALLET };
    }
    if (method === "GET" && url === "/admin/status") return runtimeStatus;
    if (method === "GET" && url === "/admin/providers?") {
      return { count: 1, providers: [providerRecord()] };
    }
    if (method === "POST" && url === "/admin/registries/sync") {
      return { registries: [{ name: "bazaar" }] };
    }
    if (method === "POST" && url === "/admin/providers/provider-1/suspend") {
      providerStatus = "suspended";
      return { provider_id: "provider-1", status: providerStatus };
    }
    if (method === "POST" && url === "/admin/providers/provider-1/restore") {
      providerStatus = "active";
      return { provider_id: "provider-1", status: providerStatus };
    }
    throw new Error(`unexpected API request ${method} ${url}`);
  });
  const window = {
    ethereum: wallet.ethereum,
    location: { host: "marketplace.example", hostname: "marketplace.example" },
  };

  createAdminConsole({ document, window, fetch: api.fetch, sessionStorage });

  await document.getElementById("connect-wallet").dispatch("click");
  assert.deepEqual(plain(wallet.calls), [
    { method: "eth_requestAccounts" },
    { method: "personal_sign", params: ["Admin sign in", WALLET] },
  ]);
  assert.deepEqual(callFor(api.calls, "POST", "/auth/siwe/challenge").body, {
    address: WALLET,
    domain: "marketplace.example",
  });
  const verifyCall = callFor(api.calls, "POST", "/auth/siwe/verify");
  assert.deepEqual(verifyCall.body, {
    address: WALLET,
    nonce: "admin-nonce",
    message: "Admin sign in",
    signature: "0xpersonal-signature",
  });
  assert.equal(verifyCall.headers.Authorization, undefined);
  assert.equal(sessionStorage.getItem("clink.marketplace.session"), TOKEN);
  assertAuthorized(callFor(api.calls, "GET", "/admin/status"), TOKEN);
  assertAuthorized(callFor(api.calls, "GET", "/admin/providers?"), TOKEN);
  assert.equal(document.getElementById("overall-status").textContent, "ok");
  assert.equal(document.getElementById("worker-status").textContent, "healthy");
  assert.equal(document.getElementById("core-status").textContent, "reachable");
  assert.match(deepText(document.getElementById("provider-table")), /Example merchant/);

  await document.getElementById("sync-registry").dispatch("click");
  assertAuthorized(callFor(api.calls, "POST", "/admin/registries/sync"), TOKEN);
  assert.match(deepText(document.getElementById("operation-log")), /Registry sync finished/);

  await findByText(document.getElementById("provider-table"), "Suspend").dispatch("click");
  assertAuthorized(callFor(api.calls, "POST", "/admin/providers/provider-1/suspend"), TOKEN);
  assert.match(deepText(document.getElementById("provider-table")), /suspended/);
  assert.ok(findByText(document.getElementById("provider-table"), "Restore"));

  await findByText(document.getElementById("provider-table"), "Restore").dispatch("click");
  assertAuthorized(callFor(api.calls, "POST", "/admin/providers/provider-1/restore"), TOKEN);
  assert.match(deepText(document.getElementById("provider-table")), /active/);
  assert.ok(findByText(document.getElementById("provider-table"), "Suspend"));
  assert.equal(document.getElementById("provider-result").textContent, "1 provider loaded.");
});
