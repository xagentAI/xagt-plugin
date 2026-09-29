import React, { useEffect, useState } from "react";
import { createRoot } from "react-dom/client";
import "./styles.css";

const emptySnapshot = {
  summary: {
    portfolio_value_usd: "0.00",
    current_value_usd: "0.00",
    capital_deployed_usd: "0.00",
    available_budget_usd: null,
    available_budget_status: "unavailable",
    realized_pnl_usd: "0.00",
    unrealized_pnl_usd: "0.00",
    total_pnl_usd: "0.00",
    total_pnl_pct: "0.00",
    open_positions: 0,
    open_orders: 0,
    fills_24h: 0,
    settlements_24h: 0,
    active_strategies: 0,
    best_strategy_id: null,
    pending_confirmations: 0,
    submitted_executions: 0,
    win_rate_pct: "0.00",
    account_equity_usd: "0.00",
    available_cash_usd: "0.00",
    locked_cash_usd: "0.00",
    platform_exposure_usd: {},
    last_updated_at: "",
    last_synced_at: null,
    sync_status: "never_synced",
    sync_source: null,
    sync_stale: true,
  },
  strategies: [],
  agent_ideas: [],
  positions: [],
  account_balances: [],
  open_orders: [],
  recent_fills: [],
  recent_settlements: [],
  pending_actions: [],
  timeline: [],
  funding: {
    status: "unavailable",
    available_budget_usdc_by_venue: {},
    settled_amount_usdc_by_venue: {},
    bridge_status: null,
    polymarket_deposit_address: null,
    pusd_buying_power_usdc: null,
    spending_authorization_count: 0,
    receipt_count: 0,
    latest_receipt_tx_hash: null,
    error: null,
  },
};

function money(value) {
  const number = Number(value || 0);
  const sign = number > 0 ? "+" : number < 0 ? "-" : "";
  return `${sign}$${Math.abs(number).toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })}`;
}

function metricTone(value) {
  const number = Number(value || 0);
  if (number > 0) return "positive";
  if (number < 0) return "negative";
  return "neutral";
}

function timeLabel(value) {
  if (!value) return "never";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return value;
  return date.toLocaleTimeString(undefined, { hour: "2-digit", minute: "2-digit", second: "2-digit" });
}

function pickPrimaryStrategy(strategies) {
  if (!strategies.length) return null;
  return [...strategies].sort((a, b) => Number(b.total_pnl_usd || 0) - Number(a.total_pnl_usd || 0))[0];
}

function confidenceLabel(value) {
  if (value === null || value === undefined) return "unscored";
  return `${Math.round(Number(value) * 100)}%`;
}

function usdc(value) {
  const number = Number(value || 0);
  return `${number.toLocaleString(undefined, { minimumFractionDigits: 2, maximumFractionDigits: 2 })} USDC`;
}

function venueAmount(map, venue = "polymarket") {
  return map?.[venue] ?? "0";
}

function shortHash(value) {
  if (!value) return "none";
  return value.length > 18 ? `${value.slice(0, 10)}...${value.slice(-6)}` : value;
}

function dashboardUserId() {
  const params = new URLSearchParams(window.location.search);
  return params.get("user_id") || import.meta.env.VITE_DEFAULT_USER_ID || "telegram_demo_user";
}

function workspaceFromHash() {
  return window.location.hash === "#account" ? "account" : "dashboard";
}

function useWorkspaceRoute() {
  const [workspace, setWorkspaceState] = useState(() => workspaceFromHash());

  useEffect(() => {
    function handleHashChange() {
      setWorkspaceState(workspaceFromHash());
    }
    window.addEventListener("hashchange", handleHashChange);
    return () => window.removeEventListener("hashchange", handleHashChange);
  }, []);

  function setWorkspace(nextWorkspace) {
    window.location.hash = nextWorkspace === "account" ? "#account" : "#dashboard";
    setWorkspaceState(nextWorkspace);
  }

  return { workspace, setWorkspace };
}

function pickActiveAuthorization(fundingStatus) {
  const spendingAuthorizations = (fundingStatus?.spending_authorizations || []).map((item) => ({
    ...item,
    authorizationKind: "spending",
  }));
  return (
    spendingAuthorizations.find((item) => item.status === "active" && item.venue === "polymarket") ||
    spendingAuthorizations.find((item) => item.status === "active") ||
    null
  );
}

