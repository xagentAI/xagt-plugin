"use client";

import { useRouter } from "next/navigation";
import { useState, type FormEvent } from "react";
import { useSession } from "@/components/SessionContext";
import { buttonClasses } from "@/components/ui";
import { apiFetch } from "@/lib/client-api";

/**
 * One screen, shown once: a new employer names their company, which creates
 * the Company and their User(EMPLOYER) row. Everything they do afterwards is
 * scoped to the company created here.
 */
export default function WelcomePage() {
  const router = useRouter();
  const { refresh } = useSession();
  const [name, setName] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);

    if (!name.trim()) {
      setError("Enter your company's name.");
      return;
    }

    setSubmitting(true);
    try {
      const res = await apiFetch("/api/company", {
        method: "POST",
        body: JSON.stringify({ name: name.trim() }),
      });
      const data = await res.json();

      // A 409 means this identity already completed onboarding — which is a
      // success from the user's point of view, not an error. Refreshing the
      // session below resolves them to their existing company.
      if (!res.ok && res.status !== 409) {
        throw new Error(data.error ?? "Could not create your company.");
      }

      // Re-read the session BEFORE navigating. The dashboard layout wraps this
      // route, so it will not remount on navigation — without this the gate
      // still believes we need a company and sends us straight back here.
      const next = await refresh();
      router.replace(next?.destination ?? "/dashboard");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create your company.");
      setSubmitting(false);
    }
  }

  return (
    <div className="mx-auto flex min-h-[70vh] max-w-lg flex-col justify-center px-6 py-16">
      <h1 className="font-display text-[40px] leading-tight tracking-[-0.01em] text-ink">
        What should we call your company?
      </h1>
      <p className="mt-4 text-[15px] leading-[1.6] text-ink-soft">
        This is the name your team sees on payout runs and receipts. You can
        change it later.
      </p>

      <form onSubmit={handleSubmit} className="mt-8">
        <label htmlFor="company-name" className="text-[13px] font-medium text-ink-soft">
          Company name
        </label>
        <input
          id="company-name"
          autoFocus
          value={name}
          onChange={(e) => setName(e.target.value)}
          placeholder="Northwind Studio"
          className="mt-2 w-full rounded-btn border border-line bg-card px-3 py-2.5 text-[15px] text-ink outline-none placeholder:text-ink-mute focus:border-emerald"
        />
        {error && <p className="mt-3 text-[13px] text-amber-text">{error}</p>}
        <button
          type="submit"
          disabled={submitting}
          className={buttonClasses("primary", "lg", "mt-6 w-full sm:w-auto")}
        >
          {submitting ? "Setting up…" : "Continue to payouts"}
        </button>
      </form>
    </div>
  );
}
