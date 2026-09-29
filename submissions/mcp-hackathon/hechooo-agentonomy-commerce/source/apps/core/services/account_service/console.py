from __future__ import annotations

from .opc_console import OPC_SETUP_CSS, OPC_SETUP_HTML, OPC_SETUP_JS


ACCOUNT_CONSOLE_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="dark">
  <title>Clink Account</title>
  <link rel="stylesheet" href="__CLINK_ACCOUNT_BASE_PATH__/static/account.css">
  <script src="__CLINK_ACCOUNT_BASE_PATH__/static/account.js" defer></script>
</head>
<body>
  <header class="masthead">
    <a class="wordmark" href="#top" aria-label="Clink Account home">CLINK / ACCOUNT</a>
    <p>Authorization ledger</p>
  </header>
  <main id="top">
    <div class="intro">
      <p id="page-eyebrow" class="eyebrow">Unified wallet authorization</p>
      <h1 id="page-heading">Control what Agentonomy can spend.</h1>
      <p id="page-lede" class="lede">Bind one wallet, set one permission for prediction markets and marketplace purchases, then keep each chain approval visible and reversible.</p>
      <p id="page-status" class="status-line" role="status" aria-live="polite">Loading account controls...</p>
    </div>

    <section aria-labelledby="wallet-heading">
      <div class="section-index">01</div>
      <div class="section-body">
        <div class="section-heading">
          <div><p class="eyebrow">Ownership</p><h2 id="wallet-heading">Wallet</h2></div>
          <span id="wallet-state" class="state">Not connected</span>
        </div>
        <p>Sign a short ownership message in your wallet. Clink never asks for wallet recovery material.</p>
        <div id="wallet-details" class="ledger-list" aria-live="polite"></div>
        <div class="wallet-selection">
          <div>
            <p class="wallet-selection-label">1. Choose browser wallet</p>
            <div id="wallet-provider-options" class="wallet-option-list" aria-live="polite">
              <p class="muted">Looking for compatible browser wallets...</p>
            </div>
          </div>
          <div>
            <p class="wallet-selection-label">2. Choose account address</p>
            <div id="wallet-account-options" class="wallet-option-list" role="radiogroup" aria-label="Wallet accounts">
              <p class="muted">Choose a browser wallet first.</p>
            </div>
          </div>
          <p id="wallet-selection-state" class="wallet-selection-state" role="status" aria-live="polite">
            No browser wallet or account selected.
          </p>
          <div class="wallet-selection-actions">
            <button id="connect-wallet" class="primary-action" type="button" disabled>
              Sign in with selected address
            </button>
            <button id="cancel-wallet-selection" class="row-action" type="button" disabled>
              Cancel selection
            </button>
            <button id="resume-wallet-disconnect" class="row-action" type="button" hidden disabled>
              Continue Clink unbind
            </button>
          </div>
          <p id="wallet-disconnect-state" class="note" hidden></p>
        </div>
      </div>
    </section>

    <div id="embedded-authorization" role="region" aria-labelledby="embedded-authorization-heading">
      <div class="section-index">02</div>
      <div class="section-body">
        <div class="section-heading">
          <div><p class="eyebrow">Embedded authorization</p><h2 id="embedded-authorization-heading">Authorize Clink</h2></div>
          <span id="embedded-state" class="state">Review</span>
        </div>
        <p id="embedded-notice" class="note">Authorization does not enable purchasing or funding. Wallet ownership, the Spending Mandate, and each chain approval are separate controls.</p>
        <div id="embedded-proof-state" class="embedded-step"><strong>Wallet ownership</strong><span>Sign in with the selected EIP-1193 / EIP-6963 provider.</span></div>
        <div id="embedded-mandate-state" class="embedded-step"><strong>Spending Mandate</strong><span>Review the exact Core terms before signing one personal_sign request.</span></div>
        <div id="embedded-approval-state" class="embedded-step"><strong>Chain approval</strong><span>Approve a finite USDC allowance and gas transaction only after an explicit confirmation.</span></div>
        <form id="embedded-permission-form" class="embedded-form">
          <div class="embedded-grid">
            <label>Network<select id="embedded-network" required></select></label>
            <label>Total USDC<input id="embedded-total-limit" inputmode="decimal" autocomplete="off" required></label>
            <label>Rolling 1-hour USDC<input id="embedded-hourly-limit" inputmode="decimal" autocomplete="off" required></label>
            <label>Duration, days<input id="embedded-duration-days" inputmode="numeric" type="number" min="1" max="365" value="7" required></label>
          </div>
          <p id="embedded-current-expiry" class="note" hidden>Existing expiry is read-only and will not be extended.</p>
          <button id="embedded-permission-submit" class="primary-action" type="submit">Review authorization</button>
        </form>
        <div id="embedded-plan" class="embedded-plan" hidden>
          <h3>Exact Core authorization terms</h3>
          <div id="embedded-plan-terms" class="ledger-list"></div>
          <p id="embedded-plan-allowance" class="note"></p>
          <div class="embedded-plan-actions">
            <button id="embedded-plan-confirm" class="primary-action" type="button" hidden>Confirm and sign Spending Mandate</button>
            <button id="embedded-plan-cancel" class="row-action" type="button" hidden>Cancel</button>
            <button id="embedded-plan-retry" class="row-action" type="button" hidden>Retry allowance query</button>
            <button id="embedded-approve" class="row-action" type="button" hidden>Review finite chain approval</button>
          </div>
        </div>
        <div id="embedded-current-actions" class="embedded-plan" hidden>
          <p id="embedded-revoke-warning" class="note">Revoke spending in Core; this does not stop the runtime. Any chain allowance is a separate shared wallet control.</p>
          <label><input id="embedded-revoke-allowance" type="checkbox"> <span id="embedded-revoke-allowance-label">Clear the selected network allowance too; this is shared with other businesses using the same wallet, token, and spender.</span></label>
          <button id="embedded-revoke-spending" class="row-action" type="button">Revoke spending</button>
        </div>
        <div id="embedded-pending-recovery" class="embedded-plan" hidden>
          <p id="embedded-pending-recovery-state" class="note"></p>
          <button id="embedded-verify-pending-allowance" class="row-action" type="button" hidden>Retry Core allowance verification</button>
        </div>
        <div id="embedded-approval-confirm" class="embedded-plan" hidden>
          <p id="embedded-approval-confirm-text" class="note"></p>
          <div class="embedded-plan-actions">
            <button id="embedded-approval-confirm-button" class="primary-action" type="button">Confirm exact allowance</button>
            <button id="embedded-approval-cancel" class="row-action" type="button">Cancel</button>
          </div>
        </div>
      </div>
    </div>

    <section aria-labelledby="permissions-heading">
      <div class="section-index">02</div>
      <div class="section-body">
        <div class="section-heading">
          <div><p class="eyebrow">Clink spending</p><h2 id="permissions-heading">Spending limit</h2></div>
          <span id="permission-state" class="state">No limit</span>
        </div>
        <p>Set one total USDC limit for every Agentonomy purchase through Clink, including <strong>prediction markets</strong> and <strong>marketplace</strong>.</p>
        <div id="grant-details" class="ledger-list" aria-live="polite"></div>
        <details id="permission-editor" class="setup-panel">
          <summary id="permission-editor-label">Set total limit</summary>
          <form id="permission-form" class="limit-form">
            <label>Total spending limit, USDC<input id="total-limit" inputmode="decimal" placeholder="Enter amount" required></label>
            <details id="new-limit-settings" class="advanced-settings">
              <summary>Advanced settings</summary>
              <div class="advanced-grid">
                <label>Permission duration, days<input id="expiry-days" inputmode="numeric" type="number" min="1" max="365" value="30" required></label>
                <fieldset class="scope-options">
                  <legend>Trusted merchants</legend>
                  <label><input id="trust-clink" type="checkbox" checked> Clink verified</label>
                  <label><input id="trust-registry" type="checkbox" checked> Registry verified</label>
                </fieldset>
                <label>Notifications
                  <select id="notification-mode">
                    <option value="silent_under_limits" selected>Silent inside limits</option>
                    <option value="notify_all">Notify every purchase</option>
                  </select>
                </label>
              </div>
            </details>
            <button id="permission-submit" class="primary-action" type="submit">Review and sign total limit</button>
          </form>
        </details>
        <p id="limit-help" class="note">This total is shared by all Clink purchases. One wallet signature sets it. Polymarket CLOB auth remains separate.</p>
      </div>
    </section>

    <section aria-labelledby="allowances-heading">
      <div class="section-index">03</div>
      <div class="section-body">
        <div class="section-heading">
          <div><p class="eyebrow">One-time setup</p><h2 id="allowances-heading">Wallet setup</h2></div>
          <button id="refresh-allowances" class="primary-action compact" type="button" disabled>Refresh status</button>
        </div>
        <p>Clink reuses your saved spending permission. A one-time wallet approval appears only when a network cannot cover the configured single purchase.</p>
        <details id="allowance-setup" class="setup-panel">
          <summary id="allowance-setup-label">Wallet setup</summary>
          <div id="network-ledger" class="network-ledger" aria-live="polite"></div>
        </details>
        <div class="pending-allowance-recovery">
          <button id="verify-pending-allowance" class="primary-action compact" type="button" hidden disabled>
            Retry Core verification
          </button>
          <p id="pending-allowance-state" class="note" hidden></p>
        </div>
      </div>
    </section>

    <section aria-labelledby="audit-heading">
      <div class="section-index">04</div>
      <div class="section-body">
        <div class="section-heading">
          <div><p class="eyebrow">Recent controls</p><h2 id="audit-heading">Recent audit summary</h2></div>
          <button id="refresh-audit" class="primary-action compact" type="button">Refresh activity</button>
        </div>
        <p>Recent wallet, permission, and allowance state changes for this account session.</p>
        <div id="audit-list" class="ledger-list" aria-live="polite"></div>
      </div>
    </section>

    <div id="opc-device-section" role="region" aria-labelledby="opc-device-heading" hidden>
      <div class="section-index">05</div>
      <div class="section-body">
        <div class="section-heading">
          <div><p class="eyebrow">Installed device</p><h2 id="opc-device-heading">Review device access</h2></div>
          <span id="opc-device-state" class="state">Hidden</span>
        </div>
        <p id="opc-device-message" class="note">No device request is available in this account session.</p>
        <p class="note">Device approval only binds this installation to the shown grant; it does not enable purchasing or funding. Stop the installed device through the existing device-stop/revoke command, separately from revoking the spending grant.</p>
        <p id="opc-device-status" class="note"></p>
        <div id="opc-device-details" class="ledger-list" aria-live="polite"></div>
        <div id="opc-device-grant" class="ledger-list" aria-live="polite"></div>
        <div class="embedded-plan-actions">
          <button id="opc-refresh" class="primary-action compact" type="button">Refresh device status</button>
          <button id="opc-review-button" class="primary-action" type="button" disabled>Review exact device request</button>
          <button id="opc-cancel-button" class="row-action" type="button" hidden>Cancel review</button>
        </div>
        <div id="opc-review" class="embedded-plan" hidden>
          <h3>Exact device signature request</h3>
          <p class="note">Read this message exactly. No wallet signature is requested until you explicitly confirm below.</p>
          <pre id="opc-exact-message" class="opc-exact-message"></pre>
          <div class="embedded-plan-actions">
            <button id="opc-sign-button" class="primary-action" type="button" hidden disabled>Confirm and sign exact device request</button>
            <button id="opc-recheck" class="row-action" type="button" hidden>Refresh device status</button>
          </div>
        </div>
      </div>
    </div>
  </main>
  <footer><span>CLINK CORE</span><span>User-controlled authorization</span></footer>
</body>
</html>
"""


ACCOUNT_CONSOLE_HTML = ACCOUNT_CONSOLE_HTML.replace(
    '    <div id="embedded-authorization" role="region" aria-labelledby="embedded-authorization-heading">',
    OPC_SETUP_HTML
    + '\n    <div id="embedded-authorization" role="region" aria-labelledby="embedded-authorization-heading">',
    1,
)


ACCOUNT_SESSION_CONFIRM_HTML = """<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <meta name="color-scheme" content="dark">
  <title>Continue to Clink Account</title>
  <link rel="stylesheet" href="__CLINK_ACCOUNT_BASE_PATH__/static/account.css">
</head>
<body>
  <header class="masthead">
    <span class="wordmark">CLINK / ACCOUNT</span>
    <p>Secure handoff</p>
  </header>
  <main>
    <div class="intro">
      <p class="eyebrow">User-controlled checkpoint</p>
      <h1>Continue to Clink Account</h1>
      <p class="lede">Open the account controls in this browser. Link previews cannot connect a wallet or consume this session.</p>
      <form method="post">
        <button class="primary-action" type="submit">Continue securely</button>
      </form>
    </div>
  </main>
  <footer><span>CLINK CORE</span><span>No wallet action happens until you continue</span></footer>
