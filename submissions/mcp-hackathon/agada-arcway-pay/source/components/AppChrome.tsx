"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { usePrivy } from "@privy-io/react-auth";
import { Wordmark } from "./Brand";
import { buttonClasses } from "./ui";
import { resolveSession } from "@/lib/client-api";
import { cn } from "@/lib/utils";

const TABS = [
  { label: "Payouts", href: "/dashboard" },
  { label: "People", href: "/dashboard/people" },
  { label: "Activity", href: "/dashboard/activity" },
  { label: "Settings", href: "/dashboard/settings" },
];

function initials(name: string): string {
  return name
    .split(/\s+/)
    .slice(0, 2)
    .map((w) => w[0]?.toUpperCase() ?? "")
    .join("");
}

export function AppChrome() {
  const pathname = usePathname();
  const { logout } = usePrivy();
  const [company, setCompany] = useState<string | null>(null);

  // The company shown here is the one the server resolved from the access
  // token, so the chrome can never label the page with a company the viewer
  // is not actually acting for.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      const session = await resolveSession();
      if (!cancelled) setCompany(session?.company?.name ?? null);
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <header className="sticky top-0 z-40 border-b border-line bg-card">
      <div className="mx-auto flex max-w-6xl items-center justify-between gap-6 px-6 pt-4">
        <Link href="/" className="text-ink">
          <Wordmark />
        </Link>

        <div className="flex items-center gap-3">
          <span className="hidden text-sm text-ink-soft sm:inline">
            {company ?? "\u00a0"}
          </span>
          <span
            aria-hidden="true"
            className="flex h-8 w-8 items-center justify-center rounded-chip border border-emerald-100 bg-emerald-50 text-xs font-semibold text-emerald"
          >
            {company ? initials(company) : ""}
          </span>
          <button onClick={() => logout()} className={buttonClasses("quiet", "sm")}>
            Sign out
          </button>
        </div>
      </div>

      <nav className="mx-auto max-w-6xl px-6">
        <ul className="flex gap-6">
          {TABS.map((tab) => {
            // /dashboard would otherwise match every child route.
            const active =
              tab.href === "/dashboard"
                ? pathname === "/dashboard" || pathname.startsWith("/dashboard/review")
                : pathname.startsWith(tab.href);
            return (
              <li key={tab.href}>
                <Link
                  href={tab.href}
                  aria-current={active ? "page" : undefined}
                  className={cn(
                    "-mb-px inline-block border-b-2 py-3 text-sm transition-colors",
                    active
                      ? "border-emerald font-semibold text-ink"
                      : "border-transparent text-ink-soft hover:text-ink"
                  )}
                >
                  {tab.label}
                </Link>
              </li>
            );
          })}
        </ul>
      </nav>
    </header>
  );
}
