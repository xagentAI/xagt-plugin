"use client";

import { usePrivy } from "@privy-io/react-auth";
import Link from "next/link";
import { useRouter } from "next/navigation";
import { useEffect } from "react";
import { Wordmark } from "@/components/Brand";
import { buttonClasses } from "@/components/ui";
import { resolveSession } from "@/lib/client-api";
import { isPrivyClientConfigured } from "./providers";

export default function LandingPage() {
  if (!isPrivyClientConfigured) {
    return <LandingContent />;
  }
  return <LandingWithAuth />;
}

/** Split out so `usePrivy()` is only ever called when a PrivyProvider is mounted. */
function LandingWithAuth() {
  const { ready, authenticated, login } = usePrivy();
  const router = useRouter();

  // Where a signed-in person goes is decided by the server from their stored
  // records and verified email — NOT by which button they pressed. A
  // contractor who clicks "Start paying" still lands on /claim.
  useEffect(() => {
    if (!ready || !authenticated) return;
    let cancelled = false;
    (async () => {
      const session = await resolveSession();
      if (cancelled) return;
      router.replace(session?.destination ?? "/dashboard");
    })();
    return () => {
      cancelled = true;
    };
  }, [ready, authenticated, router]);

  return <LandingContent onSignIn={() => login()} signInReady={ready} />;
}

/**
 * `onSignIn` is absent when Privy has no App ID configured — the app's mock
 * mode. The calls to action stay real in both cases: with Privy they open
 * the email login, without it they go straight to the sandbox dashboard.
 */
function LandingContent({
  onSignIn,
  signInReady = true,
}: {
  onSignIn?: () => void;
  signInReady?: boolean;
}) {
  const sandboxMode = !onSignIn;

  return (
    <div className="flex min-h-screen flex-col">
      <Nav onSignIn={onSignIn} signInReady={signInReady} />

      <main className="flex-1">
        <Hero
          onSignIn={onSignIn}
          signInReady={signInReady}
          sandboxMode={sandboxMode}
        />
        <HowItWorks />
        <TwoSides />
        <Questions />
      </main>

      <ClosingBand onSignIn={onSignIn} signInReady={signInReady} />
    </div>
  );
}

/* ---------------------------------------------------------------- nav --- */

function Nav({
  onSignIn,
  signInReady,
}: {
  onSignIn?: () => void;
  signInReady?: boolean;
}) {
  return (
    <header className="sticky top-0 z-40 border-b border-line bg-paper">
      <div className="mx-auto flex max-w-6xl items-center justify-between px-6 py-5">
        <Link href="/" className="text-ink">
          <Wordmark />
        </Link>

        <nav className="hidden items-center gap-8 text-sm text-ink-soft md:flex">
          <a href="#how-it-works" className="transition-colors hover:text-ink">
            How it works
          </a>
          <a href="#pricing" className="transition-colors hover:text-ink">
            Pricing
          </a>
          <a href="#docs" className="transition-colors hover:text-ink">
            Docs
          </a>
        </nav>

        <div className="flex items-center gap-2">
          {onSignIn ? (
            <>
              <button
                onClick={onSignIn}
                disabled={!signInReady}
                className={buttonClasses("quiet", "md", "hidden sm:inline-flex")}
              >
                Sign in
              </button>
              <button
                onClick={onSignIn}
                disabled={!signInReady}
                className={buttonClasses("primary", "md")}
              >
                Start paying
              </button>
            </>
          ) : (
            <>
              <Link
                href="/dashboard"
                className={buttonClasses("quiet", "md", "hidden sm:inline-flex")}
              >
                Sign in
              </Link>
              <Link href="/dashboard" className={buttonClasses("primary", "md")}>
                Start paying
              </Link>
            </>
          )}
        </div>
      </div>
    </header>
  );
}

/* --------------------------------------------------------------- hero --- */

