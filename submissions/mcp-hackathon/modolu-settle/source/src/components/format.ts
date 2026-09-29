/** Presentation helpers for the inspector. Pure; no monetary arithmetic happens here. */

const TX_HASH = /^0x[0-9a-f]{64}$/i;
const ADDRESS = /^0x[0-9a-fA-F]{40}$/;

/** Deterministic Base explorer link for a transaction hash, or null when the hash is not well-formed. */
export function explorerTxUrl(txHash: string): string | null {
  return TX_HASH.test(txHash) ? `https://basescan.org/tx/${txHash.toLowerCase()}` : null;
}

export function explorerAddressUrl(address: string): string | null {
  return ADDRESS.test(address) ? `https://basescan.org/address/${address}` : null;
}

/** `0x7db45d69…61b0f5` */
export function shortenHex(value: string, head = 10, tail = 6): string {
  return value.length <= head + tail + 1 ? value : `${value.slice(0, head)}…${value.slice(-tail)}`;
}

/** ISO timestamp → `2026-09-18 04:28:43 UTC`; unparsable input is echoed unchanged. */
export function formatUtc(iso: string): string {
  const date = new Date(iso);
  if (Number.isNaN(date.getTime())) {
    return iso;
  }
  return `${date.toISOString().slice(0, 19).replace("T", " ")} UTC`;
}

/** Whole-number grouping for display only: "20710.876899" → "20,710.876899". */
export function groupAmount(amount: string): string {
  const [whole = "", fraction] = amount.split(".");
  const grouped = whole.replace(/\B(?=(\d{3})+(?!\d))/g, ",");
  return fraction === undefined ? grouped : `${grouped}.${fraction}`;
}
