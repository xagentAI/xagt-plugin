from __future__ import annotations

import html
import json


def _script_value(value: object) -> str:
    return json.dumps(value).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def render_polymarket_console(
    session: dict, *, nonce: str = "", console_token: str = ""
) -> str:
    setup_required = session.get("next_action") == "open_polymarket_account_setup"
    replacements = {
        "__USER_ID__": html.escape(str(session.get("user_id") or "")),
        "__USER_ID_JS__": _script_value(session.get("user_id") or ""),
        "__AGENT_ID__": "Agentonomy",
        "__CORE_WALLET__": html.escape(str(session.get("wallet_address") or "")),
        "__SETUP_HIDDEN__": "" if setup_required else " hidden",
        "__INITIAL_STATUS__": html.escape(
            "Finish Polymarket account setup, then retry authorization."
            if setup_required
            else "Connect the wallet already verified in Clink Core."
        ),
        "__SESSION_ID_JS__": _script_value(session.get("session_id") or ""),
        "__MESSAGE_JS__": _script_value(session.get("message_to_sign") or ""),
        "__CORE_WALLET_JS__": _script_value(str(session.get("wallet_address") or "").lower()),
        "__DEPOSIT_WALLET_JS__": _script_value(
            session.get("polymarket_deposit_wallet") or ""
        ),
        "__BINDING_ID_JS__": _script_value(session.get("binding_id") or ""),
        "__CONSOLE_TOKEN_JS__": _script_value(console_token),
        "__CSP_NONCE__": html.escape(nonce, quote=True),
    }
    page = POLYMARKET_CONSOLE_HTML
    for marker, value in replacements.items():
        page = page.replace(marker, value)
    return page