function resolveDashboardFundingRoute(binding) {
  const accountMode = binding?.account_mode || binding?.metadata?.account_mode;
  const walletAddress = binding?.wallet_address;
  const funderAddress = binding?.funder_address;
  const depositWallet = binding?.polymarket_deposit_wallet;
  const targetAddress = accountMode === "deposit_wallet" ? depositWallet || funderAddress : funderAddress || depositWallet;
  const sameAddress = walletAddress && targetAddress && walletAddress.toLowerCase() === targetAddress.toLowerCase();

  if (binding?.status !== "active") {
    return {
      label: "Account not ready",
      status: "blocked",
      defaultRoute: "Bind Polymarket first",
      x402Status: "blocked",
      reason: binding?.next_action || "Polymarket binding is not active.",
      target: null,
    };
  }

  if (accountMode === "eoa" || sameAddress) {
    return {
      label: "EOA Direct Trading",
      status: "direct",
      defaultRoute: "EOA Direct Trading",
      x402Status: "not applicable",
      reason: "The Polymarket funder equals the connected wallet, so x402 funding would transfer to self.",
      target: null,
    };
  }

  if ((accountMode === "proxy_or_safe" || accountMode === "deposit_wallet") && targetAddress) {
    return {
      label: accountMode === "deposit_wallet" ? "Deposit Wallet Funding" : "Proxy / Safe Funding",
      status: "ready",
      defaultRoute: "Venue account trading",
      x402Status: "available",
      reason: "A distinct Polymarket funding target is available for x402 funding.",
      target: targetAddress,
    };
  }

  return {
    label: "Funding target unresolved",
    status: "blocked",
    defaultRoute: "Direct trading only after binding",
    x402Status: "blocked",
    reason: "Clink cannot verify a distinct Polymarket funding target for x402.",
    target: null,
  };
}

function usePortfolio() {
  const [snapshot, setSnapshot] = useState(emptySnapshot);
  const [status, setStatus] = useState("loading");
  const [error, setError] = useState("");

  async function refresh() {
    try {
      setStatus("loading");
      const response = await fetch("/api/portfolio/snapshot", { cache: "no-store" });
      if (!response.ok) throw new Error(`portfolio service returned ${response.status}`);
      setSnapshot(await response.json());
      setStatus("online");
      setError("");
    } catch (err) {
      setStatus("offline");
      setError(err.message || "portfolio service unavailable");
    }
  }

  useEffect(() => {
    refresh();
    const timer = window.setInterval(refresh, 20000);
    return () => window.clearInterval(timer);
  }, []);

  return { snapshot, status, error, refresh };
}

