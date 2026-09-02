const encoder = new TextEncoder();

export async function sha256Hex(value: string | Uint8Array): Promise<string> {
  const bytes = typeof value === "string" ? encoder.encode(value) : value;
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return [...new Uint8Array(digest)].map((byte) => byte.toString(16).padStart(2, "0")).join("");
}

export function timingSafeHexEqual(left: string, right: string): boolean {
  if (!/^[a-f0-9]+$/i.test(left) || !/^[a-f0-9]+$/i.test(right) || left.length !== right.length || left.length % 2 !== 0) {
    return false;
  }
  const leftBytes = Uint8Array.from(left.match(/.{2}/g) ?? [], (value) => Number.parseInt(value, 16));
  const rightBytes = Uint8Array.from(right.match(/.{2}/g) ?? [], (value) => Number.parseInt(value, 16));
  return crypto.subtle.timingSafeEqual(leftBytes, rightBytes);
}

export function secureCode(bytes = 18): string {
  const buffer = new Uint8Array(bytes);
  crypto.getRandomValues(buffer);
  return [...buffer]
    .map((byte) => byte.toString(36).padStart(2, "0"))
    .join("")
    .slice(0, bytes * 2);
}

export function nowIso(): string {
  return new Date().toISOString();
}
