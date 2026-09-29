"use client";

import Link from "next/link";
import { useCallback, useEffect, useRef, useState } from "react";

import { STATUS_COPY, publicApi, type ApiError, type EvidenceItemResponse, type PaymentIntentResponse } from "@/lib/public-api";

import { ApiCall } from "./api-call";
import { ErrorNotice } from "./error-notice";
import { EvidenceList } from "./evidence-list";
import { formatUtc } from "./format";
import { MAX_CONSECUTIVE_FAILURES, POLL_INTERVAL_MS, decidePolling, type PollingDecision } from "./inspector-polling";
import { PaymentDetails } from "./payment-details";
import { PaymentStatusHero } from "./payment-status";
import { PaymentSummary } from "./payment-summary";
import { ReconcileButton } from "./reconcile-button";
import { useOrigin, usePageVisible } from "./use-browser";

const EVIDENCE_PAGE = 100;

interface EvidenceState {
  readonly items: readonly EvidenceItemResponse[];
  readonly truncated: boolean;
  readonly loading: boolean;
  readonly error: ApiError | null;
}

function pollingCaption(decision: PollingDecision, lastCheckedAt: Date | null): string {
  const checked = lastCheckedAt === null ? "" : ` Last checked ${formatUtc(lastCheckedAt.toISOString())}.`;
  switch (decision) {
    case "poll":
    case "wait:busy":
      return `Auto-reconciling every ${POLL_INTERVAL_MS / 1000} seconds while this page is open.${checked}`;
    case "stop:terminal":
      return `Final status reached — automatic reconciliation stopped.${checked}`;
    case "stop:failures":
      return `Automatic reconciliation paused after ${MAX_CONSECUTIVE_FAILURES} consecutive failures. Reconcile now to resume.${checked}`;
    case "wait:hidden":
      return `Automatic reconciliation paused while this tab is in the background.${checked}`;
    case "wait:unloaded":
      return "";
  }
}

/** Skeleton that mirrors the loaded layout so nothing jumps when data arrives. */
function InspectorSkeleton() {
  return (
    <div aria-busy="true" aria-label="Loading payment intent" className="flex flex-col gap-6">
      <p role="status" className="sr-only">
        Loading payment intent
      </p>
      <div className="h-28 rounded-md border border-line bg-surface-muted" />
      <div className="h-32 rounded-md border border-line bg-surface-muted" />
      <div className="h-80 rounded-md border border-line bg-surface-muted" />
    </div>
  );
}

function NotFound({ id }: { readonly id: string }) {
  return (
    <div className="mx-auto flex max-w-lg flex-col items-start gap-4 rounded-md border border-line bg-surface px-6 py-8">
      <p className="text-xs font-medium tracking-[0.18em] text-ink-muted uppercase">Inspector</p>
      <h1 className="text-2xl font-semibold tracking-tight text-ink">Payment intent not found</h1>
      <p className="text-sm text-ink-muted">
        No payment intent exists with the ID <code className="font-mono break-all">{id}</code>. IDs are opaque; check the
        link you were given.
      </p>
      <Link href="/" className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-accent-ink no-underline hover:opacity-90">
        Create a payment intent
      </Link>
    </div>
  );
}

