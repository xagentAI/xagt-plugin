import { describeApiError, type ApiError } from "@/lib/public-api";

interface ErrorNoticeProps {
  readonly error: ApiError;
  readonly onRetry?: () => void;
  readonly retrying?: boolean;
}

/** Stable-code error framing; never raw provider or stack details. */
export function ErrorNotice({ error, onRetry, retrying }: ErrorNoticeProps) {
  const copy = describeApiError(error);
  return (
    <div
      role="alert"
      data-error-code={error.code}
      className="rounded-md border border-status-expired/40 bg-status-expired/5 px-4 py-3 text-sm"
    >
      <p className="font-medium text-ink">{copy.title}</p>
      <p className="mt-1 text-ink-muted">{copy.detail}</p>
      <p className="mt-2 flex flex-wrap items-center gap-3 text-xs text-ink-muted">
        <code className="font-mono">{error.code}</code>
        {error.retryable ? <span>Retryable — Settle did not change any payment state.</span> : null}
        {onRetry !== undefined && error.retryable ? (
          <button
            type="button"
            onClick={onRetry}
            disabled={retrying === true}
            className="rounded border border-line-strong px-2 py-0.5 font-medium text-ink hover:bg-surface-muted disabled:opacity-60"
          >
            {retrying === true ? "Retrying…" : "Retry"}
          </button>
        ) : null}
      </p>
    </div>
  );
}
