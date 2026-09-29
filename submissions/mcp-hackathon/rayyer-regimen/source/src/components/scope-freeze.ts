/**
 * The scope and its readout are siblings on the glass, not parent and child, so the
 * freeze is announced on the window rather than threaded through props. One event, one
 * payload, no shared state.
 */
export const SCOPE_FREEZE_EVENT = 'regimen:scope-freeze';

export interface ScopeFreezeDetail {
  readonly frozen: boolean;
}

export function emitScopeFreeze(frozen: boolean): void {
  if (typeof window === 'undefined') return;
  window.dispatchEvent(new CustomEvent<ScopeFreezeDetail>(SCOPE_FREEZE_EVENT, { detail: { frozen } }));
}