</body>
</html>
"""
ACCOUNT_CONSOLE_CSS = """:root {
  --ink: #07111f;
  --surface: #0c1828;
  --surface-raised: #122033;
  --line: #26364b;
  --text: #ecf2f5;
  --muted: #8fa0af;
  --signal: #57d68d;
  --signal-ink: #04150b;
  --warning: #d6b65b;
  --radius: 3px;
}
* { box-sizing: border-box; }
html { background: var(--ink); color: var(--text); scroll-behavior: smooth; }
body {
  margin: 0;
  min-height: 100vh;
  background: var(--ink);
  font-family: "Avenir Next", "DIN Alternate", "SF Pro Text", sans-serif;
  font-size: 15px;
  line-height: 1.55;
  letter-spacing: .01em;
}
button, input { font: inherit; }
button, a, input { -webkit-tap-highlight-color: transparent; }
:focus-visible { outline: 2px solid var(--signal); outline-offset: 4px; }
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
.intro { max-width: 780px; padding: 92px 0 78px; }
.eyebrow { margin: 0 0 12px; color: var(--signal); font-size: 11px; font-weight: 700; letter-spacing: .2em; text-transform: uppercase; }
h1, h2 { margin: 0; font-weight: 500; letter-spacing: -.035em; }
h1 { max-width: 720px; font-family: "Iowan Old Style", "Baskerville", serif; font-size: clamp(44px, 7vw, 82px); line-height: .98; }
h2 { font-size: clamp(27px, 3vw, 38px); }
.lede { max-width: 680px; margin: 28px 0 0; color: #bac6cf; font-size: 18px; }
.status-line { min-height: 24px; margin: 28px 0 0; color: var(--muted); }
section { display: grid; grid-template-columns: 80px 1fr; padding: 52px 0 60px; border-top: 1px solid var(--line); }
.section-index { color: #5f7183; font-family: "SFMono-Regular", "Cascadia Code", monospace; font-size: 12px; }
.section-body { max-width: 920px; }
.section-heading { display: flex; align-items: flex-start; justify-content: space-between; gap: 24px; margin-bottom: 20px; }
.section-body > p { max-width: 740px; color: var(--muted); }
.state { padding-top: 8px; color: var(--warning); font-size: 12px; letter-spacing: .12em; text-transform: uppercase; }
.state.ready { color: var(--signal); }
.ledger-list { margin: 30px 0; }
.wallet-selection {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 18px;
  margin: 30px 0;
}
.wallet-selection-label {
  margin: 0 0 10px;
  color: var(--muted);
  font-size: 12px;
  letter-spacing: .08em;
  text-transform: uppercase;
}
.wallet-option-list { display: grid; gap: 8px; }
.wallet-choice {
  display: flex;
  min-height: 52px;
  align-items: center;
  gap: 12px;
  padding: 10px 12px;
  border: 1px solid var(--line);
  border-radius: var(--radius);
  background: transparent;
  color: var(--text);
  cursor: pointer;
  text-align: left;
}
.wallet-choice[aria-pressed="true"],
.wallet-choice[aria-checked="true"] { border-color: var(--signal); }
.wallet-choice-icon {
  display: grid;
  width: 32px;
  height: 32px;
  flex: 0 0 32px;
  place-items: center;
  overflow: hidden;
  border-radius: 8px;
  background: var(--surface-raised);
  color: var(--muted);
  font-size: 14px;
  font-weight: 700;
}
.wallet-choice-icon > * { grid-area: 1 / 1; }
.wallet-choice-icon img {
  width: 32px;
  height: 32px;
  object-fit: cover;
  background: var(--surface-raised);
}
.wallet-choice-copy { display: grid; gap: 2px; min-width: 0; }
.wallet-choice-copy small,
.wallet-selection-state { color: var(--muted); font-family: "SFMono-Regular", "Cascadia Code", monospace; font-size: 12px; }
.wallet-address { overflow-wrap: anywhere; }
.wallet-selection-state { grid-column: 1 / -1; margin: 0; }
.wallet-selection-actions {
  display: flex;
  grid-column: 1 / -1;
  flex-wrap: wrap;
  gap: 10px;
  align-items: center;
}
.wallet-selection-actions .primary-action { align-self: auto; }
.ledger-row { display: grid; grid-template-columns: minmax(150px, 1fr) 2fr auto; gap: 20px; align-items: baseline; padding: 14px 0; border-bottom: 1px solid var(--line); }
.ledger-row:first-child { border-top: 1px solid var(--line); }
.ledger-label, .ledger-value, .ledger-meta { margin: 0; }
.ledger-label { color: var(--muted); }
.ledger-value { overflow-wrap: anywhere; }
.ledger-meta { color: var(--muted); font-family: "SFMono-Regular", "Cascadia Code", monospace; font-size: 12px; }
.row-controls { display: flex; flex-wrap: wrap; gap: 10px; padding: 14px 0 22px; }
.grant-actions { display: flex; flex-wrap: wrap; gap: 10px; padding-bottom: 24px; }
.setup-panel { margin-top: 26px; border-top: 1px solid var(--line); border-bottom: 1px solid var(--line); }
.setup-panel > summary, .advanced-settings > summary, .technical-details > summary {
  padding: 16px 0;
  color: var(--text);
  cursor: pointer;
  font-weight: 700;
}
.setup-panel > summary::marker, .advanced-settings > summary::marker, .technical-details > summary::marker { color: var(--signal); }
.limit-form { display: grid; max-width: 540px; gap: 18px; padding: 6px 0 24px; }
.advanced-settings { border-top: 1px solid var(--line); }
.advanced-grid { display: grid; gap: 16px; padding-bottom: 18px; }
label { display: grid; gap: 8px; color: var(--muted); font-size: 12px; letter-spacing: .06em; }
input, select { width: 100%; min-height: 44px; padding: 9px 11px; border: 1px solid var(--line); border-radius: var(--radius); background: #091525; color: var(--text); }
input:hover, select:hover { border-color: #3a5069; }
.scope-options { display: flex; min-width: 0; gap: 14px; align-items: center; margin: 0; padding: 9px 11px; border: 1px solid var(--line); border-radius: var(--radius); }
.scope-options legend { padding: 0 6px; color: var(--muted); font-size: 12px; }
.scope-options label { display: flex; gap: 7px; align-items: center; letter-spacing: 0; }
.scope-options input { width: auto; min-height: 0; }
#grant-token { grid-column: span 2; }
.primary-action, .network-action, .row-action {
  min-height: 44px;
  padding: 10px 17px;
  border-radius: var(--radius);
  cursor: pointer;
  font-weight: 700;
  letter-spacing: .025em;
}
.primary-action { align-self: end; border: 1px solid var(--signal); background: var(--signal); color: var(--signal-ink); }
.primary-action:hover { background: #76e3a4; }
.primary-action.compact { min-height: 38px; padding: 7px 13px; font-size: 12px; }
.network-action, .row-action { border: 1px solid #50657a; background: transparent; color: var(--text); }
.network-action:hover, .row-action:hover { border-color: var(--signal); color: var(--signal); }
button:disabled { cursor: wait; opacity: .55; }
.note { margin-top: 26px; padding-left: 16px; border-left: 2px solid var(--line); font-size: 13px; }
.network-ledger { margin-top: 30px; }
.network-row { display: grid; grid-template-columns: 160px minmax(220px, 1fr) auto; gap: 24px; align-items: center; padding: 24px 0; border-top: 1px solid var(--line); }
.network-row:last-child { border-bottom: 1px solid var(--line); }
.network-name, .network-meta { margin: 0; }
.network-name { font-size: 18px; }
.network-meta { color: var(--muted); font-size: 12px; }
.network-inputs { display: grid; grid-template-columns: 1fr 1fr; gap: 12px; }
.technical-details { min-width: 0; color: var(--muted); }
.technical-details > summary { padding: 8px 0; color: var(--muted); font-size: 12px; font-weight: 500; }
footer { min-height: 100px; border-top: 1px solid var(--line); }
.error { color: #f09b92; }
#embedded-authorization { display: none; }
body[data-account-view="authorization"] #embedded-authorization { display: grid; }
body[data-account-view="authorization"] .masthead { height: 58px; }
body[data-account-view="authorization"] .intro { max-width: 760px; padding: 32px 0 28px; }
body[data-account-view="authorization"] h1 { max-width: 760px; font-size: clamp(30px, 4vw, 36px); line-height: 1.05; }
body[data-account-view="authorization"] .lede { margin-top: 14px; font-size: 15px; }
body[data-account-view="authorization"] .status-line { margin-top: 16px; }
body[data-account-view="authorization"] main > section { padding: 28px 0 32px; }
body[data-account-view="authorization"] #embedded-authorization { padding: 28px 0 32px; border-top: 1px solid var(--line); }
body[data-account-view="authorization"] main > section[aria-labelledby="permissions-heading"],
body[data-account-view="authorization"] main > section[aria-labelledby="allowances-heading"],
body[data-account-view="authorization"] main > section[aria-labelledby="audit-heading"] { display: none; }
.embedded-form { display: grid; max-width: 760px; gap: 18px; margin-top: 28px; }
.embedded-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; }
.embedded-step { display: grid; gap: 2px; margin: 12px 0; padding: 12px 14px; border-left: 2px solid var(--line); color: var(--muted); }
.embedded-step strong { color: var(--text); }
.embedded-plan { max-width: 820px; margin-top: 28px; padding-top: 20px; border-top: 1px solid var(--line); }
.embedded-plan h3 { margin: 0; font-size: 20px; font-weight: 500; }
.embedded-plan-actions { display: flex; flex-wrap: wrap; gap: 10px; margin-top: 18px; }
body[data-account-view="authorization"] .embedded-plan .note { overflow-wrap: anywhere; }
body[data-account-view="authorization"] .embedded-plan[hidden] { display: none; }
.opc-exact-message {
  max-width: 820px;
  margin: 16px 0 0;
  padding: 14px;
  border: 1px solid var(--line);
  background: var(--surface);
  color: var(--text);
  white-space: pre-wrap;
  overflow-wrap: anywhere;
  font: inherit;
}
#opc-device-section[hidden], #opc-review[hidden] { display: none; }
@media (max-width: 760px) {
  .masthead, main, footer { width: min(100% - 32px, 1180px); }
  .masthead p { display: none; }
  .intro { padding: 64px 0 56px; }
  section { grid-template-columns: 1fr; gap: 14px; padding: 40px 0 48px; }
  .section-heading { align-items: flex-end; }
  .advanced-grid, .network-inputs, .embedded-grid { grid-template-columns: 1fr; }
  .wallet-selection { grid-template-columns: 1fr; }
  .wallet-selection-state,
  .wallet-selection-actions { grid-column: auto; }
  #grant-token { grid-column: auto; }
  .network-row { grid-template-columns: 1fr; align-items: stretch; }
  .ledger-row { grid-template-columns: 1fr; gap: 4px; }
}
@media (prefers-reduced-motion: reduce) {
  html { scroll-behavior: auto; }
  *, *::before, *::after { animation-duration: .01ms !important; transition-duration: .01ms !important; }
}
"""


ACCOUNT_CONSOLE_CSS += "\n" + OPC_SETUP_CSS


ACCOUNT_CONSOLE_JS = r"""(() => {
  "use strict";

  const $ = (selector) => document.querySelector(selector);
  const status = $("#page-status");
  const CONTROLLED_AGENT_ID = atob("aGVybWVz");
  const PUBLIC_AGENT_LABEL = "Agentonomy";
  const KNOWN_NETWORK_LABELS = Object.freeze({
    "eip155:137": "Polygon",
    "eip155:8453": "Base",
    "eip155:80002": "Polygon Amoy"
  });
  const isEmbeddedView = () => Boolean(
    document.body?.dataset?.accountView === "authorization"
  );
  let embeddedOperation = null;
  let embeddedGeneration = 0;
  let embeddedPlan = null;
  let embeddedPlanGeneration = 0;
  let embeddedApprovalReview = null;
  let embeddedRefreshRequired = false;
  let accountState = null;
  let accountStateLoadGeneration = 0;
  let opcPairing = null;
  let opcPairingGeneration = 0;
  let opcPairingLoadGeneration = 0;
  let opcReviewGeneration = 0;
  let opcReviewOperation = null;
  let opcReviewChallenge = null;
  let opcExpiryTimer = null;
  let opcUncertain = false;
  let opcSetupBlockFromRecovery = () => {};
  let opcSetupHandleConfirmedMismatch = () => false;
  const discoveredWallets = new Map();
  let selectedProviderUuid = null;
  let selectedWalletProvider = null;
  let pendingProviderSelection = null;
  let availableWalletAccounts = [];
  let selectedWalletAddress = null;
  let selectionGeneration = 0;
  let walletLoginOperation = null;
  let removeSelectedProviderListeners = () => {};
  let walletSelectionDisconnectOperation = null;
  let pendingAllowance = null;
  let pendingAllowanceCleanup = null;
  let allowanceOperation = null;
  let allowanceRecoveryBlocked = false;
  let allowanceRecoveryMessage = "";
  let allowanceRecoveryRecords = [];
  let allowanceCoreRecoveryMessage = "";
  let allowanceSessionExpired = false;
  const allowanceAttemptContexts = new Map();
  const allowanceLateWalletRequests = new Map();
  let allowancePostSendUncertainIdentityId = null;
  let allowanceMismatchNotice = "";
  let allowanceVerificationRetryTimer = null;
  let allowanceVerificationRetryAttempts = 0;
  let allowanceVerificationRetryInFlight = false;
  let embeddedAllowanceRevokeRecovery = null;
  let allowanceRecoveryProbeSequence = 0;
  let allowanceRevokeOperation = null;
  const allowanceRevokePostSendUncertain = new Set();
  let accountSessionGeneration = 0;
  let pendingWalletDisconnect = null;
  let walletDisconnectApprovalTargets = null;
  let walletDisconnectNetworkConfigs = null;
  let walletDisconnectIdentityStatus = null;
  let walletDisconnectServerComplete = false;
  let fullWalletDisconnectOperation = null;
  const PENDING_ALLOWANCE_STORAGE_PREFIX = "clink.account.pending_allowance.v1.";
  const PENDING_ALLOWANCE_STORAGE_V2_PREFIX = "clink.account.pending_allowance.v2.";
  const PENDING_ALLOWANCE_PROBE_PREFIX = "clink.account.pending_allowance_probe.v2.";
  const ALLOWANCE_ATTEMPT_STORAGE_PREFIX = "clink.account.allowance_attempt.v1.";
  const ALLOWANCE_POST_SEND_UNCERTAIN_STORAGE_PREFIX =
    "clink.account.allowance_post_send_uncertain.v1.";
  const ALLOWANCE_POST_SEND_UNCERTAIN_STORAGE_V2_PREFIX =
    "clink.account.allowance_post_send_uncertain.v2.";
  const ALLOWANCE_POST_SEND_UNCERTAIN_LABEL =
    "allowance_post_send_uncertain";
  const ALLOWANCE_POST_SEND_UNCERTAIN_MESSAGE =
    "The allowance transaction may have been submitted by your wallet. Do not retry it. Inspect the transaction in your wallet and contact support before sending another allowance transaction.";
  const ALLOWANCE_REVOKE_STORAGE_PREFIX =
    "clink.account.allowance_revoke.v1.";
  const ALLOWANCE_REVOKE_PROBE_PREFIX =
    "clink.account.allowance_revoke_probe.v1.";
  const ALLOWANCE_REVOKE_UNCERTAIN_PREFIX =
    "clink.account.allowance_revoke_uncertain.v1.";
  const ALLOWANCE_REVOKE_UNCERTAIN_LABEL =
    "allowance_revoke_post_send_uncertain";
  const ALLOWANCE_REVOKE_UNCERTAIN_MESSAGE =
    "The allowance revocation transaction may have been submitted. Do not resend it. Retry chain verification after checking the transaction in your wallet.";
  const ALLOWANCE_REVOKE_FIELDS = [
    "allowance_tx_hash",
    "asset_allowance_id",
    "network",
    "operation",
    "spender_address",
    "token_address",
    "wallet_address",
    "wallet_identity_id"
  ];
  const WALLET_DISCONNECT_STORAGE_PREFIX =
    "clink.account.wallet_disconnect.v1.";
  const WALLET_DISCONNECT_FIELDS = [
    "allowances",
    "allowances_cleared",
    "core_disconnected",
    "operation",
    "provider_uuid",
    "wallet_address",
    "wallet_identity_id"
  ];
  const LEGACY_WALLET_DISCONNECT_FIELDS =
    WALLET_DISCONNECT_FIELDS.filter(
      (field) => field !== "allowances_cleared"
    );
  const WALLET_DISCONNECT_ALLOWANCE_FIELDS = [
    "asset_allowance_id",
    "network",
    "observed_allowance_atomic",
    "spender_address",
    "token_address"
  ];
  const PENDING_ALLOWANCE_FIELDS = [
    "allowance_tx_hash",
    "network",
    "spender_address",
    "token_address",
    "wallet_identity_id"
  ];
  const ALLOWANCE_RECOVERY_FIELDS = [
    "allowance_tx_hash",
    "amount_atomic",
    "attempt_id",
    "created_at",
    "next_check_at",
    "network",
    "reason_code",
    "spender_address",
    "status",
    "token_address",
    "updated_at",
    "user_id",
    "wallet_identity_id"
  ];
  const ALLOWANCE_RECOVERY_MISMATCH_FIELDS = [
    ...ALLOWANCE_RECOVERY_FIELDS,
    "actual_approved_amount_atomic",
    "observed_allowance_atomic",
    "confirmed_block",
    "confirmed_block_hash",
    "verified_at"
  ];
  const ALLOWANCE_ATTEMPT_FIELDS = [
    "amount_atomic",
    "attempt_id",
    "network",
    "request_key",
    "spender_address",
    "status",
    "token_address",
    "wallet_identity_id"
  ];
  const ALLOWANCE_RECOVERY_STATUSES = new Set([
    "awaiting_wallet",
    "pending",
    "verified",
    "rejected",
    "attention_required",
    "confirmed_mismatch"
  ]);
  const ALLOWANCE_RECOVERY_OPEN_STATUSES = new Set([
    "awaiting_wallet",
    "pending",
    "attention_required"
  ]);
  const ALLOWANCE_RECOVERY_REASON_CODES = new Set([
    "rpc_unavailable",
    "chain_pending",
    "invalid_evidence",
    "wallet_unavailable",
    "amount_mismatch"
  ]);
  const ACCOUNT_SESSION_EXPIRED_MESSAGE =
    "Account session expired. Open a new account management link and sign in to continue verification. Your spending authorization is unchanged; do not approve again.";
  const ALLOWANCE_PREPARE_UNCERTAIN_MESSAGE =
    "Allowance preparation did not return a definitive result. Refresh account status before retrying; do not approve again.";

  const canonicalWalletAddress = (value) => {
    const normalized = String(value || "").toLowerCase();
    if (!/^0x[0-9a-f]{40}$/.test(normalized)) {
      throw new Error("Wallet returned an invalid account address");
    }
    return normalized;
  };

  const cookieValue = (name) => document.cookie
    .split("; ")
    .find((item) => item.startsWith(`${name}=`))
    ?.slice(name.length + 1) || "";

  const escapeHtml = (value) => String(value)
    .replaceAll("&", "&amp;")
    .replaceAll("<", "&lt;")
    .replaceAll(">", "&gt;")
    .replaceAll('"', "&quot;")
    .replaceAll("'", "&#039;");

  const walletChoiceCopy = (primary, secondary) => {
    const copy = document.createElement("span");
    copy.className = "wallet-choice-copy";
    const strong = document.createElement("strong");
    strong.textContent = primary;
    const small = document.createElement("small");
    small.textContent = secondary;
    copy.append(strong, small);
    return copy;
  };

  const walletChoiceIcon = (info) => {
    const frame = document.createElement("span");
    frame.className = "wallet-choice-icon";
    frame.setAttribute("aria-hidden", "true");
    const fallback = document.createElement("span");
    fallback.className = "wallet-choice-icon-fallback";
    fallback.textContent = String(info.name || "").trim().charAt(0).toUpperCase() || "?";
    frame.append(fallback);

    const source = String(info.icon || "");
    if (!source.toLowerCase().startsWith("data:image/") || !source.includes(",")) {
      return frame;
    }
    const icon = document.createElement("img");
    icon.src = source;
    icon.alt = "";
    icon.addEventListener("error", () => {
      icon.hidden = true;
    });
    frame.append(icon);
    return frame;
  };

  const renderWalletProviders = () => {
    const container = $("#wallet-provider-options");
    container.replaceChildren();
    if (!discoveredWallets.size) {
      const empty = document.createElement("p");
      empty.className = "muted";
      empty.textContent = "No compatible browser wallet detected.";
      container.append(empty);
      return;
    }
    for (const [uuid, detail] of discoveredWallets) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "wallet-choice";
      button.dataset.providerUuid = uuid;
      button.setAttribute("aria-pressed", String(uuid === selectedProviderUuid));
      button.append(
        walletChoiceIcon(detail.info),
        walletChoiceCopy(detail.info.name, detail.info.rdns)
      );
      button.addEventListener("click", () => selectWalletProvider(uuid));
      container.append(button);
    }
  };

  const renderWalletAccounts = () => {
    const container = $("#wallet-account-options");
    container.replaceChildren();
    if (!availableWalletAccounts.length) {
      const empty = document.createElement("p");
      empty.className = "muted";
      empty.textContent = selectedProviderUuid
        ? "Unlock the wallet and allow account access."
        : "Choose a browser wallet first.";
      container.append(empty);
      return;
    }
    for (const address of availableWalletAccounts) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "wallet-choice wallet-address";
      button.setAttribute("role", "radio");
      button.setAttribute("aria-checked", String(address === selectedWalletAddress));
      button.textContent = address;
      button.addEventListener("click", () => selectWalletAddress(address));
      container.append(button);
    }
  };

  const updateWalletSelectionActions = () => {
    $("#connect-wallet").disabled = Boolean(walletLoginOperation) || !(
      selectedProviderUuid && selectedWalletAddress
    );
    $("#cancel-wallet-selection").disabled = Boolean(
      walletSelectionDisconnectOperation
    ) || !(pendingProviderSelection || selectedProviderUuid);
    $("#wallet-selection-state").textContent = pendingProviderSelection
      ? "Requesting accounts from the selected wallet."
      : selectedWalletAddress
        ? `Selected ${discoveredWallets.get(selectedProviderUuid).info.name} / ${selectedWalletAddress}. ${isEmbeddedView() ? "Check Core's wallet status; sign only if ownership verification is still needed." : "Not signed in; sign to continue."}`
        : selectedProviderUuid
          ? "Addresses returned by the wallet are not signed in. Choose the exact account address to continue."
          : "No browser wallet or account selected.";
    refreshPermissionReadiness();
    updateWalletDisconnectRecovery();
    opcUpdateReviewActions?.();
  };

  const selectWalletAddress = (address) => {
    const canonical = canonicalWalletAddress(address);
    if (!availableWalletAccounts.includes(canonical)) {
      throw new Error("Choose an account returned by the selected wallet");
    }
    selectedWalletAddress = canonical;
    selectionGeneration += 1;
    opcSetupInvalidate?.("Wallet address changed. Review the exact authorization again.");
    invalidateOpcReview("Wallet address changed. Review the device request again before signing.");
    invalidateEmbeddedContext(
      "Wallet address changed. Review authorization again before signing."
    );
    renderWalletAccounts();
    updateWalletSelectionActions();
    opcUpdateReviewActions?.();
    refreshAllowanceReadiness();
  };

  const registerWalletProvider = (detail) => {
    if (!detail?.info?.uuid || !detail?.provider) return;
    const existing = discoveredWallets.get(detail.info.uuid);
    const replacesPendingProvider = Boolean(
      existing &&
      existing.provider !== detail.provider &&
      pendingProviderSelection?.uuid === detail.info.uuid &&
      pendingProviderSelection.provider === existing.provider
    );
    const replacesSelectedProvider = Boolean(
      existing &&
      existing.provider !== detail.provider &&
      selectedProviderUuid === detail.info.uuid &&
      selectedWalletProvider === existing.provider
    );
    if (replacesPendingProvider || replacesSelectedProvider) {
      invalidateWalletSelection(
        "The selected wallet provider changed. Choose the wallet and address again."
      );
    }
    discoveredWallets.set(detail.info.uuid, detail);
    renderWalletProviders();
    updateWalletDisconnectRecovery();
  };

  const announceWalletProvider = (event) => {
    registerWalletProvider(event.detail);
  };

  const clearEmbeddedReview = (message = "") => {
    embeddedPlan = null;
    embeddedPlanGeneration = 0;
    embeddedApprovalReview = null;
    const plan = $("#embedded-plan");
    const approval = $("#embedded-approval-confirm");
    if (plan) plan.hidden = true;
    if (approval) approval.hidden = true;
    const confirm = $("#embedded-plan-confirm");
    const cancel = $("#embedded-plan-cancel");
    const retry = $("#embedded-plan-retry");
    const approveButton = $("#embedded-approve");
    if (confirm) confirm.hidden = true;
    if (cancel) cancel.hidden = true;
    if (retry) retry.hidden = true;
    if (approveButton) approveButton.hidden = true;
    if (message && $("#embedded-plan-allowance")) {
      $("#embedded-plan-allowance").textContent = message;
    }
  };

  const invalidateEmbeddedContext = (message = "") => {
    if (!isEmbeddedView()) return;
    embeddedGeneration += 1;
    clearEmbeddedReview(message);
  };

  const invalidateWalletSelection = (
    message = "Wallet state changed. Choose the wallet and address again."
  ) => {
    const cleanup = removeSelectedProviderListeners;
    opcSetupInvalidate?.(message);
    invalidateOpcReview(
      "Wallet state changed. Review the device request again before signing."
    );
    invalidateEmbeddedContext(
      "Wallet selection changed. Review authorization again before signing."
    );
    selectionGeneration += 1;
    pendingProviderSelection = null;
    removeSelectedProviderListeners = () => {};
    selectedProviderUuid = null;
    selectedWalletProvider = null;
    availableWalletAccounts = [];
    selectedWalletAddress = null;
    renderWalletProviders();
    renderWalletAccounts();
    updateWalletSelectionActions();
    opcUpdateReviewActions?.();
    disableApprovalActions();
    $("#permission-form").querySelector("button").disabled = true;
    $("#wallet-selection-state").textContent = message;
    try {
      cleanup();
    } catch (_error) {
      // Listener removal is best effort after all wallet actions are disabled.
    }
  };

  const canonicalProviderAccounts = (accounts) => {
    if (!Array.isArray(accounts)) {
      throw new Error("Wallet returned an invalid account response");
    }
    return [...new Set(accounts.map(canonicalWalletAddress))];
  };

  const DEFAULT_PROVIDER_REQUEST_TIMEOUT_MS = 15000;
  const PROVIDER_FAILURE_BRAND = Symbol("clinkProviderFailure");
  const PROVIDER_TIMEOUT_BRAND = Symbol("clinkProviderTimeout");
  const providerRequestTimeoutMs = () => {
    const testOverride = globalThis.__clinkProviderRequestTimeoutMs;
    return typeof testOverride === "number" && Number.isFinite(testOverride) && testOverride > 0
      ? testOverride
      : DEFAULT_PROVIDER_REQUEST_TIMEOUT_MS;
  };
  const providerErrorCode = (error) => {
    const rawCode = error?.code;
    const code = typeof rawCode === "number"
      ? rawCode
      : typeof rawCode === "string" && /^-?\d+$/.test(rawCode)
        ? parseInt(rawCode, 10)
        : null;
    return Number.isInteger(code) && code >= -99999 && code <= 99999 ? code : null;
  };
  const providerErrorClass = (error, code) => {
    if (code === 4001) return "user_rejected";
    if (error?.[PROVIDER_TIMEOUT_BRAND]) return "timeout";
    return "provider_error";
  };
  const setAccountStage = (stage, message = "") => {
    status.dataset.stage = stage;
    status.setAttribute("data-stage", stage);
    if (message) status.textContent = message;
    const setupStatus = $("#opc-setup-status");
    if (setupStatus) {
      setupStatus.dataset.stage = stage;
      setupStatus.setAttribute("data-stage", stage);
      if (message) setupStatus.textContent = message;
    }
  };
  const providerFailure = (error, stage) => {
    const code = providerErrorCode(error);
    const classification = providerErrorClass(error, code);
    const timedOut = Boolean(error?.[PROVIDER_TIMEOUT_BRAND]);
    const safeMessage = classification === "user_rejected"
      ? `Wallet request was rejected during ${stage}${code === null ? "" : ` (code ${code})`}.`
      : classification === "timeout"
        ? `Wallet request timed out during ${stage}. It may still be open; this timeout does not cancel the wallet request.`
        : `Wallet request failed during ${stage} (${classification}${code === null ? "" : `, code ${code}`}).`;
    const safe = new Error(safeMessage);
    safe[PROVIDER_FAILURE_BRAND] = true;
    safe.providerStage = stage;
    safe.providerClass = classification;
    safe.providerCode = code;
    safe.code = code;
    safe.userRejected = code === 4001;
    safe.providerTimeout = timedOut;
    if (timedOut && error?.pendingRequest) safe.pendingRequest = error.pendingRequest;
    return safe;
  };
  const setProviderFailureStatus = (error) => {
    if (!error?.providerStage) return;
    setAccountStage(error.providerStage, error.message);
  };
  const providerRequest = async (
    provider,
    request,
    {stage = "wallet_confirmation", timeoutMs = providerRequestTimeoutMs()} = {}
  ) => {
    const pending = Promise.resolve().then(() => provider.request(request));
    let timer;
    const timeout = new Promise((_, reject) => {
      timer = window.setTimeout(() => {
        const error = new Error(
          `Wallet request timed out during ${stage}. It may still be open; this timeout does not cancel the wallet request.`
        );
        error[PROVIDER_TIMEOUT_BRAND] = true;
        error.pendingRequest = pending;
        reject(error);
      }, timeoutMs);
    });
    try {
      return await Promise.race([pending, timeout]);
    } catch (error) {
      const safe = providerFailure(error, stage);
      setProviderFailureStatus(safe);
      throw safe;
    } finally {
      if (timer !== undefined) {
        if (typeof window.clearTimeout === "function") window.clearTimeout(timer);
        else globalThis.clearTimeout?.(timer);
      }
    }
  };

  const providerAccounts = async (provider) => canonicalProviderAccounts(
    await provider.request({method: "eth_accounts"})
  );

  const allowanceProviderAccounts = async (provider) => canonicalProviderAccounts(
    await providerRequest(provider, {method: "eth_accounts"}, {stage: "wallet_confirmation"})
  );

  const cancelWalletLoginOperation = async (operation) => {
    if (
      !operation?.challengeSessionId ||
      operation.challengeCancelRequested ||
      operation.verified
    ) {
      return;
    }
    operation.challengeCancelRequested = true;
    await request(
      `/wallet-challenges/${encodeURIComponent(
        operation.challengeSessionId
      )}/cancel`,
      {method: "POST", body: "{}"}
    );
  };

  const disconnectWalletSelection = async () => {
    if (walletSelectionDisconnectOperation) {
      return walletSelectionDisconnectOperation;
    }
    const loginOperation = walletLoginOperation;
    const operation = (async () => {
      if (loginOperation) loginOperation.cancelled = true;
      invalidateWalletSelection(
        "Wallet login cancelled. Choose a wallet to start again."
      );
      if (loginOperation) {
        try {
          await cancelWalletLoginOperation(loginOperation);
        } catch (_error) {
          status.textContent =
            "Wallet login was cleared locally. The short-lived login challenge could not be cancelled.";
          status.classList.add("error");
        }
      }
      return true;
    })();
    walletSelectionDisconnectOperation = operation;
    try {
      return await operation;
    } finally {
      if (walletSelectionDisconnectOperation === operation) {
        walletSelectionDisconnectOperation = null;
      }
    }
  };

  const attachSelectedProviderListeners = (provider) => {
    try {
      removeSelectedProviderListeners();
    } catch (_error) {
      // The previous selection is already unusable.
    }
    const events = ["accountsChanged", "chainChanged", "disconnect"];
    const listeners = new Map();
    for (const eventName of events) {
      const listener = (eventValue) => {
        if (
          eventName === "chainChanged" &&
          opcSetupExpectedChainChange?.(eventValue)
        ) {
          return;
        }
        invalidateWalletSelection();
      };
      listeners.set(eventName, listener);
      provider.on?.(eventName, listener);
    }
    removeSelectedProviderListeners = () => {
      for (const eventName of events) {
        provider.removeListener?.(eventName, listeners.get(eventName));
      }
    };
  };

  const selectWalletProvider = async (uuid) => {
    const detail = discoveredWallets.get(uuid);
    if (!detail) return;
    invalidateWalletSelection("Requesting accounts from the selected wallet.");
    const generation = selectionGeneration;
    const pending = {uuid, provider: detail.provider, generation};
    pendingProviderSelection = pending;
    updateWalletSelectionActions();
    const assertCurrentSelection = () => {
      if (
        pendingProviderSelection !== pending ||
        pendingProviderSelection?.uuid !== uuid ||
        pendingProviderSelection.provider !== detail.provider ||
        pendingProviderSelection.generation !== generation ||
        generation !== selectionGeneration ||
        discoveredWallets.get(uuid)?.provider !== detail.provider
      ) {
        throw new Error(
          "Wallet selection changed before account access was requested."
        );
      }
    };
    try {
      const accounts = canonicalProviderAccounts(
        await detail.provider.request({method: "eth_requestAccounts"})
      );
      if (!accounts.length) {
        throw new Error("Wallet returned no account addresses");
      }
      assertCurrentSelection();
      if (
        pendingProviderSelection !== pending ||
        pendingProviderSelection?.uuid !== uuid ||
        pendingProviderSelection.provider !== detail.provider ||
        pendingProviderSelection.generation !== generation ||
        generation !== selectionGeneration ||
        discoveredWallets.get(uuid)?.provider !== detail.provider
      ) {
        if (pendingProviderSelection === pending) invalidateWalletSelection();
        return;
      }
      pendingProviderSelection = null;
      selectedProviderUuid = uuid;
      selectedWalletProvider = detail.provider;
      availableWalletAccounts = accounts;
      attachSelectedProviderListeners(detail.provider);
      renderWalletProviders();
      renderWalletAccounts();
      updateWalletSelectionActions();
    } catch (error) {
      if (
        pendingProviderSelection === pending &&
        generation === selectionGeneration
      ) {
        invalidateWalletSelection(
          "Wallet access was not granted. Choose the wallet again."
        );
        status.textContent = error.message;
        status.classList.add("error");
      }
    }
  };

  const selectedWalletSnapshot = () => {
    const detail = discoveredWallets.get(selectedProviderUuid);
    if (
      !detail ||
      !selectedWalletProvider ||
      detail.provider !== selectedWalletProvider ||
      !selectedWalletAddress
    ) {
      throw new Error("Choose a browser wallet and account address first");
    }
    return {
      uuid: selectedProviderUuid,
      provider: selectedWalletProvider,
      address: selectedWalletAddress,
      generation: selectionGeneration
    };
  };

  const assertWalletSnapshot = (snapshot) => {
    if (
      snapshot.generation !== selectionGeneration ||
      snapshot.uuid !== selectedProviderUuid ||
      snapshot.provider !== selectedWalletProvider ||
      snapshot.address !== selectedWalletAddress ||
      discoveredWallets.get(snapshot.uuid)?.provider !== snapshot.provider
    ) {
      throw new Error("Wallet state changed. Choose the wallet and address again.");
    }
  };

  const selectedWalletIdentity = (selection, state = accountState) => {
    if (!state) throw new Error("Account controls are not loaded");
    const identity = state.wallet_identities.find((item) =>
      item.status === "active" &&
      canonicalAddress(item.wallet_address) === selection.address
    );
    if (!identity) throw new Error("Selected wallet does not match an active bound wallet");
    return identity;
  };

  const providerAccountsContainSelection = async (
    selection,
    {bounded = false} = {}
  ) => {
    const canonical = bounded
      ? await allowanceProviderAccounts(selection.provider)
      : await providerAccounts(selection.provider);
    assertWalletSnapshot(selection);
    if (!canonical.includes(selection.address)) {
      throw new Error("Selected wallet does not match the bound wallet");
    }
  };

  const parseResponse = async (response) => {
    try {
      return await response.json();
    } catch (_error) {
      return {detail: "Request could not be completed"};
    }
  };

  const markAccountSessionExpired = () => {
    if (!allowanceSessionExpired) accountSessionGeneration += 1;
    allowanceSessionExpired = true;
    if (allowanceVerificationRetryTimer !== null) {
      window.clearTimeout(allowanceVerificationRetryTimer);
      allowanceVerificationRetryTimer = null;
    }
    allowanceVerificationRetryAttempts = 0;
    allowanceVerificationRetryInFlight = false;
    disableApprovalActions();
    const permissionButton = $("#permission-form")?.querySelector("button");
    if (permissionButton) permissionButton.disabled = true;
    opcSetupBlockFromRecovery?.();
    updatePendingAllowanceRecovery();
  };

  const beginAccountSessionAfterWalletLogin = () => {
    accountSessionGeneration += 1;
    allowanceSessionExpired = false;
  };

  const request = async (suffix = "", options = {}) => {
    const csrfToken = cookieValue("clink_account_csrf");
    const response = await fetch(`${window.location.pathname}${suffix}`, {
      ...options,
      headers: {"Accept": "application/json", "Content-Type": "application/json", "X-CSRF-Token": csrfToken, ...(options.headers || {})}
    });
    const body = await parseResponse(response);
    if (!response.ok) {
      const error = new Error(body.detail || "Request could not be completed");
      error.httpStatus = response.status;
      error.statusCode = response.status;
      if (
        response.status === 409 &&
        body?.code === "allowance_amount_mismatch"
      ) {
        try {
          const recovery = validateAllowanceRecoveryRecord(body.recovery);
          if (recovery.status === "confirmed_mismatch") {
            error.code = "allowance_amount_mismatch";
            error.allowanceMismatch = recovery;
          }
        } catch (_error) {
          // Never expose an unvalidated recovery record to callers.
        }
      }
      if (
        [401, 410].includes(response.status) &&
        body.detail !== "wallet authentication required"
      ) {
        error.accountSessionExpired = true;
        error.message = ACCOUNT_SESSION_EXPIRED_MESSAGE;
        markAccountSessionExpired();
      }
      throw error;
    }
    return body;
  };

  const ledgerRow = (label, value, meta = "") => `<div class="ledger-row"><p class="ledger-label">${escapeHtml(label)}</p><p class="ledger-value">${escapeHtml(value)}</p><p class="ledger-meta">${escapeHtml(meta)}</p></div>`;

  const localDateTime = (value) => {
    const parsed = new Date(value);
    return Number.isNaN(parsed.getTime()) ? value : parsed.toLocaleString();
  };

  const EMBEDDED_TERM_FIELDS = [
    "wallet_identity_id",
    "agent_id",
    "max_amount_usdc",
    "per_transaction_limit_usdc",
    "hourly_limit_usdc",
    "daily_limit_usdc",
    "product_scopes",
    "venue_scopes",
    "merchant_scopes",
    "merchant_trust_scopes",
    "notification_mode",
    "network_scopes",
    "asset_scopes",
    "starts_at",
    "expires_at"
  ];
  const EMBEDDED_ALLOWANCE_FIELDS = [
    "status",
    "required_usdc",
    "target_usdc",
    "target_atomic",
    "observed_atomic",
    "exceeds_budget",
    "network",
    "token_address",
    "spender_address",
    "wallet_address",
    "asset_allowance_id",
    "observed_at"
  ];

  const exactObjectKeys = (value, required, optional = []) => {
    if (!value || typeof value !== "object" || Array.isArray(value)) return false;
    const allowed = new Set([...required, ...optional]);
    const keys = Object.keys(value);
    return keys.every((key) => allowed.has(key)) &&
      required.every((key) => Object.prototype.hasOwnProperty.call(value, key));
  };

  const isEmbeddedAmount = (value) =>
    typeof value === "string" && /^(0|[1-9]\d*)(\.\d{1,6})?$/.test(value);

  const isEmbeddedAtomic = (value, allowNull = false) =>
    (allowNull && value === null) ||
    (typeof value === "string" && /^(0|[1-9]\d*)$/.test(value));

  const isEmbeddedStringArray = (value) =>
    Array.isArray(value) && value.every((item) => typeof item === "string");

  const validateEmbeddedPlan = (value) => {
    if (!exactObjectKeys(value, ["action", "terms", "allowance"])) {
      throw new Error("Core returned an invalid authorization plan");
    }
    if (!["none", "sign"].includes(value.action)) {
      throw new Error("Core returned an invalid authorization action");
    }
    if (!exactObjectKeys(value.terms, EMBEDDED_TERM_FIELDS, ["amends_spending_grant_id"])) {
      throw new Error("Core returned invalid authorization terms");
    }
    if (
      !EMBEDDED_TERM_FIELDS.filter((field) =>
        ["wallet_identity_id", "agent_id", "notification_mode", "starts_at", "expires_at"].includes(field)
      ).every((field) => typeof value.terms[field] === "string") ||
      !["max_amount_usdc", "per_transaction_limit_usdc", "hourly_limit_usdc", "daily_limit_usdc"].every(
        (field) => isEmbeddedAmount(value.terms[field])
      ) ||
      !["product_scopes", "venue_scopes", "merchant_scopes", "merchant_trust_scopes", "network_scopes", "asset_scopes"].every(
        (field) => isEmbeddedStringArray(value.terms[field])
      ) ||
      (value.terms.amends_spending_grant_id != null &&
        typeof value.terms.amends_spending_grant_id !== "string")
    ) {
      throw new Error("Core returned invalid authorization terms");
    }
    const allowance = value.allowance;
    if (!exactObjectKeys(allowance, EMBEDDED_ALLOWANCE_FIELDS)) {
      throw new Error("Core returned invalid allowance advice");
    }
    if (
      !["unknown", "exhausted", "sufficient", "insufficient"].includes(allowance.status) ||
      !isEmbeddedAmount(allowance.required_usdc) ||
      !isEmbeddedAmount(allowance.target_usdc) ||
      !isEmbeddedAtomic(allowance.target_atomic) ||
      !isEmbeddedAtomic(allowance.observed_atomic, true) ||
      (allowance.exceeds_budget !== null && typeof allowance.exceeds_budget !== "boolean") ||
      typeof allowance.network !== "string" ||
      typeof allowance.token_address !== "string" ||
      typeof allowance.spender_address !== "string" ||
      typeof allowance.wallet_address !== "string" ||
      (allowance.asset_allowance_id !== null && typeof allowance.asset_allowance_id !== "string") ||
      (allowance.observed_at !== null && typeof allowance.observed_at !== "string")
    ) {
      throw new Error("Core returned invalid allowance advice");
    }
    try {
      canonicalAddress(allowance.token_address);
      canonicalAddress(allowance.spender_address);
      canonicalAddress(allowance.wallet_address);
    } catch (_error) {
      throw new Error("Core returned invalid allowance addresses");
    }
    return value;
  };

  const embeddedOperationGuard = (operation) => {
    if (
      !operation ||
      embeddedOperation !== operation ||
      operation.cancelled ||
      operation.generation !== embeddedGeneration
    ) {
      throw new Error("authorization review expired. Review the current wallet and terms again.");
    }
  };

  const beginEmbeddedOperation = () => {
    if (embeddedOperation) {
      throw new Error("An embedded authorization operation is already in progress");
    }
    const operation = {generation: embeddedGeneration, cancelled: false};
    embeddedOperation = operation;
    return operation;
  };

  const endEmbeddedOperation = (operation) => {
    if (embeddedOperation === operation) embeddedOperation = null;
  };

  const embeddedIdentity = () => {
    const identity = accountState?.wallet_identities?.find(
      (item) => item.status === "active"
    );
    if (!identity) throw new Error("Wallet authentication is required before authorization");
    return identity;
  };

  const embeddedFormPayload = () => {
    const current = accountState?.current_spending_mandate;
    const identity = embeddedIdentity();
    if (current?.status === "paused") {
      throw new Error("The current Spending Mandate is paused. Revoke it here or resume it in the full Core console; no resume is performed in embedded authorization.");
    }
    const network = $("#embedded-network").value;
    if (typeof network !== "string" || !network) {
      throw new Error("Choose a supported authorization network");
    }
    const total = String($("#embedded-total-limit").value).trim();
    const hourly = String($("#embedded-hourly-limit").value).trim();
    if (!isEmbeddedAmount(total) || !isEmbeddedAmount(hourly)) {
      throw new Error("Enter valid USDC limits with at most six decimals");
    }
    let duration = null;
    if (!current) {
      duration = Number.parseInt($("#embedded-duration-days").value, 10);
      if (!Number.isInteger(duration) || duration < 1 || duration > 365) {
        throw new Error("Permission duration must be between 1 and 365 days");
      }
    }
    return {
      wallet_identity_id: identity.wallet_identity_id,
      network,
      total_usdc: total,
      hourly_usdc: hourly,
      duration_days: duration,
      spending_grant_id: current?.spending_grant_id || null
    };
  };

  const embeddedPlanRequest = async (operation, {render = true} = {}) => {
    embeddedOperationGuard(operation);
    const payload = embeddedFormPayload();
    const plan = validateEmbeddedPlan(await request("/authorization-plan", {
      method: "POST",
      body: JSON.stringify(payload)
    }));
    embeddedOperationGuard(operation);
    if (render) renderEmbeddedPlan(plan);
    return plan;
  };

  const renderEmbeddedNetworkOptions = (state) => {
    const select = $("#embedded-network");
    if (!select) return;
    const previousNetwork = select.value;
    const current = state.current_spending_mandate;
    const networks = current?.network_scopes?.length
      ? current.network_scopes.filter((network) => state.network_configs[network])
      : Object.keys(state.network_configs);
    select.innerHTML = networks.map((network) => {
      const label = networkLabel(network, state.network_configs[network]);
      return `<option value="${escapeHtml(network)}">${escapeHtml(label)} (${escapeHtml(network)})</option>`;
    }).join("");
    if (networks.length) {
      select.value = networks.includes(previousNetwork) ? previousNetwork : networks[0];
    }
    select.disabled = Boolean(current && networks.length <= 1);
  };

  const embeddedRevokeAllowanceForState = (state) => {
    const current = state?.current_spending_mandate;
    const checkbox = $("#embedded-revoke-allowance");
    const label = $("#embedded-revoke-allowance-label");
    if (!current) {
      if (checkbox) {
        checkbox.checked = false;
        checkbox.disabled = true;
      }
      if (label) label.textContent = "Clear the selected network allowance too; this is shared with other businesses using the same wallet, token, and spender.";
      return null;
    }
    const network = $("#embedded-network")?.value;
    const config = network ? state.network_configs?.[network] : null;
    const target = network ? state.approval_targets?.[network] : null;
    const identity = state.wallet_identities?.find(
      (item) => item.wallet_identity_id === current.wallet_identity_id
    );
    let tokenAddress = null;
    let spenderAddress = null;
    try {
      tokenAddress = target ? canonicalAddress(target.token_address) : null;
      spenderAddress = target ? canonicalAddress(target.spender_address) : null;
    } catch (_error) {
      tokenAddress = null;
      spenderAddress = null;
    }
    const allowance = identity && tokenAddress && spenderAddress
      ? (state.asset_allowances || []).find((item) => {
          if (
            item.wallet_identity_id !== current.wallet_identity_id ||
            item.network !== network ||
            item.status !== "active"
          ) return false;
          try {
            return (
              BigInt(String(item.observed_allowance_atomic)) > 0n &&
              canonicalAddress(item.token_address) === tokenAddress &&
              canonicalAddress(item.spender_address) === spenderAddress
            );
          } catch (_error) {
            return false;
          }
        })
      : null;
    if (label) {
      label.textContent = config && tokenAddress && spenderAddress
        ? `Clear the ${networkLabel(network, config)} (${network}) allowance for ${tokenAddress} → ${spenderAddress}. This wallet-wide allowance is shared with other businesses using the same token and spender.`
        : "No configured chain target is available for the selected network; Core spending can still be revoked without clearing an allowance.";
    }
    if (checkbox) {
      checkbox.disabled = !allowance;
      if (!allowance) checkbox.checked = false;
    }
    return allowance && identity
      ? {...allowance, wallet_address: allowance.wallet_address || identity.wallet_address}
      : null;
  };

  const renderEmbeddedState = (state) => {
    if (!isEmbeddedView()) return;
    renderEmbeddedNetworkOptions(state);
    const current = state.current_spending_mandate;
    const currentActions = $("#embedded-current-actions");
    const revokeButton = $("#embedded-revoke-spending");
    const submitButton = $("#embedded-permission-submit");
    const isPaused = current?.status === "paused";
    if (currentActions) currentActions.hidden = !current;
    if (revokeButton) revokeButton.hidden = !current;
    embeddedRevokeAllowanceForState(state);
    if (submitButton) {
      submitButton.disabled = isPaused;
      submitButton.textContent = current ? "Review authorization amendment" : "Review authorization";
    }
    $("#page-eyebrow").textContent = current
      ? "Existing Core authorization"
      : "Marketplace authorization";
    $("#page-heading").textContent = current
      ? "Review the current spending permission."
      : "Authorize Marketplace purchases through Clink.";
    $("#page-lede").textContent = current
      ? `Review the existing ${current.product_scopes.join(", ")} scope, budget, expiry, and shared chain allowance. Core keeps the current scope and dates intact.`
      : "Create one Marketplace-only Spending Mandate for this wallet. Core supplies the exact terms; this authorization does not enable purchasing or funding by itself.";
    const expiry = $("#embedded-current-expiry");
    const duration = $("#embedded-duration-days");
    const total = $("#embedded-total-limit");
    const hourly = $("#embedded-hourly-limit");
    if (current) {
      total.value = current.limits_usdc.total;
      hourly.value = current.limits_usdc.rolling_hour;
      duration.hidden = true;
      duration.required = false;
      if (expiry) {
        expiry.hidden = false;
        expiry.textContent = `Existing expiry: ${current.expires_at}. It is read-only and will not be extended.`;
      }
      $("#embedded-mandate-state").textContent = isPaused
        ? "Current mandate is paused. It will not be resumed here; revoke it separately if that is your intent."
        : "Current mandate is amended in place; its scope and expiry remain unchanged.";
      $("#embedded-state").textContent = isPaused ? "Paused" : "Current";
    } else {
      duration.hidden = false;
      duration.required = true;
      if (expiry) expiry.hidden = true;
      $("#embedded-mandate-state").textContent = "A new Marketplace-only Spending Mandate will be proposed by Core.";
      $("#embedded-state").textContent = "Review";
    }
    $("#embedded-proof-state").textContent = state.wallet_identities?.length
      ? "Wallet ownership is verified for this Core session."
      : "Sign in with the selected EIP-1193 / EIP-6963 provider.";
    $("#embedded-approval-state").textContent = "Chain approval is separate from the mandate and requires its own exact amount and gas confirmation.";
  };

  const embeddedTermsMarkup = (terms, allowance) => {
    const rows = [
      ledgerRow("Wallet identity", terms.wallet_identity_id),
      ledgerRow("Agent", terms.agent_id),
      ledgerRow("Total limit", terms.max_amount_usdc, "USDC"),
      ledgerRow("Per purchase", terms.per_transaction_limit_usdc, "USDC"),
      ledgerRow("Rolling hour", terms.hourly_limit_usdc, "USDC"),
      ledgerRow("Daily limit", terms.daily_limit_usdc, "USDC"),
      ledgerRow("Products", terms.product_scopes.join(", ")),
      ledgerRow("Venues", terms.venue_scopes.join(", ")),
      ledgerRow("Merchants", terms.merchant_scopes.length ? terms.merchant_scopes.join(", ") : "Any merchant within the signed trust scope"),
      ledgerRow("Merchant trust", terms.merchant_trust_scopes.join(", ")),
      ledgerRow("Notification mode", terms.notification_mode),
      ledgerRow("Network", `${allowance.network} / ${terms.network_scopes.join(", ")}`),
      ledgerRow("Signed asset scope", terms.asset_scopes.join(", ")),
      ledgerRow("Token", allowance.token_address),
      ledgerRow("Spender", allowance.spender_address),
      ledgerRow("Starts at", terms.starts_at),
      ledgerRow("Expires at", terms.expires_at)
    ];
    const current = accountState?.current_spending_mandate;
    if (current) {
      rows.push(ledgerRow("Budget used", current.used_usdc.total, "USDC (Core budget)"));
      rows.push(ledgerRow("Budget reserved", current.reserved_usdc.total, "USDC (Core budget)"));
    }
    return rows.join("");
  };

  const renderEmbeddedPlan = (value) => {
    const plan = validateEmbeddedPlan(value);
    embeddedPlan = plan;
    embeddedPlanGeneration = embeddedGeneration;
    const panel = $("#embedded-plan");
    if (!panel) return;
    panel.hidden = false;
    $("#embedded-plan-terms").innerHTML = embeddedTermsMarkup(plan.terms, plan.allowance);
    const allowance = plan.allowance;
    const confirm = $("#embedded-plan-confirm");
    const cancel = $("#embedded-plan-cancel");
    const retry = $("#embedded-plan-retry");
    const approveButton = $("#embedded-approve");
    confirm.hidden = plan.action !== "sign";
    cancel.hidden = plan.action !== "sign";
    retry.hidden = allowance.status !== "unknown";
    approveButton.hidden = plan.action === "sign" || !(
      (allowance.status === "insufficient" ||
        (allowance.status === "sufficient" && allowance.exceeds_budget === true)) &&
      BigInt(allowance.target_atomic) > 0n
    );
    if (allowance.status === "unknown") {
      $("#embedded-plan-allowance").textContent = "Current allowance observation is unknown. Retry the allowance query; no approval will be sent.";
    } else if (allowance.status === "exhausted") {
      $("#embedded-plan-allowance").textContent = "The Core budget is exhausted. No allowance replenishment is offered.";
    } else if (allowance.status === "sufficient") {
      $("#embedded-plan-allowance").textContent = allowance.exceeds_budget
        ? `Observed allowance ${formatUsdcAtomic(allowance.observed_atomic)} USDC exceeds the finite target ${allowance.target_usdc} USDC. This wallet/network/token/spender allowance is shared with other businesses; review an optional adjustment explicitly.`
        : `Observed allowance ${formatUsdcAtomic(allowance.observed_atomic)} USDC is sufficient. No approval transaction is needed.`;
    } else {
      $("#embedded-plan-allowance").textContent = `Observed allowance ${allowance.observed_atomic === null ? "unknown" : formatUsdcAtomic(allowance.observed_atomic)} USDC is insufficient. Review an exact finite approval of ${allowance.target_usdc} USDC (the unspent Core budget).`;
    }
    approveButton.textContent = allowance.exceeds_budget
      ? `Review finite adjustment to ${allowance.target_usdc} USDC`
      : `Review finite chain approval for ${allowance.target_usdc} USDC`;
    $("#embedded-state").textContent = plan.action === "sign" ? "Confirm terms" : "Observed";
  };

  const grantLedger = (item) => {
    const lifecycleAction = item.status === "paused" ? "resume" : "pause";
    const lifecycleLabel = item.status === "paused" ? "Resume access" : "Pause access";
    const closed = item.status === "revoked" || item.status === "expired";
    const controls = closed ? "" : `
      <div class="grant-actions">
        <button class="row-action" data-grant-action="${lifecycleAction}" type="button">${lifecycleLabel}</button>
        <button class="row-action" data-grant-action="revoke" type="button">Revoke access</button>
      </div>`;
    const inProgress = item.reserved_usdc.total === "0"
      ? ""
      : ledgerRow("In progress", item.reserved_usdc.total, "USDC");
    const hasPreviousSafeguards = [
      item.limits_usdc.per_transaction,
      item.limits_usdc.rolling_hour,
      item.limits_usdc.daily
    ].some((value) => value !== item.limits_usdc.total);
    const previousSafeguards = hasPreviousSafeguards
      ? ledgerRow(
          "Existing safeguards",
          `${item.limits_usdc.per_transaction} per purchase`,
          `${item.limits_usdc.rolling_hour} per hour / ${item.limits_usdc.daily} per day`
        )
      : "";
    const productLabels = (item.product_scopes || []).map((product) => ({
      marketplace: "Marketplace",
      prediction_markets: "Prediction markets"
    }[product] || product));
    const scopeDescription = productLabels.length
      ? productLabels.join(" + ")
      : "No product scope";
    return `<div class="grant-ledger" data-grant-id="${escapeHtml(item.spending_grant_id)}">
      ${ledgerRow("Applies to", scopeDescription, (item.venue_scopes || []).join(" + "))}
      ${ledgerRow("Total limit", item.limits_usdc.total, "USDC")}
      ${previousSafeguards}
      ${ledgerRow("Used", item.used_usdc.total, "USDC")}
      ${inProgress}
      ${ledgerRow("Remaining", item.remaining_usdc.total, "USDC")}
      ${ledgerRow("Valid until", localDateTime(item.expires_at), "Local time")}
      ${controls}
    </div>`;
  };

  const isAccountStateObject = (value) => Boolean(
    value && typeof value === "object" && !Array.isArray(value)
  );

  const hasAccountStateStrings = (value, fields) => Boolean(
    isAccountStateObject(value) &&
    fields.every((field) => typeof value[field] === "string")
  );

  const hasAccountStateStringArray = (value) => Boolean(
    Array.isArray(value) &&
    value.every((item) => typeof item === "string")
  );

  const isDeterministicUsdcString = (value) => Boolean(
    typeof value === "string" &&
    /^(0|[1-9]\d*)(\.\d{1,6})?$/.test(value)
  );

  const isCanonicalAtomicString = (value) => Boolean(
    typeof value === "string" && /^(0|[1-9]\d*)$/.test(value)
  );

  const UINT256_MAX = (1n << 256n) - 1n;

  const isCanonicalUint256String = (value, {positive = false} = {}) => {
    if (
      typeof value !== "string" ||
      !(positive ? /^[1-9]\d*$/.test(value) : /^(0|[1-9]\d*)$/.test(value))
    ) return false;
    try {
      return BigInt(value) <= UINT256_MAX;
    } catch (_error) {
      return false;
    }
  };

  const hasAccountStateUsdcProjection = (value, expectedFields) => {
    if (!isAccountStateObject(value)) return false;
    const actualFields = Object.keys(value).sort();
    const sortedExpectedFields = [...expectedFields].sort();
    return Boolean(
      actualFields.length === sortedExpectedFields.length &&
      actualFields.every(
        (field, index) => field === sortedExpectedFields[index]
      ) &&
      sortedExpectedFields.every((field) =>
        isDeterministicUsdcString(value[field])
      )
    );
  };

  const isValidAccountGrant = (item) => Boolean(
    hasAccountStateStrings(item, [
      "spending_grant_id",
      "wallet_identity_id",
      "agent_id",
      "status",
      "max_amount_usdc",
      "per_transaction_limit_usdc",
      "daily_limit_usdc"
    ]) &&
    (item.hourly_limit_usdc == null ||
      typeof item.hourly_limit_usdc === "string") &&
    hasAccountStateStringArray(item.product_scopes) &&
    hasAccountStateStringArray(item.network_scopes) &&
    hasAccountStateStringArray(item.asset_scopes) &&
    (item.merchant_trust_scopes == null ||
      hasAccountStateStringArray(item.merchant_trust_scopes)) &&
    (item.notification_mode == null ||
      typeof item.notification_mode === "string")
  );

  const NETWORK_KEY_PATTERN = /^eip155:[1-9]\d*$/;
  const NETWORK_CONFIG_FIELDS = [
    "chain_id",
    "required_confirmations",
    "token_decimals",
    "token_symbol"
  ];

  const isPositiveInteger = (value) =>
    typeof value === "number" && Number.isSafeInteger(value) && value > 0;

  const isValidNetworkConfig = (value) => Boolean(
    isAccountStateObject(value) &&
    Object.keys(value).sort().join(",") === NETWORK_CONFIG_FIELDS.slice().sort().join(",") &&
    isPositiveInteger(value.chain_id) &&
    isPositiveInteger(value.required_confirmations) &&
    Number.isSafeInteger(value.token_decimals) &&
    value.token_decimals >= 0 &&
    value.token_decimals <= 36 &&
    typeof value.token_symbol === "string" &&
    /^[A-Za-z0-9][A-Za-z0-9._-]{0,15}$/.test(value.token_symbol)
  );

  const isValidNetworkConfigs = (value) => Boolean(
    isAccountStateObject(value) &&
    Object.keys(value).length > 0 &&
    Object.keys(value).every(
      (network) => NETWORK_KEY_PATTERN.test(network) &&
        isValidNetworkConfig(value[network])
    )
  );

  const hasConfiguredNetwork = (state, network) => Boolean(
    state &&
    isAccountStateObject(state.network_configs) &&
    typeof network === "string" &&
    Object.prototype.hasOwnProperty.call(state.network_configs, network)
  );

  const networkLabel = (network, config) =>
    KNOWN_NETWORK_LABELS[network] || `Network ${config.chain_id}`;

  const networkSlug = (network, config) => {
    const known = KNOWN_NETWORK_LABELS[network];
    if (known) return known.toLowerCase().replace(/[^a-z0-9]+/g, "-");
    return `network-${config.chain_id}`;
  };

  const networkElementSelectors = (network, config) => {
    const slug = networkSlug(network, config);
    return {
      state: `#${slug}-state`,
      token: `#${slug}-token`,
      spender: `#${slug}-spender`
    };
  };

  const networkChainId = (config) =>
    `0x${config.chain_id.toString(16)}`;

  const renderNetworkLedger = (state) => {
    const container = $("#network-ledger");
    if (!container) return;
    container.innerHTML = Object.entries(state.network_configs)
      .map(([network, config]) => {
        const selectors = networkElementSelectors(network, config);
        const label = networkLabel(network, config);
        const safeNetwork = escapeHtml(network);
        const safeLabel = escapeHtml(label);
        return `<article class="network-row" data-network="${safeNetwork}">
          <div><p class="network-name">${safeLabel}</p><p class="network-meta" data-network-state="${safeNetwork}" id="${selectors.state.slice(1)}">No verified allowance</p></div>
          <details class="technical-details">
            <summary>Technical details</summary>
            <div class="network-inputs">
              <label>Token<input data-network-token="${safeNetwork}" id="${selectors.token.slice(1)}" spellcheck="false" autocomplete="off" placeholder="Unavailable" readonly></label>
              <label>Spender<input data-network-spender="${safeNetwork}" id="${selectors.spender.slice(1)}" spellcheck="false" autocomplete="off" placeholder="Unavailable" readonly></label>
            </div>
          </details>
          <button class="network-action" data-approve-network="${safeNetwork}" type="button" hidden disabled>Approve on ${safeLabel}</button>
        </article>`;
      })
      .join("");
  };

  const bindAllowanceActions = () => {
    document.querySelectorAll("[data-approve-network]").forEach((button) => {
      if (button.__clinkAllowanceActionBound) return;
      button.__clinkAllowanceActionBound = true;
      button.addEventListener("click", async () => {
        button.disabled = true;
        try {
          await approve(button.dataset.approveNetwork);
        } catch (error) {
          status.textContent = error.message;
          status.classList.add("error");
        }
      });
    });
  };

  const validateAccountState = (state) => {
    const validTopLevel = Boolean(
      isAccountStateObject(state) &&
      Array.isArray(state.wallet_identities) &&
      Array.isArray(state.spending_grants) &&
      Array.isArray(state.asset_allowances) &&
      Array.isArray(state.recent_audit_summary) &&
      Array.isArray(state.allowance_recovery) &&
      isAccountStateObject(state.approval_targets) &&
      isValidNetworkConfigs(state.network_configs) &&
      isAccountStateObject(state.readiness) &&
      typeof state.readiness.ready === "boolean"
    );
    const validWallets = validTopLevel && state.wallet_identities.every(
      (item) =>
        hasAccountStateStrings(
          item,
          ["wallet_identity_id", "wallet_address", "status"]
        ) &&
        (item.verified_at == null || typeof item.verified_at === "string")
    );
    const validGrants = validTopLevel && state.spending_grants.every(
      isValidAccountGrant
    );
    const currentMandate = validTopLevel
      ? state.current_spending_mandate
      : undefined;
    const validCurrentMandate = validTopLevel && Boolean(
      currentMandate === null ||
      (
        isValidAccountGrant(currentMandate) &&
        ["active", "paused"].includes(currentMandate.status) &&
        hasAccountStateUsdcProjection(
          currentMandate.limits_usdc,
          ["per_transaction", "rolling_hour", "daily", "total"]
        ) &&
        hasAccountStateUsdcProjection(
          currentMandate.used_usdc,
          ["rolling_hour", "daily", "total"]
        ) &&
        hasAccountStateUsdcProjection(
          currentMandate.reserved_usdc,
          ["rolling_hour", "daily", "total"]
        ) &&
        hasAccountStateUsdcProjection(
          currentMandate.remaining_usdc,
          ["rolling_hour", "daily", "total"]
        )
      )
    );
    const validAllowances = validTopLevel && state.asset_allowances.every(
      (item) =>
        hasAccountStateStrings(item, [
          "asset_allowance_id",
          "wallet_identity_id",
          "network",
          "token_address",
          "token_symbol",
          "spender_address",
          "status"
        ]) &&
        hasConfiguredNetwork(state, item.network) &&
        isCanonicalAtomicString(item.approved_amount_atomic) &&
        isCanonicalAtomicString(item.observed_allowance_atomic)
    );
    const validTargets = validTopLevel && Object.entries(
      state.approval_targets
    ).every(
      ([network, target]) =>
        hasConfiguredNetwork(state, network) &&
        (
          target == null ||
          hasAccountStateStrings(
            target,
            ["token_address", "spender_address"]
          )
        )
    );
    const validAudit = validTopLevel && state.recent_audit_summary.every(
      (item) => hasAccountStateStrings(item, ["event", "summary", "at"])
    );
    const validRecovery = validTopLevel && state.allowance_recovery.every((item) => {
      try {
        const record = validateAllowanceRecoveryRecord(item);
        const identity = state.wallet_identities.find(
          (candidate) => candidate.wallet_identity_id === record.wallet_identity_id
        );
        const target = state.approval_targets[record.network];
        return Boolean(
          identity && identity.status === "active" &&
          (typeof state.user_id !== "string" || record.user_id === state.user_id) &&
          target &&
          canonicalAddress(target.token_address) === record.token_address &&
          canonicalAddress(target.spender_address) === record.spender_address
        );
      } catch (_error) {
        return false;
      }
    });
    if (
      !validTopLevel ||
      !validWallets ||
      !validGrants ||
      !validCurrentMandate ||
      !validAllowances ||
      !validTargets ||
      !validAudit ||
      !validRecovery
    ) {
      throw new Error("Core returned invalid account state");
    }
    return state;
  };

  const OPC_PAIRING_FIELDS = [
    "pairing_id",
    "installation_id",
    "label",
    "public_jwk_thumbprint",
    "scope",
    "agent_id",
    "status",
    "expires_at",
    "consent_expires_at",
    "wallet_identity_id",
    "spending_grant_id"
  ];
  const OPC_PAIRING_STATUSES = new Set([
    "pending",
    "claimed",
    "active",
    "expired",
    "revoked",
    "consent_required"
  ]);
  const OPC_REVIEW_STATUSES = new Set([
    "pending",
    "claimed",
    "consent_required"
  ]);
  const OPC_CHALLENGE_FIELDS = [
    "session_id",
    "message_to_sign",
    "expires_at"
  ];
  const OPC_CLAIM_FIELDS = [
    "pairing_id",
    "installation_id",
    "public_account_session_id",
    "target_user_id",
    "status",
    "expires_at"
  ];

  const opcElement = (selector) => $(selector);

  const opcSetHidden = (selector, hidden) => {
    const element = opcElement(selector);
    if (element) element.hidden = Boolean(hidden);
  };

  const opcRows = (selector, rows) => {
    const container = opcElement(selector);
    if (!container) return;
    const children = rows.map(([label, value, meta = ""]) => {
      const row = document.createElement("div");
      row.className = "ledger-row";
      const labelElement = document.createElement("p");
      labelElement.className = "ledger-label";
      labelElement.textContent = label;
      const valueElement = document.createElement("p");
      valueElement.className = "ledger-value";
      valueElement.textContent = value;
      const metaElement = document.createElement("p");
      metaElement.className = "ledger-meta";
      metaElement.textContent = meta;
      row.append(labelElement, valueElement, metaElement);
      return row;
    });
    container.replaceChildren(...children);
  };

  const validateOpcPairing = (value) => {
    if (!exactObjectKeys(value, OPC_PAIRING_FIELDS)) {
      throw new Error("Core returned invalid device context");
    }
    if (
      !OPC_PAIRING_STATUSES.has(value.status) ||
      value.scope !== "payments" ||
      value.agent_id !== CONTROLLED_AGENT_ID ||
      !hasAccountStateStrings(value, [
        "pairing_id",
        "installation_id",
        "label",
        "public_jwk_thumbprint",
        "scope",
        "agent_id",
        "status",
        "expires_at"
      ]) ||
      ![
        "pairing_id",
        "installation_id",
        "label",
        "public_jwk_thumbprint",
        "scope",
        "agent_id",
        "status",
        "expires_at"
      ].every((field) => value[field].length > 0) ||
      (value.consent_expires_at !== null &&
        typeof value.consent_expires_at !== "string") ||
      (value.wallet_identity_id !== null &&
        typeof value.wallet_identity_id !== "string") ||
      (value.spending_grant_id !== null &&
        typeof value.spending_grant_id !== "string") ||
      Number.isNaN(Date.parse(value.expires_at)) ||
      (value.consent_expires_at !== null &&
        Number.isNaN(Date.parse(value.consent_expires_at)))
    ) {
      throw new Error("Core returned invalid device context");
    }
    return value;
  };

  const validateOpcEnvelope = (value) => {
    if (!exactObjectKeys(value, ["pairing"])) {
      throw new Error("Core returned invalid device context");
    }
    return {
      pairing: value.pairing === null ? null : validateOpcPairing(value.pairing)
    };
  };

  const validateOpcClaim = (value) => {
    if (
      !exactObjectKeys(value, OPC_CLAIM_FIELDS) ||
      !hasAccountStateStrings(value, OPC_CLAIM_FIELDS) ||
      !OPC_CLAIM_FIELDS.every((field) => value[field].length > 0) ||
      !["pending", "claimed"].includes(value.status) ||
      Number.isNaN(Date.parse(value.expires_at))
    ) {
      throw new Error("Core returned invalid device claim");
    }
    return value;
  };

  const validateOpcChallenge = (value) => {
    if (
      !exactObjectKeys(value, OPC_CHALLENGE_FIELDS, ["nonce"]) ||
      !hasAccountStateStrings(value, OPC_CHALLENGE_FIELDS) ||
      !OPC_CHALLENGE_FIELDS.every((field) => value[field].length > 0) ||
      (Object.prototype.hasOwnProperty.call(value, "nonce") &&
        typeof value.nonce !== "string") ||
      Number.isNaN(Date.parse(value.expires_at))
    ) {
      throw new Error("Core returned invalid device challenge");
    }
    return value;
  };

  const opcPairingExpired = (pairing) =>
    Boolean(
      pairing &&
      OPC_REVIEW_STATUSES.has(pairing.status) &&
      Date.parse(pairing.expires_at) <= Date.now()
    );

  const opcChallengeExpired = (challenge) =>
    Boolean(challenge && Date.parse(challenge.expires_at) <= Date.now());

  const opcConsentExpired = (pairing) =>
    Boolean(
      pairing &&
      pairing.consent_expires_at !== null &&
      Date.parse(pairing.consent_expires_at) <= Date.now()
    );

  const opcCurrentGrant = (state = accountState) => {
    const grant = state?.current_spending_mandate;
    return grant && grant.status === "active" &&
      grant.agent_id === CONTROLLED_AGENT_ID
      ? grant
      : null;
  };

  const opcCurrentWalletGrant = (selection, state = accountState) => {
    const identity = selectedWalletIdentity(selection, state);
    const grant = opcCurrentGrant(state);
    if (!grant || grant.wallet_identity_id !== identity.wallet_identity_id) {
      throw new Error(`No active ${CONTROLLED_AGENT_ID} spending grant matches the selected wallet`);
    }
    return {identity, grant};
  };

  const opcPairingMatchesCurrentAuthority = (pairing, identity, grant) =>
    Boolean(
      pairing &&
      pairing.status === "active" &&
      pairing.consent_expires_at !== null &&
      !opcConsentExpired(pairing) &&
      pairing.wallet_identity_id === identity.wallet_identity_id &&
      pairing.spending_grant_id === grant.spending_grant_id
    );

  const clearOpcReview = (message = "") => {
    opcReviewChallenge = null;
    opcSetHidden("#opc-review", true);
    opcSetHidden("#opc-sign-button", true);
    opcSetHidden("#opc-cancel-button", true);
    opcSetHidden("#opc-recheck", true);
    const sign = opcElement("#opc-sign-button");
    if (sign) sign.disabled = true;
    const exactMessage = opcElement("#opc-exact-message");
    if (exactMessage) exactMessage.textContent = "";
    if (message) {
      const messageElement = opcElement("#opc-device-message");
      if (messageElement) messageElement.textContent = message;
    }
  };

  const opcOperationUncertaintyMessage = (operation, prefix) =>
    operation?.approveStarted
      ? "Device approval may have been submitted. Refresh device status before any further action; do not sign again."
      : operation?.signatureStarted
        ? "A wallet signature may have been requested, but this page did not post device approval. Refresh device status before retrying."
        : `${prefix}. No wallet signature or device approval was sent.`;

  const invalidateOpcReview = (message = "") => {
    opcReviewGeneration += 1;
    if (opcReviewOperation) opcReviewOperation.cancelled = true;
    opcReviewOperation = null;
    clearOpcReview(message);
  };

  const opcHidePanel = (message = "") => {
    opcPairing = null;
    opcPairingGeneration += 1;
    invalidateOpcReview(message);
    opcSetHidden("#opc-device-section", true);
    opcSetHidden("#opc-review", true);
  };

  const opcUpdateReviewActions = () => {
    const section = opcElement("#opc-device-section");
    if (!section || section.hidden || !opcPairing) return;
    const reviewButton = opcElement("#opc-review-button");
    const signButton = opcElement("#opc-sign-button");
    if (!reviewButton) return;
    let authority = null;
    try {
      authority = opcCurrentWalletGrant(selectedWalletSnapshot());
    } catch (_error) {
      authority = null;
    }
    const reviewable = OPC_REVIEW_STATUSES.has(opcPairing.status) &&
      !opcPairingExpired(opcPairing) &&
      !opcUncertain;
    reviewButton.disabled = !reviewable || !authority ||
      Boolean(opcReviewOperation);
    if (signButton && !opcReviewChallenge) signButton.disabled = true;
    const deviceState = opcElement("#opc-device-state");
    const message = opcElement("#opc-device-message");
    if (opcPairing.status === "active") {
      if (authority && opcPairingMatchesCurrentAuthority(
        opcPairing, authority.identity, authority.grant
      )) {
        if (deviceState) deviceState.textContent = "Active";
        if (message) message.textContent = `Device access is active for this exact installation, wallet, and ${CONTROLLED_AGENT_ID} grant.`;
      } else {
        if (deviceState) deviceState.textContent = "Recheck required";
        if (message) message.textContent = `Core reports an active device, but the current wallet or ${CONTROLLED_AGENT_ID} grant does not match it. No device success is shown.`;
      }
    } else if (opcPairing.status === "revoked") {
      if (deviceState) deviceState.textContent = "Revoked";
      if (message) message.textContent = "This device installation was revoked. No signature or approval is available.";
    } else if (opcPairing.status === "expired") {
      if (deviceState) deviceState.textContent = "Expired";
      if (message) message.textContent = "This device request expired. Refresh the device status before reviewing again.";
      reviewButton.disabled = true;
    } else if (opcPairingExpired(opcPairing)) {
      if (deviceState) deviceState.textContent = "Expired";
      if (message) message.textContent = "This device request expired. Refresh the device status before reviewing again.";
      reviewButton.disabled = true;
    } else if (!authority) {
      if (deviceState) deviceState.textContent = "Review unavailable";
      if (message) message.textContent = `An active ${CONTROLLED_AGENT_ID} spending grant for the selected wallet is required. This device cannot create or enlarge a grant.`;
    } else {
      if (deviceState) deviceState.textContent = opcPairing.status;
      if (message) message.textContent = "Review the exact device request before any wallet signature.";
    }
  };

  const scheduleOpcExpiry = (pairing) => {
    if (opcExpiryTimer !== null) {
      window.clearTimeout?.(opcExpiryTimer);
      opcExpiryTimer = null;
    }
    if (!pairing || !OPC_REVIEW_STATUSES.has(pairing.status)) return;
    const delay = Date.parse(pairing.expires_at) - Date.now();
    if (delay <= 0) {
      opcUpdateReviewActions();
      return;
    }
    opcExpiryTimer = window.setTimeout(() => {
      if (opcPairing === pairing && opcPairingExpired(pairing)) {
        invalidateOpcReview("This device request expired. No wallet signature or approval was sent.");
        opcUpdateReviewActions();
      }
    }, Math.min(delay, 2_147_483_647));
  };

  const renderOpcPairing = (pairing) => {
    if (!opcElement("#opc-device-section")) return;
    opcPairing = pairing;
    opcPairingGeneration += 1;
    invalidateOpcReview();
    if (!pairing) {
      opcSetHidden("#opc-device-section", true);
      return;
    }
    opcSetHidden("#opc-device-section", false);
    opcRows("#opc-device-details", [
      ["Device label", pairing.label],
      ["Fingerprint", pairing.public_jwk_thumbprint],
      ["Capability", pairing.scope, "payments protocol capability bounded by the shown grant"],
      ["Agent", pairing.agent_id, "internal agent id"],
      ["Installation", pairing.installation_id],
      ["Pairing status", pairing.status]
    ]);
    const grant = opcCurrentGrant();
    opcRows("#opc-device-grant", grant
      ? [
          [`${CONTROLLED_AGENT_ID} grant`, grant.spending_grant_id],
          ["Total limit", grant.limits_usdc.total, "USDC"],
          ["Per purchase", grant.limits_usdc.per_transaction, "USDC"],
          ["Rolling hour", grant.limits_usdc.rolling_hour, "USDC"],
          ["Daily limit", grant.limits_usdc.daily, "USDC"],
          ["Remaining", grant.remaining_usdc.total, "USDC"],
          ["Products", grant.product_scopes.join(", ")]
        ]
      : [[`${CONTROLLED_AGENT_ID} grant`, "No active grant", "Device consent cannot create or enlarge a grant"]]);
    const consentExpiry = pairing.consent_expires_at || "Not active";
    const statusElement = opcElement("#opc-device-status");
    if (statusElement) statusElement.textContent = `Request expires ${pairing.expires_at}; consent expires ${consentExpiry}`;
    scheduleOpcExpiry(pairing);
    opcUpdateReviewActions();
  };

  const opcAssertOperation = (operation) => {
    if (
      !operation ||
      opcReviewOperation !== operation ||
      operation.cancelled ||
      operation.reviewGeneration !== opcReviewGeneration ||
      operation.accountGeneration !== accountStateLoadGeneration ||
      operation.contextGeneration !== opcPairingGeneration
    ) {
      throw new Error("Device review expired. Review the current wallet and request again.");
    }
    assertWalletSnapshot(operation.selection);
    const authority = opcCurrentWalletGrant(operation.selection);
    if (
      authority.identity.wallet_identity_id !== operation.walletIdentityId ||
      authority.grant.spending_grant_id !== operation.spendingGrantId ||
      opcPairing?.installation_id !== operation.installationId ||
      !OPC_REVIEW_STATUSES.has(opcPairing?.status) ||
      opcPairingExpired(opcPairing) ||
      opcChallengeExpired(opcReviewChallenge?.challenge)
    ) {
      throw new Error(`Device review no longer matches the current wallet or ${CONTROLLED_AGENT_ID} grant.`);
    }
    return authority;
  };

  const opcReview = async () => {
    if (opcReviewOperation) return;
    let selection;
    let authority;
    try {
      if (!opcPairing || !OPC_REVIEW_STATUSES.has(opcPairing.status) || opcPairingExpired(opcPairing)) {
        throw new Error("This device request is expired or no longer reviewable.");
      }
      selection = selectedWalletSnapshot();
      await providerAccountsContainSelection(selection);
      authority = opcCurrentWalletGrant(selection);
      const operation = {
        cancelled: false,
        reviewGeneration: opcReviewGeneration,
        accountGeneration: accountStateLoadGeneration,
        contextGeneration: opcPairingGeneration,
        selection,
        walletIdentityId: authority.identity.wallet_identity_id,
        spendingGrantId: authority.grant.spending_grant_id,
        installationId: opcPairing.installation_id,
        pairingId: opcPairing.pairing_id,
        signingInProgress: false,
        signatureStarted: false,
        approveStarted: false
      };
      opcReviewOperation = operation;
      opcAssertOperation(operation);
      const claimed = validateOpcClaim(await request(
        `/opc/pairings/${encodeURIComponent(operation.pairingId || opcPairing.pairing_id)}/claim`,
        {method: "POST", body: "{}"}
      ));
      opcAssertOperation(operation);
      await providerAccountsContainSelection(operation.selection);
      opcAssertOperation(operation);
      if (
        claimed.pairing_id !== operation.pairingId &&
        claimed.pairing_id !== opcPairing.pairing_id
      ) {
        throw new Error("Core returned a different device pairing");
      }
      if (claimed.installation_id !== opcPairing.installation_id) {
        throw new Error("Core returned a different device pairing");
      }
      if (!OPC_REVIEW_STATUSES.has(claimed.status) || claimed.status === "active") {
        throw new Error("Core device pairing is no longer awaiting consent");
      }
      opcPairing = {...opcPairing, status: claimed.status};
      const challenge = validateOpcChallenge(await request(
        `/opc/pairings/${encodeURIComponent(claimed.pairing_id)}/challenge`,
        {
          method: "POST",
          body: JSON.stringify({spending_grant_id: authority.grant.spending_grant_id})
        }
      ));
      opcAssertOperation(operation);
      await providerAccountsContainSelection(operation.selection);
      opcAssertOperation(operation);
      if (Date.parse(challenge.expires_at) <= Date.now()) {
        throw new Error("The device signature challenge expired. No signature was sent.");
      }
      opcReviewChallenge = {challenge, operation};
      const exactMessage = opcElement("#opc-exact-message");
      if (exactMessage) exactMessage.textContent = challenge.message_to_sign;
      opcSetHidden("#opc-review", false);
      opcSetHidden("#opc-sign-button", false);
      opcSetHidden("#opc-cancel-button", false);
      const sign = opcElement("#opc-sign-button");
      if (sign) sign.disabled = false;
      const state = opcElement("#opc-device-state");
      if (state) state.textContent = "Confirm signature";
      const message = opcElement("#opc-device-message");
      if (message) message.textContent = "Core supplied the exact message. Confirm explicitly below to request one wallet signature.";
      const delay = Date.parse(challenge.expires_at) - Date.now();
      if (delay > 0) {
        if (opcExpiryTimer !== null) window.clearTimeout?.(opcExpiryTimer);
        opcExpiryTimer = window.setTimeout(() => {
          if (opcReviewChallenge?.operation === operation && opcChallengeExpired(challenge)) {
            const message = opcOperationUncertaintyMessage(
              operation,
              "This device signature challenge expired"
            );
            if (operation.signatureStarted || operation.approveStarted) {
              opcMarkUncertain(message);
            } else {
              invalidateOpcReview(message);
              status.textContent = message;
              status.classList.add("error");
              opcUpdateReviewActions();
              const state = opcElement("#opc-device-state");
              if (state) state.textContent = "Expired";
              const deviceMessage = opcElement("#opc-device-message");
              if (deviceMessage) deviceMessage.textContent = message;
            }
          }
        }, Math.min(delay, 2_147_483_647));
      }
    } catch (error) {
      if (opcReviewOperation) {
        opcReviewOperation.cancelled = true;
        opcReviewOperation = null;
      }
      clearOpcReview(error.message);
      status.textContent = error.message;
      status.classList.add("error");
      opcUpdateReviewActions();
      const message = opcElement("#opc-device-message");
      if (message) message.textContent = error.message;
    }
  };

  const opcCancelReview = () => {
    const operation = opcReviewOperation || opcReviewChallenge?.operation;
    if (operation?.signatureStarted || operation?.approveStarted) {
      opcMarkUncertain(
        opcOperationUncertaintyMessage(operation, "Device review cancellation requested")
      );
      return;
    }
    invalidateOpcReview("Device review cancelled. No wallet signature or device approval was sent.");
    opcUncertain = false;
    status.textContent = "Device review cancelled. No wallet signature or device approval was sent.";
    status.classList.toggle("error", false);
    opcUpdateReviewActions();
  };

  const opcMarkUncertain = (message) => {
    invalidateOpcReview(message);
    opcUncertain = true;
    opcSetHidden("#opc-device-section", false);
    opcSetHidden("#opc-recheck", false);
    status.textContent = message;
    status.classList.add("error");
    opcUpdateReviewActions();
    const state = opcElement("#opc-device-state");
    if (state) state.textContent = "Recheck required";
    const deviceMessage = opcElement("#opc-device-message");
    if (deviceMessage) deviceMessage.textContent = message;
  };

  const refreshOpcPairing = async () => {
    if (!opcElement("#opc-device-section") || !accountState) return false;
    const accountGeneration = accountStateLoadGeneration;
    const loadGeneration = ++opcPairingLoadGeneration;
    try {
      const envelope = validateOpcEnvelope(await request("/opc/pairing"));
      if (
        accountGeneration !== accountStateLoadGeneration ||
        loadGeneration !== opcPairingLoadGeneration
      ) return false;
      opcUncertain = false;
      renderOpcPairing(envelope.pairing);
      if (
        envelope.pairing?.status === "active" &&
        envelope.pairing.wallet_identity_id &&
        envelope.pairing.spending_grant_id
      ) {
        try {
          const selection = selectedWalletSnapshot();
          const authority = opcCurrentWalletGrant(selection);
          if (!opcPairingMatchesCurrentAuthority(envelope.pairing, authority.identity, authority.grant)) {
            const message = opcElement("#opc-device-message");
            if (message) message.textContent = `Core returned an active device that does not exactly match the current wallet or ${CONTROLLED_AGENT_ID} grant. No success is shown.`;
          }
        } catch (_error) {
          // The panel remains a readback only until the exact current wallet is selected.
        }
      }
      return true;
    } catch (error) {
      if (
        accountGeneration === accountStateLoadGeneration &&
        loadGeneration === opcPairingLoadGeneration
      ) {
        const message = error?.accountSessionExpired || allowanceSessionExpired
          ? ACCOUNT_SESSION_EXPIRED_MESSAGE
          : "Device status is unavailable or wallet authentication expired. Device controls are locked until refresh.";
        opcUncertain = false;
        opcHidePanel(message);
        status.textContent = message;
        status.classList.add("error");
      }
      return false;
    }
  };

  const opcSign = async () => {
    const review = opcReviewChallenge;
    const operation = review?.operation;
    if (
      !review ||
      !operation ||
      operation.signingInProgress ||
      operation.signatureStarted ||
      operation.approveStarted
    ) return;
    operation.signingInProgress = true;
    try {
      const authority = opcAssertOperation(operation);
      await providerAccountsContainSelection(operation.selection);
      opcAssertOperation(operation);
      operation.signatureStarted = true;
      const signature = await operation.selection.provider.request({
        method: "personal_sign",
        params: [review.challenge.message_to_sign, operation.selection.address]
      });
      opcAssertOperation(operation);
      await providerAccountsContainSelection(operation.selection);
      opcAssertOperation(operation);
      if (typeof signature !== "string" || !signature) {
        throw new Error("Wallet returned no device signature");
      }
      operation.approveStarted = true;
      await request("/opc/installations/approve", {
        method: "POST",
        body: JSON.stringify({
          challenge_session_id: review.challenge.session_id,
          signed_message: review.challenge.message_to_sign,
          signature
        })
      });
      opcAssertOperation(operation);
      await providerAccountsContainSelection(operation.selection);
      opcAssertOperation(operation);
      const envelope = validateOpcEnvelope(await request("/opc/pairing"));
      opcAssertOperation(operation);
      await providerAccountsContainSelection(operation.selection);
      opcAssertOperation(operation);
      const pairing = envelope.pairing;
      if (
        !pairing ||
        pairing.status !== "active" ||
        !pairing.wallet_identity_id ||
        !pairing.spending_grant_id ||
        pairing.installation_id !== operation.installationId ||
        pairing.wallet_identity_id !== authority.identity.wallet_identity_id ||
        pairing.spending_grant_id !== authority.grant.spending_grant_id ||
        pairing.consent_expires_at === null ||
        opcConsentExpired(pairing)
      ) {
        throw new Error(`Core did not confirm active device access for the exact wallet and ${CONTROLLED_AGENT_ID} grant`);
      }
      opcUncertain = false;
      opcReviewOperation = null;
      opcReviewChallenge = null;
      renderOpcPairing(pairing);
      status.textContent = `Device access is active for the exact selected wallet and ${CONTROLLED_AGENT_ID} grant. No spending limit or allowance was changed.`;
      status.classList.toggle("error", false);
    } catch (error) {
      if (operation.approveStarted) {
        opcMarkUncertain("Device approval response is uncertain. Refresh device status before any further action; do not sign again.");
      } else if (operation.signatureStarted) {
        opcMarkUncertain(
          opcOperationUncertaintyMessage(operation, "Wallet signature request failed")
        );
      } else {
        invalidateOpcReview(error.message);
        status.textContent = error.message;
        status.classList.add("error");
        opcUpdateReviewActions();
      }
    } finally {
      operation.signingInProgress = false;
    }
  };

  const formatUsdcAtomic = (value) => {
    const amount = BigInt(String(value));
    if (amount < 0n) throw new Error("Allowance amount is invalid");
    const whole = amount / 1_000_000n;
    const fraction = String(amount % 1_000_000n)
      .padStart(6, "0")
      .replace(/0+$/, "");
    return fraction ? `${whole}.${fraction}` : String(whole);
  };

  const allowanceCoverage = (state, network) => {
    const mandate = state?.current_spending_mandate;
    if (!mandate || mandate.status !== "active") return null;
    const target = state.approval_targets[network];
    if (!target) return null;
    const requiredUsdc = mandate.limits_usdc.per_transaction;
    const required = BigInt(usdcAtomic(requiredUsdc));
    const allowance = state.asset_allowances.find(
      (item) =>
        item.wallet_identity_id === mandate.wallet_identity_id &&
        item.network === network &&
        item.status === "active" &&
        item.token_address.toLowerCase() === target.token_address.toLowerCase() &&
        item.spender_address.toLowerCase() === target.spender_address.toLowerCase()
    );
    let observed = 0n;
    if (allowance) {
      try {
        observed = BigInt(String(allowance.observed_allowance_atomic));
      } catch (_error) {
        observed = 0n;
      }
    }
    return {
      allowance,
      covered: observed >= required,
      observed,
      required,
      requiredUsdc
    };
  };

  const render = (state) => {
    accountState = null;
    opcHidePanel();
    $("#refresh-allowances").disabled = true;
    try {
      const validatedState = validateAccountState(state);
      accountState = validatedState;
      mergeAllowanceRecoveryProjection(validatedState);
      renderNetworkLedger(validatedState);
      const wallet = validatedState.wallet_identities[0];
      $("#wallet-state").textContent = wallet ? "Verified" : "Not connected";
      $("#wallet-state").classList.toggle("ready", Boolean(wallet));
      $("#wallet-details").innerHTML = wallet
        ? ledgerRow("Bound wallet", wallet.wallet_address, wallet.status) + ledgerRow("Proof", "EIP-191 ownership", wallet.verified_at || "") + `<div class="row-controls"><button class="row-action" data-wallet-disconnect="${escapeHtml(wallet.wallet_identity_id)}" type="button">Unbind wallet from Clink</button></div>`
        : ledgerRow("Bound wallet", "No wallet verified", "Action required");

      const currentMandate = validatedState.current_spending_mandate;
      const active = currentMandate?.status === "active";
      $("#permission-state").textContent = currentMandate
        ? currentMandate.status
        : "No limit";
      $("#permission-state").classList.toggle("ready", Boolean(active));
      $("#grant-details").innerHTML = currentMandate
        ? grantLedger(currentMandate)
        : ledgerRow(PUBLIC_AGENT_LABEL, "No active mandate", "Action required");

      const permissionEditor = $("#permission-editor");
      permissionEditor.open = !currentMandate;
      $("#permission-editor-label").textContent = currentMandate
        ? "Change total limit"
        : "Set total limit";
      $("#new-limit-settings").hidden = Boolean(currentMandate);
      $("#permission-submit").textContent = currentMandate
        ? "Save total limit"
        : "Review and sign total limit";
      $("#limit-help").textContent = currentMandate
        ? "This is the one limit for all Clink purchases. Lowering it is immediate; raising it asks for one wallet signature."
        : "This total is shared by all Clink purchases. One wallet signature sets it. Polymarket CLOB auth remains separate.";
      if (currentMandate) {
        const trustScopes = currentMandate.merchant_trust_scopes?.length
          ? currentMandate.merchant_trust_scopes
          : ["clink_verified", "registry_verified"];
        $("#total-limit").value = currentMandate.limits_usdc.total;
        $("#trust-clink").checked = trustScopes.includes("clink_verified");
        $("#trust-registry").checked = trustScopes.includes("registry_verified");
        $("#notification-mode").value = currentMandate.notification_mode || "silent_under_limits";
      }

      let hasCoveredNetwork = false;
      let hasUnavailableNetwork = false;
      for (const [network, networkConfig] of Object.entries(
        validatedState.network_configs
      )) {
        const networkName = networkLabel(network, networkConfig);
        const selectors = networkElementSelectors(network, networkConfig);
        const target = validatedState.approval_targets[network];
        const tokenInput = $(selectors.token);
        const spenderInput = $(selectors.spender);
        tokenInput.value = target ? target.token_address : "";
        spenderInput.value = target ? target.spender_address : "";
        const button = document.querySelector(`[data-approve-network="${network}"]`);
        button.disabled = true;
        const mismatch = allowanceMismatchForNetwork(validatedState, network);
        const coverage = allowanceCoverage(validatedState, network);
        if (mismatch && coverage && !coverage.covered) {
          $(selectors.state).textContent = allowanceMismatchSummary(mismatch);
          button.textContent = `Approve ${coverage.requiredUsdc} USDC on ${networkName}`;
          button.hidden = false;
          hasUnavailableNetwork = true;
        } else if (!coverage || !target) {
          $(selectors.state).textContent = currentMandate?.status === "paused"
            ? "Resume access to use this limit"
            : "Available after a total limit is set";
          button.hidden = true;
        } else if (coverage.covered) {
          $(selectors.state).textContent = `${networkName} ready for up to ${formatUsdcAtomic(coverage.observed)} USDC${mismatch ? `; ${allowanceMismatchSummary(mismatch)}` : ""}`;
          button.textContent = `${networkName} ready`;
          button.hidden = true;
          hasCoveredNetwork = true;
        } else {
          $(selectors.state).textContent = `${formatUsdcAtomic(coverage.observed)} USDC approved; ${coverage.requiredUsdc} USDC covers the configured single purchase`;
          button.textContent = `Approve ${coverage.requiredUsdc} USDC on ${networkName}`;
          button.hidden = false;
          hasUnavailableNetwork = true;
        }
      }
      const needsAllowanceSetup = Boolean(
        currentMandate?.status === "active" &&
        hasUnavailableNetwork &&
        !hasCoveredNetwork
      );
      const mismatchNotices = Object.keys(validatedState.network_configs)
        .map((network) => allowanceMismatchForNetwork(validatedState, network))
        .filter(Boolean)
        .map(allowanceMismatchSummary);
      $("#allowance-setup").open = needsAllowanceSetup;
      $("#allowance-setup-label").textContent = !currentMandate
        ? "Set a total limit first"
        : currentMandate.status === "paused"
          ? "Wallet setup paused"
          : mismatchNotices.length
            ? "Allowance amount mismatch needs review"
          : needsAllowanceSetup
            ? "One-time wallet setup needed"
            : hasUnavailableNetwork
              ? "Wallet setup saved"
              : "Wallet setup complete";
      const missingTargets = Object.keys(validatedState.network_configs).filter(
        (network) => !validatedState.approval_targets[network]
      );
      restorePendingAllowance(validatedState);
      restoreAllowanceAttemptContexts(validatedState);
      restoreAllowancePostSendUncertain(validatedState);
      restoreWalletDisconnectPlan();
      refreshPermissionReadiness(validatedState);
      void refreshAllowanceReadiness(validatedState);
      $("#audit-list").innerHTML = validatedState.recent_audit_summary.map((item) => ledgerRow(item.event, item.summary, item.at)).join("");
      status.textContent = allowanceSessionExpired
        ? ACCOUNT_SESSION_EXPIRED_MESSAGE
        : allowancePostSendUncertainIdentityId
        ? ALLOWANCE_POST_SEND_UNCERTAIN_MESSAGE
        : allowanceRecoveryBlocked
          ? allowanceRecoveryMessage
        : missingTargets.length
          ? `Core approval configuration unavailable for ${missingTargets.join(" and ")}.`
          : mismatchNotices.length
            ? mismatchNotices.join(" ")
          : needsAllowanceSetup
            ? isEmbeddedView()
              ? "Account state loaded. Review the spending authorization and chain allowance; this page does not enable purchasing or funding."
              : "Complete the one-time wallet setup shown below. Your total Clink limit will be reused afterward."
          : validatedState.readiness.ready
            ? isEmbeddedView()
              ? "Account state loaded. Review the spending authorization and chain allowance; this page does not enable purchasing or funding."
              : "Your Clink spending account is ready."
            : "Review the controls that still need your action.";
      status.classList.toggle(
        "error",
        Boolean(allowancePostSendUncertainIdentityId) ||
          allowanceRecoveryBlocked ||
          Boolean(mismatchNotices.length) ||
          Boolean(missingTargets.length)
      );
      restoreEmbeddedAllowanceRevokeRecovery(validatedState);
      renderEmbeddedState(validatedState);
      bindAllowanceActions();
      $("#refresh-allowances").disabled = false;
    } catch (error) {
      renderLocked();
      throw error;
    }
  };

  const renderLocked = () => {
    accountState = null;
    opcUncertain = false;
    opcHidePanel("Wallet proof is required before device access can be shown.");
    embeddedAllowanceRevokeRecovery = null;
    if (isEmbeddedView()) {
      clearEmbeddedReview("Wallet proof is required before reviewing authorization terms.");
      $("#embedded-state").textContent = "Locked";
      const currentActions = $("#embedded-current-actions");
      if (currentActions) currentActions.hidden = true;
      const revokeAllowanceCheckbox = $("#embedded-revoke-allowance");
      if (revokeAllowanceCheckbox) {
        revokeAllowanceCheckbox.checked = false;
        revokeAllowanceCheckbox.disabled = true;
      }
    }
    $("#refresh-allowances").disabled = true;
    updatePendingAllowanceRecovery();
    restoreWalletDisconnectPlan();
    $("#wallet-state").textContent = "Locked";
    $("#wallet-state").classList.toggle("ready", false);
    $("#wallet-details").innerHTML = ledgerRow(
      "Browser session",
      "Locked",
      "Connect an active wallet and sign to unlock"
    );
    $("#permission-state").textContent = "Locked";
    $("#permission-state").classList.toggle("ready", false);
    $("#grant-details").innerHTML = ledgerRow(
      "Spending limit",
      "Hidden while locked",
      "Wallet authentication required"
    );
    document.querySelectorAll("[data-network-state]").forEach((element) => {
      element.textContent = "Locked";
    });
    document.querySelectorAll(
      "[data-network-token], [data-network-spender]"
    ).forEach((element) => {
      element.value = "";
    });
    document.querySelectorAll("[data-approve-network]").forEach((button) => {
      button.disabled = true;
    });
    $("#permission-form").querySelector("button").disabled = true;
    $("#audit-list").innerHTML = ledgerRow(
      "Audit summary",
      "Hidden while locked",
      "Wallet authentication required"
    );
    status.textContent = allowanceSessionExpired
      ? ACCOUNT_SESSION_EXPIRED_MESSAGE
      : allowancePostSendUncertainIdentityId
        ? ALLOWANCE_POST_SEND_UNCERTAIN_MESSAGE
        : "Wallet proof is required before account details or permission controls are available.";
    status.classList.toggle(
      "error",
      Boolean(allowancePostSendUncertainIdentityId || allowanceSessionExpired)
    );
  };

  const loadState = async () => {
    const generation = ++accountStateLoadGeneration;
    const sessionGeneration = accountSessionGeneration;
    opcUncertain = false;
    if (opcElement("#opc-device-section")) {
      opcHidePanel("Loading account and device status...");
    }
    const response = await fetch(window.location.pathname, {headers: {"Accept": "application/json"}});
    const body = await parseResponse(response);
    if (generation !== accountStateLoadGeneration) return false;
    if (sessionGeneration !== accountSessionGeneration || allowanceSessionExpired) {
      if (allowanceSessionExpired) renderLocked();
      return false;
    }
    if (response.status === 401 && body.detail === "wallet authentication required") {
      renderLocked();
      return false;
    }
    if (
      [401, 410].includes(response.status) &&
      body.detail !== "wallet authentication required"
    ) {
      markAccountSessionExpired();
      renderLocked();
      return false;
    }
    if (!response.ok) throw new Error(body.detail || "Account session unavailable");
    render(body);
    await refreshOpcPairing();
    processConfirmedAllowanceMismatch(accountState);
    await opcSetupAfterState?.();
    return true;
  };

  const usdcAtomic = (value) => {
    const normalized = String(value).trim();
    if (!/^\d+(\.\d{1,6})?$/.test(normalized)) throw new Error("Enter a valid USDC amount with at most six decimals");
    const [whole, fraction = ""] = normalized.split(".");
    const amount = (BigInt(whole) * 1_000_000n) + BigInt(fraction.padEnd(6, "0"));
    if (amount <= 0n) throw new Error("USDC approval must be positive");
    return amount;
  };

  const canonicalAddress = (value) => {
    const normalized = String(value || "").toLowerCase();
    if (!/^0x[0-9a-f]{40}$/.test(normalized)) throw new Error("Allowance address is invalid");
    return normalized;
  };

  const canonicalTransactionHash = (value) => {
    const normalized = String(value || "").toLowerCase();
    if (!/^0x[0-9a-f]{64}$/.test(normalized)) {
      throw new Error("Wallet returned an invalid transaction hash");
    }
    return normalized;
  };

  const validateAllowanceRecoveryRecord = (value) => {
    const mismatch = isAccountStateObject(value) &&
      value.status === "confirmed_mismatch";
    if (!exactObjectKeys(
      value,
      mismatch ? ALLOWANCE_RECOVERY_MISMATCH_FIELDS : ALLOWANCE_RECOVERY_FIELDS
    )) {
      throw new Error("Core returned an invalid allowance recovery record");
    }
    const idPattern = /^[A-Za-z0-9][A-Za-z0-9:_-]{0,127}$/;
    if (
      !idPattern.test(value.attempt_id) ||
      !idPattern.test(value.user_id) ||
      !idPattern.test(value.wallet_identity_id) ||
      !NETWORK_KEY_PATTERN.test(value.network) ||
      !ALLOWANCE_RECOVERY_STATUSES.has(value.status) ||
      (value.reason_code !== null &&
        !ALLOWANCE_RECOVERY_REASON_CODES.has(value.reason_code)) ||
      typeof value.created_at !== "string" ||
      !Number.isFinite(Date.parse(value.created_at)) ||
      typeof value.updated_at !== "string" ||
      !Number.isFinite(Date.parse(value.updated_at)) ||
      (value.next_check_at !== null &&
        (typeof value.next_check_at !== "string" ||
          !Number.isFinite(Date.parse(value.next_check_at))))
    ) {
      throw new Error("Core returned an invalid allowance recovery record");
    }
    if (mismatch && !isCanonicalUint256String(value.amount_atomic, {positive: true})) {
      throw new Error("Core returned an invalid allowance recovery amount");
    }
    if (
      !mismatch &&
      value.amount_atomic !== null &&
      !/^[1-9][0-9]*$/.test(value.amount_atomic)
    ) {
      throw new Error("Core returned an invalid allowance recovery amount");
    }
    let tokenAddress;
    let spenderAddress;
    try {
      tokenAddress = canonicalAddress(value.token_address);
      spenderAddress = canonicalAddress(value.spender_address);
    } catch (_error) {
      throw new Error("Core returned invalid allowance recovery addresses");
    }
    if (
      tokenAddress !== value.token_address ||
      spenderAddress !== value.spender_address
    ) {
      throw new Error("Core returned non-canonical allowance recovery addresses");
    }
    const transactionHash = value.allowance_tx_hash === null
      ? null
      : canonicalTransactionHash(value.allowance_tx_hash);
    if (
      transactionHash !== value.allowance_tx_hash &&
      !(transactionHash === null && value.allowance_tx_hash === null)
    ) {
      throw new Error("Core returned a non-canonical allowance recovery hash");
    }
    if (
      (["awaiting_wallet", "rejected"].includes(value.status) &&
        transactionHash !== null) ||
      (["pending", "verified", "attention_required", "confirmed_mismatch"].includes(value.status) &&
        transactionHash === null)
    ) {
      throw new Error("Core returned an invalid allowance recovery status");
    }
    if (mismatch) {
      if (
        value.reason_code !== "amount_mismatch" ||
        value.next_check_at !== null ||
        !isCanonicalUint256String(value.actual_approved_amount_atomic, {positive: true}) ||
        !isCanonicalUint256String(value.observed_allowance_atomic) ||
        value.actual_approved_amount_atomic === value.amount_atomic ||
        typeof value.confirmed_block !== "number" ||
        !Number.isSafeInteger(value.confirmed_block) ||
        value.confirmed_block < 0 ||
        typeof value.verified_at !== "string" ||
        !Number.isFinite(Date.parse(value.verified_at))
      ) {
        throw new Error("Core returned invalid allowance mismatch evidence");
      }
      const confirmedBlockHash = canonicalTransactionHash(value.confirmed_block_hash);
      if (confirmedBlockHash !== value.confirmed_block_hash) {
        throw new Error("Core returned a non-canonical allowance mismatch block hash");
      }
    }
    return Object.freeze({
      ...value,
      token_address: tokenAddress,
      spender_address: spenderAddress,
      allowance_tx_hash: transactionHash,
      ...(mismatch ? {
        confirmed_block_hash: canonicalTransactionHash(value.confirmed_block_hash)
      } : {})
    });
  };

  const allowanceMismatchForNetwork = (state, network) => {
    const target = state?.approval_targets?.[network];
    if (!target) return null;
    let identity = null;
    try {
      identity = selectedWalletIdentity(selectedWalletSnapshot(), state);
    } catch (_error) {
      identity = state?.wallet_identities?.find((item) => item.status === "active") || null;
    }
    if (!identity) return null;
    const coverage = allowanceCoverage(state, network);
    const token = canonicalAddress(target.token_address);
    const spender = canonicalAddress(target.spender_address);
    const mismatch = allowanceRecoveryRecords
      .filter((record) =>
        record.status === "confirmed_mismatch" &&
        record.wallet_identity_id === identity.wallet_identity_id &&
        record.network === network &&
        record.token_address === token &&
        record.spender_address === spender
      )
      .reduce((latest, record) => {
        if (!latest) return record;
        return Date.parse(record.verified_at) > Date.parse(latest.verified_at)
          ? record
          : latest;
      }, null);
    if (!mismatch || !coverage?.covered || !coverage.allowance) return mismatch;
    const checkedAt = typeof coverage.allowance.last_chain_check_at === "string"
      ? Date.parse(coverage.allowance.last_chain_check_at)
      : NaN;
    const verifiedAt = typeof mismatch.verified_at === "string"
      ? Date.parse(mismatch.verified_at)
      : NaN;
    // A coverage snapshot can replace the terminal warning only when it is
    // explicitly timestamped after the independently verified mismatch.
    return Number.isFinite(checkedAt) && Number.isFinite(verifiedAt) && checkedAt > verifiedAt
      ? null
      : mismatch;
  };

  const allowanceMismatchSummary = (record) => {
    const networkName = KNOWN_NETWORK_LABELS[record.network] || record.network;
    return `${networkName}: transaction approved ${formatUsdcAtomic(record.actual_approved_amount_atomic)} USDC; requested ${formatUsdcAtomic(record.amount_atomic)} USDC; observed allowance at verification ${formatUsdcAtomic(record.observed_allowance_atomic)} USDC. No transaction was resent. Budget unchanged. Verified at ${record.verified_at}.`;
  };

  const validateAllowanceAttemptContext = (value) => {
    if (!exactObjectKeys(value, ALLOWANCE_ATTEMPT_FIELDS)) {
      throw new Error("Allowance attempt context is invalid");
    }
    if (
      typeof value.attempt_id !== "string" &&
      value.attempt_id !== null
    ) {
      throw new Error("Allowance attempt id is invalid");
    }
    if (
      value.attempt_id !== null &&
      !/^[A-Za-z0-9][A-Za-z0-9:_-]{0,127}$/.test(value.attempt_id)
    ) {
      throw new Error("Allowance attempt id is invalid");
    }
    if (
      typeof value.wallet_identity_id !== "string" ||
      !/^[A-Za-z0-9][A-Za-z0-9:_-]{0,127}$/.test(value.wallet_identity_id) ||
      !NETWORK_KEY_PATTERN.test(value.network) ||
      typeof value.request_key !== "string" ||
      !/^[0-9a-f]{64}$/.test(value.request_key) ||
      typeof value.amount_atomic !== "string" ||
      !/^[1-9][0-9]*$/.test(value.amount_atomic) ||
      !["prepare_pending", "awaiting_wallet", "pending"].includes(value.status)
    ) {
      throw new Error("Allowance attempt context is invalid");
    }
    const tokenAddress = canonicalAddress(value.token_address);
    const spenderAddress = canonicalAddress(value.spender_address);
    if (tokenAddress !== value.token_address || spenderAddress !== value.spender_address) {
      throw new Error("Allowance attempt context is not canonical");
    }
    return Object.freeze({
      ...value,
      token_address: tokenAddress,
      spender_address: spenderAddress
    });
  };

  const pendingAllowancePathScope = () =>
    encodeURIComponent(window.location.pathname);

  const walletDisconnectStoragePrefix = () =>
    `${WALLET_DISCONNECT_STORAGE_PREFIX}${pendingAllowancePathScope()}.`;

  const walletDisconnectStorageKey = (walletIdentityId) =>
    `${walletDisconnectStoragePrefix()}${walletIdentityId}`;

  const validateWalletDisconnectAllowance = (value) => {
    if (!value || typeof value !== "object" || Array.isArray(value)) {
      throw new Error("Wallet disconnect allowance is invalid");
    }
    const keys = Object.keys(value).sort();
    if (
      keys.length !== WALLET_DISCONNECT_ALLOWANCE_FIELDS.length ||
      keys.some(
        (key, index) =>
          key !== WALLET_DISCONNECT_ALLOWANCE_FIELDS[index]
      )
    ) {
      throw new Error("Wallet disconnect allowance has unexpected fields");
    }
    const assetAllowanceId = canonicalAccountObjectId(
      value.asset_allowance_id,
      "Wallet disconnect allowance"
    );
    if (
      !NETWORK_KEY_PATTERN.test(value.network) ||
      (accountState && !hasConfiguredNetwork(accountState, value.network))
    ) {
      throw new Error("Wallet disconnect network is invalid");
    }
    const tokenAddress = canonicalAddress(value.token_address);
    const spenderAddress = canonicalAddress(value.spender_address);
    let observed;
    try {
      observed = BigInt(value.observed_allowance_atomic);
    } catch (_error) {
      throw new Error("Wallet disconnect allowance amount is invalid");
    }
    if (
      observed < 0n ||
      String(observed) !== value.observed_allowance_atomic ||
      tokenAddress !== value.token_address ||
      spenderAddress !== value.spender_address
    ) {
      throw new Error("Wallet disconnect allowance is not canonical");
    }
    return Object.freeze({
      asset_allowance_id: assetAllowanceId,
      network: value.network,
      token_address: tokenAddress,
      spender_address: spenderAddress,
      observed_allowance_atomic: String(observed)
    });
  };

  const validateWalletDisconnectPlan = (value) => {
    if (!value || typeof value !== "object" || Array.isArray(value)) {
      throw new Error("Wallet disconnect plan is invalid");
    }
    const keys = Object.keys(value).sort();
    const hasCurrentFields =
      keys.length === WALLET_DISCONNECT_FIELDS.length &&
      keys.every(
        (key, index) => key === WALLET_DISCONNECT_FIELDS[index]
      );
    const hasLegacyFields =
      keys.length === LEGACY_WALLET_DISCONNECT_FIELDS.length &&
      keys.every(
        (key, index) => key === LEGACY_WALLET_DISCONNECT_FIELDS[index]
      );
    if (!hasCurrentFields && !hasLegacyFields) {
      throw new Error("Wallet disconnect plan has unexpected fields");
    }
    if (
      value.operation !== "disconnect" ||
      typeof value.core_disconnected !== "boolean" ||
      (
        hasCurrentFields &&
        typeof value.allowances_cleared !== "boolean"
      )
    ) {
      throw new Error("Wallet disconnect state is invalid");
    }
    const walletIdentityId = canonicalAccountObjectId(
      value.wallet_identity_id,
      "Wallet disconnect identity"
    );
    const walletAddress = canonicalAddress(value.wallet_address);
    const providerUuid = canonicalAccountObjectId(
      value.provider_uuid,
      "Wallet disconnect provider"
    );
    if (!Array.isArray(value.allowances)) {
      throw new Error("Wallet disconnect allowances are invalid");
    }
    const allowances = value.allowances
      .map(validateWalletDisconnectAllowance)
      .sort((left, right) => left.network.localeCompare(right.network));
    if (
      new Set(allowances.map((item) => item.network)).size !==
      allowances.length
    ) {
      throw new Error("Wallet disconnect networks must be unique");
    }
    return Object.freeze({
      operation: "disconnect",
      wallet_identity_id: walletIdentityId,
      wallet_address: walletAddress,
      provider_uuid: providerUuid,
      core_disconnected: value.core_disconnected,
      allowances_cleared: hasCurrentFields
        ? value.allowances_cleared
        : false,
      allowances: Object.freeze(allowances)
    });
  };

  const walletDisconnectPlansMatch = (left, right) =>
    JSON.stringify(left) === JSON.stringify(right);

  const readWalletDisconnectPlan = (walletIdentityId) => {
    const key = walletDisconnectStorageKey(walletIdentityId);
    const raw = window.sessionStorage.getItem(key);
    if (raw === null) return null;
    const plan = validateWalletDisconnectPlan(JSON.parse(raw));
    if (plan.wallet_identity_id !== walletIdentityId) {
      throw new Error("Wallet disconnect storage key does not match its plan");
    }
    return plan;
  };

  const persistWalletDisconnectPlan = (value) => {
    const plan = validateWalletDisconnectPlan(value);
    const key = walletDisconnectStorageKey(plan.wallet_identity_id);
    try {
      window.sessionStorage.setItem(key, JSON.stringify(plan));
      const stored = readWalletDisconnectPlan(plan.wallet_identity_id);
      if (!walletDisconnectPlansMatch(stored, plan)) {
        throw new Error("Wallet disconnect plan was not retained");
      }
    } catch (_error) {
      throw new Error(
        "Wallet disconnect recovery storage is unavailable."
      );
    }
    pendingWalletDisconnect = plan;
    updateWalletDisconnectRecovery();
    return plan;
  };

  const clearWalletDisconnectPlan = (plan) => {
    const key = walletDisconnectStorageKey(plan.wallet_identity_id);
    try {
      const stored = readWalletDisconnectPlan(plan.wallet_identity_id);
      if (stored && !walletDisconnectPlansMatch(stored, plan)) {
        throw new Error("Wallet disconnect plan changed");
      }
      window.sessionStorage.removeItem(key);
      if (window.sessionStorage.getItem(key) !== null) {
        throw new Error("Wallet disconnect plan was not cleared");
      }
    } catch (_error) {
      throw new Error(
        "Core permissions and known chain allowances are revoked, but browser disconnect recovery storage could not be cleared."
      );
    }
    pendingWalletDisconnect = null;
    walletDisconnectApprovalTargets = null;
    walletDisconnectNetworkConfigs = null;
    walletDisconnectIdentityStatus = null;
    walletDisconnectServerComplete = false;
    updateWalletDisconnectRecovery();
  };

  const updateWalletDisconnectRecovery = () => {
    const button = $("#resume-wallet-disconnect");
    const message = $("#wallet-disconnect-state");
    if (!pendingWalletDisconnect) {
      button.hidden = true;
      button.disabled = true;
      message.hidden = true;
      message.textContent = "";
      return;
    }
    button.hidden = false;
    button.disabled = Boolean(fullWalletDisconnectOperation);
    message.hidden = false;
    message.textContent =
      pendingWalletDisconnect.core_disconnected &&
      pendingWalletDisconnect.allowances_cleared
      ? "Clink is signed out. Finish clearing local disconnect recovery."
      : pendingWalletDisconnect.core_disconnected
        ? "Clink is signed out. Sign in again with the same address only if a previous chain cleanup still needs verification."
      : "Wallet disconnect is ready to continue safely.";
  };

  const restoreWalletDisconnectPlan = () => {
    let restored = null;
    try {
      const prefix = walletDisconnectStoragePrefix();
      const keys = [];
      for (
        let index = 0;
        index < window.sessionStorage.length;
        index += 1
      ) {
        const key = window.sessionStorage.key(index);
        if (key?.startsWith(prefix)) keys.push(key);
      }
      if (keys.length > 1) {
        throw new Error("Multiple wallet disconnect plans were found");
      }
      if (keys.length === 1) {
        const walletIdentityId = keys[0].slice(prefix.length);
        restored = readWalletDisconnectPlan(walletIdentityId);
      }
      pendingWalletDisconnect = restored;
      updateWalletDisconnectRecovery();
    } catch (_error) {
      pendingWalletDisconnect = null;
      const button = $("#resume-wallet-disconnect");
      const message = $("#wallet-disconnect-state");
      button.hidden = false;
      button.disabled = true;
      message.hidden = false;
      message.textContent =
        "Wallet disconnect recovery data is invalid. Do not repeat chain transactions; contact support.";
      status.textContent = message.textContent;
      status.classList.add("error");
    }
  };

  const legacyPendingAllowanceStorageKey = (walletIdentityId) =>
    `${PENDING_ALLOWANCE_STORAGE_PREFIX}${pendingAllowancePathScope()}.${walletIdentityId}`;

  const pendingAllowanceStorageKey = (walletIdentityId) =>
    `${PENDING_ALLOWANCE_STORAGE_V2_PREFIX}${walletIdentityId}`;

  const pendingAllowanceStoragePrefix = () =>
    PENDING_ALLOWANCE_STORAGE_V2_PREFIX;

  const allowanceAttemptStorageKey = (walletIdentityId) =>
    `${ALLOWANCE_ATTEMPT_STORAGE_PREFIX}${walletIdentityId}`;

  const allowanceAttemptStoragePrefix = () =>
    ALLOWANCE_ATTEMPT_STORAGE_PREFIX;

  const legacyAllowancePostSendUncertainStorageKey = (walletIdentityId) =>
    `${ALLOWANCE_POST_SEND_UNCERTAIN_STORAGE_PREFIX}${pendingAllowancePathScope()}.${walletIdentityId}`;

  const allowancePostSendUncertainStorageKey = (walletIdentityId) =>
    `${ALLOWANCE_POST_SEND_UNCERTAIN_STORAGE_V2_PREFIX}${walletIdentityId}`;

  const allowancePostSendUncertainStoragePrefix = () =>
    ALLOWANCE_POST_SEND_UNCERTAIN_STORAGE_V2_PREFIX;

  const pendingAllowanceProbeKey = () =>
    `${PENDING_ALLOWANCE_PROBE_PREFIX}${pendingAllowancePathScope()}`;

  const validatePendingAllowance = (value) => {
    if (!value || typeof value !== "object" || Array.isArray(value)) {
      throw new Error("Pending allowance record is invalid");
    }
    const keys = Object.keys(value).sort();
    if (
      keys.length !== PENDING_ALLOWANCE_FIELDS.length ||
      keys.some((key, index) => key !== PENDING_ALLOWANCE_FIELDS[index])
    ) {
      throw new Error("Pending allowance record has unexpected fields");
    }
    if (
      typeof value.wallet_identity_id !== "string" ||
      !/^[A-Za-z0-9][A-Za-z0-9:_-]{0,127}$/.test(value.wallet_identity_id)
    ) {
      throw new Error("Pending allowance identity is invalid");
    }
    if (
      !NETWORK_KEY_PATTERN.test(value.network) ||
      (accountState && !hasConfiguredNetwork(accountState, value.network))
    ) {
      throw new Error("Pending allowance network is invalid");
    }
    const tokenAddress = canonicalAddress(value.token_address);
    const spenderAddress = canonicalAddress(value.spender_address);
    const transactionHash = canonicalTransactionHash(value.allowance_tx_hash);
    if (
      tokenAddress !== value.token_address ||
      spenderAddress !== value.spender_address ||
      transactionHash !== value.allowance_tx_hash
    ) {
      throw new Error("Pending allowance record is not canonical");
    }
    return Object.freeze({
      wallet_identity_id: value.wallet_identity_id,
      network: value.network,
      token_address: tokenAddress,
      spender_address: spenderAddress,
      allowance_tx_hash: transactionHash
    });
  };

  const pendingAllowancesMatch = (left, right) => Boolean(
    left &&
    right &&
    PENDING_ALLOWANCE_FIELDS.every((field) => left[field] === right[field])
  );

  const mergeAllowanceRecoveryProjection = (state) => {
    const records = state.allowance_recovery.map((item) =>
      validateAllowanceRecoveryRecord(item)
    );
    allowanceRecoveryRecords = records;
    allowanceCoreRecoveryMessage = "";
    let projectedPending = null;
    let hasAwaitingWallet = false;
    for (const record of records) {
      if (!ALLOWANCE_RECOVERY_OPEN_STATUSES.has(record.status)) continue;
      if (record.status === "awaiting_wallet" && !record.allowance_tx_hash) {
        hasAwaitingWallet = true;
        continue;
      }
      if (record.allowance_tx_hash) {
        const candidate = validatePendingAllowance({
          wallet_identity_id: record.wallet_identity_id,
          network: record.network,
          token_address: record.token_address,
          spender_address: record.spender_address,
          allowance_tx_hash: record.allowance_tx_hash
        });
        if (projectedPending && !pendingAllowancesMatch(projectedPending, candidate)) {
          allowanceCoreRecoveryMessage =
            "Core returned multiple allowance transactions for this wallet. Keep every submitted hash unchanged and contact support before approving again.";
          continue;
        }
        projectedPending = candidate;
      }
    }
    if (projectedPending) {
      if (pendingAllowance && !pendingAllowancesMatch(pendingAllowance, projectedPending)) {
        allowanceCoreRecoveryMessage =
          "Core returned a different allowance transaction than this browser recorded. Keep both records unchanged and contact support before approving again.";
      } else {
        pendingAllowance = projectedPending;
      }
    }
    if (hasAwaitingWallet && !allowanceCoreRecoveryMessage) {
      allowanceCoreRecoveryMessage =
        "Core is waiting for the original wallet approval outcome. Do not approve again; check authorization status or refresh the account before continuing.";
    }
    if (records.some((record) => record.status === "attention_required") &&
        !allowanceCoreRecoveryMessage) {
      allowanceCoreRecoveryMessage =
        "Core needs attention for a submitted allowance transaction. Keep the hash unchanged and verify it before approving again.";
    }
    allowanceRecoveryBlocked = Boolean(allowanceCoreRecoveryMessage);
    allowanceRecoveryMessage = allowanceCoreRecoveryMessage;
  };

  const allowanceRecoveryBlocksNewApproval = () => Boolean(
    allowanceSessionExpired ||
    allowanceRecoveryBlocked ||
    pendingAllowance ||
    allowancePostSendUncertainIdentityId ||
    allowanceAttemptContexts.size ||
    allowanceRecoveryRecords.some((record) =>
      ALLOWANCE_RECOVERY_OPEN_STATUSES.has(record.status)
    )
  );

  const allowanceAttemptMatchesScope = (left, right) => Boolean(
    left &&
    right &&
    left.wallet_identity_id === right.wallet_identity_id &&
    left.network === right.network &&
    left.token_address === right.token_address &&
    left.spender_address === right.spender_address &&
    left.amount_atomic === right.amount_atomic
  );

  const readAllowanceAttemptContext = (walletIdentityId, storage = window.sessionStorage) => {
    const storedValue = storage.getItem(allowanceAttemptStorageKey(walletIdentityId));
    if (storedValue === null) return null;
    let record;
    try {
      record = validateAllowanceAttemptContext(JSON.parse(storedValue));
    } catch (_error) {
      throw new Error("Allowance attempt recovery storage is invalid; contact support before approving again.");
    }
    if (record.wallet_identity_id !== walletIdentityId) {
      throw new Error("Allowance attempt recovery storage conflicts with its wallet identity.");
    }
    return record;
  };

  const persistAllowanceAttemptContext = (value) => {
    const record = validateAllowanceAttemptContext(value);
    const storage = probeAllowanceRecoveryStorage();
    const existing = readAllowanceAttemptContext(record.wallet_identity_id, storage);
    if (existing && !allowanceAttemptMatchesScope(existing, record)) {
      throw new Error("Allowance attempt recovery storage conflicts with the selected wallet and target.");
    }
    const storageKey = allowanceAttemptStorageKey(record.wallet_identity_id);
    storage.setItem(storageKey, JSON.stringify(record));
    const storedValue = storage.getItem(storageKey);
    if (storedValue === null) {
      throw new Error("Allowance attempt recovery storage write was not retained");
    }
    const storedRecord = validateAllowanceAttemptContext(JSON.parse(storedValue));
    if (
      !allowanceAttemptMatchesScope(storedRecord, record) ||
      storedRecord.request_key !== record.request_key ||
      storedRecord.attempt_id !== record.attempt_id ||
      storedRecord.status !== record.status
    ) {
      throw new Error("Allowance attempt recovery storage conflicts with memory");
    }
    allowanceAttemptContexts.set(record.wallet_identity_id, storedRecord);
    updatePendingAllowanceRecovery();
    return storedRecord;
  };

  const clearAllowanceAttemptContext = (value) => {
    let record;
    try {
      record = validateAllowanceAttemptContext(value);
      const storage = probeAllowanceRecoveryStorage();
      const stored = readAllowanceAttemptContext(record.wallet_identity_id, storage);
      if (stored && (
        !allowanceAttemptMatchesScope(stored, record) ||
        stored.request_key !== record.request_key ||
        stored.attempt_id !== record.attempt_id
      )) return false;
      const storageKey = allowanceAttemptStorageKey(record.wallet_identity_id);
      storage.removeItem(storageKey);
      if (storage.getItem(storageKey) !== null) return false;
      allowanceAttemptContexts.delete(record.wallet_identity_id);
      updatePendingAllowanceRecovery();
      return true;
    } catch (_error) {
      if (record) {
        setAllowanceRecoveryBlock(
          "Allowance attempt recovery storage could not be cleared safely. Keep it unchanged and contact support before approving again."
        );
      }
      return false;
    }
  };

  const restoreAllowanceAttemptContexts = (state = accountState) => {
    if (!state) {
      updatePendingAllowanceRecovery();
      return;
    }
    const activeIdentityIds = new Set(
      state.wallet_identities
        .filter((item) => item.status === "active")
        .map((item) => item.wallet_identity_id)
    );
    let storage;
    try {
      storage = probeAllowanceRecoveryStorage();
      for (
        let index = 0;
        index < storage.length;
        index += 1
      ) {
        const key = storage.key(index);
        if (!key?.startsWith(allowanceAttemptStoragePrefix())) continue;
        const walletIdentityId = key.slice(allowanceAttemptStoragePrefix().length);
        if (!activeIdentityIds.has(walletIdentityId)) continue;
        const record = readAllowanceAttemptContext(walletIdentityId, storage);
        if (record) allowanceAttemptContexts.set(walletIdentityId, record);
      }
    } catch (_error) {
      setAllowanceRecoveryBlock(
        "Allowance attempt recovery storage is unavailable or invalid. Keep it unchanged and contact support before approving again."
      );
      updatePendingAllowanceRecovery();
      return;
    }
    if (allowanceAttemptContexts.size > 1) {
      setAllowanceRecoveryBlock(
        "Multiple allowance attempts are waiting for reconciliation. Keep them unchanged and contact support before approving again."
      );
    }
    updatePendingAllowanceRecovery();
  };

  const setAllowanceRecoveryBlock = (message) => {
    allowanceRecoveryBlocked = true;
    allowanceRecoveryMessage = message;
    disableApprovalActions();
    opcSetupBlockFromRecovery?.();
    updatePendingAllowanceRecovery();
    status.textContent = message;
    status.classList.add("error");
  };

  const clearAllowanceRecoveryBlock = () => {
    allowanceRecoveryBlocked = Boolean(allowanceCoreRecoveryMessage);
    allowanceRecoveryMessage = allowanceCoreRecoveryMessage;
  };

  const setAllowancePostSendUncertainBlock = (walletIdentityId) => {
    allowancePostSendUncertainIdentityId = walletIdentityId;
    disableApprovalActions();
    opcSetupBlockFromRecovery?.();
    updatePendingAllowanceRecovery();
    status.textContent = ALLOWANCE_POST_SEND_UNCERTAIN_MESSAGE;
    status.classList.add("error");
  };

  const clearAllowancePostSendUncertain = (walletIdentityId) => {
    if (allowancePostSendUncertainIdentityId !== walletIdentityId) return false;
    try {
      const storage = window.sessionStorage;
      const storageKeys = [
        allowancePostSendUncertainStorageKey(walletIdentityId),
        legacyAllowancePostSendUncertainStorageKey(walletIdentityId)
      ];
      for (const storageKey of storageKeys) {
        const storedValue = storage.getItem(storageKey);
        if (storedValue === null) continue;
        if (
          storageKey.startsWith(allowancePostSendUncertainStoragePrefix()) &&
          storedValue !== ALLOWANCE_POST_SEND_UNCERTAIN_LABEL
        ) return false;
        storage.removeItem(storageKey);
        if (storage.getItem(storageKey) !== null) return false;
      }
    } catch (_error) {
      return false;
    }
    allowancePostSendUncertainIdentityId = null;
    updatePendingAllowanceRecovery();
    return true;
  };

  const persistAllowancePostSendUncertain = (walletIdentityId) => {
    setAllowancePostSendUncertainBlock(walletIdentityId);
    try {
      const storage = window.sessionStorage;
      const storageKey =
        allowancePostSendUncertainStorageKey(walletIdentityId);
      storage.setItem(storageKey, ALLOWANCE_POST_SEND_UNCERTAIN_LABEL);
      if (storage.getItem(storageKey) !== ALLOWANCE_POST_SEND_UNCERTAIN_LABEL) {
        throw new Error("Allowance post-send uncertainty was not retained");
      }
    } catch (_error) {
      // The page-memory blocker remains until the page is closed.
    }
  };

  const restoreAllowancePostSendUncertain = (state = accountState) => {
    if (!state) {
      updatePendingAllowanceRecovery();
      return;
    }
    const activeIdentityIds = new Set(
      state.wallet_identities
        .filter((item) => item.status === "active")
        .map((item) => item.wallet_identity_id)
    );
    try {
      const storage = window.sessionStorage;
      const keys = [];
      for (let index = 0; index < storage.length; index += 1) {
        const key = storage.key(index);
        if (
          key?.startsWith(allowancePostSendUncertainStoragePrefix()) ||
          key?.startsWith(ALLOWANCE_POST_SEND_UNCERTAIN_STORAGE_PREFIX)
        ) keys.push(key);
      }
      for (const key of keys) {
        const isLegacy = key.startsWith(ALLOWANCE_POST_SEND_UNCERTAIN_STORAGE_PREFIX);
        const walletIdentityId = isLegacy
          ? key.slice(key.lastIndexOf(".") + 1)
          : key.slice(allowancePostSendUncertainStoragePrefix().length);
        if (!activeIdentityIds.has(walletIdentityId)) continue;
        const storedValue = storage.getItem(key);
        if (storedValue === null) continue;
        if (!isLegacy && storedValue !== ALLOWANCE_POST_SEND_UNCERTAIN_LABEL) {
          throw new Error("Allowance post-send uncertainty marker is invalid");
        }
        setAllowancePostSendUncertainBlock(walletIdentityId);
        return;
      }
    } catch (_error) {
      setAllowanceRecoveryBlock(
        "Allowance recovery storage became unavailable or invalid. Keep this page open, restore browser session storage access, and refresh before sending another transaction."
      );
      return;
    }
    updatePendingAllowanceRecovery();
  };

  const updatePendingAllowanceRecovery = () => {
    const button = $("#verify-pending-allowance");
    const message = $("#pending-allowance-state");
    const embeddedContainer = $("#embedded-pending-recovery");
    const embeddedButton = $("#embedded-verify-pending-allowance");
    const embeddedMessage = $("#embedded-pending-recovery-state");
    const hasPending = Boolean(pendingAllowance);
    const hasEmbeddedRevokeRecovery = Boolean(embeddedAllowanceRevokeRecovery);
    const hasPostSendUncertainty = Boolean(
      allowancePostSendUncertainIdentityId
    );
    const hasAttempt = allowanceAttemptContexts.size > 0;
    const hasOpenCoreRecovery = allowanceRecoveryRecords.some((record) =>
      ALLOWANCE_RECOVERY_OPEN_STATUSES.has(record.status)
    );
    button.hidden = !hasPending;
    if (hasAttempt || hasOpenCoreRecovery) button.hidden = false;
    button.disabled =
      (!hasPending && !hasAttempt) ||
      Boolean(allowanceOperation) ||
      hasPostSendUncertainty;
    message.hidden = !(
      hasPending ||
      hasAttempt ||
      hasOpenCoreRecovery ||
      allowanceRecoveryBlocked ||
      hasPostSendUncertainty
    );
    message.textContent = [
      hasPending
        ? `Transaction ${pendingAllowance.allowance_tx_hash} was submitted. Retry Core verification without sending another transaction.`
        : "",
      hasAttempt
        ? "An allowance authorization attempt is being reconciled. Check authorization status before approving again."
        : "",
      hasOpenCoreRecovery
        ? "Core has a durable allowance recovery record for this wallet. Do not approve again until it is reconciled."
        : "",
      allowanceRecoveryBlocked ? allowanceRecoveryMessage : "",
      hasPostSendUncertainty
        ? ALLOWANCE_POST_SEND_UNCERTAIN_MESSAGE
        : ""
    ].filter(Boolean).join(" ");
    if (
      hasPending ||
      hasAttempt ||
      hasOpenCoreRecovery ||
      allowanceRecoveryBlocked ||
      hasPostSendUncertainty
    ) {
      disableApprovalActions();
    }
    if (embeddedContainer) {
      embeddedContainer.hidden = !(
        hasPending ||
        allowanceRecoveryBlocked ||
        hasPostSendUncertainty ||
        hasEmbeddedRevokeRecovery
      );
    }
    if (embeddedButton) {
      embeddedButton.hidden = !(hasPending || hasEmbeddedRevokeRecovery);
      embeddedButton.disabled =
        (!hasPending && !hasEmbeddedRevokeRecovery) ||
        Boolean(allowanceOperation) ||
        hasPostSendUncertainty;
    }
    if (embeddedMessage) {
      embeddedMessage.textContent = [
        hasPending
          ? `Transaction ${pendingAllowance.allowance_tx_hash} was submitted. Retry Core verification without sending another transaction.`
          : "",
        allowanceRecoveryBlocked ? allowanceRecoveryMessage : "",
        hasPostSendUncertainty ? ALLOWANCE_POST_SEND_UNCERTAIN_MESSAGE : "",
        hasEmbeddedRevokeRecovery
          ? embeddedAllowanceRevokeRecovery.kind === "stored"
            ? "A chain allowance revocation was submitted. Verify the stored transaction result before retrying; no new transaction will be sent."
            : embeddedAllowanceRevokeRecovery.kind === "uncertain"
              ? "A chain allowance revocation may have been submitted. Verify the current allowance before retrying; no new transaction will be sent."
              : embeddedAllowanceRevokeRecovery.message
          : ""
      ].filter(Boolean).join(" ");
    }
    opcSetupBlockFromRecovery?.();
  };

  const probeAllowanceRecoveryStorage = () => {
    const probeKey = pendingAllowanceProbeKey();
    allowanceRecoveryProbeSequence += 1;
    const marker =
      `probe:${Date.now().toString(36)}:${allowanceRecoveryProbeSequence}`;
    let storage;
    let previousValue = null;
    let wroteMarker = false;
    try {
      storage = window.sessionStorage;
      previousValue = storage.getItem(probeKey);
      storage.setItem(probeKey, marker);
      wroteMarker = true;
      if (storage.getItem(probeKey) !== marker) {
        throw new Error("Allowance recovery storage round-trip failed");
      }
      storage.removeItem(probeKey);
      if (storage.getItem(probeKey) !== null) {
        throw new Error("Allowance recovery storage cleanup failed");
      }
      if (previousValue !== null) {
        storage.setItem(probeKey, previousValue);
        if (storage.getItem(probeKey) !== previousValue) {
          throw new Error("Allowance recovery storage restoration failed");
        }
      }
      return storage;
    } catch (_error) {
      if (storage && wroteMarker) {
        try {
          storage.removeItem(probeKey);
          if (storage.getItem(probeKey) !== null) {
            throw new Error("Allowance recovery storage cleanup failed");
          }
          if (previousValue !== null) {
            storage.setItem(probeKey, previousValue);
            if (storage.getItem(probeKey) !== previousValue) {
              throw new Error("Allowance recovery storage restoration failed");
            }
          }
        } catch (_cleanupError) {
          // The page remains blocked until a later state refresh can probe again.
        }
      }
      const message = "Allowance recovery storage is unavailable. Keep this page open, enable browser session storage, and refresh before sending another transaction.";
      setAllowanceRecoveryBlock(message);
      throw new Error(message);
    }
  };

  const writePendingAllowanceRecord = (value) => {
    const record = validatePendingAllowance(value);
    const storageKey = pendingAllowanceStorageKey(record.wallet_identity_id);
    const storage = window.sessionStorage;
    storage.setItem(storageKey, JSON.stringify(record));
    const storedValue = storage.getItem(storageKey);
    if (storedValue === null) {
      throw new Error("Pending allowance recovery storage write was not retained");
    }
    const storedRecord = validatePendingAllowance(JSON.parse(storedValue));
    if (!pendingAllowancesMatch(storedRecord, record)) {
      throw new Error("Pending allowance recovery storage conflicts with memory");
    }
  };

  const removePendingAllowanceRecord = (value) => {
    const record = validatePendingAllowance(value);
    const storage = window.sessionStorage;
    const storageKeys = [];
    for (let index = 0; index < storage.length; index += 1) {
      const storageKey = storage.key(index);
      if (
        storageKey?.startsWith(pendingAllowanceStoragePrefix()) ||
        storageKey?.startsWith(PENDING_ALLOWANCE_STORAGE_PREFIX)
      ) storageKeys.push(storageKey);
    }
    for (const storageKey of storageKeys) {
      const isLegacy = storageKey.startsWith(PENDING_ALLOWANCE_STORAGE_PREFIX);
      const keyIdentity = isLegacy
        ? storageKey.slice(storageKey.lastIndexOf(".") + 1)
        : storageKey.slice(pendingAllowanceStoragePrefix().length);
      if (keyIdentity !== record.wallet_identity_id) continue;
      const storedValue = storage.getItem(storageKey);
      if (storedValue === null) continue;
      const storedRecord = validatePendingAllowance(JSON.parse(storedValue));
      if (!pendingAllowancesMatch(storedRecord, record)) {
        throw new Error("Pending allowance recovery storage changed");
      }
      storage.removeItem(storageKey);
      if (storage.getItem(storageKey) !== null) {
        throw new Error("Pending allowance recovery storage was not cleared");
      }
    }
  };

  const restorePendingAllowance = (state = accountState) => {
    if (!state) {
      updatePendingAllowanceRecovery();
      return;
    }
    const activeIdentityIds = new Set(
      state.wallet_identities
        .filter((item) => item.status === "active")
        .map((item) => item.wallet_identity_id)
    );
    let memoryRecord = null;
    if (pendingAllowance) {
      try {
        const candidate = validatePendingAllowance(pendingAllowance);
        if (activeIdentityIds.has(candidate.wallet_identity_id)) {
          memoryRecord = candidate;
        }
      } catch (_error) {
        memoryRecord = null;
      }
    }
    pendingAllowance = memoryRecord;
    let storage;
    try {
      storage = probeAllowanceRecoveryStorage();
    } catch (_error) {
      updatePendingAllowanceRecovery();
      return;
    }
    if (pendingAllowanceCleanup) {
      try {
        removePendingAllowanceRecord(pendingAllowanceCleanup);
      } catch (_error) {
        setAllowanceRecoveryBlock(
          "Core verified the transaction, but this browser still could not safely clear allowance recovery storage. Keep this page open and refresh after restoring session storage access."
        );
        updatePendingAllowanceRecovery();
        return;
      }
      if (pendingAllowancesMatch(memoryRecord, pendingAllowanceCleanup)) {
        memoryRecord = null;
        pendingAllowance = null;
      }
      pendingAllowanceCleanup = null;
    }
    clearAllowanceRecoveryBlock();
    const storedIdentityIds = new Set();
    let restoredRecord = memoryRecord;
    const storageKeys = [];
    for (let index = 0; index < storage.length; index += 1) {
      const key = storage.key(index);
      if (key?.startsWith(pendingAllowanceStoragePrefix())) {
        storageKeys.push({
          key,
          walletIdentityId: key.slice(pendingAllowanceStoragePrefix().length)
        });
      } else if (key?.startsWith(PENDING_ALLOWANCE_STORAGE_PREFIX)) {
        storageKeys.push({
          key,
          walletIdentityId: key.slice(key.lastIndexOf(".") + 1)
        });
      }
    }
    for (const {key: storageKey, walletIdentityId} of storageKeys) {
      if (!activeIdentityIds.has(walletIdentityId)) continue;
      let storedValue;
      try {
        storedValue = storage.getItem(storageKey);
      } catch (_error) {
        setAllowanceRecoveryBlock(
          "Allowance recovery storage became unavailable. Keep this page open, restore browser session storage access, and refresh before sending another transaction."
        );
        break;
      }
      if (storedValue === null) continue;
      storedIdentityIds.add(walletIdentityId);
      try {
        const record = validatePendingAllowance(JSON.parse(storedValue));
        if (record.wallet_identity_id !== walletIdentityId) {
          throw new Error("Pending allowance storage key does not match its record");
        }
        if (restoredRecord && !pendingAllowancesMatch(restoredRecord, record)) {
          throw new Error("Pending allowance storage conflicts with memory");
        }
        restoredRecord = record;
        if (storageKey.startsWith(PENDING_ALLOWANCE_STORAGE_PREFIX)) {
          const migratedKey = pendingAllowanceStorageKey(walletIdentityId);
          if (storage.getItem(migratedKey) === null) {
            storage.setItem(migratedKey, JSON.stringify(record));
          }
        }
      } catch (_error) {
        setAllowanceRecoveryBlock(
          "Allowance recovery storage for this Core Account is invalid or conflicts with the submitted transaction. Keep it unchanged and contact support before sending another transaction."
        );
        break;
      }
    }
    pendingAllowance = restoredRecord;
    if (pendingAllowance) scheduleAllowanceVerificationRetry(pendingAllowance);
    if (
      memoryRecord &&
      !allowanceRecoveryBlocked &&
      !storedIdentityIds.has(memoryRecord.wallet_identity_id)
    ) {
      try {
        writePendingAllowanceRecord(memoryRecord);
      } catch (_error) {
        setAllowanceRecoveryBlock(
          "The submitted transaction is only available in this page's memory because allowance recovery storage could not save it. Keep this page open and retry Core verification without sending another transaction."
        );
      }
    }
    updatePendingAllowanceRecovery();
  };

  const assertAllowanceRecoveryStorageReadyForSend = (
    walletIdentityId,
    {allowAttempt = false} = {}
  ) => {
    restorePendingAllowance();
    restoreAllowanceAttemptContexts();
    restoreAllowancePostSendUncertain();
    if (allowancePostSendUncertainIdentityId) {
      throw new Error(ALLOWANCE_POST_SEND_UNCERTAIN_MESSAGE);
    }
    if (allowanceRecoveryBlocked) {
      throw new Error(allowanceRecoveryMessage);
    }
    if (pendingAllowance) {
      throw new Error("Verify the submitted allowance before sending another transaction");
    }
    if (!allowAttempt && allowanceAttemptContexts.size) {
      throw new Error("Check authorization status for the existing allowance attempt before approving again");
    }
    const storage = probeAllowanceRecoveryStorage();
    const storageKey = pendingAllowanceStorageKey(walletIdentityId);
    let storedValue;
    try {
      storedValue = storage.getItem(storageKey);
    } catch (_error) {
      const message = "Allowance recovery storage became unavailable. Keep this page open, restore browser session storage access, and refresh before sending another transaction.";
      setAllowanceRecoveryBlock(message);
      throw new Error(message);
    }
    if (storedValue === null) return;
    let record;
    try {
      record = validatePendingAllowance(JSON.parse(storedValue));
      if (record.wallet_identity_id !== walletIdentityId) {
        throw new Error("Pending allowance storage key does not match its record");
      }
    } catch (_error) {
      const message = "Allowance recovery storage for this Core Account is invalid. Keep it unchanged and contact support before sending another transaction.";
      setAllowanceRecoveryBlock(message);
      throw new Error(message);
    }
    if (pendingAllowance && !pendingAllowancesMatch(pendingAllowance, record)) {
      const message = "Allowance recovery storage conflicts with the submitted transaction in this page. Keep this page open and contact support before sending another transaction.";
      setAllowanceRecoveryBlock(message);
      throw new Error(message);
    }
    pendingAllowance = record;
    updatePendingAllowanceRecovery();
    throw new Error("Verify the submitted allowance before sending another transaction");
  };

  const persistPendingAllowance = (value) => {
    const record = validatePendingAllowance(value);
    pendingAllowance = record;
    updatePendingAllowanceRecovery();
    try {
      writePendingAllowanceRecord(record);
    } catch (_error) {
      setAllowanceRecoveryBlock(
        "The transaction was submitted, but this browser cannot save allowance recovery state. Keep this page open and retry Core verification without sending another transaction."
      );
    }
    return record;
  };

  const allowanceVerificationRetryDelayMs = (attempt) => {
    const testOverride = globalThis.__clinkAllowanceVerificationRetryDelayMs;
    if (typeof testOverride === "number" && Number.isFinite(testOverride) && testOverride > 0) return testOverride;
    return [1000, 3000, 8000][Math.min(attempt, 2)];
  };
  const cancelAllowanceVerificationRetry = () => {
    if (allowanceVerificationRetryTimer !== null) {
      window.clearTimeout(allowanceVerificationRetryTimer);
      allowanceVerificationRetryTimer = null;
    }
    allowanceVerificationRetryAttempts = 0;
  };
  const scheduleAllowanceVerificationRetry = (record) => {
    if (
      !record ||
      !pendingAllowancesMatch(pendingAllowance, record) ||
      !opcSetupView?.() ||
      allowanceSessionExpired ||
      allowanceRecoveryBlocked ||
      allowancePostSendUncertainIdentityId ||
      allowanceVerificationRetryTimer !== null ||
      allowanceVerificationRetryInFlight ||
      allowanceVerificationRetryAttempts >= 3
    ) return;
    const attempt = allowanceVerificationRetryAttempts;
    allowanceVerificationRetryAttempts += 1;
    allowanceVerificationRetryTimer = window.setTimeout(async () => {
      allowanceVerificationRetryTimer = null;
      if (
        !pendingAllowancesMatch(pendingAllowance, record) ||
        allowanceSessionExpired ||
        allowanceRecoveryBlocked ||
        allowancePostSendUncertainIdentityId
      ) return;
      if (allowanceOperation) {
        allowanceVerificationRetryAttempts -= 1;
        scheduleAllowanceVerificationRetry(record);
        return;
      }
      allowanceVerificationRetryInFlight = true;
      let retryAfter = false;
      try {
        await verifyPendingAllowance(record, {automatic: true});
        opcSetupCompleteVerifiedAllowance(record);
      } catch (error) {
        retryAfter = error?.httpStatus === 503;
      } finally {
        allowanceVerificationRetryInFlight = false;
        if (retryAfter) scheduleAllowanceVerificationRetry(record);
      }
    }, allowanceVerificationRetryDelayMs(attempt));
  };

  const retainLateAllowanceHash = async (
    pendingRequest,
    context,
    {onUserRejected = null} = {}
  ) => {
    if (!pendingRequest || typeof pendingRequest.then !== "function") return;
    let lateResult;
    try {
      lateResult = await pendingRequest;
    } catch (error) {
      if (
        providerErrorCode(error) === 4001 &&
        typeof onUserRejected === "function"
      ) {
        try {
          await onUserRejected(error, context);
        } catch (_callbackError) {
          // Keep the post-send uncertainty lock when correlated cleanup is unsafe.
        }
      }
      return;
    }
    try {
      const canonicalHash = canonicalTransactionHash(lateResult);
      const record = persistPendingAllowance({
        wallet_identity_id: context.wallet_identity_id,
        network: context.network,
        token_address: context.token_address,
        spender_address: context.spender_address,
        allowance_tx_hash: canonicalHash
      });
      if (context.attemptContext?.attempt_id) {
        await submitAllowanceAttempt(context.attemptContext, canonicalHash);
      }
      if (!allowanceRecoveryBlocked && pendingAllowancesMatch(pendingAllowance, record)) {
        clearAllowancePostSendUncertain(context.wallet_identity_id);
        setAccountStage(
          "submission_unknown",
          `The wallet returned the submitted transaction hash after the request timed out. Core verification will use ${canonicalHash}; no transaction will be sent.`
        );
        scheduleAllowanceVerificationRetry(record);
      }
    } catch (_error) {
      // Keep the post-send uncertainty lock when the provider never returns a valid hash.
    }
  };

  const clearPendingAllowance = (record) => {
    try {
      removePendingAllowanceRecord(record);
    } catch (_error) {
      pendingAllowanceCleanup = validatePendingAllowance(record);
      setAllowanceRecoveryBlock(
        "Core verified the transaction, but this browser could not safely clear allowance recovery storage. Keep this page open and refresh after restoring session storage access."
      );
      return false;
    }
    if (pendingAllowancesMatch(pendingAllowanceCleanup, record)) {
      pendingAllowanceCleanup = null;
    }
    if (pendingAllowancesMatch(pendingAllowance, record)) {
      pendingAllowance = null;
    }
    updatePendingAllowanceRecovery();
    return true;
  };

  const allowanceMismatchContextMatches = (record, context) => Boolean(
    context &&
    context.status === "pending" &&
    context.attempt_id === record.attempt_id &&
    context.wallet_identity_id === record.wallet_identity_id &&
    context.network === record.network &&
    context.token_address === record.token_address &&
    context.spender_address === record.spender_address &&
    context.amount_atomic === record.amount_atomic
  );

  const blockConfirmedMismatchRecovery = (record, reason) => {
    setAllowanceRecoveryBlock(
      `${allowanceMismatchSummary(record)} Recovery remains blocked: ${reason} Keep the local recovery records unchanged and do not approve again.`
    );
    return false;
  };

  const processConfirmedAllowanceMismatch = (state = accountState) => {
    const records = allowanceRecoveryRecords.filter(
      (record) => record.status === "confirmed_mismatch"
    );
    if (!records.length) return true;
    const visibleMismatchRecords = Object.keys(state?.network_configs || {})
      .map((network) => allowanceMismatchForNetwork(state, network))
      .filter(Boolean);
    allowanceMismatchNotice = visibleMismatchRecords
      .map(allowanceMismatchSummary)
      .join(" ");

    const contexts = [...allowanceAttemptContexts.values()];
    const localRecoveryPresent = Boolean(
      pendingAllowance ||
      pendingAllowanceCleanup ||
      allowancePostSendUncertainIdentityId ||
      contexts.length
    );
    if (!localRecoveryPresent) {
      if (opcSetupState?.blockedContext) {
        const blockedRecords = records.filter((record) =>
          opcSetupHandleConfirmedMismatch?.(record, {commit: false}) === true
        );
        if (blockedRecords.length !== 1) {
          return blockConfirmedMismatchRecovery(
            records[0],
            blockedRecords.length
              ? "more than one terminal result could match the previous OPC review."
              : "the previous OPC review does not identify this exact allowance result."
          );
        }
        const reset = opcSetupHandleConfirmedMismatch?.(blockedRecords[0]);
        if (reset === false) {
          return blockConfirmedMismatchRecovery(
            blockedRecords[0],
            "the previous OPC review does not match this exact allowance result."
          );
        }
      }
      return !allowanceRecoveryBlocked;
    }
    if (allowanceCoreRecoveryMessage) {
      return blockConfirmedMismatchRecovery(records[0], allowanceCoreRecoveryMessage);
    }
    if (allowanceRecoveryBlocked) {
      return blockConfirmedMismatchRecovery(
        records[0],
        allowanceRecoveryMessage || "an existing recovery blocker is still active."
      );
    }
    if (pendingAllowanceCleanup) {
      return blockConfirmedMismatchRecovery(
        records[0],
        "pending allowance storage was not cleared safely."
      );
    }
    if (
      allowanceOperation?.walletRequestPending ||
      allowanceLateWalletRequests.size ||
      walletLoginOperation
    ) {
      return blockConfirmedMismatchRecovery(
        records[0],
        "a wallet operation or late wallet response is still live."
      );
    }

    const pendingRecordMatches = (record) => pendingAllowancesMatch(pendingAllowance, {
      wallet_identity_id: record.wallet_identity_id,
      network: record.network,
      token_address: record.token_address,
      spender_address: record.spender_address,
      allowance_tx_hash: record.allowance_tx_hash
    });
    const contextRecordMatches = (record) => contexts.some((context) =>
      allowanceMismatchContextMatches(record, context)
    );
    const candidateRecords = records.filter((record) =>
      pendingRecordMatches(record) && contextRecordMatches(record)
    );
    if (candidateRecords.length !== 1) {
      return blockConfirmedMismatchRecovery(
        records[0],
        candidateRecords.length
          ? "more than one terminal result could match the local recovery records."
          : "the local recovery records do not identify this terminal result."
      );
    }
    const record = candidateRecords[0];
    const context = contexts.length === 1 ? contexts[0] : null;
    if (!pendingRecordMatches(record)) {
      return blockConfirmedMismatchRecovery(
        record,
        "the pending transaction hash or target changed."
      );
    }
    if (!context || !allowanceMismatchContextMatches(record, context)) {
      return blockConfirmedMismatchRecovery(
        record,
        "the allowance attempt ID, target, or expected amount changed."
      );
    }
    if (
      allowancePostSendUncertainIdentityId &&
      allowancePostSendUncertainIdentityId !== record.wallet_identity_id
    ) {
      return blockConfirmedMismatchRecovery(
        record,
        "the post-send uncertainty marker is missing or belongs to another wallet."
      );
    }

    let selection;
    let identity;
    try {
      selection = selectedWalletSnapshot();
      identity = selectedWalletIdentity(selection, state);
    } catch (_error) {
      return blockConfirmedMismatchRecovery(
        record,
        "the selected wallet could not be correlated to the terminal result."
      );
    }
    const target = state?.approval_targets?.[record.network];
    if (
      identity.wallet_identity_id !== record.wallet_identity_id ||
      canonicalAddress(identity.wallet_address) !== selection.address ||
      typeof state?.user_id === "string" && state.user_id !== record.user_id ||
      !target ||
      canonicalAddress(target.token_address) !== record.token_address ||
      canonicalAddress(target.spender_address) !== record.spender_address
    ) {
      return blockConfirmedMismatchRecovery(
        record,
        "the current wallet identity or approval target changed."
      );
    }
    if (opcSetupState?.blockedContext && !opcSetupHandleConfirmedMismatch?.(
      record,
      {commit: false}
    )) {
      return blockConfirmedMismatchRecovery(
        record,
        "the previous OPC review does not match this exact allowance result."
      );
    }

    if (!clearPendingAllowance(pendingAllowance)) return false;
    if (!clearAllowanceAttemptContext(context)) {
      return blockConfirmedMismatchRecovery(
        record,
        "allowance attempt storage could not be cleared safely."
      );
    }
    if (allowancePostSendUncertainIdentityId) {
      if (!clearAllowancePostSendUncertain(record.wallet_identity_id)) {
        return blockConfirmedMismatchRecovery(
          record,
          "post-send uncertainty storage could not be cleared safely."
        );
      }
    }
    clearAllowanceRecoveryBlock();
    cancelAllowanceVerificationRetry();
    if (opcSetupState?.blockedContext && !opcSetupHandleConfirmedMismatch?.(
      record,
      {commit: true}
    )) {
      return blockConfirmedMismatchRecovery(
        record,
        "the previous OPC review does not match this exact allowance result."
      );
    }
    return true;
  };

  const disableApprovalActions = () => {
    document.querySelectorAll("[data-approve-network]").forEach((button) => {
      button.disabled = true;
    });
  };

  const acquireAllowanceOperation = (allowPending) => {
    disableApprovalActions();
    if (allowanceOperation) {
      throw new Error("An allowance operation is already in progress");
    }
    if (allowancePostSendUncertainIdentityId) {
      throw new Error(ALLOWANCE_POST_SEND_UNCERTAIN_MESSAGE);
    }
    if (allowanceSessionExpired) {
      throw new Error(ACCOUNT_SESSION_EXPIRED_MESSAGE);
    }
    if (!allowPending && pendingAllowance) {
      throw new Error("Verify the submitted allowance before sending another transaction");
    }
    if (!allowPending && allowanceRecoveryBlocked) {
      throw new Error(allowanceRecoveryMessage);
    }
    if (!allowPending && allowanceAttemptContexts.size) {
      throw new Error("Check authorization status for the existing allowance attempt before approving again");
    }
    const operation = {
      cancelled: false,
      attemptContext: null,
      sendStarted: false,
      walletRequestPending: false
    };
    allowanceOperation = operation;
    updatePendingAllowanceRecovery();
    return operation;
  };

  const releaseAllowanceOperation = (operation) => {
    if (allowanceOperation !== operation) return;
    allowanceOperation = null;
    updatePendingAllowanceRecovery();
    void refreshAllowanceReadiness();
  };

  const refreshPermissionReadiness = (state = accountState) => {
    const button = $("#permission-form").querySelector("button");
    if (allowanceSessionExpired || allowanceRecoveryBlocksNewApproval()) {
      button.disabled = true;
      return;
    }
    if (state?.current_spending_mandate) {
      button.disabled = false;
      return;
    }
    const targetsReady = Boolean(
      state &&
      Object.keys(state.network_configs).every(
        (network) => state.approval_targets[network]
      )
    );
    let identityReady = false;
    try {
      identityReady = Boolean(
        selectedWalletIdentity(selectedWalletSnapshot(), state)
      );
    } catch (_error) {
      identityReady = false;
    }
    button.disabled = !(targetsReady && identityReady);
  };

  const allowanceContext = (
    network,
    selectedAccount,
    state = accountState
  ) => {
    if (!state) throw new Error("Account controls are not loaded");
    let selected;
    try {
      selected = canonicalAddress(selectedAccount);
    } catch (_error) {
      throw new Error("Selected wallet does not match the bound wallet");
    }
    const activeIdentities = state.wallet_identities.filter((item) => item.status === "active");
    if (!activeIdentities.length) throw new Error("No active bound wallet");
    const identity = activeIdentities.find((item) => canonicalAddress(item.wallet_address) === selected);
    if (!identity) throw new Error("Selected wallet does not match the bound wallet");
    const config = state.network_configs[network];
    if (!config) throw new Error("Unsupported allowance target");
    const target = state.approval_targets[network];
    if (!target) throw new Error("Unsupported allowance target");
    const targetToken = canonicalAddress(target.token_address);
    const mandate = state.current_spending_mandate;
    if (
      !mandate ||
      mandate.status !== "active" ||
      mandate.wallet_identity_id !== identity.wallet_identity_id ||
      !mandate.network_scopes.includes(network) ||
      !mandate.asset_scopes.some(
        (asset) => canonicalAddress(asset) === targetToken
      )
    ) throw new Error("No active permission supports this allowance");
    const selectors = networkElementSelectors(network, config);
    const token = canonicalAddress($(selectors.token).value);
    const spender = canonicalAddress($(selectors.spender).value);
    if (token !== targetToken || spender !== canonicalAddress(target.spender_address)) {
      throw new Error("Unsupported allowance target");
    }
    return {
      amount: usdcAtomic(mandate.limits_usdc.per_transaction),
      chainId: networkChainId(config),
      confirmations: config.required_confirmations,
      identity,
      selected,
      spender,
      token
    };
  };

  const refreshAllowanceReadiness = async (state = accountState) => {
    disableApprovalActions();
    if (
      allowanceSessionExpired ||
      pendingAllowance ||
      allowanceOperation ||
      allowanceRecoveryBlocked ||
      allowancePostSendUncertainIdentityId ||
      allowanceAttemptContexts.size ||
      allowanceRecoveryRecords.some((record) =>
        ALLOWANCE_RECOVERY_OPEN_STATUSES.has(record.status)
      )
    ) return;
    try {
      const selection = selectedWalletSnapshot();
      await providerAccountsContainSelection(selection);
      if (state !== accountState) return;
      if (
        allowanceSessionExpired ||
        pendingAllowance ||
        allowanceOperation ||
        allowanceRecoveryBlocked ||
        allowancePostSendUncertainIdentityId ||
        allowanceAttemptContexts.size ||
        allowanceRecoveryRecords.some((record) =>
          ALLOWANCE_RECOVERY_OPEN_STATUSES.has(record.status)
        )
      ) return;
      document.querySelectorAll("[data-approve-network]").forEach((button) => {
        try {
          const coverage = allowanceCoverage(
            state,
            button.dataset.approveNetwork
          );
          if (!coverage || coverage.covered) {
            button.disabled = true;
            button.hidden = true;
            return;
          }
          allowanceContext(
            button.dataset.approveNetwork,
            selection.address,
            state
          );
          button.hidden = false;
          button.disabled = false;
        } catch (_error) {
          button.disabled = true;
        }
      });
    } catch (_error) {
      disableApprovalActions();
    }
  };

  const loginSelectedWallet = async (selection, {onStart} = {}) => {
    if (walletLoginOperation) {
      throw new Error("Wallet login is already in progress");
    }
    const operation = {
      cancelled: false,
      challengeCancelRequested: false,
      challengeSessionId: null,
      verified: false
    };
    walletLoginOperation = operation;
    onStart?.(operation);
    try {
      const challenge = await request("/wallet-challenge", {
        method: "POST",
        body: JSON.stringify({wallet_address: selection.address})
      });
      operation.challengeSessionId = challenge.session_id;
      if (operation.cancelled) {
        throw new Error("Wallet login was cancelled.");
      }
      assertWalletSnapshot(selection);
      const signature = await selection.provider.request({
        method: "personal_sign",
        params: [challenge.message_to_sign, selection.address]
      });
      if (operation.cancelled) {
        throw new Error("Wallet login was cancelled.");
      }
      assertWalletSnapshot(selection);
      const verifiedIdentity = await request("/wallet-verify", {
        method: "POST",
        body: JSON.stringify({
          challenge_session_id: challenge.session_id,
          signed_message: challenge.message_to_sign,
          signature
        })
      });
      beginAccountSessionAfterWalletLogin();
      operation.verified = true;
      if (verifiedIdentity.status === "suspended") {
        const walletIdentityId = canonicalAccountObjectId(
          verifiedIdentity.wallet_identity_id,
          "Wallet disconnect identity"
        );
        let recoveryPlan =
          pendingWalletDisconnect?.wallet_identity_id === walletIdentityId
            ? validateWalletDisconnectPlan({
                ...pendingWalletDisconnect,
                provider_uuid: selection.uuid
              })
            : validateWalletDisconnectPlan({
                operation: "disconnect",
                wallet_identity_id: walletIdentityId,
                wallet_address: canonicalAddress(
                  verifiedIdentity.wallet_address
                ),
                provider_uuid: selection.uuid,
                core_disconnected: false,
                allowances_cleared: false,
                allowances: []
              });
        recoveryPlan = await loadWalletDisconnectState(recoveryPlan);
        persistWalletDisconnectPlan(recoveryPlan);
        await loadState();
        status.textContent =
          "Wallet ownership confirmed for cleanup only. Continue Clink unbind; spending remains disabled.";
        status.classList.toggle("error", false);
        return;
      }
      if (
        pendingWalletDisconnect?.core_disconnected &&
        pendingWalletDisconnect.wallet_address === selection.address
      ) {
        persistWalletDisconnectPlan({
          ...pendingWalletDisconnect,
          provider_uuid: selection.uuid
        });
      }
      await loadState();
      return verifiedIdentity;
    } catch (error) {
      if (!operation.verified) {
        try {
          await cancelWalletLoginOperation(operation);
        } catch (_cancelError) {
          operation.cancelError = true;
        }
      }
      throw error;
    } finally {
      if (walletLoginOperation === operation) {
        walletLoginOperation = null;
      }
      updateWalletSelectionActions();
    }
  };

  $("#connect-wallet").addEventListener("click", async (event) => {
    if (walletLoginOperation) return;
    const button = event.currentTarget;
    button.disabled = true;
    let operation = null;
    let loginResetMessage = null;
    try {
      const selection = selectedWalletSnapshot();
      await loginSelectedWallet(selection, {
        onStart: (started) => { operation = started; }
      });
    } catch (error) {
      if (operation?.cancelError) {
        status.textContent =
          "Wallet login failed and its short-lived challenge could not be cancelled.";
        status.classList.add("error");
      }
      if (operation?.verified) {
        loginResetMessage =
          "Wallet sign-in completed, but account state could not be refreshed. Reload the page.";
        status.textContent = loginResetMessage;
        status.classList.add("error");
      } else if (operation?.cancelled) {
        loginResetMessage =
          "Wallet login cancelled. Choose a wallet to start again.";
        status.textContent = loginResetMessage;
        status.classList.toggle("error", false);
      } else {
        loginResetMessage =
          "Wallet login failed. No wallet was bound. Choose a wallet to start again.";
        invalidateWalletSelection(loginResetMessage);
        status.textContent = `${error.message}. No wallet was bound.`;
        status.classList.add("error");
      }
    } finally {
      updateWalletSelectionActions();
      if (loginResetMessage) {
        $("#wallet-selection-state").textContent = loginResetMessage;
      }
    }
  });

  $("#cancel-wallet-selection").addEventListener("click", async () => {
    await disconnectWalletSelection();
  });

  const submitSignedGrant = async (terms, selection, guard = () => {}) => {
    guard();
    const callbacks = guard.callbacks || {};
    const challenge = await request("/grants", {
      method: "POST",
      body: JSON.stringify(terms)
    });
    guard();
    assertWalletSnapshot(selection);
    callbacks.onSignatureRequest?.();
    const signature = await selection.provider.request({
      method: "personal_sign",
      params: [challenge.message_to_sign, selection.address]
    });
    guard();
    assertWalletSnapshot(selection);
    guard();
    callbacks.onGrantSubmit?.();
    await request("/grants", {
      method: "POST",
      body: JSON.stringify({
        ...terms,
        challenge_session_id: challenge.session_id,
        signed_message: challenge.message_to_sign,
        signature
      })
    });
  };

  $("#permission-form").addEventListener("submit", async (event) => {
    event.preventDefault();
    const button = event.currentTarget.querySelector("button");
    button.disabled = true;
    try {
      const currentMandate = accountState?.current_spending_mandate;
      const totalLimit = $("#total-limit").value;
      if (currentMandate) {
        const requested = usdcAtomic(totalLimit);
        const current = usdcAtomic(currentMandate.limits_usdc.total);
        const currentCaps = [
          currentMandate.limits_usdc.per_transaction,
          currentMandate.limits_usdc.rolling_hour,
          currentMandate.limits_usdc.daily,
          currentMandate.limits_usdc.total
        ].map(usdcAtomic);
        if (requested < current && currentCaps.every((cap) => requested <= cap)) {
          await request(
            `/grants/${currentMandate.spending_grant_id}/reduce`,
            {
              method: "POST",
              body: JSON.stringify({
                max_amount_usdc: totalLimit,
                per_transaction_limit_usdc: totalLimit,
                hourly_limit_usdc: totalLimit,
                daily_limit_usdc: totalLimit
              })
            }
          );
        } else if (!currentCaps.every((cap) => requested === cap)) {
          const selection = selectedWalletSnapshot();
          await providerAccountsContainSelection(selection);
          selectedWalletIdentity(selection);
          const amendmentTerms = {
            wallet_identity_id: currentMandate.wallet_identity_id,
            agent_id: currentMandate.agent_id,
            max_amount_usdc: totalLimit,
            per_transaction_limit_usdc: totalLimit,
            hourly_limit_usdc: totalLimit,
            daily_limit_usdc: totalLimit,
            product_scopes: currentMandate.product_scopes,
            venue_scopes: currentMandate.venue_scopes,
            merchant_scopes: currentMandate.merchant_scopes,
            merchant_trust_scopes: currentMandate.merchant_trust_scopes,
            notification_mode: currentMandate.notification_mode,
            network_scopes: currentMandate.network_scopes,
            asset_scopes: currentMandate.asset_scopes,
            starts_at: currentMandate.starts_at,
            expires_at: currentMandate.expires_at,
            amends_spending_grant_id: currentMandate.spending_grant_id
          };
          await submitSignedGrant(amendmentTerms, selection);
        }
        await loadState();
        return;
      }
      const selection = selectedWalletSnapshot();
      await providerAccountsContainSelection(selection);
      const wallet = selectedWalletIdentity(selection);
      const now = new Date();
      const expiryDays = Number.parseInt($("#expiry-days").value, 10);
      if (!Number.isInteger(expiryDays) || expiryDays < 1 || expiryDays > 365) {
        throw new Error("Permission duration must be between 1 and 365 days");
      }
      const expires = new Date(now.getTime() + expiryDays * 24 * 60 * 60 * 1000);
      const merchantTrustScopes = [
        $("#trust-clink").checked ? "clink_verified" : null,
        $("#trust-registry").checked ? "registry_verified" : null
      ].filter(Boolean);
      if (!merchantTrustScopes.length) throw new Error("Select at least one trusted merchant tier");
      const grantNetworks = Object.keys(accountState.network_configs);
      const assetScopes = grantNetworks.map((network) => {
        const target = accountState.approval_targets[network];
        if (!target) throw new Error(`Core approval configuration unavailable for ${network}`);
        return canonicalAddress(target.token_address);
      });
      const terms = {
        wallet_identity_id: wallet.wallet_identity_id,
        agent_id: CONTROLLED_AGENT_ID,
        max_amount_usdc: totalLimit,
        per_transaction_limit_usdc: totalLimit,
        hourly_limit_usdc: totalLimit,
        daily_limit_usdc: totalLimit,
        product_scopes: ["prediction_markets", "marketplace"],
        venue_scopes: ["polymarket", "clink_marketplace"],
        merchant_scopes: [],
        merchant_trust_scopes: merchantTrustScopes,
        notification_mode: $("#notification-mode").value,
        network_scopes: grantNetworks,
        asset_scopes: assetScopes,
        starts_at: now.toISOString(),
        expires_at: expires.toISOString()
      };
      await submitSignedGrant(terms, selection);
      await loadState();
    } catch (error) {
      status.textContent = error.message;
      status.classList.add("error");
    } finally {
      refreshPermissionReadiness();
    }
  });

  $("#wallet-details").addEventListener("click", async (event) => {
    const button = event.target.closest("[data-wallet-disconnect]");
    if (!button) return;
    button.disabled = true;
    try {
      await fullyDisconnectWallet(button.dataset.walletDisconnect);
    } catch (error) {
      status.textContent = error.message;
      status.classList.add("error");
      button.disabled = false;
    }
  });

  $("#resume-wallet-disconnect").addEventListener("click", async (event) => {
    const button = event.currentTarget;
    if (!pendingWalletDisconnect) return;
    button.disabled = true;
    try {
      await fullyDisconnectWallet(
        pendingWalletDisconnect.wallet_identity_id
      );
    } catch (error) {
      status.textContent = error.message;
      status.classList.add("error");
    } finally {
      updateWalletDisconnectRecovery();
    }
  });

  opcElement("#opc-review-button")?.addEventListener("click", async (event) => {
    const button = event.currentTarget;
    if (button) button.disabled = true;
    await opcReview();
    opcUpdateReviewActions();
  });
  opcElement("#opc-sign-button")?.addEventListener("click", async (event) => {
    const button = event.currentTarget;
    if (button) button.disabled = true;
    await opcSign();
    if (button && opcReviewChallenge) button.disabled = false;
    opcUpdateReviewActions();
  });
  opcElement("#opc-cancel-button")?.addEventListener("click", (event) => {
    const button = event.currentTarget;
    if (button) button.disabled = true;
    opcCancelReview();
  });
  const refreshOpcFromButton = async (event) => {
    const button = event.currentTarget;
    if (button) button.disabled = true;
    await refreshOpcPairing();
    if (button) button.disabled = false;
    opcUpdateReviewActions();
  };
  opcElement("#opc-refresh")?.addEventListener("click", refreshOpcFromButton);
  opcElement("#opc-recheck")?.addEventListener("click", refreshOpcFromButton);

  $("#grant-details").addEventListener("click", async (event) => {
    const button = event.target.closest("[data-grant-action]");
    if (!button) return;
    const row = button.closest("[data-grant-id]");
    const grantId = row.dataset.grantId;
    const action = button.dataset.grantAction;
    button.disabled = true;
    try {
      await request(`/grants/${grantId}/${action}`, {method: "POST", body: "{}"});
      await loadState();
    } catch (error) {
      status.textContent = error.message;
      status.classList.add("error");
      button.disabled = false;
    }
  });

  const waitForConfirmations = async (
    provider,
    transactionHash,
    required,
    {bounded = false} = {}
  ) => {
    const providerRead = (request) => bounded
      ? providerRequest(provider, request, {stage: "chain_confirmation"})
      : provider.request(request);
    for (let attempt = 0; attempt < 120; attempt += 1) {
      const receipt = await providerRead({
        method: "eth_getTransactionReceipt",
        params: [transactionHash]
      });
      if (receipt && receipt.blockNumber) {
        const latest = await providerRead({method: "eth_blockNumber"});
        const confirmations = parseInt(latest, 16) - parseInt(receipt.blockNumber, 16) + 1;
        if (confirmations >= required) return;
        status.textContent = `Waiting for chain confirmation ${confirmations} of ${required}...`;
      } else {
        status.textContent = "Waiting for the approval transaction to be mined...";
      }
      await new Promise((resolve) => window.setTimeout(resolve, 3000));
    }
    throw new Error("Approval confirmation timed out; refresh status to try verification again");
  };

  const allowanceRevokeStorageKey = (walletIdentityId, network) =>
    `${ALLOWANCE_REVOKE_STORAGE_PREFIX}${pendingAllowancePathScope()}.${walletIdentityId}.${encodeURIComponent(network)}`;

  const allowanceRevokeProbeKey = (walletIdentityId, network) =>
    `${ALLOWANCE_REVOKE_PROBE_PREFIX}${pendingAllowancePathScope()}.${walletIdentityId}.${encodeURIComponent(network)}`;

  const allowanceRevokeUncertainKey = (walletIdentityId, network) =>
    `${ALLOWANCE_REVOKE_UNCERTAIN_PREFIX}${pendingAllowancePathScope()}.${walletIdentityId}.${encodeURIComponent(network)}`;

  const canonicalAccountObjectId = (value, label) => {
    if (
      typeof value !== "string" ||
      !/^[A-Za-z0-9][A-Za-z0-9:_-]{0,127}$/.test(value)
    ) {
      throw new Error(`${label} is invalid`);
    }
    return value;
  };

  const validateAllowanceRevocation = (value) => {
    if (!value || typeof value !== "object" || Array.isArray(value)) {
      throw new Error("Allowance revocation record is invalid");
    }
    const keys = Object.keys(value).sort();
    if (
      keys.length !== ALLOWANCE_REVOKE_FIELDS.length ||
      keys.some((key, index) => key !== ALLOWANCE_REVOKE_FIELDS[index])
    ) {
      throw new Error("Allowance revocation record has unexpected fields");
    }
    if (value.operation !== "revoke") {
      throw new Error("Allowance revocation operation is invalid");
    }
    const walletIdentityId = canonicalAccountObjectId(
      value.wallet_identity_id,
      "Allowance revocation identity"
    );
    const assetAllowanceId = canonicalAccountObjectId(
      value.asset_allowance_id,
      "Allowance revocation object"
    );
    if (
      !NETWORK_KEY_PATTERN.test(value.network) ||
      (accountState && !hasConfiguredNetwork(accountState, value.network))
    ) {
      throw new Error("Allowance revocation network is invalid");
    }
    const walletAddress = canonicalAddress(value.wallet_address);
    const tokenAddress = canonicalAddress(value.token_address);
    const spenderAddress = canonicalAddress(value.spender_address);
    const transactionHash = canonicalTransactionHash(value.allowance_tx_hash);
    if (
      walletAddress !== value.wallet_address ||
      tokenAddress !== value.token_address ||
      spenderAddress !== value.spender_address ||
      transactionHash !== value.allowance_tx_hash
    ) {
      throw new Error("Allowance revocation record is not canonical");
    }
    return Object.freeze({
      operation: "revoke",
      wallet_identity_id: walletIdentityId,
      wallet_address: walletAddress,
      asset_allowance_id: assetAllowanceId,
      network: value.network,
      token_address: tokenAddress,
      spender_address: spenderAddress,
      allowance_tx_hash: transactionHash
    });
  };

  const allowanceRevocationsMatch = (left, right) => Boolean(
    left &&
    right &&
    ALLOWANCE_REVOKE_FIELDS.every((field) => left[field] === right[field])
  );

  const allowanceRevokeScope = (walletIdentityId, network) =>
    `${walletIdentityId}:${network}`;

  const persistAllowanceRevokeUncertain = (walletIdentityId, network) => {
    const scope = allowanceRevokeScope(walletIdentityId, network);
    allowanceRevokePostSendUncertain.add(scope);
    try {
      const key = allowanceRevokeUncertainKey(walletIdentityId, network);
      window.sessionStorage.setItem(
        key,
        ALLOWANCE_REVOKE_UNCERTAIN_LABEL
      );
      if (
        window.sessionStorage.getItem(key) !==
        ALLOWANCE_REVOKE_UNCERTAIN_LABEL
      ) {
        throw new Error("Allowance revocation uncertainty was not retained");
      }
    } catch (_error) {
      // The in-memory no-resend lock remains active for this page.
    }
  };

  const assertAllowanceRevokeCanSend = (
    walletIdentityId,
    network
  ) => {
    const scope = allowanceRevokeScope(walletIdentityId, network);
    if (allowanceRevokePostSendUncertain.has(scope)) {
      throw new Error(ALLOWANCE_REVOKE_UNCERTAIN_MESSAGE);
    }
    const uncertainKey = allowanceRevokeUncertainKey(
      walletIdentityId,
      network
    );
    const probeKey = allowanceRevokeProbeKey(walletIdentityId, network);
    const marker = `${Date.now().toString(36)}:${Math.random().toString(36)}`;
    try {
      if (window.sessionStorage.getItem(uncertainKey) !== null) {
        allowanceRevokePostSendUncertain.add(scope);
        throw new Error(ALLOWANCE_REVOKE_UNCERTAIN_MESSAGE);
      }
      window.sessionStorage.setItem(probeKey, marker);
      if (window.sessionStorage.getItem(probeKey) !== marker) {
        throw new Error("Allowance revocation recovery storage was not retained");
      }
      window.sessionStorage.removeItem(probeKey);
      if (window.sessionStorage.getItem(probeKey) !== null) {
        throw new Error("Allowance revocation recovery storage was not cleared");
      }
    } catch (error) {
      if (error.message === ALLOWANCE_REVOKE_UNCERTAIN_MESSAGE) throw error;
      throw new Error(
        "Allowance revocation recovery storage is unavailable. No transaction was sent."
      );
    }
  };

  const storedAllowanceRevocation = (walletIdentityId, network) => {
    const key = allowanceRevokeStorageKey(walletIdentityId, network);
    let raw;
    try {
      raw = window.sessionStorage.getItem(key);
    } catch (_error) {
      throw new Error(
        "Allowance revocation recovery storage is unavailable. Do not send another transaction."
      );
    }
    if (raw === null) return null;
    try {
      const record = validateAllowanceRevocation(JSON.parse(raw));
      if (
        record.wallet_identity_id !== walletIdentityId ||
        record.network !== network
      ) {
        throw new Error("Allowance revocation storage key does not match its record");
      }
      return record;
    } catch (_error) {
      throw new Error(
        "Allowance revocation recovery record is invalid. Do not send another transaction."
      );
    }
  };

  const persistAllowanceRevocation = (record) => {
    const canonical = validateAllowanceRevocation(record);
    const key = allowanceRevokeStorageKey(
      canonical.wallet_identity_id,
      canonical.network
    );
    try {
      window.sessionStorage.setItem(key, JSON.stringify(canonical));
      const stored = storedAllowanceRevocation(
        canonical.wallet_identity_id,
        canonical.network
      );
      if (!allowanceRevocationsMatch(stored, canonical)) {
        throw new Error("Allowance revocation recovery record conflicts");
      }
    } catch (_error) {
      persistAllowanceRevokeUncertain(
        canonical.wallet_identity_id,
        canonical.network
      );
      throw new Error(ALLOWANCE_REVOKE_UNCERTAIN_MESSAGE);
    }
    return canonical;
  };

  const clearAllowanceRevocation = (record) => {
    const key = allowanceRevokeStorageKey(
      record.wallet_identity_id,
      record.network
    );
    let stored;
    try {
      stored = storedAllowanceRevocation(
        record.wallet_identity_id,
        record.network
      );
      if (stored && !allowanceRevocationsMatch(stored, record)) {
        throw new Error("Allowance revocation recovery record changed");
      }
      window.sessionStorage.removeItem(key);
      if (window.sessionStorage.getItem(key) !== null) {
        throw new Error("Allowance revocation recovery record was not cleared");
      }
    } catch (_error) {
      throw new Error(
        "The chain allowance is revoked, but browser recovery storage could not be cleared. Refresh after restoring session storage access."
      );
    }
  };

  const clearAllowanceRevokeUncertain = (walletIdentityId, network) => {
    const scope = allowanceRevokeScope(walletIdentityId, network);
    const key = allowanceRevokeUncertainKey(walletIdentityId, network);
    try {
      window.sessionStorage.removeItem(key);
      if (window.sessionStorage.getItem(key) !== null) {
        throw new Error("Allowance revocation uncertainty was not cleared");
      }
    } catch (_error) {
      throw new Error(
        "The allowance is verified at zero, but browser recovery storage could not be cleared. Refresh after restoring session storage access."
      );
    }
    allowanceRevokePostSendUncertain.delete(scope);
  };

  const restoreEmbeddedAllowanceRevokeRecovery = (state = accountState) => {
    embeddedAllowanceRevokeRecovery = null;
    if (!isEmbeddedView() || !state) {
      updatePendingAllowanceRecovery();
      return;
    }
    const activeIdentityIds = new Set(
      (state.wallet_identities || [])
        .filter((item) => item.status === "active")
        .map((item) => item.wallet_identity_id)
    );
    const storedPrefix = `${ALLOWANCE_REVOKE_STORAGE_PREFIX}${pendingAllowancePathScope()}.`;
    const uncertainPrefix = `${ALLOWANCE_REVOKE_UNCERTAIN_PREFIX}${pendingAllowancePathScope()}.`;
    const readScope = (prefix, key) => {
      const suffix = key.slice(prefix.length);
      const separator = suffix.indexOf(".");
      if (separator <= 0) return null;
      return {
        walletIdentityId: suffix.slice(0, separator),
        network: decodeURIComponent(suffix.slice(separator + 1))
      };
    };
    try {
      const keys = [];
      for (let index = 0; index < window.sessionStorage.length; index += 1) {
        const key = window.sessionStorage.key(index);
        if (key?.startsWith(storedPrefix)) keys.push(key);
      }
      for (const key of keys) {
        const scope = readScope(storedPrefix, key);
        if (!scope || !activeIdentityIds.has(scope.walletIdentityId)) continue;
        const record = storedAllowanceRevocation(
          scope.walletIdentityId,
          scope.network
        );
        if (record) {
          embeddedAllowanceRevokeRecovery = {kind: "stored", record};
          updatePendingAllowanceRecovery();
          return;
        }
      }
      const uncertainKeys = [];
      for (let index = 0; index < window.sessionStorage.length; index += 1) {
        const key = window.sessionStorage.key(index);
        if (key?.startsWith(uncertainPrefix)) uncertainKeys.push(key);
      }
      for (const key of uncertainKeys) {
        const scope = readScope(uncertainPrefix, key);
        if (!scope || !activeIdentityIds.has(scope.walletIdentityId)) continue;
        // Legacy hashless markers bind only wallet/network, not token/spender.
        // Never infer their target from the first allowance in an account.
        embeddedAllowanceRevokeRecovery = {
          kind: "uncertain",
          wallet_identity_id: scope.walletIdentityId,
          network: scope.network
        };
        updatePendingAllowanceRecovery();
        return;
      }
    } catch (error) {
      embeddedAllowanceRevokeRecovery = {
        kind: "blocked",
        message: error.message
      };
    }
    updatePendingAllowanceRecovery();
  };

  const recoverEmbeddedAllowanceRevocation = async () => {
    const recovery = embeddedAllowanceRevokeRecovery;
    if (!recovery) {
      throw new Error("No allowance revocation is waiting for verification");
    }
    if (recovery.kind === "blocked") throw new Error(recovery.message);
    const selection = selectedWalletSnapshot();
    const identity = selectedWalletIdentity(selection);
    if (recovery.kind === "stored") {
      if (identity.wallet_identity_id !== recovery.record.wallet_identity_id) {
        throw new Error("Selected wallet does not match the allowance recovery record");
      }
      await recoverAllowanceRevocation(recovery.record);
    } else {
      if (identity.wallet_identity_id !== recovery.wallet_identity_id) {
        throw new Error("Selected wallet does not match the allowance recovery record");
      }
      throw new Error("The exact token/spender and transaction hash are unavailable for this revocation. Do not resend. Check the transaction in your wallet and contact support; another allowance at zero cannot prove this revocation succeeded.");
    }
    embeddedAllowanceRevokeRecovery = null;
    updatePendingAllowanceRecovery();
    await loadState();
  };

  const refreshAllowanceRevocationState = async (value) => {
    const refreshed = await request(
      `/allowances/${value.asset_allowance_id}/refresh`,
      {method: "POST", body: "{}"}
    );
    if (
      refreshed.asset_allowance_id !== value.asset_allowance_id ||
      refreshed.wallet_identity_id !== value.wallet_identity_id ||
      refreshed.network !== value.network ||
      canonicalAddress(refreshed.token_address) !== value.token_address ||
      canonicalAddress(refreshed.spender_address) !== value.spender_address
    ) {
      throw new Error("Core returned a different allowance during revocation");
    }
    return refreshed;
  };

  const recoverAllowanceRevocation = async (value) => {
    const record = validateAllowanceRevocation(value);
    const refreshed = await refreshAllowanceRevocationState(record);
    if (
      String(refreshed.observed_allowance_atomic) !== "0" ||
      refreshed.status !== "revoked"
    ) {
      throw new Error(
        `The ${record.network} allowance is still active. Do not resend; retry chain verification.`
      );
    }
    clearAllowanceRevocation(record);
  };

  const allowanceRevokeContext = (selection, allowance) => {
    const walletIdentityId = canonicalAccountObjectId(
      allowance.wallet_identity_id,
      "Allowance wallet identity"
    );
    const assetAllowanceId = canonicalAccountObjectId(
      allowance.asset_allowance_id,
      "Asset allowance"
    );
    const config =
      accountState?.network_configs?.[allowance.network] ||
      walletDisconnectNetworkConfigs?.[allowance.network];
    if (!config) {
      throw new Error("Unsupported allowance revoke network");
    }
    const walletAddress = canonicalAddress(allowance.wallet_address);
    if (walletAddress !== selection.address) {
      throw new Error("Selected wallet does not match the allowance owner");
    }
    const tokenAddress = canonicalAddress(allowance.token_address);
    const spenderAddress = canonicalAddress(allowance.spender_address);
    const target =
      accountState?.approval_targets?.[allowance.network] ||
      walletDisconnectApprovalTargets?.[allowance.network];
    if (
      !target ||
      canonicalAddress(target.token_address) !== tokenAddress ||
      canonicalAddress(target.spender_address) !== spenderAddress
    ) {
      throw new Error("Unsupported allowance revoke target");
    }
    let observed;
    try {
      observed = BigInt(String(allowance.observed_allowance_atomic));
    } catch (_error) {
      throw new Error("Observed allowance amount is invalid");
    }
    if (observed < 0n) throw new Error("Observed allowance amount is invalid");
    return Object.freeze({
      wallet_identity_id: walletIdentityId,
      wallet_address: walletAddress,
      asset_allowance_id: assetAllowanceId,
      network: allowance.network,
      token_address: tokenAddress,
      spender_address: spenderAddress,
      observed_allowance_atomic: observed,
      chainId: networkChainId(config),
      confirmations: config.required_confirmations
    });
  };

  const revokeAllowance = async (selection, allowance, guard = () => {}) => {
    if (allowanceRevokeOperation) {
      throw new Error("An allowance revocation is already in progress");
    }
    const operation = Object.freeze({});
    allowanceRevokeOperation = operation;
    try {
      guard();
      const context = allowanceRevokeContext(selection, allowance);
      if (context.observed_allowance_atomic === 0n) return;
      const existing = storedAllowanceRevocation(
        context.wallet_identity_id,
        context.network
      );
      if (existing) {
        if (["wallet_identity_id", "wallet_address", "asset_allowance_id", "network", "token_address", "spender_address"].some(
          (key) => existing[key] !== context[key]
        )) {
          throw new Error("A different allowance target has a pending revocation. Recover that exact target first; its receipt cannot prove the selected allowance is zero.");
        }
        await recoverAllowanceRevocation(existing);
        return;
      }
      const refreshed = await refreshAllowanceRevocationState(context);
      guard();
      if (
        String(refreshed.observed_allowance_atomic) === "0" &&
        refreshed.status === "revoked"
      ) {
        return;
      }
      assertAllowanceRevokeCanSend(
        context.wallet_identity_id,
        context.network
      );
      await providerAccountsContainSelection(selection);
      guard();
      await selection.provider.request({
        method: "wallet_switchEthereumChain",
        params: [{chainId: context.chainId}]
      });
      guard();
      assertWalletSnapshot(selection);
      const chainId = await selection.provider.request({
        method: "eth_chainId"
      });
      guard();
      assertWalletSnapshot(selection);
      if (chainId !== context.chainId) {
        throw new Error("Wallet did not switch to the allowance network");
      }
      await providerAccountsContainSelection(selection);
      guard();
      assertAllowanceRevokeCanSend(
        context.wallet_identity_id,
        context.network
      );
      const data =
        `0x095ea7b3${context.spender_address.slice(2).padStart(64, "0")}${"0".padStart(64, "0")}`;
      let transactionHash;
      try {
        transactionHash = await selection.provider.request({
          method: "eth_sendTransaction",
          params: [{
            from: selection.address,
            to: context.token_address,
            data,
            chainId: context.chainId
          }]
        });
      } catch (error) {
        if (error?.code === 4001) throw error;
        persistAllowanceRevokeUncertain(context.wallet_identity_id, context.network);
        throw new Error(ALLOWANCE_REVOKE_UNCERTAIN_MESSAGE);
      }
      let canonicalHash;
      try {
        canonicalHash = canonicalTransactionHash(transactionHash);
      } catch (_error) {
        persistAllowanceRevokeUncertain(
          context.wallet_identity_id,
          context.network
        );
        throw new Error(ALLOWANCE_REVOKE_UNCERTAIN_MESSAGE);
      }
      const record = persistAllowanceRevocation({
        operation: "revoke",
        wallet_identity_id: context.wallet_identity_id,
        wallet_address: context.wallet_address,
        asset_allowance_id: context.asset_allowance_id,
        network: context.network,
        token_address: context.token_address,
        spender_address: context.spender_address,
        allowance_tx_hash: canonicalHash
      });
      try {
        await waitForConfirmations(
          selection.provider,
          record.allowance_tx_hash,
          context.confirmations
        );
      } catch (_error) {
        status.textContent =
          "Wallet receipt confirmation was unavailable. Core is checking the allowance revocation.";
      }
      await recoverAllowanceRevocation(record);
    } finally {
      if (allowanceRevokeOperation === operation) {
        allowanceRevokeOperation = null;
      }
    }
  };

  const createWalletDisconnectPlan = (walletIdentityId) => {
    const selection = selectedWalletSnapshot();
    const identity = selectedWalletIdentity(selection);
    if (identity.wallet_identity_id !== walletIdentityId) {
      throw new Error("Selected wallet does not match the disconnect target");
    }
    const allowances = accountState.asset_allowances
      .filter((item) => item.wallet_identity_id === walletIdentityId)
      .map((item) => {
        let observed;
        try {
          observed = BigInt(String(item.observed_allowance_atomic));
        } catch (_error) {
          throw new Error("Observed allowance amount is invalid");
        }
        if (observed < 0n) {
          throw new Error("Observed allowance amount is invalid");
        }
        return {
          asset_allowance_id: item.asset_allowance_id,
          network: item.network,
          token_address: canonicalAddress(item.token_address),
          spender_address: canonicalAddress(item.spender_address),
          observed_allowance_atomic: String(observed)
        };
      })
      .filter((item) => item.observed_allowance_atomic !== "0");
    const plan = persistWalletDisconnectPlan({
      operation: "disconnect",
      wallet_identity_id: identity.wallet_identity_id,
      wallet_address: canonicalAddress(identity.wallet_address),
      provider_uuid: selection.uuid,
      core_disconnected: false,
      allowances_cleared: false,
      allowances
    });
    return {plan, selection};
  };

  const selectedWalletForDisconnectPlan = (plan) => {
    try {
      const selection = selectedWalletSnapshot();
      if (
        selection.uuid !== plan.provider_uuid ||
        selection.address !== plan.wallet_address
      ) {
        return null;
      }
      return selection;
    } catch (_error) {
      return null;
    }
  };

  const loadWalletDisconnectState = async (plan) => {
    const state = await request(
      `/wallet-identities/${plan.wallet_identity_id}/disconnect-state`
    );
    const identity = state?.wallet_identity;
    if (
      !identity ||
      typeof state.disconnect_complete !== "boolean" ||
      canonicalAccountObjectId(
        identity.wallet_identity_id,
        "Wallet disconnect identity"
      ) !== plan.wallet_identity_id ||
      canonicalAddress(identity.wallet_address) !== plan.wallet_address ||
      !["active", "suspended", "revoked"].includes(identity.status)
    ) {
      throw new Error("Core returned a different wallet disconnect identity");
    }
    if (
      !Array.isArray(state.asset_allowances) ||
      !state.approval_targets ||
      typeof state.approval_targets !== "object" ||
      Array.isArray(state.approval_targets) ||
      !isValidNetworkConfigs(state.network_configs)
    ) {
      throw new Error("Core returned invalid wallet disconnect state");
    }
    const approvalTargets = {};
    const allowances = state.asset_allowances
      .map((item) => {
        if (
          canonicalAccountObjectId(
            item.wallet_identity_id,
            "Allowance wallet identity"
          ) !== plan.wallet_identity_id
        ) {
          throw new Error(
            "Core returned an allowance for a different wallet"
          );
        }
        const allowance = validateWalletDisconnectAllowance({
          asset_allowance_id: item.asset_allowance_id,
          network: item.network,
          token_address: item.token_address,
          spender_address: item.spender_address,
          observed_allowance_atomic: String(
            item.observed_allowance_atomic
          )
        });
        if (!hasConfiguredNetwork(state, allowance.network)) {
          throw new Error("Core returned an allowance for an unsupported network");
        }
        const target = state.approval_targets[allowance.network];
        if (
          !target ||
          canonicalAddress(target.token_address) !==
            allowance.token_address ||
          canonicalAddress(target.spender_address) !==
            allowance.spender_address
        ) {
          throw new Error("Core returned an unsupported allowance target");
        }
        approvalTargets[allowance.network] = Object.freeze({
          token_address: allowance.token_address,
          spender_address: allowance.spender_address
        });
        return allowance;
      })
      .sort((left, right) => left.network.localeCompare(right.network));
    if (
      new Set(allowances.map((item) => item.network)).size !==
      allowances.length
    ) {
      throw new Error("Core returned duplicate wallet allowances");
    }
    walletDisconnectApprovalTargets = Object.freeze(approvalTargets);
    walletDisconnectNetworkConfigs = Object.freeze({
      ...state.network_configs
    });
    walletDisconnectIdentityStatus = identity.status;
    walletDisconnectServerComplete = state.disconnect_complete;
    return validateWalletDisconnectPlan({
      ...plan,
      allowances
    });
  };

  const fullyDisconnectWallet = (walletIdentityId) => {
    if (fullWalletDisconnectOperation) {
      return fullWalletDisconnectOperation;
    }
    let workingPlan = null;
    const runDisconnect = async () => {
      let selection = null;
      let coreWasAlreadyDisconnected = false;
      try {
        if (pendingWalletDisconnect) {
          if (
            pendingWalletDisconnect.wallet_identity_id !== walletIdentityId
          ) {
            throw new Error("Another wallet disconnect is already pending");
          }
          workingPlan = pendingWalletDisconnect;
          selection = selectedWalletForDisconnectPlan(workingPlan);
          workingPlan = await loadWalletDisconnectState(workingPlan);
          if (
            walletDisconnectIdentityStatus === "revoked" &&
            walletDisconnectServerComplete
          ) {
            workingPlan = validateWalletDisconnectPlan({
              ...workingPlan,
              core_disconnected: true,
              allowances_cleared: true
            });
          }
          persistWalletDisconnectPlan(workingPlan);
        } else {
          const created = createWalletDisconnectPlan(walletIdentityId);
          workingPlan = created.plan;
          selection = created.selection;
          workingPlan = await loadWalletDisconnectState(workingPlan);
          if (
            walletDisconnectIdentityStatus === "revoked" &&
            walletDisconnectServerComplete
          ) {
            workingPlan = validateWalletDisconnectPlan({
              ...workingPlan,
              core_disconnected: true,
              allowances_cleared: true
            });
          }
          persistWalletDisconnectPlan(workingPlan);
        }

        coreWasAlreadyDisconnected = workingPlan.core_disconnected;
        if (
          workingPlan.core_disconnected &&
          workingPlan.allowances_cleared
        ) {
          clearWalletDisconnectPlan(workingPlan);
          invalidateWalletSelection(
            "Clink signed out. Choose a wallet to start a new login."
          );
          await loadState();
          status.textContent =
            "Clink signed out. Core permissions and known chain allowances are revoked. To remove site access too, disconnect Clink in your wallet extension.";
          status.classList.toggle("error", false);
          return;
        }

        if (!workingPlan.core_disconnected) {
          if (!selection) {
            throw new Error(
              "Choose the same wallet and address before disconnecting Core access."
            );
          }
          await providerAccountsContainSelection(selection);
          await request(
            `/wallet-identities/${workingPlan.wallet_identity_id}/prepare-disconnect`,
            {method: "POST", body: "{}"}
          );
        }

        workingPlan = await loadWalletDisconnectState(workingPlan);
        persistWalletDisconnectPlan(workingPlan);

        const remaining = [];
        for (const allowance of workingPlan.allowances) {
          const context = {
            ...allowance,
            wallet_identity_id: workingPlan.wallet_identity_id,
            wallet_address: workingPlan.wallet_address
          };
          const refreshed = await refreshAllowanceRevocationState(context);
          if (
            String(refreshed.observed_allowance_atomic) !== "0" ||
            refreshed.status !== "revoked"
          ) {
            remaining.push({...context, refreshed});
          }
        }

        if (remaining.length) {
          selection =
            selection || selectedWalletForDisconnectPlan(workingPlan);
          if (!selection) {
            const networks = remaining
              .map((item) => item.network)
              .join(", ");
            throw new Error(
              `Choose the same wallet address to revoke ${networks} allowances.`
            );
          }
          for (const item of remaining) {
            await revokeAllowance(selection, {
              ...item,
              observed_allowance_atomic:
                item.refreshed.observed_allowance_atomic
            });
          }
        }

        workingPlan = validateWalletDisconnectPlan({
          ...workingPlan,
          allowances_cleared: true
        });
        persistWalletDisconnectPlan(workingPlan);

        if (!workingPlan.core_disconnected) {
          await request(
            `/wallet-identities/${workingPlan.wallet_identity_id}/disconnect`,
            {method: "POST", body: "{}"}
          );
          workingPlan = validateWalletDisconnectPlan({
            ...workingPlan,
            core_disconnected: true
          });
          persistWalletDisconnectPlan(workingPlan);
        }

        clearWalletDisconnectPlan(workingPlan);
        if (!coreWasAlreadyDisconnected) {
          invalidateWalletSelection(
            "Clink signed out. Choose a wallet to start a new login."
          );
        }
        await loadState();
        status.textContent = coreWasAlreadyDisconnected
          ? "Previous wallet cleanup completed. The current Clink login was not changed."
          : "Clink signed out. Core permissions and known chain allowances are revoked. To remove site access too, disconnect Clink in your wallet extension.";
        status.classList.toggle("error", false);
      } catch (error) {
        const message = workingPlan?.core_disconnected
          ? `Core access is revoked, but wallet disconnect is incomplete: ${error.message}`
          : error.message;
        status.textContent = message;
        status.classList.add("error");
        updateWalletDisconnectRecovery();
        throw new Error(message);
      }
    };
    const operation = (async () => {
      const lockManager = globalThis.navigator?.locks;
      if (!lockManager?.request) {
        throw new Error(
          "This browser cannot coordinate wallet unbind safely across tabs."
        );
      }
      return lockManager.request(
        `clink.wallet_disconnect.${walletIdentityId}`,
        {mode: "exclusive"},
        runDisconnect
      );
    })();
    fullWalletDisconnectOperation = operation;
    updateWalletDisconnectRecovery();
    return operation.finally(() => {
      if (fullWalletDisconnectOperation === operation) {
        fullWalletDisconnectOperation = null;
        updateWalletDisconnectRecovery();
      }
    });
  };

  const validateEmbeddedApprovalContext = (explicitContext, selection, network) => {
    if (!explicitContext) return null;
    if (!isEmbeddedView() || !explicitContext.expected || !explicitContext.plan) {
      throw new Error("Embedded approval context is required");
    }
    const expected = explicitContext.expected;
    const plan = validateEmbeddedPlan(explicitContext.plan);
    if (
      expected.network !== network ||
      plan.allowance.network !== network ||
      plan.allowance.status === "unknown" ||
      plan.allowance.status === "exhausted" ||
      (plan.allowance.status !== "insufficient" &&
        !(plan.allowance.status === "sufficient" && plan.allowance.exceeds_budget === true))
    ) {
      throw new Error("Approval plan changed. Review the current allowance advice again.");
    }
    let approvedAmount;
    let targetAmount;
    try {
      approvedAmount = BigInt(String(explicitContext.approvedAmountAtomic));
      targetAmount = BigInt(plan.allowance.target_atomic);
    } catch (_error) {
      throw new Error("Approval amount is invalid");
    }
    if (approvedAmount <= 0n || approvedAmount !== targetAmount) {
      throw new Error("Approval amount must equal the current finite target");
    }
    if (
      expected.wallet_identity_id !== plan.terms.wallet_identity_id ||
      expected.wallet_identity_id !== accountState?.current_spending_mandate?.wallet_identity_id ||
      expected.wallet_address !== plan.allowance.wallet_address ||
      expected.token_address !== plan.allowance.token_address ||
      expected.spender_address !== plan.allowance.spender_address ||
      expected.target_atomic !== plan.allowance.target_atomic
    ) {
      throw new Error("Approval plan no longer matches the current Core state");
    }
    if (selection.address !== expected.wallet_address) {
      throw new Error("Selected wallet does not match the approval owner");
    }
    const config = accountState?.network_configs?.[network];
    const target = accountState?.approval_targets?.[network];
    if (
      !config ||
      !target ||
      canonicalAddress(target.token_address) !== expected.token_address ||
      canonicalAddress(target.spender_address) !== expected.spender_address
    ) {
      throw new Error("Approval target changed. Review the current Core state again.");
    }
    return approvedAmount;
  };

  const preflightAllowance = async (
    selection,
    network,
    explicitContext = null,
    guard = () => {}
  ) => {
    guard();
    await providerAccountsContainSelection(selection, {bounded: true});
    guard();
    const beforeSwitch = allowanceContext(network, selection.address);
    const approvedAmount = validateEmbeddedApprovalContext(
      explicitContext,
      selection,
      network
    );
    await providerRequest(
      selection.provider,
      {
        method: "wallet_switchEthereumChain",
        params: [{chainId: beforeSwitch.chainId}]
      },
      {stage: "chain_confirmation"}
    );
    guard();
    assertWalletSnapshot(selection);
    const switchedChainId = await providerRequest(
      selection.provider,
      {method: "eth_chainId"},
      {stage: "chain_confirmation"}
    );
    guard();
    assertWalletSnapshot(selection);
    if (switchedChainId !== beforeSwitch.chainId) {
      throw new Error("Wallet did not switch to the required network");
    }
    await providerAccountsContainSelection(selection, {bounded: true});
    guard();
    const afterSwitch = allowanceContext(network, selection.address);
    if (afterSwitch.identity.wallet_identity_id !== beforeSwitch.identity.wallet_identity_id) {
      throw new Error("Selected wallet does not match the bound wallet");
    }
    return {
      ...afterSwitch,
      amount: approvedAmount ?? afterSwitch.amount,
      from: selection.address,
      network
    };
  };

  const allowanceRequestKey = () => {
    const cryptoApi = globalThis.crypto || window.crypto;
    if (!cryptoApi?.getRandomValues) {
      throw new Error("This browser cannot create a safe allowance recovery key; no transaction was sent.");
    }
    const bytes = new Uint8Array(32);
    cryptoApi.getRandomValues(bytes);
    return [...bytes].map((byte) => byte.toString(16).padStart(2, "0")).join("");
  };

  const allowanceAttemptRecord = (value) => {
    const record = validateAllowanceRecoveryRecord(value);
    if (!record.allowance_tx_hash && !["awaiting_wallet", "rejected"].includes(record.status)) {
      throw new Error("Core returned an invalid allowance attempt state");
    }
    return record;
  };

  const allowanceAttemptContextFromPreflight = (preflight, network) => ({
    attempt_id: null,
    wallet_identity_id: preflight.identity.wallet_identity_id,
    network,
    token_address: preflight.token,
    spender_address: preflight.spender,
    amount_atomic: preflight.amount.toString(),
    request_key: allowanceRequestKey(),
    status: "prepare_pending"
  });

  const validateAllowanceAttemptScope = (record, context) => {
    if (
      record.wallet_identity_id !== context.wallet_identity_id ||
      record.network !== context.network ||
      record.token_address !== context.token_address ||
      record.spender_address !== context.spender_address ||
      record.amount_atomic !== context.amount_atomic
    ) {
      throw new Error("Core returned an allowance attempt for a different target or amount");
    }
    return record;
  };

  const beginAllowanceAttempt = async (context, guard) => {
    const prepared = persistAllowanceAttemptContext(context);
    guard();
    let response;
    try {
      response = await request("/allowances/attempts", {
        method: "POST",
        body: JSON.stringify({
          wallet_identity_id: prepared.wallet_identity_id,
          network: prepared.network,
          token_address: prepared.token_address,
          spender_address: prepared.spender_address,
          amount_atomic: prepared.amount_atomic,
          request_key: prepared.request_key
        })
      });
    } catch (error) {
      if (!error?.accountSessionExpired) {
        setAllowanceRecoveryBlock(ALLOWANCE_PREPARE_UNCERTAIN_MESSAGE);
      }
      throw error;
    }
    if (!exactObjectKeys(response, ["created", "attempt"]) ||
        typeof response.created !== "boolean") {
      setAllowanceRecoveryBlock(ALLOWANCE_PREPARE_UNCERTAIN_MESSAGE);
      throw new Error("Core returned an invalid allowance preparation response");
    }
    let record;
    try {
      record = allowanceAttemptRecord(response.attempt);
      validateAllowanceAttemptScope(record, prepared);
    } catch (error) {
      setAllowanceRecoveryBlock(ALLOWANCE_PREPARE_UNCERTAIN_MESSAGE);
      throw error;
    }
    const next = validateAllowanceAttemptContext({
      ...prepared,
      attempt_id: record.attempt_id,
      status: record.allowance_tx_hash ? "pending" : "awaiting_wallet"
    });
    persistAllowanceAttemptContext(next);
    if (!response.created) {
      if (record.allowance_tx_hash) {
        persistPendingAllowance({
          wallet_identity_id: record.wallet_identity_id,
          network: record.network,
          token_address: record.token_address,
          spender_address: record.spender_address,
          allowance_tx_hash: record.allowance_tx_hash
        });
      }
      setAllowanceRecoveryBlock(
        record.allowance_tx_hash
          ? "Core already has a submitted allowance transaction for this wallet. Verify its hash; no new transaction will be sent."
          : "Core is already waiting for the original wallet approval outcome. Do not approve again; check authorization status first."
      );
    }
    return {created: response.created, attempt: record, context: next};
  };

  const submitAllowanceAttempt = async (context, allowanceTxHash) => {
    const prepared = validateAllowanceAttemptContext({
      ...context,
      status: "awaiting_wallet"
    });
    if (!prepared.attempt_id) {
      throw new Error("Allowance attempt is not prepared; no transaction will be sent");
    }
    let record;
    try {
      record = allowanceAttemptRecord(await request(
        `/allowances/attempts/${encodeURIComponent(prepared.attempt_id)}/submitted`,
        {
          method: "POST",
          body: JSON.stringify({
            request_key: prepared.request_key,
            allowance_tx_hash: canonicalTransactionHash(allowanceTxHash)
          })
        }
      ));
      validateAllowanceAttemptScope(record, prepared);
      if (record.allowance_tx_hash !== canonicalTransactionHash(allowanceTxHash)) {
        throw new Error("Core returned a different submitted allowance hash");
      }
    } catch (error) {
      if ((error?.httpStatus ?? error?.statusCode) === 503) {
        setAllowanceRecoveryBlock(
          "Core could not record the submitted allowance hash yet. Keep this page open and retry status with the same hash; do not approve again."
        );
      } else if (!error?.accountSessionExpired) {
        setAllowanceRecoveryBlock(
          "Core could not attach the submitted allowance hash. Keep the transaction evidence unchanged and do not approve again."
        );
      }
      throw error;
    }
    const next = validateAllowanceAttemptContext({
      ...prepared,
      status: "pending"
    });
    persistAllowanceAttemptContext(next);
    return record;
  };

  const rejectAllowanceAttempt = async (context) => {
    const prepared = validateAllowanceAttemptContext({
      ...context,
      status: "awaiting_wallet"
    });
    if (!prepared.attempt_id) return false;
    let record;
    try {
      record = allowanceAttemptRecord(await request(
        `/allowances/attempts/${encodeURIComponent(prepared.attempt_id)}/rejected`,
        {
          method: "POST",
          body: JSON.stringify({request_key: prepared.request_key})
        }
      ));
      validateAllowanceAttemptScope(record, prepared);
      if (record.status !== "rejected" || record.allowance_tx_hash !== null) {
        throw new Error("Core did not confirm a rejected allowance attempt");
      }
    } catch (error) {
      if (error?.accountSessionExpired) throw error;
      return false;
    }
    return clearAllowanceAttemptContext(prepared);
  };

  const approve = async (network, explicitContext = null) => {
    const operation = acquireAllowanceOperation(false);
    try {
      const guard = explicitContext?.guard || (() => {});
      const allowanceSendGuard = () => {
        guard();
        if (allowanceSessionExpired) {
          throw new Error(ACCOUNT_SESSION_EXPIRED_MESSAGE);
        }
      };
      allowanceSendGuard();
      const selection = selectedWalletSnapshot();
      const initialIdentity = selectedWalletIdentity(selection);
      validateEmbeddedApprovalContext(explicitContext, selection, network);
      assertAllowanceRecoveryStorageReadyForSend(
        initialIdentity.wallet_identity_id
      );
      const {amount, chainId, confirmations, from, identity, spender, token} =
        await preflightAllowance(
          selection,
          network,
          explicitContext,
          allowanceSendGuard
        );
      allowanceSendGuard();
      if (identity.wallet_identity_id !== initialIdentity.wallet_identity_id) {
        throw new Error("Selected wallet does not match the bound wallet");
      }
      validateEmbeddedApprovalContext(explicitContext, selection, network);
      const attemptContext = allowanceAttemptContextFromPreflight(
        {amount, identity, spender, token},
        network
      );
      const preparedAttempt = await beginAllowanceAttempt(
        attemptContext,
        allowanceSendGuard
      );
      operation.attemptContext = preparedAttempt.context;
      if (explicitContext?.expected) {
        explicitContext.expected.attemptContext = operation.attemptContext;
      }
      explicitContext?.onAttemptPrepared?.(operation.attemptContext);
      allowanceSendGuard();
      assertWalletSnapshot(selection);
      const currentIdentity = selectedWalletIdentity(selection);
      if (
        currentIdentity.wallet_identity_id !== identity.wallet_identity_id ||
        canonicalAddress(currentIdentity.wallet_address) !== selection.address
      ) {
        throw new Error("Selected wallet changed before allowance submission");
      }
      if (!preparedAttempt.created) return;
      const data = `0x095ea7b3${spender.slice(2).padStart(64, "0")}${amount.toString(16).padStart(64, "0")}`;
      assertWalletSnapshot(selection);
      const sendChainId = await providerRequest(
        selection.provider,
        {method: "eth_chainId"},
        {stage: "chain_confirmation"}
      );
      allowanceSendGuard();
      assertWalletSnapshot(selection);
      if (sendChainId !== chainId) {
        throw new Error("Wallet network changed before transaction submission");
      }
      allowanceSendGuard();
      assertAllowanceRecoveryStorageReadyForSend(identity.wallet_identity_id, {
        allowAttempt: true
      });
      allowanceSendGuard();
      operation.sendStarted = true;
      explicitContext?.onBroadcast?.();
      let transactionHash;
      try {
        operation.walletRequestPending = true;
        transactionHash = await providerRequest(
          selection.provider,
          {
            method: "eth_sendTransaction",
            params: [{from, to: token, data, chainId}]
          },
          {stage: "wallet_confirmation"}
        );
      } catch (error) {
        if (error?.code === 4001 || error?.userRejected) {
          const rejected = await rejectAllowanceAttempt(operation.attemptContext);
          if (rejected) {
            allowanceSendGuard();
            operation.sendStarted = false;
            explicitContext?.onRejected?.();
            throw error;
          }
        }
        persistAllowancePostSendUncertain(identity.wallet_identity_id);
        if (error?.providerTimeout && error.pendingRequest) {
          const lateRequest = retainLateAllowanceHash(error.pendingRequest, {
            wallet_identity_id: identity.wallet_identity_id,
            network,
            token_address: token,
            spender_address: spender,
            attemptContext: operation.attemptContext,
            selection,
            operation
          }, {
            onUserRejected: explicitContext?.onUserRejected || (async () => {
              const rejected = await rejectAllowanceAttempt(operation.attemptContext);
              if (!rejected || !clearAllowancePostSendUncertain(identity.wallet_identity_id)) {
                throw new Error("Allowance rejection could not be acknowledged safely");
              }
              operation.sendStarted = false;
            })
          });
          allowanceLateWalletRequests.set(identity.wallet_identity_id, lateRequest);
          void lateRequest.finally(() => {
            if (allowanceLateWalletRequests.get(identity.wallet_identity_id) === lateRequest) {
              allowanceLateWalletRequests.delete(identity.wallet_identity_id);
            }
          });
        }
        const safe = new Error(
          `${ALLOWANCE_POST_SEND_UNCERTAIN_MESSAGE} ${error?.message || "Wallet confirmation did not return a definitive result."}`
        );
        safe.allowanceUnknown = true;
        safe.providerStage = "submission_unknown";
        safe.providerClass = error?.providerClass || "provider_error";
        safe.providerCode = error?.providerCode ?? null;
        safe.code = error?.code ?? null;
        safe.pendingRequest = error?.pendingRequest;
        safe.providerTimeout = Boolean(error?.providerTimeout);
        throw safe;
      } finally {
        operation.walletRequestPending = false;
      }
      let canonicalHash;
      try {
        canonicalHash = canonicalTransactionHash(transactionHash);
      } catch (_error) {
        persistAllowancePostSendUncertain(identity.wallet_identity_id);
        const safe = new Error(
          `${ALLOWANCE_POST_SEND_UNCERTAIN_MESSAGE} Wallet returned an invalid transaction result; keep this page open and verify the submitted hash in Core.`
        );
        safe.allowanceUnknown = true;
        safe.providerStage = "submission_unknown";
        safe.providerClass = "invalid_result";
        safe.providerCode = null;
        safe.code = null;
        throw safe;
      }
      const submitted = persistPendingAllowance({
        wallet_identity_id: identity.wallet_identity_id,
        network,
        token_address: token,
        spender_address: spender,
        allowance_tx_hash: canonicalHash
      });
      try {
        await submitAllowanceAttempt(operation.attemptContext, canonicalHash);
      } catch (error) {
        const safe = new Error(
          `${ALLOWANCE_POST_SEND_UNCERTAIN_MESSAGE} ${error?.message || "Core could not attach the submitted hash; verify it before retrying."}`
        );
        safe.allowanceUnknown = true;
        safe.providerStage = "core_verification";
        safe.providerClass = "attempt_attach_failed";
        safe.providerCode = error?.providerCode ?? null;
        safe.code = error?.code ?? null;
        safe.httpStatus = error?.httpStatus ?? error?.statusCode ?? null;
        throw safe;
      }
      try {
        await waitForConfirmations(
          selection.provider,
          submitted.allowance_tx_hash,
          confirmations,
          {bounded: true}
        );
      } catch (_error) {
        status.textContent = "Wallet receipt confirmation was unavailable. Core is verifying the submitted transaction.";
      }
      await verifyPendingAllowance(submitted);
    } finally {
      releaseAllowanceOperation(operation);
    }
  };

  const attachPendingAllowanceAttempt = async (record) => {
    const context = allowanceAttemptContexts.get(record.wallet_identity_id);
    if (!context) return null;
    if (
      record.wallet_identity_id !== context.wallet_identity_id ||
      !allowanceAttemptMatchesScope(context, {
        ...context,
        network: record.network,
        token_address: record.token_address,
        spender_address: record.spender_address,
        amount_atomic: context.amount_atomic
      })
    ) {
      throw new Error("Allowance attempt context conflicts with the submitted transaction");
    }
    if (context.status === "pending") return context;
    if (!context.attempt_id) {
      setAllowanceRecoveryBlock(ALLOWANCE_PREPARE_UNCERTAIN_MESSAGE);
      throw new Error(ALLOWANCE_PREPARE_UNCERTAIN_MESSAGE);
    }
    await submitAllowanceAttempt(context, record.allowance_tx_hash);
    return allowanceAttemptContexts.get(record.wallet_identity_id) || null;
  };

  const allowanceMismatchError = (record, recoveryError = null) => {
    const safe = new Error(
      `${allowanceMismatchSummary(record)} This is a terminal transaction result, not a successful allowance approval.`
    );
    safe.httpStatus = 409;
    safe.statusCode = 409;
    safe.code = "allowance_amount_mismatch";
    safe.allowanceMismatch = record;
    if (recoveryError) safe.recoveryError = true;
    return safe;
  };

  const handleAllowanceAmountMismatch = async (error) => {
    const record = error?.allowanceMismatch;
    if (!record) return;
    try {
      const refreshed = await loadState();
      if (!refreshed) {
        throw new Error("Account state could not be refreshed");
      }
      const visible = allowanceRecoveryRecords.some((candidate) =>
        candidate.status === "confirmed_mismatch" &&
        candidate.attempt_id === record.attempt_id &&
        candidate.wallet_identity_id === record.wallet_identity_id &&
        candidate.network === record.network &&
        candidate.token_address === record.token_address &&
        candidate.spender_address === record.spender_address &&
        candidate.amount_atomic === record.amount_atomic &&
        candidate.allowance_tx_hash === record.allowance_tx_hash
      );
      if (!visible) throw new Error("Refreshed account state omitted the mismatch evidence");
      if (allowanceRecoveryBlocked) {
        throw new Error(allowanceRecoveryMessage || "Allowance mismatch recovery remains blocked");
      }
    } catch (recoveryError) {
      if (!allowanceRecoveryBlocked) {
        setAllowanceRecoveryBlock(
          `${allowanceMismatchSummary(record)} The terminal result was received, but local recovery could not be reconciled safely. Keep all recovery records unchanged and contact support.`
        );
      }
      const safe = allowanceMismatchError(record, recoveryError);
      safe.message = allowanceRecoveryBlocked
        ? `${allowanceMismatchSummary(record)} ${allowanceRecoveryMessage}`
        : safe.message;
      setAccountStage("core_verification", safe.message);
      throw safe;
    }
    setAccountStage("core_verification", allowanceMismatchSummary(record));
    throw allowanceMismatchError(record);
  };

  const verifyPendingAllowance = async (submitted, {automatic = false} = {}) => {
    const record = validatePendingAllowance(submitted);
    if (!automatic) cancelAllowanceVerificationRetry();
    setAccountStage(
      "core_verification",
      `Core is verifying the submitted allowance transaction ${record.allowance_tx_hash}. No transaction will be sent.`
    );
    try {
      await attachPendingAllowanceAttempt(record);
      await request("/allowances/verify", {
        method: "POST",
        body: JSON.stringify(record)
      });
    } catch (error) {
      const httpStatus = error?.httpStatus ?? error?.statusCode ?? null;
      if (error?.allowanceMismatch) {
        await handleAllowanceAmountMismatch(error);
      }
      if (httpStatus === 503) {
        const safe = new Error(
          "Core verification is temporarily unavailable (HTTP 503). The submitted hash is retained and will be checked again automatically; no transaction will be sent."
        );
        safe.httpStatus = httpStatus;
        if (!automatic && opcSetupView?.()) scheduleAllowanceVerificationRetry(record);
        setAccountStage("core_verification", safe.message);
        throw safe;
      }
      if (error?.accountSessionExpired || httpStatus === 410) {
        const safe = new Error(ACCOUNT_SESSION_EXPIRED_MESSAGE);
        safe.httpStatus = httpStatus;
        safe.accountSessionExpired = true;
        markAccountSessionExpired();
        setAccountStage("core_verification", safe.message);
        throw safe;
      }
      if (httpStatus === 400 || httpStatus === 401) {
        const safe = new Error(
          `Core could not verify the submitted allowance hash (HTTP ${httpStatus}). The hash is retained; do not resend the transaction.`
        );
        safe.httpStatus = httpStatus;
        setAllowanceRecoveryBlock(safe.message);
        setAccountStage("core_verification", safe.message);
        throw safe;
      }
      const safe = new Error(
        "Core could not verify the submitted allowance hash. The hash is retained; do not resend the transaction."
      );
      safe.httpStatus = httpStatus;
      setAccountStage("core_verification", safe.message);
      throw safe;
    }
    clearPendingAllowance(record);
    const attempt = allowanceAttemptContexts.get(record.wallet_identity_id);
    if (attempt &&
        attempt.network === record.network &&
        attempt.token_address === record.token_address &&
        attempt.spender_address === record.spender_address &&
        attempt.status === "pending") {
      clearAllowanceAttemptContext(attempt);
    }
    await loadState();
  };

  const recoverPendingAllowance = async () => {
    const operation = acquireAllowanceOperation(true);
    try {
      if (!pendingAllowance) {
        throw new Error("No submitted allowance is waiting for verification");
      }
      const submitted = pendingAllowance;
      await verifyPendingAllowance(submitted, {automatic: false});
    } finally {
      releaseAllowanceOperation(operation);
    }
  };

  const cancelEmbeddedReview = () => {
    const operation = embeddedOperation;
    if (operation) operation.cancelled = true;
    embeddedGeneration += 1;
    const allowanceSubmitted = Boolean(
      embeddedApprovalReview?.broadcastStarted
    );
    const grantSubmitted = Boolean(operation?.grantPostStarted);
    const signatureStarted = Boolean(operation?.signatureStarted);
    const message = allowanceSubmitted || grantSubmitted
      ? "Cancellation requested after a wallet transaction may have been submitted. Query Core before retrying; do not resend."
      : signatureStarted
        ? "Wallet signature was in progress. The signed grant was not posted; review current Core state before retrying."
        : "authorization review cancelled. No signature or chain transaction was sent.";
    clearEmbeddedReview(message);
    $("#embedded-state").textContent = "Cancelled";
  };

  const embeddedReviewGuard = (operation, plan) => {
    embeddedOperationGuard(operation);
    if (
      embeddedPlan !== plan ||
      embeddedPlanGeneration !== embeddedGeneration
    ) {
      throw new Error("authorization review expired. Review the current terms again.");
    }
  };

  const beginEmbeddedApprovalReview = () => {
    const plan = embeddedPlan;
    if (!plan || embeddedPlanGeneration !== embeddedGeneration) {
      throw new Error("Review the current authorization plan before approving an allowance");
    }
    if (
      plan.action === "sign" ||
      !["insufficient", "sufficient"].includes(plan.allowance.status) ||
      plan.allowance.target_atomic === "0" ||
      (plan.allowance.status === "sufficient" && plan.allowance.exceeds_budget !== true)
    ) {
      throw new Error("The current allowance advice does not require an approval transaction");
    }
    embeddedApprovalReview = {
      plan,
      generation: embeddedGeneration,
      broadcastStarted: false
    };
    $("#embedded-approval-confirm").hidden = false;
    $("#embedded-approval-confirm-text").textContent = plan.allowance.exceeds_budget
      ? `This shared ${plan.allowance.network} allowance will be adjusted to exactly ${plan.allowance.target_usdc} USDC for the current unspent Core budget. Other businesses using the same wallet, token, and spender may be affected.`
      : `Confirm one finite ${plan.allowance.target_usdc} USDC allowance for ${plan.allowance.network}. This is a separate wallet transaction and may require gas.`;
  };

  const sameEmbeddedAllowanceTuple = (left, right) => Boolean(
    left && right &&
    left.network === right.network &&
    left.token_address.toLowerCase() === right.token_address.toLowerCase() &&
    left.spender_address.toLowerCase() === right.spender_address.toLowerCase() &&
    left.wallet_address.toLowerCase() === right.wallet_address.toLowerCase() &&
    left.target_atomic === right.target_atomic
  );

  const confirmEmbeddedApproval = async () => {
    const review = embeddedApprovalReview;
    if (!review || review.generation !== embeddedGeneration) {
      throw new Error("Approval review expired. Query the current allowance again.");
    }
    let operation;
    try {
      operation = beginEmbeddedOperation();
    } catch (error) {
      status.textContent = error.message;
      status.classList.add("error");
      return;
    }
    let broadcastStarted = false;
    try {
      embeddedOperationGuard(operation);
      const selection = selectedWalletSnapshot();
      await providerAccountsContainSelection(selection);
      embeddedOperationGuard(operation);
      await loadState();
      embeddedOperationGuard(operation);
      const fresh = await embeddedPlanRequest(operation, {render: false});
      if (!sameEmbeddedAllowanceTuple(review.plan.allowance, fresh.allowance)) {
        throw new Error("Approval plan changed. Review the current exact amount again.");
      }
      const expected = {
        wallet_identity_id: fresh.terms.wallet_identity_id,
        wallet_address: fresh.allowance.wallet_address.toLowerCase(),
        network: fresh.allowance.network,
        token_address: fresh.allowance.token_address.toLowerCase(),
        spender_address: fresh.allowance.spender_address.toLowerCase(),
        target_atomic: fresh.allowance.target_atomic
      };
      await approve(fresh.allowance.network, {
        approvedAmountAtomic: fresh.allowance.target_atomic,
        expected,
        plan: fresh,
        guard: () => embeddedOperationGuard(operation),
        onBroadcast: () => {
          broadcastStarted = true;
          if (embeddedApprovalReview === review) {
            embeddedApprovalReview.broadcastStarted = true;
          }
        }
      });
      if (broadcastStarted && operation.cancelled) {
        status.textContent = "The allowance transaction may already have been submitted. Query Core before retrying; do not resend it.";
        status.classList.add("error");
        return;
      }
      embeddedOperationGuard(operation);
      const refreshed = await embeddedPlanRequest(operation);
      if (
        refreshed.allowance.status !== "sufficient" ||
        refreshed.allowance.observed_atomic !== fresh.allowance.target_atomic
      ) {
        throw new Error("Core has not verified the exact allowance target. Refresh and query again; no success is shown.");
      }
      $("#embedded-approval-confirm").hidden = true;
      embeddedApprovalReview = null;
      status.textContent = "Exact finite chain allowance verified by Core. The authorization remains separate from purchasing and funding.";
      status.classList.toggle("error", false);
    } catch (error) {
      status.textContent = operation.cancelled
        ? broadcastStarted
          ? "The allowance transaction may already have been submitted. Query Core before retrying; do not resend it."
          : "Allowance approval cancelled before broadcast. No chain transaction was sent; review the current allowance again before retrying."
        : error.message;
      status.classList.add("error");
    } finally {
      endEmbeddedOperation(operation);
    }
  };

  const submitEmbeddedPlan = async () => {
    if (embeddedOperation) {
      status.textContent = "An embedded authorization operation is already in progress";
      status.classList.add("error");
      return;
    }
    const operation = beginEmbeddedOperation();
    const button = $("#embedded-permission-submit");
    if (button) button.disabled = true;
    try {
      if (embeddedRefreshRequired) {
        await loadState();
        embeddedOperationGuard(operation);
        embeddedRefreshRequired = false;
      }
      await embeddedPlanRequest(operation);
      status.textContent = "Review the exact Core terms and choose whether to continue.";
      status.classList.toggle("error", false);
    } catch (error) {
      clearEmbeddedReview();
      status.textContent = error.message;
      status.classList.add("error");
    } finally {
      endEmbeddedOperation(operation);
      if (button) button.disabled = false;
    }
  };

  const confirmEmbeddedPlan = async () => {
    const plan = embeddedPlan;
    if (!plan || embeddedPlanGeneration !== embeddedGeneration) {
      status.textContent = "authorization review expired. Query the current terms again.";
      status.classList.add("error");
      return;
    }
    if (plan.action !== "sign") return;
    let operation;
    try {
      operation = beginEmbeddedOperation();
    } catch (error) {
      status.textContent = error.message;
      status.classList.add("error");
      return;
    }
    const guard = () => embeddedReviewGuard(operation, plan);
    guard.callbacks = {
      onSignatureRequest: () => {
        operation.signatureStarted = true;
      },
      onGrantSubmit: () => {
        operation.grantPostStarted = true;
      }
    };
    try {
      const selection = selectedWalletSnapshot();
      await providerAccountsContainSelection(selection);
      const identity = selectedWalletIdentity(selection);
      if (identity.wallet_identity_id !== plan.terms.wallet_identity_id) {
        throw new Error("Selected wallet does not match the authorization plan");
      }
      await submitSignedGrant(plan.terms, selection, guard);
      guard();
      await loadState();
      guard();
      await embeddedPlanRequest(operation);
      status.textContent = "Spending Mandate updated. Review the fresh allowance advice before any chain approval.";
      status.classList.toggle("error", false);
    } catch (error) {
      if (operation.grantPostStarted) {
        const message = "Signed grant submission may have succeeded. Refresh and query the current Core authorization before retrying; do not sign or resend the old terms.";
        embeddedGeneration += 1;
        clearEmbeddedReview(message);
        embeddedRefreshRequired = true;
        const submitButton = $("#embedded-permission-submit");
        if (submitButton) submitButton.textContent = "Refresh and review authorization";
        status.textContent = message;
      } else if (operation.cancelled) {
        status.textContent = operation.signatureStarted
          ? "Wallet signature was cancelled before the signed grant was posted. Review current Core state before retrying."
          : "authorization review cancelled. No signature or chain transaction was sent.";
      } else {
        status.textContent = error.message;
      }
      status.classList.add("error");
    } finally {
      endEmbeddedOperation(operation);
    }
  };

  const retryEmbeddedPlan = async () => {
    if (embeddedOperation) return;
    const operation = beginEmbeddedOperation();
    const button = $("#embedded-plan-retry");
    if (button) button.disabled = true;
    try {
      await embeddedPlanRequest(operation);
      status.textContent = "Allowance observation refreshed. Review the current advice.";
      status.classList.toggle("error", false);
    } catch (error) {
      status.textContent = error.message;
      status.classList.add("error");
    } finally {
      endEmbeddedOperation(operation);
      if (button) button.disabled = false;
    }
  };

  if (isEmbeddedView()) {
    $("#embedded-permission-form")?.addEventListener("submit", async (event) => {
      event.preventDefault();
      await submitEmbeddedPlan();
    });
    ["#embedded-network", "#embedded-total-limit", "#embedded-hourly-limit", "#embedded-duration-days"].forEach((selector) => {
      const onInput = () => {
        invalidateEmbeddedContext("Inputs changed. Review authorization again.");
        if (selector === "#embedded-network") embeddedRevokeAllowanceForState(accountState);
      };
      $(selector)?.addEventListener("input", onInput);
      $(selector)?.addEventListener("change", onInput);
    });
    $("#embedded-plan-confirm")?.addEventListener("click", confirmEmbeddedPlan);
    $("#embedded-plan-cancel")?.addEventListener("click", cancelEmbeddedReview);
    $("#embedded-plan-retry")?.addEventListener("click", retryEmbeddedPlan);
    $("#embedded-approve")?.addEventListener("click", () => {
      try {
        beginEmbeddedApprovalReview();
      } catch (error) {
        status.textContent = error.message;
        status.classList.add("error");
      }
    });
    $("#embedded-approval-confirm-button")?.addEventListener("click", confirmEmbeddedApproval);
    $("#embedded-approval-cancel")?.addEventListener("click", cancelEmbeddedReview);
    $("#embedded-revoke-spending")?.addEventListener("click", async (event) => {
      const button = event.currentTarget;
      const mandate = accountState?.current_spending_mandate;
      const grantId = mandate?.spending_grant_id;
      if (!grantId || embeddedOperation) return;
      const clearAllowance = Boolean($("#embedded-revoke-allowance")?.checked);
      let selection = null;
      let allowances = [];
      try {
        if (clearAllowance) {
          selection = selectedWalletSnapshot();
          const identity = selectedWalletIdentity(selection);
          if (identity.wallet_identity_id !== mandate.wallet_identity_id) {
            throw new Error("Selected wallet does not match the spending mandate");
          }
          const allowance = embeddedRevokeAllowanceForState(accountState);
          if (!allowance) {
            throw new Error("No active known allowance matches the selected network target");
          }
          allowances = [allowance];
        }
      } catch (error) {
        status.textContent = error.message;
        status.classList.add("error");
        return;
      }
      let operation;
      try {
        operation = beginEmbeddedOperation();
      } catch (error) {
        status.textContent = error.message;
        status.classList.add("error");
        return;
      }
      button.disabled = true;
      let coreRevoked = false;
      try {
        await request(`/grants/${encodeURIComponent(grantId)}/revoke`, {
          method: "POST",
          body: "{}"
        });
        coreRevoked = true;
        if (clearAllowance) {
          embeddedOperationGuard(operation);
          for (const allowance of allowances) {
            await revokeAllowance(selection, allowance, () => embeddedOperationGuard(operation));
          }
        }
        await loadState();
        status.textContent = clearAllowance
          ? "Spending revoked in Core and each selected known chain allowance was verified at zero. This does not stop the runtime."
          : "Spending revoked in Core. This does not stop the runtime; any known chain allowance remains a separate shared wallet control.";
        status.classList.toggle("error", false);
      } catch (error) {
        const message = coreRevoked
          ? `Spending was revoked in Core, but chain allowance cleanup is incomplete: ${error.message} Query Core and chain state before retrying; do not assume the allowance is cleared.`
          : `Core spending revocation may be incomplete: ${error.message} Refresh the account before retrying.`;
        status.textContent = message;
        status.classList.add("error");
        if (coreRevoked) {
          embeddedRefreshRequired = true;
          restoreEmbeddedAllowanceRevokeRecovery(accountState);
        }
      } finally {
        endEmbeddedOperation(operation);
        button.disabled = false;
      }
    });
    $("#embedded-verify-pending-allowance")?.addEventListener("click", async (event) => {
      const button = event.currentTarget;
      button.disabled = true;
      try {
        if (embeddedAllowanceRevokeRecovery) {
          await recoverEmbeddedAllowanceRevocation();
        } else {
          await recoverPendingAllowance();
        }
      } catch (error) {
        status.textContent = error.message;
        status.classList.add("error");
      } finally {
        updatePendingAllowanceRecovery();
      }
    });
  }

  /* __OPC_SETUP_JS__ */

  $("#verify-pending-allowance").addEventListener("click", async (event) => {
    const button = event.currentTarget;
    button.disabled = true;
    try {
      await recoverPendingAllowance();
    } catch (error) {
      status.textContent = error.message;
      status.classList.add("error");
      updatePendingAllowanceRecovery();
    }
  });

  $("#refresh-allowances").addEventListener("click", async () => {
    try {
      if (allowanceSessionExpired) {
        throw new Error(ACCOUNT_SESSION_EXPIRED_MESSAGE);
      }
      if (!accountState || !Array.isArray(accountState.asset_allowances)) {
        throw new Error("Wallet authentication is required before refreshing allowances");
      }
      for (const item of accountState.asset_allowances) {
        await request(`/allowances/${item.asset_allowance_id}/refresh`, {method: "POST", body: "{}"});
      }
      await loadState();
    } catch (error) {
      status.textContent = error.message;
      status.classList.add("error");
    }
  });
  $("#refresh-audit").addEventListener("click", loadState);
  window.addEventListener("eip6963:announceProvider", announceWalletProvider);
  window.dispatchEvent(new Event("eip6963:requestProvider"));
  renderWalletProviders();
  renderWalletAccounts();
  updateWalletSelectionActions();
  loadState().catch((error) => {
    status.textContent = error.message;
    status.classList.add("error");
  });
})();
"""


ACCOUNT_CONSOLE_JS = ACCOUNT_CONSOLE_JS.replace(
    "  /* __OPC_SETUP_JS__ */",
    OPC_SETUP_JS.rstrip(),
    1,
)