function useAccountControl() {
  const [userId] = useState(() => dashboardUserId());
  const [coreAccount, setCoreAccount] = useState({ wallet_bound: false, spending_grant_active: false, ready: false });
  const [binding, setBinding] = useState({ status: "loading" });
  const [fundingStatus, setFundingStatus] = useState({ spending_authorizations: [] });
  const [depositWalletReadiness, setDepositWalletReadiness] = useState({ status: "loading", missing: [] });
  const [status, setStatus] = useState("loading");
  const [error, setError] = useState("");
  const [actionState, setActionState] = useState("");

  async function refresh() {
    try {
      setStatus("loading");
      const coreAccountPromise = fetch(`/account-api/clink/account/readiness?user_id=${encodeURIComponent(userId)}`, { cache: "no-store" });
      const bindingResponse = await fetch(`/account-api/polymarket/bindings/latest/${encodeURIComponent(userId)}`, { cache: "no-store" });
      const fundingPromise = fetch(`/core-funding-api/funding/status?user_id=${encodeURIComponent(userId)}&venue=polymarket`, { cache: "no-store" });
      const nextBinding = bindingResponse.ok ? await bindingResponse.json() : { status: "offline", next_action: "start_account_binding_service" };
      setBinding(nextBinding);

      const ownerWallet = nextBinding.wallet_address || nextBinding.funder_address || "";
      if (ownerWallet) {
        const query = new URLSearchParams({ user_id: userId, owner_wallet: ownerWallet });
        const readinessResponse = await fetch(`/deposit-wallet-api/polymarket/deposit-wallet/readiness?${query.toString()}`, { cache: "no-store" });
        setDepositWalletReadiness(readinessResponse.ok ? await readinessResponse.json() : { status: "offline", missing: [] });
      } else {
        setDepositWalletReadiness({ status: "waiting_for_binding", missing: [], next_action: "bind_polymarket_account" });
      }

      const [fundingResult, coreAccountResult] = await Promise.allSettled([fundingPromise, coreAccountPromise]);
      if (fundingResult.status === "fulfilled" && fundingResult.value.ok) {
        setFundingStatus(await fundingResult.value.json());
      } else {
        setFundingStatus({ spending_authorizations: [], available_budget_usdc_by_venue: {}, settled_amount_usdc_by_venue: {} });
      }
      if (coreAccountResult.status === "fulfilled" && coreAccountResult.value.ok) {
        setCoreAccount(await coreAccountResult.value.json());
      } else {
        setCoreAccount({ wallet_bound: false, spending_grant_active: false, ready: false, reason: "Core Account unavailable" });
      }

      setStatus("online");
      setError("");
    } catch (err) {
      setStatus("offline");
      setError(err.message || "account control services unavailable");
    }
  }

  async function openCoreAccount() {
    setActionState("Creating a secure Core Account session...");
    const response = await fetch("/account-api/clink/account/setup-link", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ user_id: userId }),
    });
    if (!response.ok) throw new Error(`Core Account link failed: ${response.status}`);
    const session = await response.json();
    if (!session.account_url) throw new Error("Core Account did not return a public URL");
    window.location.assign(session.account_url);
  }

  async function revokePolymarketBinding() {
    if (!binding?.binding_id) return;
    const confirmation = window.prompt("Type UNBIND to revoke Clink-side Polymarket access.");
    if (confirmation !== "UNBIND") return;

    setActionState("Revoking Polymarket binding...");
    const response = await fetch(`/account-api/polymarket/bindings/${binding.binding_id}/revoke`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        reason: "dashboard_user_requested_unbind",
        metadata: { source: "clink_prediction_markets_dashboard" },
      }),
    });
    if (!response.ok) throw new Error(`Polymarket unbind failed: ${response.status}`);
    setActionState("Polymarket binding revoked.");
    await refresh();
  }

  async function revokeFundingAuthorization(authorization) {
    const authorizationId = authorization?.spending_authorization_id;
    if (!authorizationId) return;
    const confirmation = window.prompt("Type UNBIND to revoke this wallet funding authorization.");
    if (confirmation !== "UNBIND") return;

    setActionState("Revoking wallet authorization...");
    const response = await fetch(`/core-funding-api/funding/spending-authorizations/${authorizationId}/revoke`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        reason: "dashboard_user_requested_wallet_unbind",
        metadata: { source: "clink_prediction_markets_dashboard" },
      }),
    });
    if (!response.ok) throw new Error(`Wallet authorization revoke failed: ${response.status}`);
    setActionState("Wallet spending authorization revoked.");
    await refresh();
  }

  useEffect(() => {
    refresh();
    const timer = window.setInterval(refresh, 20000);
    return () => window.clearInterval(timer);
  }, []);

  return {
    userId,
    coreAccount,
    binding,
    fundingStatus,
    depositWalletReadiness,
    status,
    error,
    actionState,
    refresh,
    openCoreAccount,
    revokePolymarketBinding,
    revokeFundingAuthorization,
  };
}

function AgentIdeas({ ideas }) {
  return (
    <section className="agent-ideas">
      <div className="section-kicker">
        <p className="eyebrow">Agentonomy Observations</p>
        <span>{ideas.length} recorded</span>
      </div>
      <div className="idea-ledger">
        {ideas.length === 0 && (
          <p className="empty">When Agentonomy scans a market and records a recommendation, it appears here automatically.</p>
        )}
        {ideas.slice(0, 8).map((idea) => {
          const market = idea.market || {};
          const trade = idea.suggested_trade || {};
          return (
            <article className={`idea-row ${idea.status}`} key={idea.idea_id}>
              <div className="idea-row-status">
                <span>{idea.status}</span>
                <b>{confidenceLabel(idea.confidence)}</b>
              </div>
              <div className="idea-row-main">
                <h3>{idea.topic}</h3>
                <p>{idea.agent_message}</p>
              </div>
              <div className="idea-row-market">
                <strong>{market.title || "No market attached"}</strong>
                <small>
                  {market.platform || "clink"} · {market.market_id || "no market id"} · Yes {market.yes_price ?? "n/a"}
                </small>
              </div>
              <div className="idea-row-trade">
                <small>Trade</small>
                <strong>{trade.side || "watch"} {trade.outcome || ""} · {trade.amount_usd || "0"} USD</strong>
              </div>
              <div className="idea-row-preview">
                <small>Preview</small>
                <strong>{idea.preview_id || "waiting"}</strong>
              </div>
              <div className="idea-row-execution">
                <small>Execution</small>
                <strong>{idea.execution_id || "not submitted"}</strong>
              </div>
              <div className="idea-row-risk">
                <small>Risk</small>
                <span>{(idea.risks || [])[0] || "No risk notes"}</span>
              </div>
            </article>
          );
        })}
      </div>
    </section>
  );
}

