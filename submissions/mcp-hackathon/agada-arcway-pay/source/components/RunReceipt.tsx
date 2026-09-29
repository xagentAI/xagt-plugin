"use client";

import Link from "next/link";
import { useCallback, useEffect, useId, useRef, useState } from "react";
import { buttonClasses, Chip, Eyebrow } from "@/components/ui";
import { LastSent, ResendNotification } from "@/components/ResendNotification";
import { useSession } from "@/components/SessionContext";
import { apiFetch } from "@/lib/client-api";
import { ARC_TESTNET_RPC, fromNativeWei } from "@/lib/chain";
import type { Payout } from "@/lib/types";
import { formatUsdc, truncateAddress } from "@/lib/utils";

const EXPLORER_TX = "https://testnet.arcscan.app/tx/";

/**
 * A payout's `transferId` is only a chain hash once the transfer has settled.
 * While in flight it is Circle's internal UUID, and in mock mode it is
 * `mock_…` — neither resolves on an explorer, so neither gets a link.
 */
const TX_HASH = /^0x[0-9a-fA-F]{64}$/;

/**
 * A payout run's receipt.
 *
 * Shared by the screen shown immediately after confirming a run, by the
 * permalink at /dashboard/runs/<id>, and by the read-only modal opened from
 * Activity and the dashboard — one renderer, so what you see on camera later
 * is byte-for-byte what you saw at the time, and the views cannot drift.
 */
