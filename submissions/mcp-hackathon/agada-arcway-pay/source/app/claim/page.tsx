"use client";

import { useLoginWithEmail, usePrivy } from "@privy-io/react-auth";
import Link from "next/link";
import { useRouter, useSearchParams } from "next/navigation";
import { Suspense, useCallback, useEffect, useState } from "react";
import { Wordmark } from "@/components/Brand";
import { StatusBadge } from "@/components/StatusBadge";
import { WithdrawPanel } from "@/components/WithdrawPanel";
import { buttonClasses, Chip, Eyebrow } from "@/components/ui";
import { apiFetch } from "@/lib/client-api";
import type { ClaimSummary } from "@/lib/types";
import { cn, formatUsdc, truncateAddress } from "@/lib/utils";
import { isPrivyClientConfigured } from "../providers";

export default function ClaimPage() {
  if (!isPrivyClientConfigured) return <NotConfigured />;
  return (
    <Suspense fallback={<Shell><div className="py-20 text-center text-[15px] text-ink-mute">Loading…</div></Shell>}>
      <ClaimGate />
    </Suspense>
  );
}

/**
 * Signed-out visitors arriving from the email land here. The `?email=` param
 * only PREFILLS the address field — it is not a credential and grants no
 * access. Privy still emails a one-time code, which is the actual security
 * boundary, so a forwarded link is harmless.
 */
function ClaimGate() {
  const { ready, authenticated, user } = usePrivy();
  const params = useSearchParams();
  const prefill = params.get("email") ?? "";

  if (!ready) {
    return <Shell><div className="py-20 text-center text-[15px] text-ink-mute">Loading…</div></Shell>;
  }
  if (!authenticated) return <SignIn prefill={prefill} />;

  // Arriving from someone else's claim link while already signed in. Without
  // this the page silently shows the wrong person's account — or nothing at
  // all — with no explanation and no way forward.
  const signedInEmail = user?.email?.address?.toLowerCase() ?? null;
  if (prefill && signedInEmail && signedInEmail !== prefill.trim().toLowerCase()) {
    return <WrongIdentity signedInAs={signedInEmail} wanted={prefill.trim()} />;
  }

  return <ClaimInner />;
}

/**
 * The claim link names one address; the browser is signed in as another.
 * Says so plainly and offers the only action that helps — signing out and
 * returning here with the link's address intact, so the flow resumes rather
 * than restarting.
 */
function WrongIdentity({ signedInAs, wanted }: { signedInAs: string; wanted: string }) {
  const { logout } = usePrivy();
  const [busy, setBusy] = useState(false);

  async function switchAccount() {
    setBusy(true);
    try {
      // No navigation needed: the URL already carries ?email=<wanted>, so once
      // Privy clears the session this gate re-renders straight into the
      // sign-in form with that address prefilled.
      await logout();
    } finally {
      setBusy(false);
    }
  }

  return (
    <Shell email={signedInAs}>
      <div className="mx-auto max-w-md py-10">
        <h1 className="font-display text-[36px] leading-tight tracking-[-0.01em] text-ink">
          That&rsquo;s a different account
        </h1>
        <p className="mt-4 text-[15px] leading-[1.6] text-ink-soft">
          You&rsquo;re signed in as{" "}
          <span className="font-medium text-ink">{signedInAs}</span>, but this
          payment was sent to{" "}
          <span className="font-medium text-ink">{wanted}</span>.
        </p>

        <div className="mt-6 rounded-card border border-amber-100 bg-amber-50 p-5">
          <p className="text-[14px] leading-[1.6] text-amber-text">
            Sign out and back in as {wanted} to claim it. Nothing is lost in the
            meantime — the money stays in that wallet until it&rsquo;s claimed.
          </p>
        </div>

        <button
          onClick={switchAccount}
          disabled={busy}
          className={buttonClasses("primary", "lg", "mt-6 w-full sm:w-auto")}
        >
          {busy ? "Signing out…" : `Sign out and claim as ${wanted}`}
        </button>

        <p className="mt-4 text-[13px] text-ink-mute">
          Or{" "}
          <Link href="/claim" className="text-emerald underline underline-offset-2">
            stay signed in as {signedInAs}
          </Link>{" "}
          and view your own payments.
        </p>
      </div>
    </Shell>
  );
}