function Signal({ label, value, tone = "neutral" }) {
  return (
    <div className={`signal ${tone}`}>
      <span>{label}</span>
      <strong>{value}</strong>
    </div>
  );
}

function ProductNav({ workspace, setWorkspace, status, summary }) {
  return (
    <nav className="product-nav" aria-label="Clink product areas">
      <button className={`nav-pill ${workspace === "dashboard" ? "active" : ""}`} onClick={() => setWorkspace("dashboard")}>
        <span>Trading Dashboard</span>
        <small>ideas · orders · PnL</small>
      </button>
      <button className={`nav-pill ${workspace === "account" ? "active" : ""}`} onClick={() => setWorkspace("account")}>
        <span>Account / Binding Console</span>
        <small>wallet · Polymarket · x402</small>
      </button>
      <div className="nav-health">
        <span className={`status-dot ${status}`} />
        <strong>{status}</strong>
        <small>{summary.sync_stale ? "sync stale" : "live sync"}</small>
      </div>
    </nav>
  );
}

function CapitalPulse({ summary }) {
  return (
    <section className="capital-pulse" aria-label="Capital Pulse">
      <div>
        <p className="eyebrow">Money State</p>
        <h2>{money(summary.total_pnl_usd)}</h2>
        <small>Auto-synced PnL, {summary.total_pnl_pct}% across reconciled holdings</small>
      </div>
      <Signal label="Equity" value={money(summary.account_equity_usd)} />
      <Signal label="Available" value={money(summary.available_cash_usd)} />
      <Signal label="Deployed" value={money(summary.capital_deployed_usd)} />
      <Signal label="Pending" value={summary.pending_confirmations} tone={summary.pending_confirmations > 0 ? "warning" : "neutral"} />
    </section>
  );
}

function AccountWorkspace({ onPortfolioRefresh }) {
  return (
    <section className="account-workspace">
      <div className="workspace-intro">
        <p className="eyebrow">Account / Binding Console</p>
        <h2>Control what Agentonomy is allowed to touch.</h2>
        <p>
          Core Account owns wallet identity and the shared spending cap. Polymarket Account separately owns CLOB access. After both are ready,
          Agentonomy can fund and trade only inside Clink policy and the approved cap.
        </p>
      </div>
      <AccountControl onPortfolioRefresh={onPortfolioRefresh} />
    </section>
  );
}

function TradingWorkspace({ snapshot, status, error, refresh }) {
  const { summary } = snapshot;
  const primaryStrategy = pickPrimaryStrategy(snapshot.strategies);

  return (
    <section className="trading-workspace">
      <div className="workspace-intro">
        <p className="eyebrow">Trading Dashboard</p>
        <h2>Watch what the agent did, not how the plumbing works.</h2>
        <p>
          Agentonomy scans and discusses opportunities in Telegram. This board reconciles the resulting ideas, previews, executions, holdings, funding
          receipts, and PnL.
        </p>
      </div>

      <section className="status-line">
        <span className={`status-dot ${status}`} />
        <b>{status}</b>
        <span>Auto sync {summary.sync_status}</span>
        <span>Last sync {timeLabel(summary.last_synced_at)}</span>
        <span>Refreshes every 20s</span>
        {error && <strong>{error}</strong>}
      </section>

      <CapitalPulse summary={summary} />

      <FundingRail funding={snapshot.funding} />

      <AgentIdeas ideas={snapshot.agent_ideas || []} />

      <section className="command-grid">
        <ActiveThesis strategy={primaryStrategy} summary={summary} />
        <ClinkGate summary={summary} timeline={snapshot.timeline} pendingActions={snapshot.pending_actions} status={status} />
      </section>

      <section className="market-grid">
        <StrategyList strategies={snapshot.strategies} />
        <TradeBlotter openOrders={snapshot.open_orders} fills={snapshot.recent_fills} />
      </section>

      <section className="ledger-grid">
        <HoldingsTable positions={snapshot.positions} />
        <ControlLedger timeline={snapshot.timeline} />
      </section>
    </section>
  );
}