export function RunReceipt({
  payouts: initial,
  heading,
  subheading,
  mode = "page",
  companyName,
  headingId,
}: {
  payouts: Payout[];
  heading?: string;
  subheading?: string;
  /**
   * "page" is the full interactive receipt. "modal" is read-only and performs
   * NO writes: no status refresh (that route updates rows and sends
   * notifications), no resend, and no navigation away.
   */
  mode?: "page" | "modal";
  companyName?: string;
  headingId?: string;
}) {
  const readOnly = mode === "modal";
  const [payouts, setPayouts] = useState<Payout[]>(initial);

  const [refreshing, setRefreshing] = useState(false);
  const runId = payouts[0]?.runId;
  const settled = payouts.filter((p) => p.status === "sent");
  const inFlight = payouts.filter((p) => p.status === "sending" || p.status === "pending");

  const refresh = useCallback(async () => {
    if (!runId) return;
    setRefreshing(true);
    try {
      const res = await apiFetch(`/api/runs/${runId}/refresh`, { method: "POST" });
      const data = await res.json();
      if (res.ok && data.payouts) setPayouts(data.payouts);
    } finally {
      setRefreshing(false);
    }
  }, [runId]);

  // Poll only while something is actually in flight, and stop as soon as
  // everything has settled — no background traffic on a finished run. Never in
  // the read-only modal: the refresh route writes.
  useEffect(() => {
    if (readOnly || inFlight.length === 0) return;
    const timer = setInterval(() => void refresh(), 5000);
    return () => clearInterval(timer);
  }, [readOnly, inFlight.length, refresh]);
  const failedNotices = payouts.filter((p) => p.notifyStatus === "failed");
  const total = payouts.reduce((sum, p) => sum + p.amountUsdc, 0);

  const hashes = payouts
    .map((p) => p.transferId)
    .filter((t): t is string => !!t && TX_HASH.test(t));
  const fee = useNetworkFee(hashes, readOnly);
  const runAt = payouts.reduce<string | null>(
    (earliest, p) => (!earliest || p.createdAt < earliest ? p.createdAt : earliest),
    null
  );

  function downloadReceipt() {
    const header = "name,email,wallet,amount_usdc,status,transaction_hash,sent_at,notified";
    const rows = payouts.map((p) =>
      [
        p.payeeName,
        p.payeeEmail,
        p.walletAddress,
        p.amountUsdc.toFixed(2),
        p.status,
        p.transferId ?? "",
        p.sentAt ?? "",
        p.notifyStatus,
      ]
        .map((cell) => `"${String(cell).replace(/"/g, '""')}"`)
        .join(",")
    );
    const blob = new Blob([[header, ...rows].join("\n")], { type: "text/csv" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = `arcway-receipt-${new Date().toISOString().slice(0, 10)}.csv`;
    a.click();
    URL.revokeObjectURL(url);
  }

  return (
    <>
      {readOnly ? (
        <>
          <Eyebrow>{companyName ?? "Payout run"}</Eyebrow>
          <h2
            id={headingId}
            className="mt-2 font-display text-[36px] leading-none tracking-[-0.01em] text-ink"
          >
            Run receipt
          </h2>
          <p className="mt-3 text-[15px] text-ink-soft tabular-nums">
            {runAt
              ? new Date(runAt).toLocaleString([], { dateStyle: "medium", timeStyle: "short" })
              : "—"}
          </p>
          <div className="mt-6 grid gap-3 sm:grid-cols-3">
            <Figure label="Recipients" value={String(payouts.length)} />
            <Figure label="Run total" value={`${formatUsdc(total)} USDC`} />
            <FeeFigure fee={fee} payouts={payouts} counted={hashes.length} />
          </div>
        </>
      ) : (
        <>
          <h1 className="font-display text-[40px] leading-none tracking-[-0.01em] text-ink">
            {heading ?? `${settled.length} payment${settled.length === 1 ? "" : "s"} sent`}
          </h1>
          <p className="mt-3 text-[15px] text-ink-soft">
            {subheading ??
              `${formatUsdc(total)} USDC across ${payouts.length} recipient${
                payouts.length === 1 ? "" : "s"
              }. Every line has a receipt.`}
          </p>
        </>
      )}

      {inFlight.length > 0 && (
        <div className="mt-6 flex flex-wrap items-center gap-3 rounded-card border border-line bg-card p-5">
          <span className="h-2 w-2 animate-pulse rounded-chip bg-emerald" />
          <span className="text-[14px] text-ink-soft tabular-nums">
            {inFlight.length} transfer{inFlight.length === 1 ? "" : "s"} still
            settling on chain.
            {readOnly ? "" : " This updates itself every few seconds."}
          </span>
          {!readOnly && (
            <button
              onClick={refresh}
              disabled={refreshing}
              className={buttonClasses("secondary", "sm", "ml-auto")}
            >
              {refreshing ? "Checking…" : "Check now"}
            </button>
          )}
        </div>
      )}

      {failedNotices.length > 0 && (
        <div className="mt-6 rounded-card border border-amber-100 bg-amber-50 p-5">
          <div className="text-[13px] font-semibold text-amber-text tabular-nums">
            {failedNotices.length} notification
            {failedNotices.length === 1 ? "" : "s"} could not be sent
          </div>
          <p className="mt-2 text-[14px] leading-[1.6] text-amber-text">
            The money moved regardless — these people simply have not been told
            yet.{readOnly ? "" : " Retry any of them below."}
          </p>
        </div>
      )}

      <div className="mt-8 overflow-hidden rounded-card border border-line bg-card">
        <ul>
          {payouts.map((p) => (
            <li
              key={p.id}
              className="flex flex-wrap items-center justify-between gap-4 border-b border-line-soft px-5 py-4 last:border-0"
            >
              <div className="min-w-0">
                <div className="font-medium text-ink">{p.payeeName}</div>
                <div className="text-[13px] text-ink-mute">{p.payeeEmail}</div>
                <div className="mt-1 break-all font-mono text-[12px] text-ink-mute">
                  {p.walletAddress}
                </div>
                <TransactionHash payout={p} />
                {p.status === "failed" && p.failureReason && (
                  <div className="mt-1 text-[12px] text-amber-text">{p.failureReason}</div>
                )}
              </div>
              <div className="flex shrink-0 items-center gap-4">
                {readOnly ? (
                  <LastSent
                    notifyStatus={p.notifyStatus}
                    notifiedAt={p.notifiedAt}
                    attempts={p.notifyAttempts}
                  />
                ) : (
                  <ResendNotification
                    payoutId={p.id}
                    notifyStatus={p.notifyStatus}
                    notifiedAt={p.notifiedAt}
                    attempts={p.notifyAttempts}
                    onUpdated={(updated) =>
                      setPayouts((prev) =>
                        prev.map((row) => (row.id === p.id ? (updated as Payout) : row))
                      )
                    }
                  />
                )}
                <ReceiptChip payout={p} />
                <div className="text-right font-medium text-ink tabular-nums">
                  {formatUsdc(p.amountUsdc)} <span className="text-ink-mute">USDC</span>
                </div>
              </div>
            </li>
          ))}
        </ul>
      </div>

      <div className="mt-8 flex flex-wrap gap-3">
        <button onClick={downloadReceipt} className={buttonClasses("primary", "lg")}>
          Download receipt
        </button>
        {!readOnly && (
          <Link href="/dashboard" className={buttonClasses("secondary", "lg")}>
            Back to payouts
          </Link>
        )}
      </div>

      {/* A div, not a p: Eyebrow renders a block element, and a <div> inside a
          <p> is invalid HTML that React reports as a hydration error. */}
      {!readOnly && (
        <div className="mt-4 flex flex-wrap items-center gap-2 text-[13px] text-ink-mute">
          <Eyebrow>Permalink</Eyebrow>
          <Link
            href={`/dashboard/runs/${payouts[0]?.runId ?? ""}`}
            className="text-emerald underline underline-offset-2"
          >
            /dashboard/runs/{payouts[0]?.runId ?? ""}
          </Link>
        </div>
      )}
    </>
  );
}

/**
 * The read-only receipt modal for any past run, opened from Activity and the
 * dashboard. It renders RunReceipt in "modal" mode rather than a second
 * renderer, so the two cannot drift.
 *
 * A native <dialog> opened with showModal(): Escape closes it, focus stays
 * inside, and it sits in the top layer above the sticky app bar. Clicking the
 * backdrop closes it too. Its only network traffic is the GET for the run and
 * read-only receipt lookups against the Arc RPC — it writes nothing.
 */
export function RunReceiptModal({ runId, onClose }: { runId: string; onClose: () => void }) {
  const dialogRef = useRef<HTMLDialogElement>(null);
  const headingId = useId();
  const { session } = useSession();
  const [loaded, setLoaded] = useState<{
    runId: string;
    payouts?: Payout[];
    error?: string;
  } | null>(null);

  useEffect(() => {
    const dialog = dialogRef.current;
    if (dialog && !dialog.open) dialog.showModal();
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        const res = await apiFetch(`/api/runs/${runId}`);
        const data = await res.json();
        if (cancelled) return;
        if (!res.ok) setLoaded({ runId, error: data.error ?? "Could not load that run." });
        else setLoaded({ runId, payouts: data.payouts });
      } catch {
        if (!cancelled) setLoaded({ runId, error: "Could not load that run." });
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [runId]);

  const current = loaded?.runId === runId ? loaded : null;
  const close = () => dialogRef.current?.close();

  return (
    <dialog
      ref={dialogRef}
      aria-labelledby={headingId}
      onClose={onClose}
      // The panel below fills the dialog box, so the dialog itself is only the
      // click target when the click lands on the backdrop.
      onClick={(e) => {
        if (e.target === e.currentTarget) close();
      }}
      className="m-auto w-[min(56rem,calc(100vw-2rem))] rounded-card border border-line bg-paper p-0 text-ink backdrop:bg-ink/40"
    >
      <div className="relative max-h-[calc(100dvh-3rem)] overflow-y-auto p-6 sm:p-8">
        <button
          type="button"
          onClick={close}
          className={buttonClasses("quiet", "sm", "absolute right-4 top-4")}
        >
          Close
        </button>
        {current?.payouts ? (
          <RunReceipt
            key={runId}
            payouts={current.payouts}
            mode="modal"
            companyName={session?.company?.name}
            headingId={headingId}
          />
        ) : current?.error ? (
          <>
            <h2 id={headingId} className="font-display text-[28px] leading-none text-ink">
              Receipt unavailable
            </h2>
            <p className="mt-3 text-[15px] text-amber-text">{current.error}</p>
          </>
        ) : (
          <p id={headingId} className="py-12 text-center text-[15px] text-ink-mute">
            Loading receipt…
          </p>
        )}
      </div>
    </dialog>
  );
}

/** Truncated hash, a copy of the full value, and a link to the explorer. */
function TransactionHash({ payout }: { payout: Payout }) {
  const [copied, setCopied] = useState(false);
  const ref = payout.transferId;

  if (!ref || !TX_HASH.test(ref)) {
    const text = !ref
      ? "No transaction hash"
      : ref.startsWith("mock_")
        ? "Simulated — no on-chain transaction"
        : payout.status === "failed"
          ? "No on-chain transaction"
          : "Awaiting transaction hash";
    return <div className="mt-1 text-[12px] text-ink-mute">{text}</div>;
  }

  const hash = ref;
  async function copy() {
    try {
      await navigator.clipboard.writeText(hash);
      setCopied(true);
      setTimeout(() => setCopied(false), 1500);
    } catch {
      // Clipboard can be refused (permissions, insecure context); the full
      // hash is still one click away on the explorer.
    }
  }

  return (
    <div className="mt-1 flex flex-wrap items-center gap-x-3 gap-y-1 text-[12px]">
      <span className="font-mono text-ink-mute" title={hash}>
        {truncateAddress(hash, 6)}
      </span>
      <button
        type="button"
        onClick={copy}
        aria-label="Copy full transaction hash"
        className="text-ink-soft underline underline-offset-2 hover:text-ink"
      >
        {copied ? "Copied" : "Copy"}
      </button>
      <a
        href={`${EXPLORER_TX}${hash}`}
        target="_blank"
        rel="noopener noreferrer"
        className="text-emerald underline underline-offset-2"
      >
        View on Arcscan ↗
      </a>
    </div>
  );
}

type FeeState =
  | { kind: "loading" }
  | { kind: "done"; feeUsdc: number }
  | { kind: "error" };

/**
 * The network fee a run actually cost, read from the chain.
 *
 * Read rather than stored because `Payout` has no fee column — `feeUsdc` exists
 * only on `Withdrawal`. On this leg the treasury pays its own gas: verified
 * against a real run, where the receipt's `from` is the treasury wallet and the
 * USDC leaves that same address. So gasUsed × effectiveGasPrice is exactly
 * what the treasury was charged, in native 18-decimal USDC.
 *
 * Only runs in the modal. Read-only JSON-RPC; nothing is written anywhere.
 */
function useNetworkFee(hashes: string[], enabled: boolean): FeeState | null {
  const key = hashes.join(",");
  const [state, setState] = useState<{ key: string; value: FeeState } | null>(null);

  useEffect(() => {
    if (!enabled || !key) return;
    let cancelled = false;
    (async () => {
      try {
        const fees = await Promise.all(key.split(",").map(readTransactionFee));
        if (cancelled) return;
        setState({ key, value: { kind: "done", feeUsdc: fees.reduce((a, b) => a + b, 0) } });
      } catch {
        if (!cancelled) setState({ key, value: { kind: "error" } });
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [key, enabled]);

  if (!enabled || !key) return null;
  return state?.key === key ? state.value : { kind: "loading" };
}

async function readTransactionFee(hash: string): Promise<number> {
  const res = await fetch(ARC_TESTNET_RPC, {
    method: "POST",
    headers: { "content-type": "application/json" },
    body: JSON.stringify({
      jsonrpc: "2.0",
      id: 1,
      method: "eth_getTransactionReceipt",
      params: [hash],
    }),
  });
  const receipt = (await res.json())?.result;
  if (!receipt) throw new Error(`No receipt for ${hash}`);
  return fromNativeWei(BigInt(receipt.gasUsed) * BigInt(receipt.effectiveGasPrice));
}

function FeeFigure({
  fee,
  payouts,
  counted,
}: {
  fee: FeeState | null;
  payouts: Payout[];
  counted: number;
}) {
  if (fee === null) {
    const simulated = payouts.every((p) => p.transferId?.startsWith("mock_"));
    return (
      <Figure
        label="Network fee"
        value="—"
        note={simulated ? "Simulated run — nothing on chain" : "No settled transactions yet"}
      />
    );
  }
  if (fee.kind === "loading") return <Figure label="Network fee" value="Reading…" />;
  if (fee.kind === "error") {
    return <Figure label="Network fee" value="Unavailable" note="Couldn’t reach the Arc RPC" />;
  }
  return (
    <Figure
      label="Network fee"
      value={`${fee.feeUsdc.toFixed(6)} USDC`}
      note={
        counted < payouts.length
          ? `Paid by treasury · ${counted} of ${payouts.length} on chain`
          : "Paid by treasury · read from chain"
      }
    />
  );
}

function Figure({ label, value, note }: { label: string; value: string; note?: string }) {
  return (
    <div className="rounded-card border border-line bg-card p-4">
      <Eyebrow>{label}</Eyebrow>
      <div className="mt-2 text-[20px] leading-none font-semibold text-ink tabular-nums">
        {value}
      </div>
      {note && <div className="mt-2 text-[12px] text-ink-mute tabular-nums">{note}</div>}
    </div>
  );
}

/**
 * Settlement and claim state are two different things, and a row can fail at
 * either. A transfer that never left is "Failed"; one that landed in a wallet
 * nobody has signed into yet is "Unclaimed" — the money is theirs, waiting.
 * Only a landed transfer into a claimed wallet is fully "Settled".
 */
function ReceiptChip({ payout }: { payout: Payout }) {
  if (payout.status === "failed") return <Chip tone="amber">Failed</Chip>;
  if (payout.status !== "sent") return <Chip tone="neutral">Pending</Chip>;
  return payout.claimed ? (
    <Chip tone="emerald">Settled</Chip>
  ) : (
    <Chip tone="amber">Unclaimed</Chip>
  );
}