function SignIn({ prefill }: { prefill: string }) {
  const { sendCode, loginWithCode } = useLoginWithEmail();
  const [email, setEmail] = useState(prefill);
  const [code, setCode] = useState("");
  const [stage, setStage] = useState<"email" | "code">("email");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function submitEmail() {
    setBusy(true);
    setError(null);
    try {
      await sendCode({ email: email.trim() });
      setStage("code");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not send the code.");
    } finally {
      setBusy(false);
    }
  }

  async function submitCode() {
    setBusy(true);
    setError(null);
    try {
      await loginWithCode({ code: code.trim() });
    } catch (err) {
      setError(err instanceof Error ? err.message : "That code was not accepted.");
      setBusy(false);
    }
  }

  const inputClasses =
    "mt-2 w-full rounded-btn border border-line bg-card px-3 py-2.5 text-[15px] text-ink " +
    "outline-none placeholder:text-ink-mute focus:border-emerald";

  return (
    <Shell>
      <div className="mx-auto max-w-md py-10">
        <h1 className="font-display text-[36px] leading-tight tracking-[-0.01em] text-ink">
          Claim your payment
        </h1>
        <p className="mt-3 text-[15px] leading-[1.6] text-ink-soft">
          {stage === "email"
            ? "Sign in with the email address you were paid at. We'll send you a one-time code."
            : `We sent a code to ${email}. Enter it below.`}
        </p>

        {stage === "email" ? (
          <div className="mt-8">
            <label htmlFor="claim-email" className="text-[13px] font-medium text-ink-soft">
              Email address
            </label>
            <input
              id="claim-email"
              type="email"
              autoFocus
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@example.com"
              className={inputClasses}
            />
            <button
              onClick={submitEmail}
              disabled={busy || !email.trim()}
              className={buttonClasses("primary", "lg", "mt-5 w-full")}
            >
              {busy ? "Sending…" : "Send me a code"}
            </button>
          </div>
        ) : (
          <div className="mt-8">
            <label htmlFor="claim-code" className="text-[13px] font-medium text-ink-soft">
              One-time code
            </label>
            <input
              id="claim-code"
              autoFocus
              inputMode="numeric"
              value={code}
              onChange={(e) => setCode(e.target.value)}
              placeholder="123456"
              className={inputClasses}
            />
            <button
              onClick={submitCode}
              disabled={busy || !code.trim()}
              className={buttonClasses("primary", "lg", "mt-5 w-full")}
            >
              {busy ? "Checking…" : "Sign in"}
            </button>
          </div>
        )}

        {error && <p className="mt-3 text-[13px] text-amber-text">{error}</p>}
      </div>
    </Shell>
  );
}

function NotConfigured() {
  return (
    <Shell>
      <div className="py-16 text-center text-[15px] text-ink-mute">
        Sign-in isn&rsquo;t configured on this server.
      </div>
    </Shell>
  );
}