function FundingRail({ funding = emptySnapshot.funding }) {
  const available = venueAmount(funding.available_budget_usdc_by_venue);
  const settled = venueAmount(funding.settled_amount_usdc_by_venue);
  const isOnline = funding.status === "ok";
  const bridgeStatus = funding.bridge_status || (isOnline ? "waiting" : "offline");
  const pusdBuyingPower = funding.pusd_buying_power_usdc || "0";
  const settlementRail = funding.settlement_rail || "unknown";
  const railLabel = settlementRail === "clink_native_facilitator" ? "Clink Native" : settlementRail.replaceAll("_", " ");

  return (
    <section className={`funding-rail ${isOnline ? "online" : "offline"}`} aria-label="x402 Funding Rail">
      <span className="funding-beam" aria-hidden="true" />
      <div className="funding-main">
        <p className="eyebrow">x402 Funding Rail</p>
        <h2>{isOnline ? "Signed budget is visible to the agent." : "Funding rail waiting for Clink Core."}</h2>
        <small>
          Wallet signature stays with the user. Agentonomy can request funding through Clink, while policy, receipt, and venue bridge state remain audit-ready.
        </small>
        {funding.error && <em>{funding.error}</em>}
      </div>
      <div className="funding-cell positive">
        <span>Polymarket spending cap</span>
        <strong>{usdc(available)}</strong>
      </div>
      <div className="funding-cell">
        <span>x402 settled</span>
        <strong>{usdc(settled)}</strong>
      </div>
      <div className="funding-cell">
        <span>Receipts</span>
        <strong>{funding.receipt_count}</strong>
      </div>
      <div className="funding-cell">
        <span>Latest tx</span>
        <strong>{shortHash(funding.latest_receipt_tx_hash)}</strong>
      </div>
      <div className="funding-cell warning">
        <span>Bridge state</span>
        <strong>{bridgeStatus}</strong>
      </div>
      <div className="funding-cell">
        <span>Deposit wallet</span>
        <strong>{shortHash(funding.polymarket_deposit_address)}</strong>
      </div>
      <div className="funding-cell positive">
        <span>pUSD buying power</span>
        <strong>{usdc(pusdBuyingPower)}</strong>
      </div>
      <div className={`funding-cell ${funding.native_facilitator_ready ? "positive" : "warning"}`}>
        <span>Settlement rail</span>
        <strong>{railLabel}</strong>
      </div>
      <div className="funding-cell">
        <span>Gas relayer</span>
        <strong>{shortHash(funding.relayer_address)}</strong>
      </div>
    </section>
  );
}