function Hero({
  onSignIn,
  signInReady,
  sandboxMode,
}: {
  onSignIn?: () => void;
  signInReady?: boolean;
  sandboxMode: boolean;
}) {
  return (
    <section className="mx-auto max-w-6xl px-6 pt-20 pb-24 sm:pt-28">
      <span className="inline-flex items-center rounded-chip border border-line bg-card px-3 py-1.5 text-[13px] text-ink-soft">
        Stablecoin payouts, built on Circle &amp; Privy
      </span>

      <h1 className="mt-8 max-w-4xl font-display text-[44px] leading-[1.02] tracking-[-0.02em] text-ink sm:text-[58px] lg:text-[76px]">
        Payday shouldn&rsquo;t take{" "}
        <em className="italic text-emerald">five days.</em>
      </h1>

      <p className="mt-7 max-w-155 text-[17px] leading-[1.6] text-ink-soft sm:text-xl">
        Arcway pays your contractors and remote staff in USDC using nothing but
        their email address. No wallets to collect, no correspondent banks, no
        waiting on a Friday cut-off.
      </p>

      <div className="mt-9 flex flex-col gap-3 sm:flex-row sm:items-center">
        {onSignIn ? (
          <button
            onClick={onSignIn}
            disabled={!signInReady}
            className={buttonClasses("primary", "lg")}
          >
            Start paying your team
          </button>
        ) : (
          <Link href="/dashboard" className={buttonClasses("primary", "lg")}>
            Start paying your team
          </Link>
        )}
        <a href="#how-it-works" className={buttonClasses("secondary", "lg")}>
          See how it works
        </a>
      </div>

      {/* <p className="mt-5 text-sm text-ink-mute">
        Sandbox is free. No card required.
      </p> */}

      {/* {sandboxMode && (
        <p className="mt-2 text-[13px] text-ink-mute">
          Running in sandbox mode — set{" "}
          <code className="font-mono text-[12px]">NEXT_PUBLIC_PRIVY_APP_ID</code>{" "}
          to enable email sign-in.
        </p>
      )} */}
    </section>
  );
}

/* ------------------------------------------------------- how it works --- */

const STEPS = [
  {
    n: "1",
    title: "You add an email",
    body: "Name, email, amount. Nothing else — no wallet address to chase, no onboarding form to send them.",
  },
  {
    n: "2",
    title: "We create their wallet",
    body: "A secure wallet is provisioned in their name before they've ever heard of us. They don't install anything.",
  },
  {
    n: "3",
    title: "They claim and cash out",
    body: "They sign in with the same email, see the money, and move it where they want it.",
  },
];

function HowItWorks() {
  return (
    <section id="how-it-works" className="mx-auto max-w-6xl px-6 pb-24">
      <div className="grid overflow-hidden rounded-card border border-line bg-card sm:grid-cols-3">
        {STEPS.map((step) => (
          <div
            key={step.n}
            className="border-b border-line-soft p-8 last:border-b-0 sm:border-r sm:border-b-0 sm:last:border-r-0"
          >
            <div className="flex h-7 w-7 items-center justify-center rounded-chip border border-emerald-100 bg-emerald-50 text-[13px] font-semibold text-emerald">
              {step.n}
            </div>
            <h3 className="mt-5 text-[17px] font-semibold text-ink">
              {step.title}
            </h3>
            <p className="mt-2 text-[15px] leading-[1.6] text-ink-soft">
              {step.body}
            </p>
          </div>
        ))}
      </div>
    </section>
  );
}

/* ----------------------------------------------------------- two sides --- */

const SIDES = [
  {
    eyebrow: "For the company",
    points: [
      "Add payees by email — one at a time or by import.",
      "Review every run before a cent moves.",
      "Watch each payment settle, with a receipt for every one.",
    ],
  },
  {
    eyebrow: "For the person paid",
    points: [
      "No app, no wallet, no seed phrase.",
      "Sign in with the email they were paid at.",
      "Hold it in dollars, or move it out whenever they like.",
    ],
  },
];

