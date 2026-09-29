import { createBrowserClient } from "@supabase/ssr";
import type { Database } from "./database.types";

/**
 * Client-side Supabase client (browser).
 * Uses the anon key — RLS policies enforce access control.
 */
export function createClient() {
  return createBrowserClient<Database>(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!
  );
}
