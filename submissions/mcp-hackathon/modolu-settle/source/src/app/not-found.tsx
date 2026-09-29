import Link from "next/link";
import { connection } from "next/server";

/**
 * Styled with classes only so the nonce-based CSP never needs inline styles,
 * and rendered per request (`connection()`) so the nonce applies to it too.
 */
export default async function NotFound() {
  await connection();
  return (
    <div className="mx-auto flex max-w-lg flex-col items-start gap-4 rounded-md border border-line bg-surface px-6 py-8">
      <p className="text-xs font-medium tracking-[0.18em] text-ink-muted uppercase">404</p>
      <h1 className="text-2xl font-semibold tracking-tight text-ink">Page not found</h1>
      <p className="text-sm text-ink-muted">Settle has two pages: the create console and the payment inspector.</p>
      <Link href="/" className="rounded-md bg-accent px-4 py-2 text-sm font-medium text-accent-ink no-underline hover:opacity-90">
        Create a payment intent
      </Link>
    </div>
  );
}
