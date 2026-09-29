"""The isolated one-action OPC authorization component.

The account console is deliberately kept as a single page for ordinary and C
embedded sessions.  This module contains the small HTML/CSS/JS fragment that
is composed into that page for a server-resolved OPC browser session.  The
JavaScript is inserted inside the existing account-console closure so it can
reuse the wallet, Core, and allowance guards that already protect the regular
console.
"""

from __future__ import annotations


OPC_SETUP_HTML = r"""
    <div id="opc-setup" data-opc-setup-component hidden role="region" aria-labelledby="opc-setup-heading">
      <div class="opc-setup-card">
        <div class="opc-setup-kicker">
          <span class="eyebrow">OPC / one-time setup</span>
          <span id="opc-setup-state" class="state">Review</span>
        </div>
        <h2 id="opc-setup-heading">Confirm spending authorization</h2>
        <p id="opc-setup-intro" class="opc-setup-intro">
          Set one spending boundary for this installed Clink device. Core will show the exact terms before any wallet signature.
        </p>
        <div id="opc-setup-device-summary" class="opc-setup-device-summary" aria-live="polite"></div>
        <form id="opc-setup-form" class="opc-setup-form">
          <div class="opc-setup-grid">
            <label>Network
              <select id="opc-setup-network" required></select>
            </label>
            <label>Total USDC
              <input id="opc-setup-total" inputmode="decimal" autocomplete="off" value="20" required>
            </label>
          </div>
          <p id="opc-setup-allowance-help" class="note">This amount is filled in for your wallet confirmation. No need to enter it again. If you change it in the wallet, Clink will show the actual on-chain amount; your spending budget will not be changed automatically.</p>
          <details id="opc-setup-limits" class="opc-setup-limits">
            <summary>Hourly limit and duration</summary>
            <div class="opc-setup-grid">
              <label>Rolling 1-hour USDC
                <input id="opc-setup-hourly" inputmode="decimal" autocomplete="off" value="5" required>
              </label>
              <label>Duration, days
                <input id="opc-setup-duration" inputmode="numeric" type="number" min="1" max="365" value="7" required>
              </label>
            </div>
          </details>
          <fieldset id="opc-setup-products" class="opc-setup-products">
            <legend>Allowed products</legend>
            <label>
              <input id="opc-setup-marketplace" name="products" type="checkbox" value="marketplace" checked>
              Service purchases
            </label>
            <label>
              <input id="opc-setup-transfers" name="products" type="checkbox" value="transfers">
              Direct-address transfers
            </label>
            <p class="note">Transfers send USDC to an exact address you review. They are separate from verified Marketplace merchants and share this grant's budget.</p>
          </fieldset>
          <div id="opc-setup-review" class="opc-setup-review" hidden aria-live="polite"></div>
          <button id="opc-setup-submit" class="primary-action" type="submit">Confirm spending authorization</button>
          <button id="opc-setup-cancel" class="row-action" type="button" hidden>Cancel</button>
        </form>
        <p id="opc-setup-status" class="note" role="status" aria-live="polite"></p>
        <div id="opc-setup-summary" class="ledger-list" aria-live="polite"></div>
        <details id="opc-setup-details" class="opc-setup-details">
          <summary>Technical details</summary>
          <div id="opc-setup-technical" class="ledger-list"></div>
        </details>
        <div id="opc-setup-recovery" class="opc-setup-recovery" hidden>
          <p id="opc-setup-recovery-message" class="note"></p>
          <button id="opc-setup-recover" class="row-action" type="button">Refresh and verify</button>
        </div>
        <button id="opc-setup-revoke" class="row-action" type="button" hidden>Revoke spending</button>
      </div>
    </div>
"""


OPC_SETUP_CSS = r"""
/* OPC setup is an opt-in view.  The data attribute is server-projected from
   the current browser session; ordinary and C embedded views do not match. */
body[data-account-view="authorization"][data-opc-setup] #opc-setup {
  display: block;
  max-width: 760px;
  margin: 0 auto;
  padding: 26px 0 42px;
}
body[data-account-view="authorization"][data-opc-setup] #opc-setup[hidden] {
  display: none;
}
body[data-account-view="authorization"][data-opc-setup] > main > section[aria-labelledby="permissions-heading"],
body[data-account-view="authorization"][data-opc-setup] > main > section[aria-labelledby="allowances-heading"],
body[data-account-view="authorization"][data-opc-setup] > main > section[aria-labelledby="audit-heading"],
body[data-account-view="authorization"][data-opc-setup] > main #embedded-authorization,
body[data-account-view="authorization"][data-opc-setup] > main #opc-device-section {
  display: none;
}
body[data-account-view="authorization"][data-opc-setup] #connect-wallet {
  display: none;
}
body[data-account-view="authorization"][data-opc-setup] .intro {
  max-width: 760px;
  padding-bottom: 18px;
}
body[data-account-view="authorization"][data-opc-setup] .intro h1,
body[data-account-view="authorization"][data-opc-setup] .intro .lede {
  display: none;
}
.opc-setup-card {
  border: 1px solid var(--line);
  border-top: 3px solid var(--signal);
  background: var(--surface-raised);
  padding: clamp(20px, 4vw, 34px);
  box-shadow: 0 18px 46px rgba(0, 0, 0, .18);
}
.opc-setup-kicker {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 16px;
}
.opc-setup-card h2 {
  margin: 10px 0 8px;
  font-size: clamp(27px, 5vw, 38px);
  line-height: 1.05;
  letter-spacing: -.025em;
}
.opc-setup-intro { max-width: 58ch; color: var(--muted); margin: 0 0 22px; }
.opc-setup-device-summary {
  display: grid;
  grid-template-columns: repeat(2, minmax(0, 1fr));
  gap: 10px;
  margin: 22px 0 24px;
  padding: 14px;
  border: 1px solid var(--line);
  background: var(--surface);
}
.opc-setup-device-summary .opc-summary-item { min-width: 0; }
.opc-setup-device-summary strong,
.opc-setup-device-summary span { display: block; overflow-wrap: anywhere; }
.opc-setup-device-summary strong { color: var(--text); font-size: 13px; }
.opc-setup-device-summary span { color: var(--muted); font-size: 12px; }
.opc-setup-form { display: grid; gap: 14px; }
.opc-setup-card #opc-setup-submit { width: 100%; margin-top: 4px; }
.opc-setup-grid { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 14px; }
.opc-setup-products { display: grid; gap: 8px; border: 1px solid var(--line); padding: 12px 14px; }
.opc-setup-products legend { padding: 0 4px; color: var(--muted); font-size: 13px; }
.opc-setup-products label { display: flex; align-items: center; gap: 8px; }
.opc-setup-products input { accent-color: var(--signal); }
.opc-setup-products input[type="checkbox"] {
  width: 18px; height: 18px; flex: 0 0 18px; padding: 0; margin: 0;
}
.opc-setup-products .note { margin: 2px 0 0; }
.opc-setup-limits { border-top: 1px solid var(--line); border-bottom: 1px solid var(--line); padding: 10px 0 12px; }
.opc-setup-limits > summary,
.opc-setup-details > summary { cursor: pointer; color: var(--muted); font-size: 13px; }
.opc-setup-limits[open] > summary { margin-bottom: 14px; }
.opc-setup-review { border-left: 2px solid var(--warning); padding: 10px 12px; color: var(--muted); overflow-wrap: anywhere; }
.opc-setup-review[hidden] { display: none; }
.opc-setup-status { min-height: 1.55em; margin: 16px 0 0; overflow-wrap: anywhere; }
.opc-setup-summary { margin-top: 22px; }
.opc-setup-details { margin-top: 18px; }
.opc-setup-details[open] { padding-top: 6px; }
.opc-setup-recovery { margin-top: 20px; padding-top: 16px; border-top: 1px solid var(--line); }
.opc-setup-recovery[hidden] { display: none; }
#opc-setup-revoke { margin-top: 18px; }
@media (max-width: 760px) {
  body[data-account-view="authorization"][data-opc-setup] #opc-setup { width: 100%; padding-top: 10px; }
  .opc-setup-card { padding: 20px 16px; }
  .opc-setup-grid, .opc-setup-device-summary { grid-template-columns: 1fr; }
}
"""