function AccountControl({ onPortfolioRefresh }) {
  const {
    userId,
    coreAccount,
    binding,
    fundingStatus,
    depositWalletReadiness,
    status,
    error,
    actionState,
    refresh,
    openCoreAccount,
    revokePolymarketBinding,
    revokeFundingAuthorization,
  } = useAccountControl();
  const activeAuthorization = pickActiveAuthorization(fundingStatus);
  const coreWalletBound = Boolean(coreAccount.wallet_bound);
  const coreSpendingReady = Boolean(coreAccount.spending_grant_active);
  const bindingActive = binding.status === "active";
  const fundingActive = coreSpendingReady;
  const fundingRoute = resolveDashboardFundingRoute(binding);

  async function handleRefresh() {
    await refresh();
    onPortfolioRefresh?.();
  }

  async function handleRevokeBinding() {
    try {
      await revokePolymarketBinding();
      onPortfolioRefresh?.();
    } catch (err) {
      window.alert(err.message || "Failed to unbind Polymarket account");
    }
  }

  async function handleRevokeFunding() {
    try {
      await revokeFundingAuthorization(activeAuthorization);
      onPortfolioRefresh?.();
    } catch (err) {
      window.alert(err.message || "Failed to revoke wallet authorization");
    }
  }

  async function handleOpenCoreAccount() {
    try {
      await openCoreAccount();
    } catch (err) {
      window.alert(err.message || "Failed to open Core Account");
    }
  }

  return (
    <section className={`account-control ${status}`} aria-label="Account Control">
      <div className="section-kicker">
        <p className="eyebrow">Account Control</p>
        <span>{userId}</span>
      </div>
      <div className={`funding-route ${fundingRoute.status}`}>
        <div>
          <p className="eyebrow">Funding Route</p>
          <h3>{fundingRoute.label}</h3>
          <small>{fundingRoute.reason}</small>
        </div>
        <span className="route-badge">Default: {fundingRoute.defaultRoute}</span>
        <span className="route-badge">x402 funding: {fundingRoute.x402Status}</span>
        <span className="route-badge">Target: {shortHash(fundingRoute.target)}</span>
      </div>
      <div className="account-grid">
        <article className={`account-card ${coreWalletBound ? "online" : "warning"}`}>
          <span>Core Account</span>
          <strong>{coreWalletBound ? "wallet bound" : "setup required"}</strong>
          <small>{coreSpendingReady ? "Shared spending grant active." : "Open Core Account to bind a wallet and authorize a spending cap."}</small>
          <small>{coreAccount.ready ? "Wallet, grant, and chain allowances are ready." : coreAccount.reason || "User-controlled wallet authorization."}</small>
        </article>
        <article className={`account-card ${bindingActive ? "online" : "warning"}`}>
          <span>Polymarket Account</span>
          <strong>{binding.status || "unknown"}</strong>
          <small>
            {bindingActive
              ? `${binding.account_mode || "account"} · ${shortHash(binding.funder_address || binding.wallet_address)}`
              : binding.next_action || "create_polymarket_account_binding"}
          </small>
          <small>{binding.api_key_fingerprint || binding.reason || "CLOB credential fingerprint appears after binding."}</small>
        </article>
        <article className={`account-card ${fundingActive ? "online" : "warning"}`}>
          <span>Wallet spending cap</span>
          <strong>{fundingActive ? (activeAuthorization ? usdc(activeAuthorization.remaining_amount_usdc) : "active") : "not active"}</strong>
          <small>
            {activeAuthorization?.spending_authorization_id || (fundingActive ? "Managed by Core Account" : "Authorize a spending cap from Core Account before agent-managed top-up.")}
          </small>
          <small>
            {fundingActive && activeAuthorization
              ? `limit ${usdc(activeAuthorization.max_amount_usdc)} · per order ${usdc(activeAuthorization.per_order_limit_usdc)}`
              : fundingActive
              ? "Shared spending limits are managed in Core Account."
              : "No active spending cap for Polymarket."}
          </small>
        </article>
        <article className="account-card">
          <span>Core wallet</span>
          <strong>{coreWalletBound ? "verified" : "not bound"}</strong>
          <small>Agentonomy cannot read private keys. Core stores only wallet identity and signed permissions.</small>
        </article>
        <article className={`account-card ${depositWalletReadiness.can_use_x402 ? "online" : "warning"}`}>
          <span>Deposit wallet readiness</span>
          <strong>{depositWalletReadiness.status || "unknown"}</strong>
          <small>{depositWalletReadiness.deposit_wallet ? shortHash(depositWalletReadiness.deposit_wallet) : depositWalletReadiness.next_action || "waiting"}</small>
          <small>
            {depositWalletReadiness.missing?.length
              ? `Missing ${depositWalletReadiness.missing.join(", ")}`
              : depositWalletReadiness.can_use_x402
              ? "x402 target can be resolved from Clink."
              : depositWalletReadiness.reason || "No deposit wallet prepared yet."}
          </small>
        </article>
        <article className="account-card">
          <span>Control status</span>
          <strong>{status}</strong>
          <small>{actionState || error || "Refreshes every 20s with the rest of the dashboard."}</small>
        </article>
      </div>
      <div className="account-actions">
        <button onClick={handleOpenCoreAccount}>Open Core Account</button>
        <button onClick={handleRefresh}>Refresh account control</button>
        <button className="danger-button" disabled={!binding?.binding_id || !bindingActive} onClick={handleRevokeBinding}>
          Unbind Polymarket account
        </button>
        <button
          className="danger-button"
          disabled={!activeAuthorization?.spending_authorization_id}
          onClick={handleRevokeFunding}
        >
          Revoke spending cap
        </button>
      </div>
    </section>
  );
}