/** The inspector: loads, reconciles and polls one intent through the public API only. */
export function PaymentInspector({ id }: { readonly id: string }) {
  const [intent, setIntent] = useState<PaymentIntentResponse | null>(null);
  const [loadError, setLoadError] = useState<ApiError | null>(null);
  const [evidence, setEvidence] = useState<EvidenceState>({ items: [], truncated: false, loading: true, error: null });
  const [reconciling, setReconciling] = useState(false);
  const [reconcileError, setReconcileError] = useState<ApiError | null>(null);
  const [consecutiveFailures, setConsecutiveFailures] = useState(0);
  const pageVisible = usePageVisible();
  const [lastCheckedAt, setLastCheckedAt] = useState<Date | null>(null);
  /** Increments after every completed reconciliation so the next poll is armed from that moment. */
  const [cycle, setCycle] = useState(0);
  const origin = useOrigin();
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
    };
  }, []);

  const loadEvidence = useCallback(async () => {
    setEvidence((current) => ({ ...current, loading: true }));
    const result = await publicApi.getEvidence(id, EVIDENCE_PAGE);
    if (!mounted.current) {
      return;
    }
    if (result.ok) {
      setEvidence({ items: result.data.evidence, truncated: result.data.nextCursor !== null, loading: false, error: null });
    } else {
      setEvidence((current) => ({ ...current, loading: false, error: result.error }));
    }
  }, [id]);

  // Initial load: the intent and its evidence, through the same public API an agent uses.
  useEffect(() => {
    let cancelled = false;
    void (async () => {
      const result = await publicApi.getPaymentIntent(id);
      if (cancelled) {
        return;
      }
      if (result.ok) {
        setIntent(result.data);
        void loadEvidence();
      } else {
        setLoadError(result.error);
        setEvidence((current) => ({ ...current, loading: false }));
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [id, loadEvidence]);

  const reconcile = useCallback(
    async (trigger: "manual" | "poll") => {
      if (reconciling) {
        return;
      }
      setReconciling(true);
      if (trigger === "manual") {
        // A deliberate retry re-arms automatic reconciliation after repeated failures.
        setConsecutiveFailures(0);
      }
      const result = await publicApi.reconcilePaymentIntent(id);
      if (!mounted.current) {
        return;
      }
      setLastCheckedAt(new Date());
      setCycle((count) => count + 1);
      if (result.ok) {
        // The API's state replaces ours wholesale; nothing is derived in the browser.
        setIntent(result.data);
        setReconcileError(null);
        setConsecutiveFailures(0);
        setReconciling(false);
        void loadEvidence();
      } else {
        // Previous known state is preserved; only the notice changes.
        setReconcileError(result.error);
        setConsecutiveFailures((count) => count + 1);
        setReconciling(false);
        if (result.error.code === "INTENT_NOT_FOUND") {
          setLoadError(result.error);
        }
      }
    },
    [id, loadEvidence, reconciling],
  );

  const decision = decidePolling({
    status: intent?.status ?? null,
    consecutiveFailures,
    pageVisible,
    reconciling,
  });

  // 7-second cadence measured from the end of the previous reconciliation (`cycle`),
  // not from intermediate renders — a fast response must still arm the next poll.
  useEffect(() => {
    if (decision !== "poll") {
      return;
    }
    const timer = setTimeout(() => void reconcile("poll"), POLL_INTERVAL_MS);
    return () => clearTimeout(timer);
  }, [decision, reconcile, cycle]);

  if (loadError !== null && (loadError.code === "INTENT_NOT_FOUND" || loadError.code === "VALIDATION_ERROR")) {
    return <NotFound id={id} />;
  }
  if (loadError !== null) {
    return (
      <div className="mx-auto flex max-w-lg flex-col gap-4">
        <ErrorNotice error={loadError} />
        <Link href="/" className="text-sm underline underline-offset-4">
          Back to create an intent
        </Link>
      </div>
    );
  }
  if (intent === null) {
    return <InspectorSkeleton />;
  }

  const reconcileCurl = `curl -X POST ${origin}/v1/payment-intents/${intent.id}/reconcile`;
  const evidenceCurl = `curl ${origin}/v1/payment-intents/${intent.id}/evidence?limit=50`;
  const statusCopy = STATUS_COPY[intent.status];

  return (
    <div className="flex min-w-0 flex-col gap-8">
      <div className="flex flex-wrap items-end justify-between gap-4">
        <div className="min-w-0">
          <p className="text-xs font-medium tracking-[0.18em] text-ink-muted uppercase">Payment intent</p>
          <h1 className="mt-1 text-2xl font-semibold tracking-tight text-ink">
            {intent.externalReference ?? "Untitled obligation"}
          </h1>
          <p className="mt-1 font-mono text-xs break-all text-ink-muted">{intent.id}</p>
        </div>
        <div className="flex flex-col items-start gap-2 sm:items-end">
          <ReconcileButton reconciling={reconciling} onClick={() => void reconcile("manual")} />
          <p className="max-w-xs text-xs text-ink-muted sm:text-right" data-polling={decision}>
            {pollingCaption(decision, lastCheckedAt)}
          </p>
        </div>
      </div>

      {reconcileError !== null ? (
        <ErrorNotice error={reconcileError} onRetry={() => void reconcile("manual")} retrying={reconciling} />
      ) : null}

      <section aria-label={`Payment status: ${statusCopy.label}`} className="flex flex-col gap-4">
        <PaymentStatusHero status={intent.status} reconciling={reconciling} />
        <PaymentSummary intent={intent} />
      </section>

      <section aria-labelledby="details-heading" className="flex flex-col gap-3">
        <h2 id="details-heading" className="text-xs font-medium tracking-[0.18em] text-ink-muted uppercase">
          Obligation
        </h2>
        <PaymentDetails intent={intent} />
      </section>

      <section aria-labelledby="evidence-heading" className="flex flex-col gap-3">
        <div className="flex flex-wrap items-baseline justify-between gap-2">
          <h2 id="evidence-heading" className="text-xs font-medium tracking-[0.18em] text-ink-muted uppercase">
            Onchain evidence
          </h2>
          <p className="text-xs text-ink-muted">Native USDC transfers to the recipient observed inside the payment window.</p>
        </div>
        {evidence.error !== null ? <ErrorNotice error={evidence.error} onRetry={() => void loadEvidence()} retrying={evidence.loading} /> : null}
        <EvidenceList evidence={evidence.items} loading={evidence.loading} truncated={evidence.truncated} />
      </section>

      <section aria-labelledby="api-heading" className="flex flex-col gap-3">
        <div className="flex flex-col gap-1">
          <h2 id="api-heading" className="text-xs font-medium tracking-[0.18em] text-ink-muted uppercase">
            Same calls, from your agent
          </h2>
          <p className="text-xs text-ink-muted">This console only uses the public API. Possession of the intent ID is the capability.</p>
        </div>
        <div className="grid grid-cols-1 gap-3 lg:grid-cols-2">
          <ApiCall title="Reconcile" command={reconcileCurl} />
          <ApiCall title="Evidence" command={evidenceCurl} />
        </div>
      </section>
    </div>
  );
}