function ClaimInner() {
  const { ready, authenticated } = usePrivy();
  const router = useRouter();
  const [summary, setSummary] = useState<ClaimSummary | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    if (ready && !authenticated) router.replace("/");
  }, [ready, authenticated, router]);

  const load = useCallback(async () => {
    const res = await apiFetch("/api/claim");
    if (!res.ok) {
      const body = await res.json().catch(() => ({}));
      throw new Error(body.error ?? "Could not load your account.");
    }
    setSummary(await res.json());
  }, []);

  useEffect(() => {
    if (!ready || !authenticated) return;
    let cancelled = false;
    (async () => {
      try {
        await load();
      } catch (err) {
        if (!cancelled) setError(err instanceof Error ? err.message : "Something went wrong.");
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [ready, authenticated, load]);

  if (!ready || !authenticated || loading) {
    return (
      <Shell>
        <div className="py-20 text-center text-[15px] text-ink-mute">Loading…</div>
      </Shell>
    );
  }

  if (error || !summary) {
    return (
      <Shell>
        <div className="mx-auto max-w-md py-10">
          <h1 className="font-display text-[36px] leading-tight tracking-[-0.01em] text-ink">
            Nothing to claim yet
          </h1>
          <p className="mt-4 text-[15px] leading-[1.6] text-ink-soft">{error}</p>
          <p className="mt-4 text-[14px] leading-[1.6] text-ink-mute">
            If you were expecting a payment, check that you signed in with the
            same address it was sent to.
          </p>
          <Link href="/" className={buttonClasses("secondary", "md", "mt-6")}>
            Back to Arcway
          </Link>
        </div>
      </Shell>
    );
  }

  const employers = summary.accounts.length;

  return (
    <Shell email={summary.email}>
      <h1 className="mt-2 font-display text-[40px] leading-none tracking-[-0.01em] text-ink">
        Your money
      </h1>
      <p className="mt-3 text-[15px] leading-[1.6] text-ink-soft">
        {employers === 0
          ? "Nobody has paid you through Arcway yet."
          : `Paid by ${employers} ${employers === 1 ? "company" : "companies"}, shown together.`}
      </p>

      <BalanceCard summary={summary} />
      <WithdrawPanel
        balanceUsdc={summary.balance.amountUsdc}
        walletAddress={summary.walletAddress}
        live={summary.withdrawalsLive}
        onComplete={load}
      />
      <WalletCard address={summary.walletAddress} />
      <TrustNote />
      <Activity summary={summary} />
    </Shell>
  );
}

function Shell({ children, email }: { children: React.ReactNode; email?: string }) {
  // `authenticated` gates the sign-out control: the signed-out claim screen
  // has nothing to sign out of.
  const { authenticated, logout } = usePrivy();
  const router = useRouter();

  // Sign out leaves the claim flow entirely and lands on the marketing page,
  // matching the dashboard. Without the redirect, logging out just re-renders
  // this route into its own sign-in form, which reads as "it didn't work".
  //
  // Note this is deliberately NOT what the wrong-identity screen does: there,
  // signing out is a step *within* the claim flow, so it stays put and
  // re-renders into the prefilled sign-in for the address on the link.
  async function signOutToHome() {
    await logout();
    router.replace("/");
  }

  return (
    <div className="flex min-h-screen flex-col">
      <header className="sticky top-0 z-40 border-b border-line bg-card">
        <div className="mx-auto flex max-w-3xl items-center justify-between px-6 py-5">
          <Link href="/" className="text-ink">
            <Wordmark />
          </Link>
          <div className="flex items-center gap-3">
            {email && <span className="hidden text-sm text-ink-soft sm:inline">{email}</span>}
            {authenticated && (
              <button
                onClick={signOutToHome}
                className={buttonClasses("quiet", "sm")}
              >
                Sign out
              </button>
            )}
          </div>
        </div>
      </header>
      <main className="mx-auto w-full max-w-3xl flex-1 px-6 py-10">{children}</main>
    </div>
  );
}

function BalanceCard({ summary }: { summary: ClaimSummary }) {
  return (
    <div className="mt-8 rounded-card border border-emerald-100 bg-emerald-50 p-8">
      <Eyebrow className="text-emerald">Balance</Eyebrow>
      <div className="mt-3 text-[44px] leading-none font-semibold text-emerald">
        {formatUsdc(summary.balance.amountUsdc)}{" "}
        <span className="text-[24px]">USDC</span>
      </div>
      <div className="mt-4 flex flex-wrap items-center gap-3">
        {summary.balance.simulated ? (
          <Chip tone="amber">Simulated balance</Chip>
        ) : (
          <Chip tone="emerald">Read from chain</Chip>
        )}
        <span className="text-[13px] text-ink-soft">
          {summary.balance.simulated
            ? `Derived from this app's ${summary.balance.source} — no chain was read.`
            : "Live on-chain balance for your wallet."}
        </span>
      </div>
    </div>
  );
}

function WalletCard({ address }: { address: string | null }) {
  const [copied, setCopied] = useState(false);

  async function copy() {
    if (!address) return;
    try {
      await navigator.clipboard.writeText(address);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch {
      // Clipboard can be blocked; the address is on screen either way.
    }
  }

  return (
    <div className="mt-4 rounded-card border border-line bg-card p-6">
      <Eyebrow>Your wallet</Eyebrow>
      <div className="mt-3 flex flex-wrap items-center gap-3">
        <code className="min-w-0 break-all font-mono text-[13px] text-ink">
          {address ?? "No wallet yet"}
        </code>
        {address && (
          <button onClick={copy} className={buttonClasses("secondary", "sm")}>
            {copied ? "Copied" : "Copy"}
          </button>
        )}
      </div>
    </div>
  );
}

function TrustNote() {
  return (
    <div className="mt-4 rounded-card border border-line bg-card p-6">
      <p className="text-[15px] leading-[1.65] text-ink-soft">
        <span className="font-semibold text-ink">This wallet is yours.</span>{" "}
        It was created in your name when you were first paid, and signing in is
        what put you in control of it. Neither the company that paid you nor
        Arcway can move these funds.
      </p>
    </div>
  );
}

/**
 * One chronological stream of money in and money out, newest first, with the
 * balance each line produced.
 *
 * Payments and withdrawals used to be two separate tables, which made the
 * balance impossible to follow: you could see a number at the top and two
 * lists underneath, with no way to trace how one became the other. A running
 * balance column is the whole point of putting them together.
 */
function Activity({ summary }: { summary: ClaimSummary }) {
  if (summary.ledger.length === 0) {
    return (
      <div className="mt-8 rounded-card border border-dashed border-line bg-card p-12 text-center text-[15px] text-ink-mute">
        Nothing yet. When someone pays you, it shows up here.
      </div>
    );
  }

  return (
    <div className="mt-8">
      <Eyebrow>Activity</Eyebrow>
      <div className="mt-3 overflow-hidden rounded-card border border-line bg-card">
        <ul>
          {summary.ledger.map((entry) => (
            <li
              key={`${entry.kind}-${entry.id}`}
              className="flex flex-wrap items-center justify-between gap-4 border-b border-line-soft px-5 py-4 last:border-0"
            >
              <div className="min-w-0">
                {entry.kind === "payment" ? (
                  <>
                    <div className="font-medium text-ink">
                      {entry.companyName} paid you
                    </div>
                    {entry.transferId && (
                      <div className="mt-1 font-mono text-[12px] text-ink-mute">
                        {entry.transferId}
                      </div>
                    )}
                  </>
                ) : (
                  <>
                    <Link
                      href={`/claim/withdrawals/${entry.id}`}
                      className="font-medium text-ink underline decoration-line underline-offset-2 hover:decoration-emerald"
                    >
                      Withdrawn to {truncateAddress(entry.destinationAddress)}
                    </Link>
                    {entry.txHash && (
                      <div className="mt-1 font-mono text-[12px] text-ink-mute">
                        {truncateAddress(entry.txHash, 6)}
                      </div>
                    )}
                  </>
                )}
                <div className="mt-0.5 text-[13px] text-ink-mute">
                  {new Date(entry.at).toLocaleString()}
                </div>
              </div>

              <div className="flex shrink-0 items-center gap-4">
                {entry.kind === "withdrawal" && entry.simulated && (
                  <Chip tone="amber">Simulated</Chip>
                )}
                <StatusBadge status={entry.status} />
                <div className="text-right">
                  <div
                    className={cn(
                      "font-medium",
                      entry.kind === "payment" ? "text-emerald" : "text-ink-mute"
                    )}
                  >
                    {entry.kind === "payment" ? "+" : "\u2212"}
                    {formatUsdc(Math.abs(entry.amountUsdc))}{" "}
                    <span className="text-ink-mute">USDC</span>
                  </div>
                  <div className="mt-0.5 text-[12px] text-ink-mute">
                    balance {formatUsdc(entry.balanceAfter)}
                  </div>
                </div>
              </div>
            </li>
          ))}
        </ul>
      </div>
    </div>
  );
}