function ActiveThesis({ strategy, summary }) {
  const reasoning = strategy?.agent_reasoning?.slice(0, 3) || [];
  const tone = metricTone(strategy?.total_pnl_usd);
  return (
    <section className="thesis-ledger">
      <div className="section-kicker">
        <p className="eyebrow">Active Signal</p>
        <span>{strategy ? strategy.status : "unattributed"}</span>
      </div>
      <div className="thesis-main">
        <div>
          <h2>{strategy?.topic || "No strategy attributed yet"}</h2>
          <p>
            {strategy?.hypothesis ||
              "Ask Agentonomy to scan a market and explain the opportunity. Clink records the idea, preview, execution, and outcome here."}
          </p>
        </div>
        <div className={`thesis-pnl ${tone}`}>
          <span>Strategy PnL</span>
          <strong>{money(strategy?.total_pnl_usd)}</strong>
          <small>{strategy?.total_pnl_pct || "0.00"}%</small>
        </div>
      </div>
      <div className="thesis-grid">
        <Signal label="Capital" value={money(strategy?.capital_deployed_usd)} />
        <Signal label="Marked value" value={money(strategy?.current_value_usd)} />
        <Signal label="Platforms" value={strategy?.platforms?.join(" / ") || "none"} />
        <Signal label="Current leader" value={summary.best_strategy_id || "none"} />
      </div>
      <div className="reasoning-stack">
        {reasoning.length === 0 && <p>No Agentonomy reasoning attached yet. The next recorded idea will populate this trail.</p>}
        {reasoning.map((line) => (
          <p key={line}>{line}</p>
        ))}
      </div>
    </section>
  );
}

function StrategyList({ strategies }) {
  return (
    <section className="strategy-list">
      <div className="section-kicker">
        <p className="eyebrow">Thesis History</p>
        <span>{strategies.length} tracked</span>
      </div>
      <div className="strategy-table">
        {strategies.length === 0 && <p className="empty">Agentonomy-attributed theses appear here after it links ideas or trades to a strategy.</p>}
        {strategies.slice(0, 6).map((strategy) => (
          <div className="strategy-row" key={strategy.strategy_id}>
            <div>
              <strong>{strategy.topic}</strong>
              <small>{strategy.platforms?.join(" / ") || "unattributed"}</small>
            </div>
            <span>{money(strategy.capital_deployed_usd)}</span>
            <b className={metricTone(strategy.total_pnl_usd)}>{money(strategy.total_pnl_usd)}</b>
          </div>
        ))}
      </div>
    </section>
  );
}

function ClinkGate({ summary, timeline, pendingActions, status }) {
  const policyEvents = timeline.filter((item) => item.policy_decision_id).length;
  const auditEvents = timeline.reduce((count, item) => count + (item.audit_event_ids?.length || 0), 0);
  const gateItems = [
    ["Portfolio view", status],
    ["Auto sync", summary.sync_status || "unknown"],
    ["Policy decisions", policyEvents],
    ["Audit links", auditEvents],
    ["Human confirmations", pendingActions.length],
  ];
  return (
    <aside className="audit-strip" aria-label="Clink Gate">
      <div className="section-kicker">
        <p className="eyebrow">Clink Audit Strip</p>
        <span>{summary.sync_stale ? "stale" : "live"}</span>
      </div>
      <h2>Every trade leaves a control trail.</h2>
      <div className="gate-stack">
        {gateItems.map(([label, value]) => (
          <div key={label}>
            <span>{label}</span>
            <strong>{value}</strong>
          </div>
        ))}
      </div>
      <small>Last sync {timeLabel(summary.last_synced_at)}. Agentonomy is the interface; this panel only explains what Clink recorded.</small>
    </aside>
  );
}

