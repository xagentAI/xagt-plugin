"use client";

import { useSyncExternalStore } from "react";

const noop = () => () => {};

/** `false` during server rendering and hydration, `true` afterwards. */
export function useHydrated(): boolean {
  return useSyncExternalStore(
    noop,
    () => true,
    () => false,
  );
}

export const ORIGIN_PLACEHOLDER = "https://<settle-host>";

/** The browser's current origin; a placeholder while rendering on the server. */
export function useOrigin(): string {
  return useSyncExternalStore(
    noop,
    () => window.location.origin,
    () => ORIGIN_PLACEHOLDER,
  );
}

function subscribeVisibility(onChange: () => void): () => void {
  document.addEventListener("visibilitychange", onChange);
  return () => document.removeEventListener("visibilitychange", onChange);
}

/** Whether the document is currently visible; `true` on the server. */
export function usePageVisible(): boolean {
  return useSyncExternalStore(
    subscribeVisibility,
    () => document.visibilityState !== "hidden",
    () => true,
  );
}
