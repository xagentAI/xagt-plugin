"use client";

import { useRouter } from "next/navigation";
import { useId, useState, type FormEvent, type ReactNode } from "react";

import { describeApiError, publicApi } from "@/lib/public-api";

import { ApiCall } from "./api-call";
import {
  DEFAULT_REQUIRED_CONFIRMATIONS,
  buildCreateIntentRequest,
  curlForCreate,
  defaultExpiryLocal,
  localDateTimeToIso,
  mapServerErrorToFields,
  validateCreateIntentForm,
  type CreateIntentField,
  type CreateIntentFormValues,
  type FieldErrors,
} from "./create-intent-request";
import { useHydrated, useOrigin } from "./use-browser";

const EMPTY: CreateIntentFormValues = {
  amount: "",
  recipient: "",
  payer: "",
  expiresAt: "",
  externalReference: "",
  requiredConfirmations: DEFAULT_REQUIRED_CONFIRMATIONS,
};

interface FieldProps {
  readonly name: CreateIntentField;
  readonly label: string;
  readonly hint?: string | undefined;
  readonly optional?: boolean | undefined;
  readonly error?: string | undefined;
  readonly children: (props: {
    id: string;
    "aria-invalid": boolean | undefined;
    "aria-describedby": string | undefined;
  }) => ReactNode;
}

function Field({ name, label, hint, optional, error, children }: FieldProps) {
  const id = useId();
  const hintId = hint !== undefined ? `${id}-hint` : undefined;
  const errorId = error !== undefined ? `${id}-error` : undefined;
  const describedBy = [errorId, hintId].filter(Boolean).join(" ") || undefined;
  return (
    <div className="flex flex-col gap-1.5">
      <label htmlFor={id} className="flex items-baseline justify-between text-sm font-medium text-ink">
        <span>{label}</span>
        {optional === true ? <span className="text-xs font-normal text-ink-faint">Optional</span> : null}
      </label>
      {children({ id, "aria-invalid": error !== undefined ? true : undefined, "aria-describedby": describedBy })}
      {hint !== undefined ? (
        <p id={hintId} className="text-xs text-ink-muted">
          {hint}
        </p>
      ) : null}
      {error !== undefined ? (
        <p id={errorId} className="text-xs font-medium text-status-expired" data-field-error={name}>
          {error}
        </p>
      ) : null}
    </div>
  );
}

const inputClass =
  "w-full rounded-md border border-line-strong bg-surface px-3 py-2 text-sm text-ink placeholder:text-ink-faint aria-invalid:border-status-expired";
const monoInputClass = `${inputClass} font-mono`;