OPC_SETUP_JS = r"""
  // This controller is deliberately scoped to a validated server bootstrap.
  // It shares all wallet/Core/allowance mutation helpers with the legacy view.
  let opcSetupAfterState = null;
  let opcSetupInvalidate = null;
  let opcSetupExpectedChainChange = null;

  const opcSetupElement = (selector) => $(selector);
  const opcSetupSetText = (selector, value) => {
    const element = opcSetupElement(selector);
    if (element) element.textContent = String(value ?? "");
  };
  const opcSetupSetStage = (stage, message = "") => {
    const allowed = new Set([
      "wallet_confirmation",
      "chain_confirmation",
      "core_verification",
      "submission_unknown"
    ]);
    const safeStage = allowed.has(stage) ? stage : "core_verification";
    setAccountStage(safeStage, message);
  };
  const OPC_SETUP_BOUND_WALLET_MISMATCH = Symbol("opcSetupBoundWalletMismatch");
  const opcSetupErrorMessage = (error) => {
    if (error?.accountSessionExpired || allowanceSessionExpired) {
      return ACCOUNT_SESSION_EXPIRED_MESSAGE;
    }
    if (error?.allowanceUnknown) {
      return error.message || "The allowance submission is uncertain. Verify the submitted hash before retrying; do not resend.";
    }
    if (error?.[PROVIDER_FAILURE_BRAND]) {
      return error.message || `Wallet request failed during ${error.providerStage}.`;
    }
    return error?.message || "The authorization could not be completed.";
  };
  const opcSetupSetError = (error, fallbackStage = "core_verification") => {
    const stage = error?.allowanceUnknown
      ? "submission_unknown"
      : error?.[PROVIDER_FAILURE_BRAND] || error?.[OPC_SETUP_BOUND_WALLET_MISMATCH]
        ? error.providerStage
        : fallbackStage;
    const message = opcSetupErrorMessage(error);
    opcSetupSetStage(stage, message);
    return message;
  };
  const opcSetupSetHidden = (selector, hidden) => {
    const element = opcSetupElement(selector);
    if (element) element.hidden = Boolean(hidden);
  };
  const opcSetupRows = (selector, rows) => {
    const container = opcSetupElement(selector);
    if (!container) return;
    const children = rows.map(([label, value, meta = ""]) => {
      const row = document.createElement("div");
      row.className = "ledger-row";
      const labelElement = document.createElement("p");
      labelElement.className = "ledger-label";
      labelElement.textContent = String(label);
      const valueElement = document.createElement("p");
      valueElement.className = "ledger-value";
      valueElement.textContent = String(value ?? "");
      const metaElement = document.createElement("p");
      metaElement.className = "ledger-meta";
      metaElement.textContent = String(meta ?? "");
      row.append(labelElement, valueElement, metaElement);
      return row;
    });
    container.replaceChildren(...children);
  };

  const opcSetupObject = (value) =>
    Boolean(value && typeof value === "object" && !Array.isArray(value));
  const opcSetupExactKeys = (value, required, optional = []) => {
    if (!opcSetupObject(value)) return false;
    const allowed = new Set([...required, ...optional]);
    return Object.keys(value).every((key) => allowed.has(key)) &&
      required.every((key) => Object.prototype.hasOwnProperty.call(value, key));
  };
  const opcSetupSafeText = (value) => typeof value === "string" && value.length > 0 && value.length <= 512;
  const opcSetupValidAmount = (value) =>
    typeof value === "string" && /^(0|[1-9]\d*)(\.\d{1,6})?$/.test(value) && value !== "0";
  const opcSetupProductVenues = Object.freeze({
    marketplace: "clink_marketplace",
    transfers: "clink_transfers"
  });
  const opcSetupReviewedProducts = Object.keys(opcSetupProductVenues);
  const opcSetupSelectedProducts = ({required = true} = {}) => {
    const controls = opcSetupReviewedProducts
      .map((product) => opcSetupElement(`#opc-setup-${product}`))
      .filter(Boolean);
    // Keep the controller compatible with a cached/older console fragment
    // while the server-rendered component rolls out.  The real component
    // always renders both controls, so an omitted transfer choice remains
    // Marketplace-only rather than silently expanding authority.
    if (!controls.length) return ["marketplace"];
    const selected = opcSetupReviewedProducts.filter((product) =>
      Boolean(opcSetupElement(`#opc-setup-${product}`)?.checked)
    );
    if (required && !selected.length) throw new Error("Choose at least one allowed product");
    return selected.sort();
  };
  const opcSetupSetProducts = (products) => {
    const selected = new Set(Array.isArray(products) ? products : ["marketplace"]);
    opcSetupReviewedProducts.forEach((product) => {
      const element = opcSetupElement(`#opc-setup-${product}`);
      if (element) element.checked = selected.has(product);
    });
  };
  const opcSetupExpectedScopes = (grant, products) => {
    const selected = new Set(
      Array.isArray(products) && products.length ? products : ["marketplace"]
    );
    const currentProducts = Array.isArray(grant?.product_scopes) ? grant.product_scopes : [];
    const currentVenues = Array.isArray(grant?.venue_scopes) ? grant.venue_scopes : [];
    const productScopes = grant
      ? currentProducts.filter((product) => !opcSetupReviewedProducts.includes(product))
      : [];
    const venueScopes = grant
      ? currentVenues.filter((venue) => !Object.values(opcSetupProductVenues).includes(venue))
      : [];
    selected.forEach((product) => {
      productScopes.push(product);
      venueScopes.push(opcSetupProductVenues[product]);
    });
    return {
      productScopes: [...new Set(productScopes)].sort(),
      venueScopes: [...new Set(venueScopes)].sort()
    };
  };

  const opcSetupValidateBootstrap = (value) => {
    if (!opcSetupExactKeys(value, ["pairing", "network_configs", "approval_targets", "defaults"])) {
      throw new Error("OPC setup context is unavailable");
    }
    const pairingFields = [
      "pairing_id", "installation_id", "label", "public_jwk_thumbprint",
      "scope", "agent_id", "status", "expires_at"
    ];
    const pairing = value.pairing;
    if (!opcSetupExactKeys(pairing, pairingFields) ||
      !pairingFields.every((field) => opcSetupSafeText(pairing[field])) ||
      pairing.scope !== "payments" || pairing.agent_id !== CONTROLLED_AGENT_ID ||
      !["pending", "claimed", "active", "consent_required", "expired", "revoked"].includes(pairing.status) ||
      Number.isNaN(Date.parse(pairing.expires_at))) {
      throw new Error("OPC setup device context is invalid");
    }
    if (!opcSetupObject(value.network_configs) || !Object.keys(value.network_configs).length) {
      throw new Error("OPC setup has no configured network");
    }
    for (const [network, config] of Object.entries(value.network_configs)) {
      if (!/^eip155:[1-9]\d*$/.test(network) || !opcSetupObject(config) ||
        !Number.isInteger(config.chain_id) || config.chain_id < 1 ||
        !Number.isInteger(config.token_decimals) || config.token_decimals < 0 ||
        !Number.isInteger(config.required_confirmations) || config.required_confirmations < 1 ||
        !opcSetupSafeText(config.token_symbol)) {
        throw new Error("OPC setup network configuration is invalid");
      }
    }
    if (!opcSetupObject(value.approval_targets)) {
      throw new Error("OPC setup approval targets are invalid");
    }
    for (const [network, target] of Object.entries(value.approval_targets)) {
      if (!Object.prototype.hasOwnProperty.call(value.network_configs, network)) {
        throw new Error("OPC setup approval target network is invalid");
      }
      if (target !== null && (!opcSetupObject(target) ||
        !opcSetupSafeText(target.token_address) || !opcSetupSafeText(target.spender_address))) {
        throw new Error("OPC setup approval target is invalid");
      }
    }
    const defaults = value.defaults;
    if (!opcSetupExactKeys(defaults, ["total_usdc", "hourly_usdc", "duration_days"]) ||
      !opcSetupValidAmount(defaults.total_usdc) || !opcSetupValidAmount(defaults.hourly_usdc) ||
      !Number.isInteger(defaults.duration_days) || defaults.duration_days < 1 || defaults.duration_days > 365) {
      throw new Error("OPC setup defaults are invalid");
    }
    return value;
  };

  let opcSetupBootstrapError = "";
  const opcSetupBootstrap = (() => {
    if (!document.body?.dataset?.opcSetup) return null;
    try {
      return opcSetupValidateBootstrap(JSON.parse(document.body.dataset.opcSetup));
    } catch (error) {
      opcSetupBootstrapError = "This OPC setup link is invalid or expired. Refresh it from Clink.";
      return {__invalid: true};
    }
  })();

  const opcSetupState = {
    bootstrap: opcSetupBootstrap,
    operation: null,
    generation: 0,
    initialized: false,
    blocked: false,
    blockedContext: null,
    hydratedGrantId: null,
    lastPlan: null,
    lastPairing: null,
    lastAllowance: null,
    lastMismatch: null
  };

  const opcSetupView = () => Boolean(opcSetupState.bootstrap && opcSetupElement("#opc-setup"));
  const opcSetupRecoveryMessage = () => allowanceSessionExpired
    ? ACCOUNT_SESSION_EXPIRED_MESSAGE
    : allowanceRecoveryMessage || allowancePostSendUncertainIdentityId
      ? (allowanceRecoveryMessage || ALLOWANCE_POST_SEND_UNCERTAIN_MESSAGE)
      : "Core has an allowance recovery record for this wallet. Check authorization status before approving again.";
  const opcSetupApplyRecoveryBlock = () => {
    if (!opcSetupView()) return;
    const blocked = allowanceRecoveryBlocksNewApproval();
    if (!blocked) {
      if (!opcSetupState.blockedContext) {
        opcSetupState.blocked = false;
        const submit = opcSetupElement("#opc-setup-submit");
        if (submit && !opcSetupState.operation) {
          submit.disabled = false;
          submit.textContent = opcSetupState.lastMismatch
            ? "Review current authorization"
            : "Confirm spending authorization";
        }
        opcSetupSetHidden("#opc-setup-recovery", true);
      }
      return;
    }
    opcSetupState.blocked = true;
    const message = opcSetupRecoveryMessage();
    const recovery = opcSetupElement("#opc-setup-recovery");
    const preserveRecoveryMessage = Boolean(
      recovery && !recovery.hidden && opcSetupElement("#opc-setup-recovery-message")?.textContent
    );
    opcSetupSetText("#opc-setup-state", "Action required");
    if (!preserveRecoveryMessage || allowanceSessionExpired) {
      opcSetupSetText("#opc-setup-status", message);
      opcSetupSetText("#opc-setup-recovery-message", message);
    }
    opcSetupSetHidden("#opc-setup-recovery", false);
    const submit = opcSetupElement("#opc-setup-submit");
    if (submit) {
      submit.textContent = "Check authorization status";
      submit.disabled = Boolean(opcSetupState.operation || allowanceSessionExpired);
    }
    const recover = opcSetupElement("#opc-setup-recover");
    if (recover) recover.disabled = Boolean(opcSetupState.operation || allowanceSessionExpired);
  };
  opcSetupBlockFromRecovery = opcSetupApplyRecoveryBlock;
  const opcSetupConfiguredNetworks = () => {
    if (!opcSetupState.bootstrap || opcSetupState.bootstrap.__invalid) return [];
    return Object.keys(opcSetupState.bootstrap.network_configs).filter((network) =>
      opcSetupState.bootstrap.approval_targets[network]
    );
  };
  const opcSetupNetworkLabel = (network) => {
    const config = opcSetupState.bootstrap?.network_configs?.[network];
    try {
      return networkLabel(network, config);
    } catch (_error) {
      return network;
    }
  };
  const opcSetupGrant = (state = accountState) => {
    const current = state?.current_spending_mandate;
    if (current && ["active", "paused"].includes(current.status) && current.agent_id === CONTROLLED_AGENT_ID) {
      return current;
    }
    const candidates = (state?.spending_grants || []).filter((grant) =>
      grant && ["active", "paused", "pending"].includes(grant.status) && grant.agent_id === CONTROLLED_AGENT_ID
    );
    return candidates.length === 1 ? candidates[0] : null;
  };
  const opcSetupGrantValues = (grant) => {
    if (!grant) return null;
    const limits = grant.limits_usdc || {};
    return {
      id: grant.spending_grant_id,
      walletIdentityId: grant.wallet_identity_id,
      total: String(limits.total ?? grant.max_amount_usdc ?? ""),
      perTransaction: String(limits.per_transaction ?? grant.per_transaction_limit_usdc ?? ""),
      hourly: String(limits.rolling_hour ?? grant.hourly_limit_usdc ?? ""),
      daily: String(limits.daily ?? grant.daily_limit_usdc ?? ""),
      startsAt: String(grant.starts_at || ""),
      expiresAt: String(grant.expires_at || ""),
      status: grant.status,
      productScopes: Array.isArray(grant.product_scopes) ? [...grant.product_scopes] : [],
      venueScopes: Array.isArray(grant.venue_scopes) ? [...grant.venue_scopes] : [],
      used: String(grant.used_usdc?.total ?? grant.used_amount_usdc ?? "0"),
      reserved: String(grant.reserved_usdc?.total ?? grant.reserved_amount_usdc ?? "0")
    };
  };
  const opcSetupSelectedNetwork = (grant = opcSetupGrant()) => {
    const networks = opcSetupConfiguredNetworks();
    const grantNetworks = Array.isArray(grant?.network_scopes) ? grant.network_scopes : [];
    return grantNetworks.find((network) => networks.includes(network)) || networks[0] || "";
  };
  const opcSetupForm = () => {
    const network = String(opcSetupElement("#opc-setup-network")?.value || "");
    const total = String(opcSetupElement("#opc-setup-total")?.value || "").trim();
    const hourly = String(opcSetupElement("#opc-setup-hourly")?.value || "").trim();
    const durationValue = String(opcSetupElement("#opc-setup-duration")?.value || "").trim();
    const products = opcSetupSelectedProducts();
    if (!opcSetupConfiguredNetworks().includes(network)) throw new Error("Choose a supported authorization network");
    if (!isEmbeddedAmount(total) || !isEmbeddedAmount(hourly) || total === "0" || hourly === "0") {
      throw new Error("Enter valid USDC limits with at most six decimals");
    }
    if (opcSetupGrant()) return {network, total, hourly, duration: null, products};
    if (!/^[1-9]\d{0,2}$/.test(durationValue)) {
      throw new Error("Permission duration must be between 1 and 365 days");
    }
    const duration = Number.parseInt(durationValue, 10);
    if (!Number.isInteger(duration) || duration < 1 || duration > 365) {
      throw new Error("Permission duration must be between 1 and 365 days");
    }
    return {network, total, hourly, duration, products};
  };
  const opcSetupFormSame = (left, right) => Boolean(left && right &&
    left.network === right.network && left.total === right.total && left.hourly === right.hourly &&
    JSON.stringify(left.products || []) === JSON.stringify(right.products || []));
  const opcSetupAmountSame = (left, right) => {
    try { return usdcAtomic(String(left)) === usdcAtomic(String(right)); } catch (_error) { return false; }
  };
  const opcSetupNonNegativeAtomic = (value) => {
    const normalized = String(value).trim();
    if (!/^(0|[1-9]\d*)(\.\d{1,6})?$/.test(normalized)) throw new Error("Core returned an invalid non-negative USDC amount");
    const [whole, fraction = ""] = normalized.split(".");
    return BigInt(whole) * 1_000_000n + BigInt(fraction.padEnd(6, "0") || "0");
  };
  const opcSetupGrantMatchesForm = (form, grant) => {
    const values = opcSetupGrantValues(grant);
    const target = opcSetupState.bootstrap?.approval_targets?.[form?.network];
    const expectedScopes = opcSetupExpectedScopes(grant, form?.products);
    let token = null;
    try { token = target ? canonicalAddress(target.token_address) : null; } catch (_error) { return false; }
    const durationMatches = form?.duration === null || (
      Number.isInteger(form?.duration) &&
      Number.isFinite(Date.parse(values.startsAt)) &&
      Number.isFinite(Date.parse(values.expiresAt)) &&
      Date.parse(values.expiresAt) - Date.parse(values.startsAt) ===
        form.duration * 24 * 60 * 60 * 1000
    );
    return Boolean(form && values && durationMatches &&
      opcSetupAmountSame(form.total, values.total) &&
      opcSetupAmountSame(form.hourly, values.hourly) &&
      JSON.stringify(grant.product_scopes || []) === JSON.stringify(expectedScopes.productScopes) &&
      JSON.stringify(grant.venue_scopes || []) === JSON.stringify(expectedScopes.venueScopes) &&
      JSON.stringify(grant.network_scopes || []) === JSON.stringify([form.network]) &&
      JSON.stringify(grant.asset_scopes || []) === JSON.stringify([token]));
  };
  const opcSetupSetForm = (form, {existing = false} = {}) => {
    if (!form) return;
    const network = opcSetupElement("#opc-setup-network");
    const total = opcSetupElement("#opc-setup-total");
    const hourly = opcSetupElement("#opc-setup-hourly");
    const duration = opcSetupElement("#opc-setup-duration");
    opcSetupSetProducts(form.products);
    if (network) network.value = form.network;
    if (total) total.value = form.total;
    if (hourly) hourly.value = form.hourly;
    if (duration) {
      duration.value = String(form.duration ?? "");
      duration.hidden = existing;
      duration.required = !existing;
    }
  };
  const opcSetupPopulate = () => {
    if (!opcSetupView() || opcSetupState.initialized) return;
    const bootstrap = opcSetupState.bootstrap;
    if (bootstrap.__invalid) {
      opcSetupState.initialized = true;
      opcSetupSetHidden("#opc-setup", false);
      opcSetupSetText("#opc-setup-state", "Unavailable");
      opcSetupSetText("#opc-setup-status", opcSetupBootstrapError || "This OPC setup context is invalid. Refresh it from Clink.");
      const submit = opcSetupElement("#opc-setup-submit");
      if (submit) submit.disabled = true;
      return;
    }
    const networks = opcSetupConfiguredNetworks();
    const select = opcSetupElement("#opc-setup-network");
    if (!networks.length) {
      opcSetupSetText("#opc-setup-status", "No configured approval target is available for this setup link.");
      opcSetupSetHidden("#opc-setup", false);
      opcSetupSetText("#opc-setup-state", "Unavailable");
      const submit = opcSetupElement("#opc-setup-submit");
      if (submit) submit.disabled = true;
      opcSetupState.initialized = true;
      return;
    }
    if (select) {
      select.innerHTML = networks.map((network) =>
        `<option value="${escapeHtml(network)}">${escapeHtml(opcSetupNetworkLabel(network))} (${escapeHtml(network)})</option>`
      ).join("");
      select.value = networks[0];
    }
    opcSetupSetForm({
      network: networks[0],
      total: bootstrap.defaults.total_usdc,
      hourly: bootstrap.defaults.hourly_usdc,
      duration: bootstrap.defaults.duration_days,
      products: ["marketplace"]
    });
    opcSetupSetText("#opc-setup-device-summary", "");
    const pairing = bootstrap.pairing;
    const device = opcSetupElement("#opc-setup-device-summary");
    if (device) {
      const items = [
        ["Device", pairing.label],
        ["Scope", pairing.scope],
        ["Agent", "Clink"],
        ["Request", pairing.status]
      ];
      device.replaceChildren(...items.map(([label, value]) => {
        const item = document.createElement("div");
        item.className = "opc-summary-item";
        const strong = document.createElement("strong");
        strong.textContent = label;
        const span = document.createElement("span");
        span.textContent = value;
        item.append(strong, span);
        return item;
      }));
    }
    opcSetupState.initialized = true;
    opcSetupSetHidden("#opc-setup", false);
    const terminal = ["expired", "revoked"].includes(pairing.status);
    const submit = opcSetupElement("#opc-setup-submit");
    if (submit) submit.disabled = terminal;
    opcSetupSetText("#opc-setup-status", terminal
      ? "This OPC device request is no longer available. Refresh it from Clink to reconnect."
      : "Review the network, total, hourly limit, and duration before authorizing.");
  };
  const opcSetupRenderGrant = (grant, pairing = opcPairing) => {
    if (!opcSetupView()) return;
    const values = opcSetupGrantValues(grant);
    if (values && opcSetupState.hydratedGrantId !== values.id) {
      const currentForm = {
        network: opcSetupSelectedNetwork(grant),
        total: values.total,
        hourly: values.hourly,
        duration: null,
        products: opcSetupReviewedProducts.filter((product) => values.productScopes.includes(product))
      };
      opcSetupSetForm(currentForm, {existing: true});
      opcSetupState.hydratedGrantId = values.id;
    } else if (!values && opcSetupState.hydratedGrantId !== null) {
      const networks = opcSetupConfiguredNetworks();
      opcSetupSetForm({
        network: networks[0] || "",
        total: opcSetupState.bootstrap.defaults.total_usdc,
        hourly: opcSetupState.bootstrap.defaults.hourly_usdc,
        duration: opcSetupState.bootstrap.defaults.duration_days,
        products: ["marketplace"]
      });
      opcSetupState.hydratedGrantId = null;
    }
    const allowance = opcSetupState.lastAllowance;
    const rows = [];
    if (values) {
      rows.push(["Current grant", values.id]);
      rows.push(["Limits", `${values.total} total / ${values.hourly} rolling hour`, "USDC"]);
      rows.push(["Used / reserved", `${values.used} / ${values.reserved}`, "USDC; preserved by amendments"]);
      rows.push(["Scope", values.productScopes.join(", ") || "No product scope", values.venueScopes.join(", ")]);
      rows.push(["Valid until", values.expiresAt, values.status]);
    } else {
      rows.push(["New authorization", opcSetupSelectedProducts({required: false}).join(", ") || "No product selected", "one configured network"]);
      rows.push(["Limits", `${opcSetupElement("#opc-setup-total")?.value || ""} total / ${opcSetupElement("#opc-setup-hourly")?.value || ""} rolling hour`, "USDC"]);
    }
    if (pairing) rows.push(["Device", pairing.label, `${pairing.scope} / ${pairing.status}`]);
    if (allowance) {
      rows.push(["On-chain allowance", allowance.status, allowance.observed_atomic === null ? "unknown observation" : `${formatUsdcAtomic(allowance.observed_atomic)} USDC observed`]);
      if (allowance.observed_atomic !== null && BigInt(allowance.observed_atomic) > BigInt(allowance.target_atomic)) {
        rows.push(["Larger shared allowance", `${formatUsdcAtomic(allowance.observed_atomic)} USDC`,
          "Shared by this wallet, token and spender on this network, not reserved for this Agent. It is not reduced automatically; changes require your wallet confirmation."]);
      }
    }
    const mismatch = opcSetupState.lastMismatch;
    if (mismatch) {
      rows.push([
        "Allowance amount mismatch",
        `${formatUsdcAtomic(mismatch.actual_approved_amount_atomic)} USDC approved; ${formatUsdcAtomic(mismatch.amount_atomic)} USDC requested`,
        `Observed at verification: ${formatUsdcAtomic(mismatch.observed_allowance_atomic)} USDC; verified at ${mismatch.verified_at}. No transaction was resent. Budget unchanged.`
      ]);
    }
    opcSetupRows("#opc-setup-summary", rows);
    const technical = [];
    if (pairing) technical.push(["Installation", pairing.installation_id]);
    if (pairing) technical.push(["Public-key thumbprint", pairing.public_jwk_thumbprint]);
    const network = opcSetupElement("#opc-setup-network")?.value;
    const target = opcSetupState.bootstrap.approval_targets[network];
    if (target) {
      technical.push(["Network", network]);
      technical.push(["Token", target.token_address]);
      technical.push(["Spender", target.spender_address]);
    }
    if (allowance) {
      technical.push(["Allowance target", allowance.target_usdc, "USDC"]);
      technical.push(["Allowance atomic", allowance.target_atomic]);
      technical.push(["Observed at", allowance.observed_at || "Unavailable"]);
    }
    opcSetupRows("#opc-setup-technical", technical);
    const revoke = opcSetupElement("#opc-setup-revoke");
    if (revoke) revoke.hidden = !values;
    const duration = opcSetupElement("#opc-setup-duration");
    if (duration) {
      duration.hidden = Boolean(values);
      duration.required = !values;
    }
  };
  const opcSetupPairingMatches = (pairing) => Boolean(
    pairing && opcSetupState.bootstrap &&
    pairing.pairing_id === opcSetupState.bootstrap.pairing.pairing_id &&
    pairing.installation_id === opcSetupState.bootstrap.pairing.installation_id &&
    pairing.public_jwk_thumbprint === opcSetupState.bootstrap.pairing.public_jwk_thumbprint &&
    pairing.scope === "payments" && pairing.agent_id === CONTROLLED_AGENT_ID
  );
  const opcSetupGrantImmutableTermsMatch = (grant, terms, {includeReviewedScopes = true} = {}) => {
    if (!grant || !terms || grant.wallet_identity_id !== terms.wallet_identity_id ||
      grant.agent_id !== terms.agent_id || grant.expires_at !== terms.expires_at ||
      grant.starts_at !== terms.starts_at || grant.notification_mode !== terms.notification_mode) return false;
    const arrays = [
      ...(includeReviewedScopes ? ["product_scopes", "venue_scopes"] : []),
      "merchant_scopes", "merchant_trust_scopes", "network_scopes", "asset_scopes"
    ];
    return arrays.every((field) => JSON.stringify(grant[field] || []) === JSON.stringify(terms[field] || []));
  };
  const opcSetupGrantMatchesTerms = (grant, terms) => {
    if (!opcSetupGrantImmutableTermsMatch(grant, terms)) return false;
    const limits = grant.limits_usdc || {};
    return opcSetupAmountSame(limits.total ?? grant.max_amount_usdc, terms.max_amount_usdc) &&
      opcSetupAmountSame(limits.per_transaction ?? grant.per_transaction_limit_usdc, terms.per_transaction_limit_usdc) &&
      opcSetupAmountSame(limits.rolling_hour ?? grant.hourly_limit_usdc, terms.hourly_limit_usdc) &&
      opcSetupAmountSame(limits.daily ?? grant.daily_limit_usdc, terms.daily_limit_usdc);
  };
  const opcSetupAllowanceMatchesGrant = (plan, form, grant) => {
    const allowance = plan?.allowance;
    const terms = plan?.terms;
    if (!allowance || !terms || !form) return false;
    const total = terms.max_amount_usdc;
    const used = grant ? grant.used_usdc?.total ?? grant.used_amount_usdc ?? "0" : "0";
    const perTransaction = terms.per_transaction_limit_usdc;
    let totalAtomic;
    let usedAtomic;
    let perTransactionAtomic;
    let targetAtomic;
    let targetUsdcAtomic;
    let requiredAtomic;
    let observedAtomic = null;
    try {
      totalAtomic = opcSetupNonNegativeAtomic(total);
      usedAtomic = opcSetupNonNegativeAtomic(used);
      perTransactionAtomic = opcSetupNonNegativeAtomic(perTransaction);
      targetAtomic = BigInt(allowance.target_atomic);
      targetUsdcAtomic = opcSetupNonNegativeAtomic(allowance.target_usdc);
      requiredAtomic = opcSetupNonNegativeAtomic(allowance.required_usdc);
      if (allowance.observed_atomic !== null) observedAtomic = BigInt(allowance.observed_atomic);
    } catch (_error) {
      return false;
    }
    if (usedAtomic > totalAtomic || targetAtomic !== targetUsdcAtomic || targetAtomic > totalAtomic - usedAtomic) return false;
    const expectedRequired = perTransactionAtomic < targetAtomic ? perTransactionAtomic : targetAtomic;
    if (requiredAtomic !== expectedRequired) return false;
    const expectedStatus = targetAtomic === 0n
      ? "exhausted"
      : observedAtomic === null
        ? "unknown"
        : observedAtomic >= requiredAtomic ? "sufficient" : "insufficient";
    if (allowance.status !== expectedStatus) return false;
    const expectedExcess = observedAtomic === null ? null : observedAtomic > targetAtomic;
    return allowance.exceeds_budget === expectedExcess;
  };
  const opcSetupPlanMatchesReview = (plan, form, grant, target) => {
    const terms = plan?.terms;
    const identity = accountState?.wallet_identities?.find((item) =>
      item.status === "active" && canonicalAddress(item.wallet_address) === selectedWalletAddress
    );
    if (!terms || !form || !target || !identity || terms.agent_id !== CONTROLLED_AGENT_ID ||
      terms.wallet_identity_id !== identity.wallet_identity_id ||
      !opcSetupAmountSame(terms.max_amount_usdc, form.total) || !opcSetupAmountSame(terms.hourly_limit_usdc, form.hourly)) return false;
    const expectedToken = canonicalAddress(target.token_address);
    const expectedScopes = opcSetupExpectedScopes(grant, form.products);
    if (JSON.stringify(terms.product_scopes || []) !== JSON.stringify(expectedScopes.productScopes) ||
      JSON.stringify(terms.venue_scopes || []) !== JSON.stringify(expectedScopes.venueScopes)) return false;
    if (grant) {
      if (!opcSetupGrantImmutableTermsMatch(grant, terms, {includeReviewedScopes: false}) ||
        terms.amends_spending_grant_id !== grant.spending_grant_id) return false;
      const limits = grant.limits_usdc || {};
      const oldPerTransaction = limits.per_transaction ?? grant.per_transaction_limit_usdc;
      const oldDaily = limits.daily ?? grant.daily_limit_usdc;
      const expectedPerTransaction = usdcAtomic(String(oldPerTransaction)) <= usdcAtomic(form.hourly)
        ? oldPerTransaction : form.hourly;
      const expectedDaily = usdcAtomic(String(oldDaily)) <= usdcAtomic(form.total)
        ? oldDaily : form.total;
      return opcSetupAmountSame(terms.per_transaction_limit_usdc, expectedPerTransaction) &&
        opcSetupAmountSame(terms.daily_limit_usdc, expectedDaily);
    }
    if (plan.action !== "sign" || Object.prototype.hasOwnProperty.call(terms, "amends_spending_grant_id") ||
      !opcSetupAmountSame(terms.per_transaction_limit_usdc, form.hourly) || !opcSetupAmountSame(terms.daily_limit_usdc, form.total) ||
      terms.notification_mode !== "silent_under_limits" ||
      JSON.stringify(terms.merchant_scopes) !== JSON.stringify([]) ||
      JSON.stringify(terms.merchant_trust_scopes) !== JSON.stringify(["clink_verified", "registry_verified"]) ||
      JSON.stringify(terms.network_scopes) !== JSON.stringify([form.network]) ||
      JSON.stringify(terms.asset_scopes) !== JSON.stringify([expectedToken])) return false;
    const starts = Date.parse(terms.starts_at);
    const expires = Date.parse(terms.expires_at);
    return Number.isFinite(starts) && Number.isFinite(expires) &&
      expires > starts && expires - starts === form.duration * 24 * 60 * 60 * 1000;
  };
  const opcSetupPairingActiveFor = (pairing, identity, grant) => Boolean(
    opcSetupPairingMatches(pairing) && pairing.status === "active" &&
    pairing.wallet_identity_id === identity.wallet_identity_id &&
    pairing.spending_grant_id === grant.spending_grant_id &&
    pairing.consent_expires_at !== null && !opcConsentExpired(pairing)
  );
  opcSetupHandleConfirmedMismatch = (record, {commit = true} = {}) => {
    if (!opcSetupView()) return true;
    const context = opcSetupState.blockedContext;
    if (!context) return true;
    if (
      !opcSetupState.blocked ||
      opcSetupState.operation ||
      !context.identity ||
      !context.allowance ||
      !context.terms ||
      !context.selection ||
      !context.pairing ||
      !context.attemptContext ||
      context.generation !== opcSetupState.generation
    ) return false;
    try {
      assertWalletSnapshot(context.selection);
      const identity = selectedWalletIdentity(context.selection);
      const grant = opcSetupGrant();
      const target = context.allowance;
      const attempt = context.attemptContext;
      if (
        record.status !== "confirmed_mismatch" ||
        record.attempt_id !== attempt.attempt_id ||
        record.wallet_identity_id !== identity.wallet_identity_id ||
        record.network !== target.network ||
        record.token_address !== canonicalAddress(target.token_address) ||
        record.spender_address !== canonicalAddress(target.spender_address) ||
        record.amount_atomic !== target.target_atomic ||
        attempt.wallet_identity_id !== identity.wallet_identity_id ||
        attempt.network !== target.network ||
        attempt.token_address !== record.token_address ||
        attempt.spender_address !== record.spender_address ||
        attempt.amount_atomic !== record.amount_atomic ||
        !grant ||
        grant.spending_grant_id !== context.grantId ||
        grant.wallet_identity_id !== identity.wallet_identity_id ||
        !opcSetupGrantMatchesTerms(grant, context.terms) ||
        !opcSetupPairingMatches(opcPairing) ||
        context.pairing.pairing_id !== opcPairing.pairing_id ||
        context.pairing.installation_id !== opcPairing.installation_id ||
        context.pairing.public_jwk_thumbprint !== opcPairing.public_jwk_thumbprint ||
        !opcSetupPairingActiveFor(opcPairing, identity, grant)
      ) return false;
    } catch (_error) {
      return false;
    }
    if (!commit) return true;
    opcSetupState.blocked = false;
    opcSetupState.blockedContext = null;
    opcSetupState.lastPlan = null;
    opcSetupState.lastAllowance = null;
    opcSetupState.lastMismatch = record;
    opcSetupSetText("#opc-setup-state", "Review");
    opcSetupSetText("#opc-setup-status", allowanceMismatchSummary(record));
    opcSetupSetHidden("#opc-setup-recovery", true);
    const submit = opcSetupElement("#opc-setup-submit");
    if (submit) {
      submit.disabled = false;
      submit.textContent = "Review current authorization";
    }
    opcSetupRenderGrant(opcSetupGrant(), opcPairing);
    opcSetupSetStage("core_verification", allowanceMismatchSummary(record));
    status.textContent = allowanceMismatchSummary(record);
    status.classList.add("error");
    return true;
  };
  const opcSetupGuard = (operation) => {
    if (!operation || opcSetupState.operation !== operation || operation.cancelled ||
      operation.generation !== opcSetupState.generation) {
      throw new Error("OPC authorization was cancelled or changed. Review the current setup again.");
    }
    assertWalletSnapshot(operation.selection);
    if (operation.formGeneration !== opcSetupState.generation) {
      throw new Error("Setup values changed. Review the current authorization again.");
    }
  };
  const opcSetupStart = () => {
    if (opcSetupState.operation) throw new Error("An OPC authorization operation is already in progress");
    if (allowanceRecoveryBlocksNewApproval()) {
      opcSetupApplyRecoveryBlock();
      throw new Error(opcSetupRecoveryMessage());
    }
    const operation = {
      cancelled: false,
      generation: opcSetupState.generation,
      formGeneration: opcSetupState.generation,
      selection: null,
      grantPostStarted: false,
      devicePostStarted: false,
      signatureStarted: false,
      approveStarted: false
    };
    opcSetupState.operation = operation;
    opcSetupSetHidden("#opc-setup-cancel", false);
    const submit = opcSetupElement("#opc-setup-submit");
    if (submit) submit.disabled = true;
    return operation;
  };
  const opcSetupEnd = (operation) => {
    if (opcSetupState.operation === operation) opcSetupState.operation = null;
    if (operation?.confirmedMismatch) {
      processConfirmedAllowanceMismatch(accountState);
    }
    const submit = opcSetupElement("#opc-setup-submit");
    if (submit) {
      submit.disabled = Boolean(allowanceSessionExpired || allowanceRecoveryBlocksNewApproval());
      if (allowanceRecoveryBlocksNewApproval()) submit.textContent = "Check authorization status";
    }
    opcSetupSetHidden("#opc-setup-cancel", true);
    opcSetupApplyRecoveryBlock();
  };
  const opcSetupReadback = async (operation) => {
    const body = validateOpcEnvelope(await request("/opc/pairing"));
    if (operation) opcSetupGuard(operation);
    opcPairing = body.pairing;
    opcSetupState.lastPairing = body.pairing;
    if (body.pairing) renderOpcPairing(body.pairing);
    return body.pairing;
  };
  const opcSetupReadAccountAndPairing = async (operation) => {
    const loaded = await loadState();
    if (!loaded) throw new Error("Wallet authentication expired. Refresh and choose the wallet again.");
    opcSetupGuard(operation);
    if (!opcSetupPairingMatches(opcPairing)) throw new Error("Core returned a different OPC device context");
    return opcPairing;
  };
  const opcSetupMutationRecovery = async (operation, expected) => {
    try {
      const loaded = await loadState();
      if (!loaded) return false;
      const grant = opcSetupGrant();
      const pairing = opcPairing;
      if (expected.grantId && grant?.spending_grant_id !== expected.grantId) return false;
      if (expected.walletIdentityId && grant?.wallet_identity_id !== expected.walletIdentityId) return false;
      if (expected.terms && !opcSetupGrantMatchesTerms(grant, expected.terms)) return false;
      if (expected.pairing && !opcSetupPairingActiveFor(pairing, expected.identity, grant)) return false;
      return Boolean(grant);
    } catch (_error) {
      return false;
    }
  };
  const opcSetupDisplayPlan = (plan) => {
    const allowance = plan.allowance;
    opcSetupState.lastPlan = plan;
    opcSetupState.lastAllowance = allowance;
    opcSetupState.lastMismatch = null;
    const termRows = [
      ["Action", plan.action],
      ["Clink device", opcSetupState.bootstrap.pairing.label],
      ["Allowed business scope", plan.terms.product_scopes.join(", ")],
      ["Network", allowance.network],
      ["Total limit", plan.terms.max_amount_usdc, "USDC"],
      ["Per purchase", plan.terms.per_transaction_limit_usdc, "USDC"],
      ["Rolling hour", plan.terms.hourly_limit_usdc, "USDC"],
      ["Daily limit", plan.terms.daily_limit_usdc, "USDC"],
      ["Starts", plan.terms.starts_at],
      ["Expires", plan.terms.expires_at],
      ["Allowance", allowance.status, allowance.observed_atomic === null ? "unknown observation" : `${formatUsdcAtomic(allowance.observed_atomic)} observed`]
    ];
    opcSetupRows("#opc-setup-review", termRows);
    opcSetupSetHidden("#opc-setup-review", false);
    const review = opcSetupElement("#opc-setup-review");
    if (review) review.hidden = false;
    opcSetupRows("#opc-setup-technical", [
      ["Core agent identifier", plan.terms.agent_id],
      ["Network", allowance.network],
      ["Token", allowance.token_address],
      ["Spender", allowance.spender_address],
      ["Wallet", allowance.wallet_address],
      ["Allowance target", allowance.target_usdc, "USDC"],
      ["Allowance atomic", allowance.target_atomic],
      ["Observed at", allowance.observed_at || "Unavailable"]
    ]);
  };
  const opcSetupPlan = async (operation, form, grant) => {
    opcSetupGuard(operation);
    const identity = selectedWalletIdentity(operation.selection);
    const target = opcSetupState.bootstrap.approval_targets[form.network];
    if (!target) throw new Error("Core approval configuration is unavailable for the selected network");
    const payload = {
      wallet_identity_id: identity.wallet_identity_id,
      network: form.network,
      total_usdc: form.total,
      hourly_usdc: form.hourly,
      spending_grant_id: grant?.spending_grant_id || null,
      products: form.products
    };
    if (!grant) payload.duration_days = form.duration;
    const plan = validateEmbeddedPlan(await request("/authorization-plan", {
      method: "POST",
      body: JSON.stringify(payload)
    }));
    opcSetupGuard(operation);
    if (plan.terms.wallet_identity_id !== identity.wallet_identity_id ||
      plan.allowance.network !== form.network ||
      plan.allowance.token_address.toLowerCase() !== target.token_address.toLowerCase() ||
      plan.allowance.spender_address.toLowerCase() !== target.spender_address.toLowerCase() ||
      plan.allowance.wallet_address.toLowerCase() !== operation.selection.address) {
      throw new Error("Core returned authorization terms for a different wallet or approval target");
    }
    if (!opcSetupPlanMatchesReview(plan, form, grant, target)) {
      throw new Error("Core returned authorization terms that differ from the reviewed limits, scope, or dates");
    }
    if (!opcSetupAllowanceMatchesGrant(plan, form, grant)) {
      throw new Error("Core returned allowance advice that exceeds the reviewed unspent budget");
    }
    opcSetupDisplayPlan(plan);
    return plan;
  };
  const opcSetupPairingForGrant = (pairing, identity, grant) => {
    if (!opcSetupPairingMatches(pairing)) throw new Error("Core returned a different OPC pairing");
    if (pairing.status === "active") {
      if (!opcSetupPairingActiveFor(pairing, identity, grant)) {
        throw new Error("Core did not confirm active device access for the exact wallet and grant");
      }
      return "active";
    }
    if (!["pending", "claimed", "consent_required"].includes(pairing.status) || opcPairingExpired(pairing) ||
      (pairing.status === "consent_required" && opcConsentExpired(pairing))) {
      throw new Error("The OPC device request is expired or no longer available");
    }
    return "consent";
  };
  const opcSetupConsent = async (operation, identity, grant, pairing, terms) => {
    const pairingState = opcSetupPairingForGrant(pairing, identity, grant);
    if (pairingState === "active") return pairing;
    opcSetupGuard(operation);
    const challenge = validateOpcChallenge(await request(
      `/opc/pairings/${encodeURIComponent(pairing.pairing_id)}/challenge`,
      {method: "POST", body: JSON.stringify({spending_grant_id: grant.spending_grant_id})}
    ));
    opcSetupGuard(operation);
    if (opcChallengeExpired(challenge)) throw new Error("The device consent challenge expired. No signature was sent.");
    opcSetupSetStage("wallet_confirmation", `Confirm the exact device message in your wallet for ${pairing.label}.`);
    opcSetupSetText("#opc-setup-review", challenge.message_to_sign);
    operation.deviceExpected = {
      pairing: true,
      identity,
      grantId: grant.spending_grant_id,
      walletIdentityId: identity.wallet_identity_id,
      terms
    };
    operation.signatureStarted = true;
    const signature = await operation.selection.provider.request({
      method: "personal_sign",
      params: [challenge.message_to_sign, operation.selection.address]
    });
    opcSetupGuard(operation);
    if (typeof signature !== "string" || !signature) throw new Error("Wallet returned no device signature");
    operation.devicePostStarted = true;
    try {
      await request("/opc/installations/approve", {
        method: "POST",
        body: JSON.stringify({
          challenge_session_id: challenge.session_id,
          signed_message: challenge.message_to_sign,
          signature
        })
      });
    } catch (error) {
      const recovered = await opcSetupMutationRecovery(operation, {
        pairing: true,
        identity,
        grantId: grant.spending_grant_id,
        walletIdentityId: identity.wallet_identity_id,
        terms
      });
      if (!recovered) {
        opcSetupState.blocked = true;
        opcSetupState.blockedContext = {
          pairing: true,
          identity,
          grantId: grant.spending_grant_id,
          walletIdentityId: identity.wallet_identity_id,
          terms
        };
        const safe = new Error("Device approval response is uncertain. Refresh device status before any further action; do not sign again.");
        safe.providerStage = "submission_unknown";
        safe.allowanceUnknown = false;
        throw safe;
      }
    }
    opcSetupGuard(operation);
    const readback = await opcSetupReadback(operation);
    if (!opcSetupPairingActiveFor(readback, identity, grant)) {
      throw new Error("Core did not confirm active device access for the exact wallet and grant");
    }
    return readback;
  };
  const opcSetupGrantMutation = async (operation, identity, plan, pairing, isNew) => {
    if (plan.action !== "sign") return opcSetupGrant();
    const terms = {...plan.terms};
    if (isNew) terms.opc_pairing_id = pairing.pairing_id;
    operation.grantExpected = {
      pairing: isNew,
      identity,
      grantId: plan.terms.amends_spending_grant_id || null,
      walletIdentityId: identity.wallet_identity_id,
      terms: plan.terms
    };
    const callbacks = {
      onSignatureRequest: () => { operation.signatureStarted = true; },
      onGrantSubmit: () => { operation.grantPostStarted = true; }
    };
    const guard = () => opcSetupGuard(operation);
    guard.callbacks = callbacks;
    try {
      await submitSignedGrant(terms, operation.selection, guard);
    } catch (error) {
      if (!operation.grantPostStarted) throw error;
      const recovered = await opcSetupMutationRecovery(operation, {
        pairing: isNew,
        identity,
        grantId: plan.terms.amends_spending_grant_id || null,
        walletIdentityId: identity.wallet_identity_id,
        terms: plan.terms
      });
      if (!recovered) {
        opcSetupState.blocked = true;
        opcSetupState.blockedContext = operation.grantExpected;
        throw new Error("Signed grant response is uncertain. Refresh and verify the current authorization before retrying; do not sign or resend.");
      }
    }
    await opcSetupReadAccountAndPairing(operation);
    const grant = opcSetupGrant();
    if (!grant || grant.wallet_identity_id !== identity.wallet_identity_id ||
      !opcSetupGrantMatchesTerms(grant, plan.terms) ||
      (plan.terms.amends_spending_grant_id && grant.spending_grant_id !== plan.terms.amends_spending_grant_id)) {
      throw new Error("Core did not confirm the exact spending authorization");
    }
    return grant;
  };
  const opcSetupAllowance = (plan) => {
    const allowance = plan.allowance;
    if (allowance.status === "unknown") throw new Error("Current allowance observation is unknown. Refresh Core before approving; no transaction was sent.");
    if (allowance.status === "exhausted") throw new Error("The Core budget is exhausted. No allowance top-up is offered.");
    if (allowance.status === "sufficient") {
      if (allowance.exceeds_budget === true) {
        opcSetupSetText("#opc-setup-status", `The existing allowance (${formatUsdcAtomic(allowance.observed_atomic)} USDC) exceeds the current unspent budget (${allowance.target_usdc} USDC). It is disclosed and will not be reduced automatically.`);
      }
      return false;
    }
    if (allowance.status !== "insufficient" || allowance.target_atomic === "0") {
      throw new Error("Core returned an invalid allowance action");
    }
    const target = BigInt(allowance.target_atomic);
    const budget = BigInt(usdcAtomic(allowance.target_usdc));
    if (target <= 0n || target > budget) throw new Error("Finite allowance target exceeds the displayed unspent budget");
    return true;
  };
  const opcSetupLateAllowanceTargetMatches = (context, identity) => {
    const target = context?.allowance;
    const coreTarget = accountState?.approval_targets?.[target?.network];
    const bootstrapTarget = opcSetupState.bootstrap?.approval_targets?.[target?.network];
    if (!target || !coreTarget || !bootstrapTarget) return false;
    try {
      return canonicalAddress(target.wallet_address) === canonicalAddress(identity.wallet_address) &&
        canonicalAddress(target.token_address) === canonicalAddress(coreTarget.token_address) &&
        canonicalAddress(target.spender_address) === canonicalAddress(coreTarget.spender_address) &&
        canonicalAddress(target.token_address) === canonicalAddress(bootstrapTarget.token_address) &&
        canonicalAddress(target.spender_address) === canonicalAddress(bootstrapTarget.spender_address);
    } catch (_error) {
      return false;
    }
  };
  const opcSetupLateAllowanceContextIsValid = (operation, expected) => {
    if (
      !operation ||
      operation.allowanceExpected !== expected ||
      opcSetupState.blockedContext !== expected ||
      !opcSetupState.blocked ||
      opcSetupState.operation ||
      operation.cancelled ||
      operation.generation !== expected.generation ||
      expected.generation !== opcSetupState.generation ||
      expected.selection !== operation.selection ||
      pendingAllowance ||
      pendingAllowanceCleanup ||
      allowanceRecoveryBlocked ||
      allowanceOperation ||
      allowancePostSendUncertainIdentityId !== expected.identity?.wallet_identity_id
    ) {
      return false;
    }
    try {
      assertWalletSnapshot(expected.selection);
      const identity = selectedWalletIdentity(expected.selection);
      const grant = opcSetupGrant();
      const storage = probeAllowanceRecoveryStorage();
      if (
        storage.getItem(pendingAllowanceStorageKey(identity.wallet_identity_id)) !== null ||
        storage.getItem(allowancePostSendUncertainStorageKey(identity.wallet_identity_id)) !==
          ALLOWANCE_POST_SEND_UNCERTAIN_LABEL ||
        identity.wallet_identity_id !== expected.identity.wallet_identity_id ||
        canonicalAddress(identity.wallet_address) !== canonicalAddress(expected.identity.wallet_address) ||
        !grant ||
        grant.status !== "active" ||
        grant.spending_grant_id !== expected.grantId ||
        grant.wallet_identity_id !== identity.wallet_identity_id ||
        !opcSetupGrantMatchesTerms(grant, expected.terms) ||
        opcPairing !== expected.pairing ||
        opcPairingGeneration !== expected.pairingGeneration ||
        !opcSetupPairingActiveFor(expected.pairing, identity, grant) ||
        !opcSetupLateAllowanceTargetMatches(expected, identity)
      ) {
        return false;
      }
      return true;
    } catch (_error) {
      return false;
    }
  };
  const opcSetupHandleLateAllowanceRejection = async (operation, expected) => {
    if (!opcSetupLateAllowanceContextIsValid(operation, expected)) return false;
    const attemptContext = operation.attemptContext || expected?.attemptContext;
    if (!attemptContext) return false;
    let rejected = false;
    try {
      rejected = await rejectAllowanceAttempt(attemptContext);
    } catch (error) {
      if (error?.accountSessionExpired) opcSetupApplyRecoveryBlock();
      return false;
    }
    if (!rejected || !opcSetupLateAllowanceContextIsValid(operation, expected)) return false;
    try {
      if (!clearAllowancePostSendUncertain(expected.identity.wallet_identity_id)) return false;
    } catch (_error) {
      return false;
    }
    operation.approveStarted = false;
    opcSetupState.blocked = false;
    opcSetupState.blockedContext = null;
    opcSetupSetText("#opc-setup-state", "Rejected");
    opcSetupSetStage(
      "wallet_confirmation",
      "Wallet request was rejected after timing out. Spending authorization was not completed; no retry was sent."
    );
    opcSetupSetHidden("#opc-setup-recovery", true);
    status.classList.remove("error");
    return true;
  };
  const opcSetupApprove = async (operation, plan) => {
    if (!opcSetupAllowance(plan)) return;
    const identity = selectedWalletIdentity(operation.selection);
    const expected = {
      wallet_identity_id: identity.wallet_identity_id,
      wallet_address: plan.allowance.wallet_address.toLowerCase(),
      network: plan.allowance.network,
      token_address: plan.allowance.token_address.toLowerCase(),
      spender_address: plan.allowance.spender_address.toLowerCase(),
      target_atomic: plan.allowance.target_atomic
    };
    operation.allowanceExpected = {
      identity, allowance: {...plan.allowance},
      grantId: opcSetupGrant()?.spending_grant_id,
      terms: plan.terms,
      generation: operation.generation,
      selection: operation.selection,
      pairing: opcPairing,
      pairingGeneration: opcPairingGeneration
    };
    opcSetupSetStage("chain_confirmation", `Finite approval: ${plan.allowance.target_usdc} USDC on ${plan.allowance.network}; confirm the amount and gas in your wallet.`);
    opcSetupSetText("#opc-setup-review", `Finite approval: ${plan.allowance.target_usdc} USDC on ${plan.allowance.network}; token ${plan.allowance.token_address}; spender ${plan.allowance.spender_address}. Confirm the amount and gas in your wallet.`);
    const config = opcSetupState.bootstrap.network_configs[plan.allowance.network];
    opcSetupExpectedChainChange = (chainId) => {
      const expectedChain = `0x${parseInt(String(config.chain_id), 10).toString(16)}`;
      return typeof chainId === "string" && String(chainId).toLowerCase() === expectedChain;
    };
    operation.approveStarted = false;
    try {
      await approve(plan.allowance.network, {
        approvedAmountAtomic: plan.allowance.target_atomic,
        expected,
        plan,
        guard: () => opcSetupGuard(operation),
        onBroadcast: () => { operation.approveStarted = true; },
        onAttemptPrepared: (attemptContext) => {
          operation.attemptContext = attemptContext;
          operation.allowanceExpected.attemptContext = attemptContext;
        },
        onUserRejected: () => opcSetupHandleLateAllowanceRejection(
          operation,
          operation.allowanceExpected
        )
      });
    } catch (error) {
      if (error?.accountSessionExpired || allowanceSessionExpired) {
        opcSetupState.blocked = true;
        opcSetupState.blockedContext = operation.allowanceExpected;
        throw error;
      }
      if (error?.allowanceMismatch) {
        operation.confirmedMismatch = error.allowanceMismatch;
        opcSetupState.blocked = true;
        opcSetupState.blockedContext = operation.allowanceExpected;
        throw error;
      }
      if (error?.code === 4001 && !allowancePostSendUncertainIdentityId) {
        operation.approveStarted = false;
        throw error;
      }
      if (operation.approveStarted || allowancePostSendUncertainIdentityId) {
        opcSetupState.blocked = true;
        opcSetupState.blockedContext = operation.allowanceExpected;
        const submittedHashKnown = pendingAllowance &&
          pendingAllowance.wallet_identity_id === expected.wallet_identity_id &&
          pendingAllowance.network === expected.network &&
          pendingAllowance.token_address === expected.token_address &&
          pendingAllowance.spender_address === expected.spender_address;
        const safe = new Error(submittedHashKnown
          ? opcSetupErrorMessage(error)
          : `Allowance approval is uncertain. Query Core and chain state before retrying; do not resend. ${opcSetupErrorMessage(error)}`);
        safe[PROVIDER_FAILURE_BRAND] = true;
        safe.allowanceUnknown = !submittedHashKnown;
        safe.providerStage = submittedHashKnown ? "core_verification" : "submission_unknown";
        safe.providerClass = error?.providerClass || "provider_error";
        safe.providerCode = error?.providerCode ?? null;
        safe.code = error?.code ?? null;
        throw safe;
      }
      throw error;
    } finally {
      opcSetupExpectedChainChange = null;
    }
    opcSetupGuard(operation);
  };
  const opcSetupAllowanceObservation = (identity, target) => {
    const observed = (accountState?.asset_allowances || []).find((item) =>
      item.status === "active" && item.wallet_identity_id === identity.wallet_identity_id &&
      item.network === target.network && item.token_address.toLowerCase() === target.token_address.toLowerCase() &&
      item.spender_address.toLowerCase() === target.spender_address.toLowerCase()
    );
    if (!observed) return null;
    let observedAtomic;
    try { observedAtomic = BigInt(String(observed.observed_allowance_atomic)); } catch (_error) { return null; }
    if (observedAtomic < BigInt(usdcAtomic(String(target.required_usdc)))) return null;
    return {observed, observedAtomic};
  };
  const opcSetupFinalReadback = async (operation, identity, expectedPlan, expectedGrantId) => {
    await opcSetupReadAccountAndPairing(operation);
    const grant = opcSetupGrant();
    if (!grant || grant.spending_grant_id !== expectedGrantId || grant.wallet_identity_id !== identity.wallet_identity_id || grant.agent_id !== CONTROLLED_AGENT_ID ||
      !opcSetupGrantMatchesTerms(grant, expectedPlan.terms)) {
      throw new Error("Core did not confirm the exact spending authorization");
    }
    const pairing = opcPairing;
    if (!opcSetupPairingActiveFor(pairing, identity, grant)) {
      throw new Error("Core did not confirm the exact active device connection");
    }
    const target = expectedPlan.allowance;
    const observation = opcSetupAllowanceObservation(identity, target);
    if (!observation) throw new Error("Core did not return a sufficient active allowance for the selected target");
    opcSetupState.lastAllowance = {
      ...target,
      status: "sufficient",
      observed_atomic: String(observation.observedAtomic)
    };
    opcSetupRenderGrant(grant, pairing);
    return true;
  };
  const opcSetupAssertBoundWallet = (selection) => {
    const activeIdentities = (accountState?.wallet_identities || []).filter((item) =>
      item.status === "active"
    );
    if (!activeIdentities.length) return;
    const selectedIsBound = activeIdentities.some((item) => {
      try { return canonicalAddress(item.wallet_address) === selection.address; } catch (_error) { return false; }
    });
    if (selectedIsBound) return;
    const error = new Error(
      "Selected wallet does not match the bound wallet. Choose the existing bound wallet; no wallet signature or transaction was sent."
    );
    error[OPC_SETUP_BOUND_WALLET_MISMATCH] = true;
    error.providerStage = "wallet_confirmation";
    error.providerClass = "bound_wallet_mismatch";
    opcSetupSetStage("wallet_confirmation", error.message);
    throw error;
  };
  const opcSetupRun = async () => {
    if (allowanceRecoveryBlocksNewApproval()) {
      opcSetupApplyRecoveryBlock();
      return;
    }
    const operation = opcSetupStart();
    try {
      opcSetupSetStage("core_verification", "Core is checking the selected authorization context.");
      const form = opcSetupForm();
      operation.form = {...form};
      const initialGrant = opcSetupGrant();
      const selection = selectedWalletSnapshot();
      operation.selection = selection;
      opcSetupGuard(operation);
      opcSetupAssertBoundWallet(selection);
      if (!accountState || !accountState.wallet_identities?.some((item) =>
        item.status === "active" && item.wallet_identity_id && item.wallet_address.toLowerCase() === selection.address
      )) {
        opcSetupSetStage("wallet_confirmation", "Confirm wallet ownership only if this selected address still needs verification.");
        await loginSelectedWallet(selection, {onStart: (loginOperation) => { operation.loginOperation = loginOperation; }});
        opcSetupGuard(operation);
      }
      await opcSetupReadAccountAndPairing(operation);
      if (allowanceRecoveryBlocksNewApproval()) {
        opcSetupApplyRecoveryBlock();
        return;
      }
      const identity = selectedWalletIdentity(selection);
      const discoveredGrant = opcSetupGrant();
      const discoveredValues = opcSetupGrantValues(discoveredGrant);
      const discoveredMatchesReviewedLimits = discoveredValues &&
        opcSetupGrantMatchesForm(operation.form, discoveredGrant) &&
        opcSetupAmountSame(operation.form.hourly, discoveredValues.perTransaction) &&
        opcSetupAmountSame(operation.form.total, discoveredValues.daily);
      if (discoveredGrant && !initialGrant && !discoveredMatchesReviewedLimits) {
        opcSetupState.blocked = false;
        opcSetupRenderGrant(discoveredGrant, opcPairing);
        opcSetupSetText("#opc-setup-state", "Review required");
        opcSetupSetStage("core_verification", "An existing authorization differs from the submitted limits, scope, or duration. Review the actual terms above before continuing.");
        return;
      }
      if (discoveredGrant?.status === "paused") throw new Error("The current spending authorization is paused. Revoke it here or manage it in the full Core console.");
      const planForm = discoveredGrant && !initialGrant ? operation.form : opcSetupForm();
      const plan = await opcSetupPlan(operation, planForm, discoveredGrant || null);
      opcSetupSetStage("core_verification", "Core returned the exact authorization terms. Continuing only while the current wallet and device context still match.");
      if (["unknown", "exhausted"].includes(plan.allowance.status)) {
        throw new Error(plan.allowance.status === "unknown"
          ? "Current allowance observation is unknown. Refresh Core before signing; no grant or device mutation was sent."
          : "The Core budget is exhausted. No grant, device mutation, or allowance transaction was sent.");
      }
      const isNew = !discoveredGrant;
      const grant = await opcSetupGrantMutation(operation, identity, plan, opcPairing, isNew);
      opcSetupGuard(operation);
      const pairing = await opcSetupReadback(operation);
      const connectedPairing = isNew
        ? (opcSetupPairingForGrant(pairing, identity, grant) === "active" ? pairing : null)
        : await opcSetupConsent(operation, identity, grant, pairing, plan.terms);
      if (!connectedPairing) throw new Error("Core did not confirm the OPC device connection");
      await opcSetupReadAccountAndPairing(operation);
      const freshGrant = opcSetupGrant();
      if (!freshGrant || freshGrant.spending_grant_id !== grant.spending_grant_id || !opcSetupGrantMatchesTerms(freshGrant, plan.terms)) {
        throw new Error("Core returned a different authorization after the wallet action. No success is shown.");
      }
      const freshPlan = await opcSetupPlan(operation, {
        network: planForm.network,
        total: String(freshGrant.limits_usdc.total),
        hourly: String(freshGrant.limits_usdc.rolling_hour),
        duration: null,
        products: planForm.products
      }, freshGrant);
      await opcSetupApprove(operation, freshPlan);
      await opcSetupFinalReadback(operation, identity, freshPlan, grant.spending_grant_id);
      opcSetupState.blocked = false;
      opcSetupSetText("#opc-setup-state", "Saved");
      opcSetupSetText("#opc-setup-status", "Permission saved / device connected. Core will verify payment capability before use.");
      opcSetupSetHidden("#opc-setup-recovery", true);
    } catch (error) {
      const message = opcSetupSetError(error);
      if (opcSetupState.blocked) {
        opcSetupSetHidden("#opc-setup-recovery", false);
        opcSetupSetText("#opc-setup-recovery-message", message);
      }
      opcSetupSetText("#opc-setup-state", "Action required");
      opcSetupSetText("#opc-setup-status", message);
      status.textContent = message;
      status.classList.add("error");
    } finally {
      opcSetupEnd(operation);
    }
  };
  const opcSetupCancel = () => {
    const operation = opcSetupState.operation;
    if (!operation) return;
    operation.cancelled = true;
    if (operation.loginOperation) operation.loginOperation.cancelled = true;
    opcSetupState.generation += 1;
    opcSetupState.blocked = Boolean(operation.grantPostStarted || operation.devicePostStarted || operation.approveStarted);
    if (opcSetupState.blocked) {
      opcSetupState.blockedContext ||= operation.allowanceExpected || operation.deviceExpected || operation.grantExpected || null;
    }
    const message = opcSetupState.blocked
      ? "Cancellation requested after a wallet transaction may have been submitted. Refresh and verify Core before retrying; do not resend."
      : operation.loginOperation
        ? "Setup cancelled while wallet confirmation was pending. No later step will be sent; close the wallet prompt before retrying."
      : operation.signatureStarted
        ? "Setup cancelled while the wallet signature was pending. No later mutation will be sent; review Core before retrying."
        : "Setup cancelled. No wallet signature or chain transaction was sent.";
    opcSetupSetText("#opc-setup-status", message);
    status.textContent = message;
    status.classList.toggle("error", opcSetupState.blocked);
    if (opcSetupState.blocked) opcSetupSetHidden("#opc-setup-recovery", false);
  };
  const opcSetupCompleteVerifiedAllowance = (record) => {
    const context = opcSetupState.blockedContext;
    if (!context?.allowance || !context.grantId || !context.terms ||
      opcSetupState.operation || context.generation !== opcSetupState.generation ||
      pendingAllowance || allowanceRecoveryBlocked || allowancePostSendUncertainIdentityId) return;
    try {
      assertWalletSnapshot(context.selection);
      const identity = selectedWalletIdentity(context.selection);
      const target = context.allowance;
      if (identity.wallet_identity_id !== context.identity.wallet_identity_id ||
        record.wallet_identity_id !== identity.wallet_identity_id ||
        record.network !== target.network ||
        record.token_address !== target.token_address.toLowerCase() ||
        record.spender_address !== target.spender_address.toLowerCase()) return;
      const grant = opcSetupGrant();
      if (!grant || grant.spending_grant_id !== context.grantId ||
        grant.wallet_identity_id !== identity.wallet_identity_id ||
        !opcSetupGrantMatchesTerms(grant, context.terms) ||
        !opcSetupPairingActiveFor(opcPairing, identity, grant) ||
        !opcSetupAllowanceObservation(identity, target)) return;
      opcSetupState.blocked = false;
      opcSetupState.blockedContext = null;
      opcSetupSetText("#opc-setup-state", "Saved");
      opcSetupSetStage("core_verification", "Spending authorization confirmed. Core will enforce the saved limits and scope before each use.");
      opcSetupSetHidden("#opc-setup-recovery", true);
      status.classList.remove("error");
    } catch (_error) {
      // A changed wallet/context cannot be completed by a late read-only result.
    }
  };
  const opcSetupRecover = async () => {
    if (opcSetupState.operation) return;
    if (allowanceSessionExpired) {
      opcSetupApplyRecoveryBlock();
      return;
    }
    const context = opcSetupState.blockedContext;
    try {
      if (context?.identity) {
        const selection = selectedWalletSnapshot();
        const identity = selectedWalletIdentity(selection);
        if (identity.wallet_identity_id !== context.identity.wallet_identity_id) {
          throw new Error("Choose the same wallet before recovering this authorization; recovery remains blocked.");
        }
      }
      const loaded = await loadState();
      if (!loaded) throw new Error("Wallet authentication expired. Refresh and choose the wallet again; recovery remains blocked.");
      if (allowanceSessionExpired) throw new Error(ACCOUNT_SESSION_EXPIRED_MESSAGE);
      // A confirmed amount mismatch is a terminal transaction fact, not a
      // sufficient allowance. The shared loader has already reconciled the
      // exact local records and returned the OPC flow to review; do not run
      // the ordinary recovery observation check against the old context.
      if (
        context?.allowance &&
        opcSetupState.lastMismatch?.status === "confirmed_mismatch" &&
        !opcSetupState.blocked &&
        !opcSetupState.blockedContext
      ) {
        return;
      }
      if (pendingAllowance) {
        await recoverPendingAllowance();
        if (allowanceSessionExpired) throw new Error(ACCOUNT_SESSION_EXPIRED_MESSAGE);
      }
      if (allowanceRecoveryBlocksNewApproval()) {
        opcSetupApplyRecoveryBlock();
        throw new Error(opcSetupRecoveryMessage());
      }
      if (!opcSetupPairingMatches(opcPairing)) throw new Error("Core returned a different OPC device context; recovery remains blocked.");
      const grant = opcSetupGrant();
      if (!grant) throw new Error("Core has not confirmed the spending authorization; recovery remains blocked.");
      if (context?.grantId && grant.spending_grant_id !== context.grantId) throw new Error("Core returned a different spending authorization; recovery remains blocked.");
      if (context?.walletIdentityId && grant.wallet_identity_id !== context.walletIdentityId) throw new Error("Core returned a different wallet authorization; recovery remains blocked.");
      if (context?.terms && !opcSetupGrantMatchesTerms(grant, context.terms)) throw new Error("Core has not confirmed the exact signed authorization terms; recovery remains blocked.");
      if (context?.pairing && !opcSetupPairingActiveFor(opcPairing, context.identity, grant)) throw new Error("Core has not confirmed the exact active device connection; recovery remains blocked.");
      if (context?.allowance) {
        if (!opcSetupAllowanceObservation(context.identity, context.allowance)) throw new Error("Core has not confirmed a sufficient selected allowance; recovery remains blocked.");
      }
      opcSetupState.blocked = false;
      opcSetupState.blockedContext = null;
      opcSetupSetText("#opc-setup-status", "Core state refreshed. Review the exact current authorization before continuing.");
      opcSetupSetHidden("#opc-setup-recovery", true);
    } catch (error) {
      if (
        error?.allowanceMismatch &&
        context?.allowance &&
        opcSetupState.lastMismatch?.status === "confirmed_mismatch" &&
        !opcSetupState.blocked &&
        !opcSetupState.blockedContext
      ) {
        return;
      }
      opcSetupState.blocked = true;
      opcSetupSetText("#opc-setup-recovery-message", error.message);
      opcSetupSetText("#opc-setup-status", error.message);
    }
  };

  opcSetupAfterState = async () => {
    if (!opcSetupView()) return;
    if (allowanceRecoveryBlocksNewApproval()) opcSetupApplyRecoveryBlock();
    opcSetupPopulate();
    if (opcSetupState.bootstrap.__invalid || !opcSetupConfiguredNetworks().length) return;
    const grant = opcSetupGrant();
    opcSetupState.lastPairing = opcPairing;
    opcSetupState.lastMismatch = allowanceMismatchForNetwork(
      accountState,
      opcSetupElement("#opc-setup-network")?.value
    );
    opcSetupRenderGrant(grant, opcPairing);
    if (opcPairing && !opcSetupPairingMatches(opcPairing)) {
      opcSetupState.blocked = true;
      opcSetupSetText("#opc-setup-status", "Core returned a different OPC device context. This setup is locked until a matching link is opened.");
    }
    if (allowanceRecoveryBlocksNewApproval()) opcSetupApplyRecoveryBlock();
  };
  opcSetupInvalidate = (message = "Wallet or setup values changed. Review the exact authorization again.") => {
    if (!opcSetupView()) return;
    opcSetupState.generation += 1;
    const operation = opcSetupState.operation;
    if (operation) {
      operation.cancelled = true;
      if (operation.loginOperation) operation.loginOperation.cancelled = true;
      if (operation.grantPostStarted || operation.devicePostStarted || operation.approveStarted) {
        opcSetupState.blocked = true;
        opcSetupState.blockedContext ||= operation.allowanceExpected || operation.deviceExpected || operation.grantExpected || null;
      }
    }
    opcSetupState.lastPlan = null;
    opcSetupState.lastMismatch = null;
    opcSetupSetHidden("#opc-setup-review", true);
    opcSetupSetText("#opc-setup-status", message);
    if (!opcSetupGrant()) opcSetupRenderGrant(null, opcPairing);
  };

  if (opcSetupView()) {
    opcSetupPopulate();
    ["#opc-setup-network", "#opc-setup-total", "#opc-setup-hourly", "#opc-setup-duration", "#opc-setup-marketplace", "#opc-setup-transfers"].forEach((selector) => {
      const element = opcSetupElement(selector);
      element?.addEventListener("input", () => opcSetupInvalidate("Setup values changed. Review the exact authorization again."));
      element?.addEventListener("change", () => opcSetupInvalidate("Setup values changed. Review the exact authorization again."));
    });
    opcSetupElement("#opc-setup-form")?.addEventListener("submit", async (event) => {
      event.preventDefault();
      if (opcSetupState.blocked) {
        await opcSetupRecover();
        return;
      }
      if (opcSetupState.operation) return;
      await opcSetupRun();
    });
    opcSetupElement("#opc-setup-cancel")?.addEventListener("click", opcSetupCancel);
    opcSetupElement("#opc-setup-recover")?.addEventListener("click", opcSetupRecover);
    opcSetupElement("#opc-setup-revoke")?.addEventListener("click", async (event) => {
      const grant = opcSetupGrant();
      if (!grant || opcSetupState.operation) return;
      const button = event.currentTarget;
      button.disabled = true;
      try {
        await request(`/grants/${encodeURIComponent(grant.spending_grant_id)}/revoke`, {method: "POST", body: "{}"});
        await loadState();
        opcSetupSetText("#opc-setup-status", "Spending revoked in Core. This does not stop the runtime or clear a shared chain allowance.");
      } catch (error) {
        opcSetupSetText("#opc-setup-status", error.message);
        status.textContent = error.message;
        status.classList.add("error");
      } finally {
        button.disabled = false;
      }
    });
  }
"""


__all__ = ["OPC_SETUP_CSS", "OPC_SETUP_HTML", "OPC_SETUP_JS"]
