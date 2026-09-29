"use client";

import { usePrivy } from "@privy-io/react-auth";
import { usePathname, useRouter } from "next/navigation";
import { useEffect } from "react";
import { AppChrome } from "@/components/AppChrome";
import { SessionProvider, useSession } from "@/components/SessionContext";
import { isPrivyClientConfigured } from "../providers";

/**
 * Chrome + auth gate for every dashboard route.
 *
 * Unauthenticated visitors are sent to "/" rather than shown a sign-in prompt
 * here — the landing page owns login, and routing after login is decided by
 * identity. A signed-in identity that is a payee, or an employer who has not
 * yet named their company, is redirected to where it actually belongs.
 */
export default function DashboardLayout({ children }: { children: React.ReactNode }) {
  if (!isPrivyClientConfigured) return <NotConfigured />;
  return (
    <SessionProvider>
      <AuthGate>
        <div className="flex min-h-screen flex-col">
          <AppChrome />
          <main className="flex-1">{children}</main>
        </div>
      </AuthGate>
    </SessionProvider>
  );
}

function Waiting() {
  return (
    <main className="flex min-h-screen items-center justify-center text-sm text-ink-mute">
      Loading…
    </main>
  );
}

function NotConfigured() {
  return (
    <main className="flex min-h-screen flex-col items-center justify-center gap-4 px-6 text-center">
      <h1 className="font-display text-[32px] text-ink">Sign-in isn&rsquo;t configured</h1>
      <p className="max-w-md text-[15px] text-ink-soft">
        Set <code className="font-mono text-[13px]">NEXT_PUBLIC_PRIVY_APP_ID</code> to
        enable the dashboard. The agent capability endpoint still runs in mock mode.
      </p>
    </main>
  );
}

function AuthGate({ children }: { children: React.ReactNode }) {
  const { ready, authenticated } = usePrivy();
  const router = useRouter();
  const pathname = usePathname();
  const { session, resolved } = useSession();

  useEffect(() => {
    if (ready && !authenticated) router.replace("/");
  }, [ready, authenticated, router]);

  const onWelcome = pathname === "/dashboard/welcome";

  // Redirect on CAPABILITY, not role: someone who has a company belongs here
  // even if they are also a payee elsewhere. Only a person with no company at
  // all is sent away — to /claim if they have payments, otherwise to onboarding.
  useEffect(() => {
    if (!ready || !authenticated || !resolved || !session) return;
    if (session.canUseDashboard) {
      if (onWelcome) router.replace("/dashboard");
      return;
    }
    if (session.canUseClaim) {
      router.replace("/claim");
    } else if (!onWelcome) {
      router.replace("/dashboard/welcome");
    }
  }, [ready, authenticated, resolved, session, onWelcome, router]);

  if (!ready || !authenticated || !resolved) return <Waiting />;
  if (session && !session.canUseDashboard) {
    // Only the welcome screen is reachable without a company.
    if (!onWelcome || session.canUseClaim) return <Waiting />;
  }

  return <>{children}</>;
}
