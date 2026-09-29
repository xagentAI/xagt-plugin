"use client";

import { createContext, useCallback, useContext, useEffect, useState } from "react";
import { resolveSession, type SessionInfo } from "@/lib/client-api";

/**
 * Shared session state for the dashboard.
 *
 * This exists because the dashboard layout wraps both /dashboard and
 * /dashboard/welcome, so it does NOT remount when onboarding finishes.
 * Fetching the session once per mount therefore left a freshly-onboarded
 * employer holding a stale "needs-company" answer, which bounced them back to
 * the welcome screen forever. Anything that changes the session — creating a
 * company — must call `refresh()` so the next redirect decision is made on
 * current data.
 */
interface SessionState {
  session: SessionInfo | null;
  resolved: boolean;
  refresh: () => Promise<SessionInfo | null>;
}

const Context = createContext<SessionState | null>(null);

export function SessionProvider({ children }: { children: React.ReactNode }) {
  const [session, setSession] = useState<SessionInfo | null>(null);
  const [resolved, setResolved] = useState(false);

  const refresh = useCallback(async () => {
    const next = await resolveSession();
    setSession(next);
    setResolved(true);
    return next;
  }, []);

  // The initial fetch is inlined rather than delegating to `refresh()` so the
  // state update is visibly deferred behind an await — the lint rule that
  // guards against synchronous setState in an effect cannot see through an
  // async helper.
  useEffect(() => {
    let cancelled = false;
    (async () => {
      const next = await resolveSession();
      if (cancelled) return;
      setSession(next);
      setResolved(true);
    })();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <Context.Provider value={{ session, resolved, refresh }}>
      {children}
    </Context.Provider>
  );
}

export function useSession(): SessionState {
  const ctx = useContext(Context);
  if (!ctx) throw new Error("useSession must be used inside a SessionProvider.");
  return ctx;
}
