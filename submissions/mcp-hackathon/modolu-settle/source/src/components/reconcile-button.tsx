"use client";

interface ReconcileButtonProps {
  readonly reconciling: boolean;
  readonly disabled?: boolean;
  readonly onClick: () => void;
}

export function ReconcileButton({ reconciling, disabled, onClick }: ReconcileButtonProps) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={reconciling || disabled === true}
      aria-busy={reconciling}
      className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-accent-ink hover:opacity-90 disabled:cursor-progress disabled:opacity-60"
    >
      {reconciling ? "Reconciling…" : "Reconcile now"}
    </button>
  );
}
