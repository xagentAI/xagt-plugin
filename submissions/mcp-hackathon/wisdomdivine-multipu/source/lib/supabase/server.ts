import { createServerClient } from "@supabase/ssr";
import { createClient } from "@supabase/supabase-js";
import { cookies } from "next/headers";
import type { Database } from "./database.types";

/**
 * Server-side Supabase client (API routes, server components).
 * Uses anon key with cookie-based auth forwarding.
 */
export async function createServerSupabase() {
  const cookieStore = await cookies();

  return createServerClient<Database>(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
    {
      cookies: {
        getAll() {
          return cookieStore.getAll();
        },
        setAll(cookiesToSet) {
          try {
            cookiesToSet.forEach(({ name, value, options }) =>
              cookieStore.set(name, value, options)
            );
          } catch {
            // Can fail in Server Components (read-only cookies).
            // Safe to ignore — only matters in Route Handlers.
          }
        },
      },
    }
  );
}

/**
 * Admin Supabase client — bypasses RLS.
 * Only use in trusted server contexts (webhooks, cron jobs).
 */
export function createAdminSupabase() {
  const serviceKey =
    process.env.SUPABASE_SERVICE_ROLE_KEY ||
    process.env.SUPABASE_SERVICE_KEY;

  if (!serviceKey) {
    throw new Error("CRITICAL: SUPABASE_SERVICE_KEY or SUPABASE_SERVICE_ROLE_KEY is required for admin database operations.");
  }

  return createClient<Database>(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    serviceKey,
    { auth: { persistSession: false } }
  );
}