/** The demo's create surface: builds and sends the real `POST /v1/payment-intents` request. */
export function CreateIntentForm() {
  const router = useRouter();
  const [values, setValues] = useState<CreateIntentFormValues>(EMPTY);
  const [fieldErrors, setFieldErrors] = useState<FieldErrors>({});
  const [formError, setFormError] = useState<{ title: string; detail: string } | null>(null);
  const [submitting, setSubmitting] = useState(false);
  // Browser-only defaults (local time, current origin) only render after hydration.
  const hydrated = useHydrated();
  const origin = useOrigin();
  const [defaultExpiry] = useState(() => defaultExpiryLocal());
  const effective: CreateIntentFormValues = {
    ...values,
    expiresAt: values.expiresAt !== "" ? values.expiresAt : hydrated ? defaultExpiry : "",
  };

  function update(name: CreateIntentField, value: string) {
    setValues((current) => ({ ...current, [name]: value }));
    setFieldErrors((current) => {
      if (current[name] === undefined) {
        return current;
      }
      const next = { ...current };
      delete next[name];
      return next;
    });
  }

  async function onSubmit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (submitting) {
      return;
    }
    setFormError(null);
    const errors = validateCreateIntentForm(effective);
    setFieldErrors(errors);
    if (Object.keys(errors).length > 0) {
      return;
    }

    setSubmitting(true);
    const result = await publicApi.createPaymentIntent(buildCreateIntentRequest(effective));
    if (result.ok) {
      router.push(`/inspect/${result.data.id}`);
      return;
    }
    setSubmitting(false);
    const mapped = mapServerErrorToFields(result.error);
    setFieldErrors(mapped.fields);
    const copy = describeApiError(result.error);
    if (Object.keys(mapped.fields).length === 0 || mapped.form !== null) {
      setFormError({ title: copy.title, detail: mapped.form ?? copy.detail });
    }
  }

  const expiryIso = localDateTimeToIso(effective.expiresAt);
  const preview = curlForCreate(origin, buildCreateIntentRequest(effective.amount === "" ? { ...effective, amount: "25.00" } : effective));

  return (
    <div className="grid grid-cols-1 gap-8 lg:grid-cols-2 lg:gap-12">
      <form onSubmit={(event) => void onSubmit(event)} noValidate className="flex min-w-0 flex-col gap-5" aria-busy={submitting}>
        <div className="grid grid-cols-2 gap-3 rounded-md border border-line bg-surface-muted px-4 py-3 text-sm">
          <div>
            <p className="text-xs tracking-[0.12em] text-ink-muted uppercase">Network</p>
            <p className="font-medium text-ink">Base</p>
          </div>
          <div>
            <p className="text-xs tracking-[0.12em] text-ink-muted uppercase">Asset</p>
            <p className="font-medium text-ink">USDC (native)</p>
          </div>
        </div>

        <Field name="amount" label="Expected amount (USDC)" error={fieldErrors.amount}>
          {(props) => (
            <input
              {...props}
              name="amount"
              inputMode="decimal"
              autoComplete="off"
              placeholder="25.00"
              value={values.amount}
              onChange={(event) => update("amount", event.target.value)}
              className={monoInputClass}
            />
          )}
        </Field>

        <Field name="recipient" label="Recipient address" hint="The Base address that should receive the USDC." error={fieldErrors.recipient}>
          {(props) => (
            <input
              {...props}
              name="recipient"
              autoComplete="off"
              spellCheck={false}
              placeholder="0x…"
              value={values.recipient}
              onChange={(event) => update("recipient", event.target.value)}
              className={monoInputClass}
            />
          )}
        </Field>

        <Field
          name="payer"
          label="Payer address"
          optional
          hint="Strongly recommended: with a declared payer, matching is exact. Without one, Settle only accepts a single unambiguous sender."
          error={fieldErrors.payer}
        >
          {(props) => (
            <input
              {...props}
              name="payer"
              autoComplete="off"
              spellCheck={false}
              placeholder="0x…"
              value={values.payer}
              onChange={(event) => update("payer", event.target.value)}
              className={monoInputClass}
            />
          )}
        </Field>

        <div className="grid grid-cols-1 gap-5 sm:grid-cols-[minmax(0,1fr)_9rem]">
          <Field
            name="expiresAt"
            label="Payment window closes"
            hint={expiryIso !== null ? `Sent as ${expiryIso} (UTC). At most 7 days from now.` : "At most 7 days from now."}
            error={fieldErrors.expiresAt}
          >
            {(props) => (
              <input
                {...props}
                name="expiresAt"
                type="datetime-local"
                value={effective.expiresAt}
                onChange={(event) => update("expiresAt", event.target.value)}
                className={inputClass}
              />
            )}
          </Field>
          <Field name="requiredConfirmations" label="Confirmations" hint="1–64, default 3." error={fieldErrors.requiredConfirmations}>
            {(props) => (
              <input
                {...props}
                name="requiredConfirmations"
                inputMode="numeric"
                value={values.requiredConfirmations}
                onChange={(event) => update("requiredConfirmations", event.target.value)}
                className={monoInputClass}
              />
            )}
          </Field>
        </div>

        <Field name="externalReference" label="External reference" optional hint="Your invoice or order ID, up to 128 characters." error={fieldErrors.externalReference}>
          {(props) => (
            <input
              {...props}
              name="externalReference"
              autoComplete="off"
              placeholder="INV-204"
              value={values.externalReference}
              onChange={(event) => update("externalReference", event.target.value)}
              className={inputClass}
            />
          )}
        </Field>

        {formError !== null ? (
          <div role="alert" className="rounded-md border border-status-expired/40 bg-status-expired/5 px-4 py-3 text-sm">
            <p className="font-medium text-ink">{formError.title}</p>
            <p className="mt-1 text-ink-muted">{formError.detail}</p>
          </div>
        ) : null}

        <div className="flex flex-wrap items-center gap-4">
          <button
            type="submit"
            disabled={submitting}
            className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-accent-ink hover:opacity-90 disabled:cursor-progress disabled:opacity-60"
          >
            {submitting ? "Creating intent…" : "Create payment intent"}
          </button>
          <p className="text-xs text-ink-muted">Settle records the obligation. The payment itself happens outside Settle.</p>
        </div>
        <p role="status" aria-live="polite" className="sr-only">
          {submitting ? "Creating payment intent" : ""}
        </p>
      </form>

      <div className="flex min-w-0 flex-col gap-3">
        <ApiCall title="Same request, as an agent would send it" command={preview} caption="Live preview of the exact body this form submits." />
        <p className="text-xs text-ink-muted">
          The response carries an opaque <code className="font-mono">pi_…</code> ID. Possession of that ID is what lets an agent read or reconcile the intent.
        </p>
      </div>
    </div>
  );
}
