"use client";

import { useState, type FormEvent } from "react";
import { buttonClasses } from "./ui";

export interface PayeeFormValues {
  name: string;
  email: string;
  amountUsdc: number;
}

const inputClasses =
  "rounded-btn border border-line bg-card px-3 py-2 text-sm text-ink outline-none " +
  "placeholder:text-ink-mute focus:border-emerald";

export function PayeeForm({
  onSubmit,
  submitting,
}: {
  onSubmit: (values: PayeeFormValues) => Promise<void> | void;
  submitting: boolean;
}) {
  const [name, setName] = useState("");
  const [email, setEmail] = useState("");
  const [amount, setAmount] = useState("");
  const [error, setError] = useState<string | null>(null);

  async function handleSubmit(e: FormEvent<HTMLFormElement>) {
    e.preventDefault();
    setError(null);

    const amountUsdc = Number(amount);
    if (!name.trim() || !email.trim()) {
      setError("Name and email are required.");
      return;
    }
    if (!Number.isFinite(amountUsdc) || amountUsdc <= 0) {
      setError("Enter a valid USDC amount greater than 0.");
      return;
    }

    try {
      await onSubmit({ name: name.trim(), email: email.trim(), amountUsdc });
      setName("");
      setEmail("");
      setAmount("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Failed to add payee.");
    }
  }

  return (
    <form
      onSubmit={handleSubmit}
      className="rounded-card border border-line bg-card p-6"
    >
      <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:gap-3">
        <div className="flex flex-1 flex-col gap-1.5">
          <label htmlFor="payee-name" className="text-[13px] font-medium text-ink-soft">
            Name
          </label>
          <input
            id="payee-name"
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder="Amara Okafor"
            className={inputClasses}
          />
        </div>
        <div className="flex flex-1 flex-col gap-1.5">
          <label htmlFor="payee-email" className="text-[13px] font-medium text-ink-soft">
            Email
          </label>
          <input
            id="payee-email"
            type="email"
            value={email}
            onChange={(e) => setEmail(e.target.value)}
            placeholder="amara@example.com"
            className={inputClasses}
          />
        </div>
        <div className="flex w-full flex-col gap-1.5 sm:w-40">
          <label htmlFor="payee-amount" className="text-[13px] font-medium text-ink-soft">
            Amount (USDC)
          </label>
          <input
            id="payee-amount"
            type="number"
            min="0"
            step="0.01"
            value={amount}
            onChange={(e) => setAmount(e.target.value)}
            placeholder="500"
            className={inputClasses}
          />
        </div>
        <button
          type="submit"
          disabled={submitting}
          className={buttonClasses("primary", "md", "sm:w-auto")}
        >
          {submitting ? "Adding…" : "Add to next run"}
        </button>
      </div>

      <p className="mt-4 border-t border-line-soft pt-4 text-[13px] leading-[1.6] text-ink-mute">
        A wallet is created for them the moment you add them. They&rsquo;re not
        emailed until you send the run.
      </p>

      {error && <p className="mt-3 text-[13px] text-amber-text">{error}</p>}
    </form>
  );
}
