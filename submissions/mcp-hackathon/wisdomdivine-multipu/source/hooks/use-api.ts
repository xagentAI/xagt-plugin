"use client";

import { useState, useEffect, useCallback } from "react";

interface UseApiOptions {
  /** Skip initial fetch (e.g. wait for auth) */
  skip?: boolean;
}

interface UseApiResult<T> {
  data: T | null;
  error: string | null;
  loading: boolean;
  refetch: () => Promise<void>;
}

/**
 * Generic hook for fetching data from our API routes.
 * Handles loading states, errors, and refetching.
 */
export function useApi<T>(
  url: string | null,
  options: UseApiOptions = {}
): UseApiResult<T> {
  const { skip = false } = options;
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(!skip);

  const fetchData = useCallback(async () => {
    if (!url) return;
    setLoading(true);
    setError(null);

    try {
      const res = await fetch(url, {
        credentials: "include",
        headers: { Accept: "application/json" },
      });

      if (!res.ok) {
        const body = await res.json().catch(() => ({}));
        throw new Error(body.error || `Request failed (${res.status})`);
      }

      const json = await res.json();
      setData(json);
    } catch (err) {
      const message = err instanceof Error ? err.message : "Network error";
      setError(message);
    } finally {
      setLoading(false);
    }
  }, [url]);

  useEffect(() => {
    if (!skip && url) {
      fetchData();
    }
  }, [skip, url, fetchData]);

  return { data, error, loading, refetch: fetchData };
}