function TwoSides() {
  return (
    <section className="border-y border-line bg-card">
      <div className="mx-auto max-w-6xl px-6 py-24">
        <h2 className="font-display text-[36px] leading-tight tracking-[-0.01em] text-ink sm:text-[44px]">
          One payment, two sides.
        </h2>
        <p className="mt-4 max-w-155 text-[17px] leading-[1.6] text-ink-soft">
          Finance runs the payroll. The person getting paid does almost nothing.
        </p>

        <div className="mt-10 grid gap-6 md:grid-cols-2">
          {SIDES.map((side) => (
            <div
              key={side.eyebrow}
              className="rounded-card border border-line bg-paper p-8"
            >
              <div className="text-[11px] font-semibold uppercase tracking-[0.12em] text-ink-mute">
                {side.eyebrow}
              </div>
              <ul className="mt-6 flex flex-col gap-4">
                {side.points.map((point) => (
                  <li key={point} className="flex gap-3">
                    <CheckMark />
                    <span className="text-[15px] leading-[1.55] text-ink-soft">
                      {point}
                    </span>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>
      </div>
    </section>
  );
}

function CheckMark() {
  return (
    <svg
      viewBox="0 0 16 16"
      fill="none"
      aria-hidden="true"
      className="mt-0.75 h-4 w-4 shrink-0 text-emerald"
    >
      <path
        d="M3 8.5 6.25 11.75 13 5"
        stroke="currentColor"
        strokeWidth="1.75"
        strokeLinecap="round"
        strokeLinejoin="round"
      />
    </svg>
  );
}

/* ---------------------------------------------------------- questions --- */

const QUESTIONS = [
  {
    q: "Does my contractor need to understand crypto?",
    a: "No. They receive an email, click a link, enter a code. The wallet exists in the background; they never manage a key or install anything.",
  },
  {
    q: "How do they turn it into local currency?",
    a: "Today, by sending it to an exchange or wallet they already use. Direct bank cash-out is on the roadmap and will require a one-time identity check — that part is the law, not our design.",
  },
  {
    q: "Who controls the money before they claim it?",
    a: "The wallet is provisioned in their name from the moment you add them. Signing in is what puts them in control of it — we can't move their funds afterwards, and neither can you.",
  },
  {
    q: "Can our systems trigger payouts automatically?",
    a: "Yes. Every payout in the dashboard is also a single authenticated API call, so your own tooling — or an agent — can pay someone by email.",
  },
];

function Questions() {
  return (
    <section id="docs" className="mx-auto max-w-6xl px-6 py-24">
      <h2 className="font-display text-[36px] leading-tight tracking-[-0.01em] text-ink sm:text-[44px]">
        The questions people actually ask.
      </h2>

      <div className="mt-10 grid gap-6 md:grid-cols-2">
        {QUESTIONS.map((item) => (
          <div
            key={item.q}
            className="rounded-card border border-line bg-card p-8"
          >
            <h3 className="text-[17px] font-semibold text-ink">{item.q}</h3>
            <p className="mt-3 text-[15px] leading-[1.65] text-ink-soft">
              {item.a}
            </p>
          </div>
        ))}
      </div>
    </section>
  );
}

/* ------------------------------------------------- closing band + footer --- */

function ClosingBand({
  onSignIn,
  signInReady,
}: {
  onSignIn?: () => void;
  signInReady?: boolean;
}) {
  return (
    <div id="pricing" className="bg-ink text-paper">
      <section className="mx-auto max-w-6xl px-6 py-24 text-center">
        <h2 className="mx-auto max-w-3xl font-display text-[36px] leading-[1.1] tracking-[-0.01em] sm:text-[52px]">
          Send your first payment{" "}
          <em className="italic text-emerald-bright">this afternoon.</em>
        </h2>
        <p className="mx-auto mt-5 max-w-140 text-[17px] leading-[1.6] text-balance text-line">
          Set up a sandbox account, add one payee, and watch it land. Nothing to
          install.
        </p>
        <div className="mt-9 flex justify-center">
          {onSignIn ? (
            <button
              onClick={onSignIn}
              disabled={!signInReady}
              className={buttonClasses("paper", "lg")}
            >
              Start paying your team
            </button>
          ) : (
            <Link href="/dashboard" className={buttonClasses("paper", "lg")}>
              Start paying your team
            </Link>
          )}
        </div>
      </section>

      <footer className="mx-auto flex max-w-6xl flex-col gap-4 border-t border-white/10 px-6 py-8 sm:flex-row sm:items-center sm:justify-between">
        <Wordmark markClassName="text-emerald-bright" />
        <p className="text-sm text-ink-mute">
          Embedded wallets by{" "}
          <a
            href="https://www.privy.io"
            target="_blank"
            rel="noreferrer"
            className="text-line transition-colors hover:text-paper"
          >
            Privy
          </a>{" "}
          &middot; USDC settlement by{" "}
          <a
            href="https://www.circle.com/arc"
            target="_blank"
            rel="noreferrer"
            className="text-line transition-colors hover:text-paper"
          >
            Circle
          </a>
        </p>
      </footer>
    </div>
  );
}