POLYMARKET_CONSOLE_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="dark">
  <title>Clink Polymarket Account</title>
  <style nonce="__CSP_NONCE__">
    :root {
      --ink: #07111f;
      --surface: #0c1828;
      --surface-raised: #122033;
      --line: #26364b;
      --text: #ecf2f5;
      --muted: #8fa0af;
      --signal: #57d68d;
      --signal-ink: #04150b;
      --warning: #d6b65b;
      --error: #f09b92;
      --radius: 3px;
    }
    * { box-sizing: border-box; }
    html { background: var(--ink); color: var(--text); }
    body {
      margin: 0;
      min-height: 100vh;
      background: var(--ink);
      font-family: "Avenir Next", "DIN Alternate", "SF Pro Text", sans-serif;
      font-size: 15px;
      line-height: 1.55;
      letter-spacing: .01em;
    }
    button { font: inherit; -webkit-tap-highlight-color: transparent; }
    button:focus-visible, a:focus-visible { outline: 2px solid var(--signal); outline-offset: 4px; }
    .masthead, footer {
      width: min(1180px, calc(100% - 48px));
      margin: 0 auto;
      display: flex;
      align-items: center;
      justify-content: space-between;
      color: var(--muted);
      font-size: 12px;
      letter-spacing: .16em;
      text-transform: uppercase;
    }
    .masthead { height: 82px; border-bottom: 1px solid var(--line); }
    .wordmark { color: var(--text); font-weight: 700; text-decoration: none; }
    main { width: min(1180px, calc(100% - 48px)); margin: 0 auto; }
    .intro { max-width: 800px; padding: 92px 0 78px; }
    .eyebrow { margin: 0 0 12px; color: var(--signal); font-size: 11px; font-weight: 700; letter-spacing: .2em; text-transform: uppercase; }
    h1, h2 { margin: 0; font-weight: 500; letter-spacing: -.035em; }
    h1 { max-width: 760px; font-family: "Iowan Old Style", "Baskerville", serif; font-size: clamp(44px, 7vw, 82px); line-height: .98; }
    h2 { font-size: clamp(27px, 3vw, 38px); }
    .lede { max-width: 700px; margin: 28px 0 0; color: #bac6cf; font-size: 18px; }
    .status-line { min-height: 24px; margin: 28px 0 0; color: var(--muted); }
    .status-line.error { color: var(--error); }
    section { display: grid; grid-template-columns: 80px 1fr; padding: 52px 0 60px; border-top: 1px solid var(--line); }
    .section-index { color: #5f7183; font-family: "SFMono-Regular", "Cascadia Code", monospace; font-size: 12px; }
    .section-body { max-width: 920px; }
    .section-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 24px; margin-bottom: 20px; }
    .section-body > p { max-width: 760px; color: var(--muted); }
    .state { padding-top: 8px; color: var(--warning); font-size: 12px; letter-spacing: .12em; text-transform: uppercase; }
    .state.ready { color: var(--signal); }
    .ledger-list { margin: 30px 0; }
    .ledger-row { display: grid; grid-template-columns: minmax(150px, 1fr) 2fr auto; gap: 20px; align-items: baseline; padding: 14px 0; border-bottom: 1px solid var(--line); }
    .ledger-row:first-child { border-top: 1px solid var(--line); }
    .ledger-label, .ledger-value, .ledger-meta { margin: 0; }
    .ledger-label { color: var(--muted); }
    .ledger-value { overflow-wrap: anywhere; }
    .ledger-meta { color: var(--muted); font-family: "SFMono-Regular", "Cascadia Code", monospace; font-size: 12px; }
    .provider-list, .actions { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 28px; }
    .primary-action, .secondary-action {
      min-height: 44px;
      padding: 10px 17px;
      border-radius: var(--radius);
      cursor: pointer;
      font-weight: 700;
      letter-spacing: .025em;
    }
    .primary-action { border: 1px solid var(--signal); background: var(--signal); color: var(--signal-ink); }
    .primary-action:hover { background: #76e3a4; }
    .secondary-action { border: 1px solid #50657a; background: transparent; color: var(--text); }
    .secondary-action:hover, .secondary-action.selected { border-color: var(--signal); color: var(--signal); }
    button:disabled { cursor: not-allowed; opacity: .45; }
    .note { margin-top: 26px; padding-left: 16px; border-left: 2px solid var(--line); color: var(--muted); font-size: 13px; }
    .setup-panel { margin-top: 28px; padding: 18px 0; border-top: 1px solid var(--warning); }
    [hidden] { display: none !important; }
    footer { min-height: 100px; border-top: 1px solid var(--line); }
    @media (max-width: 760px) {
      .masthead, main, footer { width: min(100% - 32px, 1180px); }
      .masthead p { display: none; }
      .intro { padding: 64px 0 56px; }
      section { grid-template-columns: 1fr; gap: 14px; padding: 40px 0 48px; }
      .section-heading { align-items: flex-end; }
      .ledger-row { grid-template-columns: 1fr; gap: 4px; }
      .provider-list, .actions { align-items: stretch; }
      .provider-list button, .actions button { flex: 1 1 180px; }
    }
    @media (prefers-reduced-motion: reduce) {
      *, *::before, *::after { animation-duration: .01ms !important; transition-duration: .01ms !important; }
    }
  </style>
</head>
<body>
  <header class="masthead">
    <a class="wordmark" href="#top">CLINK / POLYMARKET</a>
    <p>Venue authorization</p>
  </header>
  <main id="top">
    <div class="intro">
      <p class="eyebrow">Prediction-market access</p>
      <h1>Authorize your Polymarket account.</h1>
      <p class="lede">Use the wallet already verified in Clink Core. This page grants Polymarket CLOB access; it does not bind another Core wallet or create a new spending permission.</p>
      <p id="status" class="status-line" role="status" aria-live="polite">__INITIAL_STATUS__</p>
    </div>

    <section aria-labelledby="identity-heading">
      <div class="section-index">01</div>
      <div class="section-body">
        <div class="section-heading">
          <div><p class="eyebrow">Core identity</p><h2 id="identity-heading">Verified wallet</h2></div>
          <span class="state ready">Core verified</span>
        </div>
        <p>Polymarket authorization must use this exact wallet. A different connected account will be blocked.</p>
        <div class="ledger-list">
          <div class="ledger-row"><p class="ledger-label">Core wallet</p><p class="ledger-value" id="core-wallet">__CORE_WALLET__</p><p class="ledger-meta">identity source</p></div>
          <div class="ledger-row"><p class="ledger-label">Shared spending permission</p><p class="ledger-value">Managed in Clink Core</p><p class="ledger-meta">not editable here</p></div>
          <div class="ledger-row"><p class="ledger-label">User / agent</p><p class="ledger-value">__USER_ID__ / __AGENT_ID__</p><p class="ledger-meta">session scope</p></div>
        </div>
      </div>
    </section>

    <section aria-labelledby="wallet-heading">
      <div class="section-index">02</div>
      <div class="section-body">
        <div class="section-heading">
          <div><p class="eyebrow">Wallet connection</p><h2 id="wallet-heading">Connect Core wallet</h2></div>
          <span id="wallet-state" class="state">Not connected</span>
        </div>
        <p>Choose the wallet application that holds the Core wallet. Connecting does not grant spending access.</p>
        <div class="provider-list" aria-label="Choose wallet">
          <button class="secondary-action selected" id="walletAuto" type="button" data-provider="auto">Browser Wallet</button>
          <button class="secondary-action" id="walletOkx" type="button" data-provider="okxwallet">OKX Wallet</button>
          <button class="secondary-action" id="walletMetaMask" type="button" data-provider="ethereum">MetaMask</button>
        </div>
        <div class="actions"><button class="primary-action" id="connectWalletButton" type="button">Connect Core wallet</button></div>
        <div class="ledger-list"><div class="ledger-row"><p class="ledger-label">Connected wallet</p><p class="ledger-value" id="connected-wallet">Not connected</p><p class="ledger-meta" id="wallet-match">waiting</p></div></div>
      </div>
    </section>

    <section aria-labelledby="authorization-heading">
      <div class="section-index">03</div>
      <div class="section-body">
        <div class="section-heading">
          <div><p class="eyebrow">Venue credential</p><h2 id="authorization-heading">Polymarket authorization</h2></div>
          <span id="authorization-state" class="state">Waiting</span>
        </div>
        <p>Your wallet signs the Clink binding message and Polymarket CLOB typed data. Clink stores encrypted user-scoped credentials, never your private key.</p>
        <div class="actions"><button class="primary-action" id="authorizePolymarketButton" type="button" disabled>Authorize Polymarket</button></div>
        <p class="note">This is a venue authorization, not another Core wallet binding and not another spending-cap approval.</p>
      </div>
    </section>

    <section aria-labelledby="controls-heading">
      <div class="section-index">04</div>
      <div class="section-body">
        <div class="section-heading">
          <div><p class="eyebrow">Account controls</p><h2 id="controls-heading">Polymarket access</h2></div>
          <span id="binding-state" class="state">Pending</span>
        </div>
        <p>Retry Polymarket account discovery when required, or remove only the saved Polymarket credentials.</p>
        <div id="accountSetupPanel" class="setup-panel"__SETUP_HIDDEN__>
          <p>Finish wallet/account setup on Polymarket, then return and retry account discovery. No address entry is required.</p>
          <div class="actions">
            <button class="primary-action" id="openPolymarketSetup" type="button">Open Polymarket account setup</button>
            <button class="secondary-action" id="retryAccountDiscovery" type="button">Retry account discovery</button>
          </div>
        </div>
        <div class="actions"><button class="secondary-action" id="unbindPolymarketButton" type="button">Unbind Polymarket account</button></div>
        <p class="note">Type UNBIND when prompted. Core wallet identity and shared spending permissions remain unchanged.</p>
      </div>
    </section>
  </main>
  <footer><span>CLINK PREDICTION MARKETS</span><span>User-controlled venue access</span></footer>
  <script nonce="__CSP_NONCE__">
    (() => {
      "use strict";
      const sessionId = __SESSION_ID_JS__;
      const bindingMessage = __MESSAGE_JS__;
      const expectedWallet = __CORE_WALLET_JS__;
      const expectedDepositWallet = __DEPOSIT_WALLET_JS__;
      const userId = __USER_ID_JS__;
      let currentBindingId = __BINDING_ID_JS__;
      const consoleToken = __CONSOLE_TOKEN_JS__;
      let selectedProviderKey = "auto";
      let connectedWallet = null;
      const status = document.getElementById("status");
      const authorizeButton = document.getElementById("authorizePolymarketButton");

      function hasRequest(candidate) { return Boolean(candidate && typeof candidate.request === 'function'); }
      function findInjectedProvider(predicate) {
        const providers = window.ethereum?.providers || [];
        return providers.find(predicate) || null;
      }
      function providerForKey(key) {
        if (key === "okxwallet") {
          if (hasRequest(window.okxwallet?.ethereum)) return window.okxwallet.ethereum;
          if (hasRequest(window.okxwallet)) return window.okxwallet;
          return findInjectedProvider((item) => item.isOkxWallet || item.isOKExWallet || item.isOkxWalletExtension);
        }
        if (key === "ethereum") {
          return findInjectedProvider((item) => item.isMetaMask) || (window.ethereum?.isMetaMask ? window.ethereum : null);
        }
        return window.ethereum || window.okxwallet?.ethereum || window.okxwallet || null;
      }
      function provider() { return providerForKey(selectedProviderKey); }
      function setStatus(message, isError = false) {
        status.textContent = message;
        status.classList.toggle("error", isError);
      }
      function shortAddress(value) { return value ? `${value.slice(0, 8)}...${value.slice(-6)}` : "Not connected"; }
      function walletMatches(value) { return String(value || "").toLowerCase() === expectedWallet; }
      function resetConnectedWallet(message = "Connect the wallet already verified in Clink Core.") {
        connectedWallet = null;
        authorizeButton.disabled = true;
        document.getElementById("connected-wallet").textContent = "Not connected";
        document.getElementById("wallet-state").textContent = "Not connected";
        document.getElementById("wallet-state").classList.remove("ready");
        document.getElementById("wallet-match").textContent = "waiting";
        setStatus(message);
      }

      document.querySelectorAll("[data-provider]").forEach((button) => {
        button.addEventListener("click", () => {
          resetConnectedWallet("Wallet provider changed. Connect the Core wallet again.");
          selectedProviderKey = button.dataset.provider;
          document.querySelectorAll("[data-provider]").forEach((item) => item.classList.toggle("selected", item === button));
          setStatus(hasRequest(provider()) ? "Wallet selected. Connect the Core wallet next." : "Provider not found in this browser.", !hasRequest(provider()));
        });
      });

      document.getElementById("connectWalletButton").addEventListener("click", async () => {
        const walletProvider = provider();
        if (!hasRequest(walletProvider)) {
          setStatus("No injected wallet found. Open this page in the selected wallet browser.", true);
          return;
        }
        try {
          const accounts = await walletProvider.request({method: "eth_requestAccounts"});
          const selected = accounts?.[0];
          connectedWallet = selected || null;
          if (typeof walletProvider.on === "function") {
            walletProvider.on("accountsChanged", () => resetConnectedWallet("Wallet account changed. Reconnect the Core wallet."));
          }
          document.getElementById("connected-wallet").textContent = selected || "Not connected";
          if (!walletMatches(selected)) {
            document.getElementById("wallet-state").textContent = "Mismatch";
            document.getElementById("wallet-match").textContent = "blocked";
            authorizeButton.disabled = true;
            setStatus(`Selected wallet does not match the Core wallet. Expected ${shortAddress(expectedWallet)}, received ${shortAddress(selected)}.`, true);
            return;
          }
          document.getElementById("wallet-state").textContent = "Matched";
          document.getElementById("wallet-state").classList.add("ready");
          document.getElementById("wallet-match").textContent = "Core match";
          authorizeButton.disabled = false;
          setStatus("Core wallet matched. Authorize Polymarket when ready.");
        } catch (error) {
          connectedWallet = null;
          authorizeButton.disabled = true;
          setStatus(`Wallet connection failed: ${error?.message || error}`, true);
        }
      });

      async function authorizePolymarket() {
        const walletProvider = provider();
        if (!hasRequest(walletProvider) || !walletMatches(connectedWallet)) {
          setStatus("Connect the verified Core wallet before authorizing Polymarket.", true);
          return;
        }
        authorizeButton.disabled = true;
        try {
          setStatus("Sign the Clink account-binding message in your wallet.");
          const signature = await walletProvider.request({method: "personal_sign", params: [bindingMessage, connectedWallet]});
          let timestamp = String(Math.floor(Date.now() / 1000));
          const timeResponse = await fetch("/polymarket/clob-server-time");
          if (timeResponse.ok) {
            const timePayload = await timeResponse.json();
            timestamp = String(timePayload.timestamp || timestamp);
          }
          const nonce = 0;
          const typedData = {
            domain: {name: "ClobAuthDomain", version: "1", chainId: 137},
            types: {
              EIP712Domain: [
                {name: "name", type: "string"},
                {name: "version", type: "string"},
                {name: "chainId", type: "uint256"}
              ],
              ClobAuth: [
                {name: "address", type: "address"},
                {name: "timestamp", type: "string"},
                {name: "nonce", type: "uint256"},
                {name: "message", type: "string"}
              ]
            },
            primaryType: "ClobAuth",
            message: {address: connectedWallet, timestamp, nonce, message: "This message attests that I control the given wallet"}
          };
          setStatus("Sign the Polymarket CLOB authorization.");
          const clobAuthSignature = await walletProvider.request({method: "eth_signTypedData_v4", params: [connectedWallet, JSON.stringify(typedData)]});
          const response = await fetch(`/polymarket/binding-sessions/${sessionId}/complete`, {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              "X-Clink-Console-Token": consoleToken
            },
            body: JSON.stringify({
              wallet_address: connectedWallet,
              signature,
              signed_message: bindingMessage,
              polymarket_deposit_wallet: expectedDepositWallet || null,
              clob_auth_signature: clobAuthSignature,
              clob_auth_timestamp: timestamp,
              clob_auth_nonce: nonce,
              polymarket_signature_type: expectedDepositWallet ? "3" : "auto",
              metadata: {source: "clink_polymarket_binding_console"}
            })
          });
          const result = await response.json();
          if (!response.ok) throw new Error(typeof result.detail === "string" ? result.detail : JSON.stringify(result.detail || result));
          currentBindingId = result.binding_id || currentBindingId;
          if (["polymarket_account_mode_unresolved", "open_polymarket_account_setup"].includes(result.next_action)) {
            document.getElementById("accountSetupPanel").hidden = false;
            document.getElementById("binding-state").textContent = "Setup required";
            setStatus("Finish account setup on Polymarket, then retry discovery here.");
          } else if (result.next_action === "account_binding_active" && result.status === "completed") {
            document.getElementById("authorization-state").textContent = "Authorized";
            document.getElementById("authorization-state").classList.add("ready");
            document.getElementById("binding-state").textContent = "Active";
            document.getElementById("binding-state").classList.add("ready");
            setStatus("Polymarket account active. You can return to Agentonomy.");
          } else {
            document.getElementById("authorization-state").textContent = "Not active";
            document.getElementById("binding-state").textContent = result.status || "Pending";
            setStatus(`Unexpected Polymarket authorization state: ${result.next_action || result.status || "unknown"}.`, true);
            authorizeButton.disabled = false;
          }
        } catch (error) {
          setStatus(`Polymarket authorization failed: ${error?.message || error}`, true);
          authorizeButton.disabled = false;
        }
      }

      authorizeButton.addEventListener("click", authorizePolymarket);
      document.getElementById("openPolymarketSetup").addEventListener("click", () => {
        window.open("https://polymarket.com/settings", "_blank", "noopener,noreferrer");
        setStatus("Finish account setup on Polymarket, then return and retry discovery.");
      });
      document.getElementById("retryAccountDiscovery").addEventListener("click", authorizePolymarket);
      document.getElementById("unbindPolymarketButton").addEventListener("click", async () => {
        if (!currentBindingId) {
          setStatus("No active Polymarket binding is available on this page.", true);
          return;
        }
        if (window.prompt("Type UNBIND to remove Polymarket credentials.") !== "UNBIND") {
          setStatus("Polymarket unbind cancelled.");
          return;
        }
        try {
          if (!hasRequest(provider()) || !walletMatches(connectedWallet)) {
            throw new Error("Reconnect the verified Core wallet before unbinding Polymarket.");
          }
          const revokeMessage = [
            "Revoke Clink Polymarket Binding",
            `session_id=${sessionId}`,
            `binding_id=${currentBindingId}`,
            `user_id=${userId}`,
            `wallet_address=${expectedWallet}`
          ].join("\\n");
          const revokeSignature = await provider().request({
            method: "personal_sign",
            params: [revokeMessage, connectedWallet]
          });
          const response = await fetch(`/polymarket/binding-sessions/${sessionId}/revoke`, {
            method: "POST",
            headers: {
              "Content-Type": "application/json",
              "X-Clink-Console-Token": consoleToken
            },
            body: JSON.stringify({
              wallet_address: connectedWallet,
              signature: revokeSignature,
              signed_message: revokeMessage,
              reason: "user_requested_unbind_from_console",
              metadata: {source: "clink_polymarket_binding_console"}
            })
          });
          const result = await response.json();
          if (!response.ok) throw new Error(result.detail || "Unbind failed");
          currentBindingId = "";
          document.getElementById("binding-state").textContent = "Unbound";
          setStatus("Polymarket credentials removed. Core wallet and spending permissions are unchanged.");
        } catch (error) {
          setStatus(`Polymarket unbind failed: ${error?.message || error}`, true);
        }
      });
    })();
  </script>
</body>
</html>
"""