function TradeBlotter({ openOrders, fills }) {
  const rows = [
    ...openOrders.slice(0, 5).map((order) => ({
      id: `${order.platform}-${order.order_id}`,
      type: "order",
      time: order.created_at || order.updated_at,
      platform: order.platform,
      title: order.title || order.market_id,
      side: `${order.side} ${order.outcome}`,
      price: order.limit_price,
      size: `${order.filled_contracts}/${order.contracts}`,
      status: order.status || "open",
      pnl: "--",
      clink: order.policy_decision_id ? "Policy OK" : "Recorded",
      amount: money(order.cost_basis_usd),
    })),
    ...fills.slice(0, 5).map((fill) => ({
      id: `${fill.platform}-${fill.fill_id}`,
      type: "fill",
      time: fill.created_at || fill.filled_at,
      platform: fill.platform,
      title: fill.market_id,
      side: `${fill.side} ${fill.outcome}`,
      price: fill.price,
      size: fill.contracts,
      status: "filled",
      pnl: money(fill.realized_pnl_usd),
      clink: fill.audit_event_ids?.length ? `${fill.audit_event_ids.length} audit` : "Synced",
      amount: money(fill.amount_usd),
    })),
  ];

  return (
    <section className="trade-blotter">
      <div className="section-kicker">
        <p className="eyebrow">Trade Blotter</p>
        <span>{rows.length} reconciled</span>
      </div>
      {rows.length === 0 ? (
        <p className="empty">Venue orders and fills appear after execution and automatic sync.</p>
      ) : (
        <div className="blotter-table" role="table" aria-label="Trade Blotter">
          <div className="blotter-head" role="row">
            <span>Time</span>
            <span>Market</span>
            <span>Side</span>
            <span>Price</span>
            <span>Size</span>
            <span>Status</span>
            <span>PnL</span>
            <span>Clink</span>
          </div>
          {rows.map((row) => (
            <div className={`blotter-row ${row.type}`} role="row" key={row.id}>
              <span>{timeLabel(row.time)}</span>
              <strong>{row.title}</strong>
              <span>{row.side}</span>
              <span>{row.price ?? "--"}</span>
              <span>{row.size ?? "--"}</span>
              <span>{row.status}</span>
              <b className={metricTone(row.pnl)}>{row.pnl}</b>
              <span>{row.clink}</span>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

function HoldingsTable({ positions }) {
  return (
    <section className="holdings-table">
      <div className="section-kicker">
        <p className="eyebrow">Holdings Table</p>
        <span>{positions.length} open</span>
      </div>
      {positions.length === 0 ? (
        <p className="empty">Holdings appear here automatically after live execution and venue reconciliation.</p>
      ) : (
        <div className="holding-list">
          {positions.slice(0, 8).map((position) => (
            <div className="holding-row" key={position.position_id}>
              <div>
                <strong>{position.title}</strong>
                <small>
                  {position.platform} · {position.side} {position.outcome} · {position.contracts} contracts
                </small>
              </div>
              <span>{money(position.current_value_usd)}</span>
              <span>
                {position.entry_price ?? "--"} {"->"} {position.current_price ?? "--"}
              </span>
              <b className={metricTone(position.unrealized_pnl_usd)}>{money(position.unrealized_pnl_usd)}</b>
            </div>
          ))}
        </div>
      )}
    </section>
  );
}

function ControlLedger({ timeline }) {
  return (
    <section className="control-ledger">
      <div className="section-kicker">
        <p className="eyebrow">Process Timeline</p>
        <span>{timeline.length} events</span>
      </div>
      <ol>
        {timeline.length === 0 && <p className="empty">Clink action, policy, execution, and audit events appear here as Agentonomy works.</p>}
        {timeline.slice(0, 10).map((item) => (
          <li key={`${item.kind}-${item.id}`}>
            <span>{item.kind}</span>
            <div>
              <strong>{item.description}</strong>
              <small>{item.platform || "clink"} · {item.state || "recorded"} · {item.created_at}</small>
            </div>
          </li>
        ))}
      </ol>
    </section>
  );
}

function App() {
  const { snapshot, status, error, refresh } = usePortfolio();
  const { summary } = snapshot;
  const { workspace, setWorkspace } = useWorkspaceRoute();

  return (
    <main className="shell">
      <div className="scan-layer" aria-hidden="true">
        <span className="radar-grid" />
      </div>
      <header className="hero">
        <div>
          <p className="eyebrow">Clink Prediction Markets</p>
          <h1>{workspace === "account" ? "Bind the rails. Then let Agentonomy work." : "Watch the agent money loop."}</h1>
          <span>
            {workspace === "account"
              ? "One place for wallet binding, Polymarket account binding, x402 funding readiness, and revocation."
              : "Talk to Agentonomy in Telegram. Clink records every market idea, policy gate, execution, holding, and PnL here automatically."}
          </span>
        </div>
        <div className="hero-actions">
          <ProductNav workspace={workspace} setWorkspace={setWorkspace} status={status} summary={summary} />
          <button onClick={refresh}>Refresh view</button>
        </div>
      </header>

      {workspace === "account" ? (
        <AccountWorkspace onPortfolioRefresh={refresh} />
      ) : (
        <TradingWorkspace snapshot={snapshot} status={status} error={error} refresh={refresh} />
      )}
    </main>
  );
}

createRoot(document.getElementById("root")).render(<App />);
