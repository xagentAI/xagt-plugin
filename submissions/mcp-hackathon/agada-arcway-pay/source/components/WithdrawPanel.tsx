"use client";

import { useSendTransaction } from "@privy-io/react-auth";
import { useCallback, useMemo, useState } from "react";
import { buttonClasses, Chip, Eyebrow } from "@/components/ui";
import { ARC_USDC_ADDRESS } from "@/lib/chain";
import { apiFetch } from "@/lib/client-api";
import {
  encodeUsdcTransfer,
  nativeBalanceUsdc,
  quoteGas,
  type GasQuote,
} from "@/lib/withdraw-client";
import { cn, formatUsdc } from "@/lib/utils";

/** Fee shown before a real quote arrives, and used by the mock path. */
const FALLBACK_FEE_USDC = 0.01;

interface Success {
  txHash: string;
  amountUsdc: number;
  destinationAddress: string;
  simulated: boolean;
}

const inputClasses =
  "mt-2 w-full rounded-btn border border-line bg-card px-3 py-2.5 text-[15px] text-ink " +
  "outline-none placeholder:text-ink-mute focus:border-emerald";

export function WithdrawPanel({
  balanceUsdc,
  walletAddress,
  live,
  onComplete,
}: {
  balanceUsdc: number;
  /** The payee's embedded wallet — the account that signs. */
  walletAddress: string | null;
  /** True when signing happens for real on Arc; false runs the mock path. */
  live: boolean;
  onComplete: () => void | Promise<void>;
}) {
  const { sendTransaction } = useSendTransaction();

  const [open, setOpen] = useState(false);
  const [amount, setAmount] = useState("");
  const [destination, setDestination] = useState("");
  const [confirming, setConfirming] = useState(false);
  const [busy, setBusy] = useState(false);
  const [stage, setStage] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [success, setSuccess] = useState<Success | null>(null);
  const [quote, setQuote] = useState<GasQuote | null>(null);

  const parsed = Number(amount);
  const valid = Number.isFinite(parsed) && parsed > 0;

  // Gas is estimated for the REAL transfer — this calldata, this sender — not
  // assumed. On Arc the fee comes out of the same balance as the money, so a
  // wrong estimate is the difference between a withdrawal and a failed one.
  const refreshQuote = useCallback(async () => {
    if (!live || !walletAddress) return;
    const probeAmount = valid ? parsed : Math.min(balanceUsdc, 0.01);
    if (probeAmount <= 0) return;
    try {
      setQuote(await quoteGas(walletAddress, destination || walletAddress, probeAmount));
    } catch {
      // Leave the previous quote in place rather than blanking the fee line.
    }
  }, [live, walletAddress, destination, parsed, valid, balanceUsdc]);

  const feeUsdc = quote?.feeUsdc ?? FALLBACK_FEE_USDC;
  const maxSendable = live
    ? quote?.maxSendableUsdc ?? Math.max(0, balanceUsdc - FALLBACK_FEE_USDC)
    : Math.max(0, balanceUsdc - FALLBACK_FEE_USDC);

  const receives = useMemo(() => (valid ? parsed : 0), [valid, parsed]);
  const total = receives > 0 ? receives + feeUsdc : 0;
  const overBalance = total > balanceUsdc + 1e-9;

  async function submit() {
    setBusy(true);
    setError(null);
    try {
      if (live) await withdrawOnChain();
      else await withdrawSimulated();
      await onComplete();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not complete the withdrawal.");
    } finally {
      setBusy(false);
      setStage(null);
      setConfirming(false);
    }
  }

  /** Mock mode: unchanged, and still the path reviewers exercise. */
  async function withdrawSimulated() {
    const res = await apiFetch("/api/claim/withdraw", {
      method: "POST",
      body: JSON.stringify({ amountUsdc: parsed, destinationAddress: destination.trim() }),
    });
    const data = await res.json();
    if (!res.ok) throw new Error(data.error ?? "Could not complete the withdrawal.");
    setSuccess(data);
  }

  /**
   * Live path. ORDER MATTERS:
   *   1. assert affordability against the real balance
   *   2. sign + broadcast in the browser
   *   3. only then tell the server the hash
   *
   * Nothing is written before broadcast: a row with no hash is unresolvable.
   * If the browser dies between 2 and 3 the money still moved and the chain is
   * the record, which is recoverable — the reverse is not.
   */
  async function withdrawOnChain() {
    if (!walletAddress) throw new Error("No wallet to withdraw from.");

    setStage("Checking the network fee…");
    const fresh = await quoteGas(walletAddress, destination.trim(), parsed);
    setQuote(fresh);

    const onChainBalance = await nativeBalanceUsdc(walletAddress);
    if (parsed + fresh.feeUsdc > onChainBalance + 1e-9) {
      // Refuse BEFORE broadcasting or writing anything, with the real numbers.
      throw new Error(
        `Not enough to cover this. You hold ${formatUsdc(onChainBalance)} USDC; ` +
          `sending ${formatUsdc(parsed)} plus about ${formatUsdc(fresh.feeUsdc)} in ` +
          `network fees needs ${formatUsdc(parsed + fresh.feeUsdc)}. ` +
          `The most you can send right now is ${formatUsdc(fresh.maxSendableUsdc)}.`
      );
    }

    setStage("Waiting for you to approve…");
    const { hash } = await sendTransaction({
      to: ARC_USDC_ADDRESS,
      data: encodeUsdcTransfer(destination.trim(), parsed),
      value: 0,
    });

    setStage("Recording it…");
    await recordWithRetry(hash, fresh.feeUsdc);

    setSuccess({
      txHash: hash,
      amountUsdc: parsed,
      destinationAddress: destination.trim(),
      simulated: false,
    });

    void pollUntilSettled(hash);
  }

  /**
   * The recovery path: the money has already moved, so this must not give up
   * easily. Retries with backoff; if every attempt fails the hash is surfaced
   * so the withdrawal can still be traced on chain.
   */
  async function recordWithRetry(txHash: string, fee: number) {
    const delays = [0, 1000, 3000, 6000];
    let lastError: unknown;
    for (const delay of delays) {
      if (delay) await new Promise((r) => setTimeout(r, delay));
      try {
        const res = await apiFetch("/api/claim/withdraw/record", {
          method: "POST",
          body: JSON.stringify({
            txHash,
            amountUsdc: parsed,
            feeUsdc: fee,
            destinationAddress: destination.trim(),
          }),
        });
        if (res.ok) return;
        lastError = new Error((await res.json()).error ?? "Record failed.");
      } catch (err) {
        lastError = err;
      }
    }
    console.error("Could not record broadcast withdrawal:", lastError);
    setError(
      `Your withdrawal was sent (${txHash.slice(0, 10)}…) but we couldn't record it. ` +
        `The money has moved — the transaction is on chain. Refresh in a moment.`
    );
  }

  /** Ask the server to confirm against the chain until it settles. */
  async function pollUntilSettled(txHash: string) {
    for (let i = 0; i < 20; i++) {
      await new Promise((r) => setTimeout(r, 3000));
      try {
        const res = await apiFetch("/api/claim/withdraw/settle", {
          method: "POST",
          body: JSON.stringify({ txHash }),
        });
        const data = await res.json();
        if (res.ok && data.settled) {
          await onComplete();
          return;
        }
      } catch {
        // Keep trying; the chain is the source of truth either way.
      }
    }
  }

  function reset() {
    setSuccess(null);
    setAmount("");
    setDestination("");
    setError(null);
    setQuote(null);
    setOpen(false);
  }

  if (success) {
    return (
      <div className="mt-4 rounded-card border border-emerald-100 bg-emerald-50 p-6">
        <Eyebrow className="text-emerald">Withdrawal sent</Eyebrow>
        <div className="mt-3 text-[24px] leading-none font-semibold text-emerald">
          {formatUsdc(success.amountUsdc)} USDC
        </div>
        <div className="mt-3 text-[14px] text-ink-soft">
          to <span className="font-mono text-[13px]">{success.destinationAddress}</span>
        </div>
        <div className="mt-3">
          <Eyebrow>Transaction hash</Eyebrow>
          <div className="mt-1 break-all font-mono text-[12px] text-ink-soft">
            {success.txHash}
          </div>
        </div>
        <div className="mt-4">
          {success.simulated ? (
            <Chip tone="amber">Simulated — no chain was touched</Chip>
          ) : (
            <Chip tone="emerald">Broadcast on Arc — confirming</Chip>
          )}
        </div>
        {error && <p className="mt-3 text-[13px] text-amber-text">{error}</p>}
        <button onClick={reset} className={buttonClasses("secondary", "md", "mt-5")}>
          Done
        </button>
      </div>
    );
  }

  if (!open) {
    return (
      <div className="mt-4 flex flex-wrap gap-3">
        <button
          onClick={() => {
            setOpen(true);
            // Quote as soon as the form appears, so the fee line is populated
            // before the user reaches it.
            void refreshQuote();
          }}
          disabled={balanceUsdc <= 0}
          className={buttonClasses("primary", "lg")}
        >
          Withdraw
        </button>
        <CashOutToBank />
      </div>
    );
  }

  return (
    <div className="mt-4 rounded-card border border-line bg-card p-6">
      <Eyebrow>Withdraw USDC</Eyebrow>

      <div className="mt-4">
        <div className="flex items-end justify-between gap-3">
          <label htmlFor="wd-amount" className="text-[13px] font-medium text-ink-soft">
            Amount
          </label>
          <button
            onClick={() => setAmount(maxSendable.toFixed(2))}
            className="text-[13px] text-emerald underline underline-offset-2"
          >
            Max ({formatUsdc(maxSendable)})
          </button>
        </div>
        <input
          id="wd-amount"
          type="number"
          min="0"
          step="0.01"
          value={amount}
          onChange={(e) => setAmount(e.target.value)}
          onBlur={() => void refreshQuote()}
          placeholder="0.00"
          className={inputClasses}
        />
      </div>

      <div className="mt-4">
        <label htmlFor="wd-dest" className="text-[13px] font-medium text-ink-soft">
          Destination address
        </label>
        <input
          id="wd-dest"
          value={destination}
          onChange={(e) => setDestination(e.target.value)}
          onBlur={() => void refreshQuote()}
          placeholder="0x…"
          className={cn(inputClasses, "font-mono text-[13px]")}
        />
      </div>

      <dl className="mt-5 border-t border-line-soft pt-4 text-[14px]">
        <div className="flex justify-between py-1">
          <dt className="text-ink-soft">You send</dt>
          <dd className="font-medium text-ink">{formatUsdc(receives)} USDC</dd>
        </div>
        <div className="flex justify-between py-1">
          <dt className="text-ink-soft">
            Network fee{" "}
            <span className="text-ink-mute">
              {live ? (quote ? "(estimated)" : "(estimating…)") : "(simulated)"}
            </span>
          </dt>
          <dd className="text-ink-soft">{formatUsdc(feeUsdc)} USDC</dd>
        </div>
        <div className="flex justify-between border-t border-line-soft py-2 pt-3">
          <dt className="font-medium text-ink">Total from your balance</dt>
          <dd className={cn("font-semibold", overBalance ? "text-amber-text" : "text-ink")}>
            {formatUsdc(total)} USDC
          </dd>
        </div>
      </dl>

      {live && (
        <p className="mt-2 text-[12px] leading-[1.5] text-ink-mute">
          On Arc the network fee is paid in USDC from this same balance, so you
          can&rsquo;t send quite all of it.
        </p>
      )}

      {overBalance && (
        <p className="mt-2 text-[13px] text-amber-text">
          That&rsquo;s more than your balance once the fee is included.
        </p>
      )}

      <div className="mt-5 rounded-card border border-amber-100 bg-amber-50 p-4">
        <p className="text-[13px] leading-[1.6] text-amber-text">
          <strong>This cannot be undone.</strong> Once sent, the money is gone
          from this wallet — check the address character by character. There is
          no way for Arcway to reverse it or recover funds sent to the wrong
          place.
        </p>
      </div>

      {error && <p className="mt-3 text-[13px] text-amber-text">{error}</p>}
      {stage && <p className="mt-3 text-[13px] text-ink-soft">{stage}</p>}

      <div className="mt-5 flex flex-wrap gap-3">
        {confirming ? (
          <>
            <button onClick={submit} disabled={busy} className={buttonClasses("primary", "md")}>
              {busy ? "Working…" : `Yes — send ${formatUsdc(receives)} USDC`}
            </button>
            <button
              onClick={() => setConfirming(false)}
              disabled={busy}
              className={buttonClasses("secondary", "md")}
            >
              Go back
            </button>
          </>
        ) : (
          <>
            <button
              onClick={() => setConfirming(true)}
              disabled={!valid || overBalance || !destination.trim()}
              className={buttonClasses("primary", "md")}
            >
              Review withdrawal
            </button>
            <button onClick={reset} className={buttonClasses("secondary", "md")}>
              Cancel
            </button>
          </>
        )}
      </div>
    </div>
  );
}

function CashOutToBank() {
  return (
    <div className="flex flex-col gap-2">
      <button disabled title="Not available yet" className={buttonClasses("secondary", "lg")}>
        Cash out to bank
        <Chip tone="amber" className="ml-1">Coming soon</Chip>
      </button>
      <p className="max-w-sm text-[12px] leading-[1.5] text-ink-mute">
        Paying out to a bank account needs a licensed off-ramp partner and a
        one-time identity check. That check is required by
        anti-money-laundering law, not by us.
      </p>
    </div>
  );
}
