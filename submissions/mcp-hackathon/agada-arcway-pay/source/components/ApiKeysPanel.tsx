"use client";

import { useCallback, useEffect, useState } from "react";
import { buttonClasses, Chip, Eyebrow } from "@/components/ui";
import { apiFetch } from "@/lib/client-api";

interface ApiKeyRow {
  id: string;
  label: string;
  createdAt: string;
  lastUsedAt: string | null;
  revokedAt: string | null;
  rateLimitPerMinute: number;
  maxAmountUsdc: number | null;
}

/**
 * Agent API keys. Deliberately plain: create, see, revoke.
 *
 * A created key is displayed once and never again — there is no stored copy to
 * show, only a SHA-256 hash — so the one-time panel is the only chance to copy it.
 */
export function ApiKeysPanel() {
  const [keys, setKeys] = useState<ApiKeyRow[]>([]);
  const [loading, setLoading] = useState(true);
  const [label, setLabel] = useState("");
  const [creating, setCreating] = useState(false);
  const [justCreated, setJustCreated] = useState<{ key: string; label: string } | null>(null);
  const [copied, setCopied] = useState(false);
  const [error, setError] = useState<string | null>(null);

  const load = useCallback(async () => {
    const res = await apiFetch("/api/keys");
    const data = await res.json();
    if (res.ok) setKeys(data.keys ?? []);
  }, []);

  useEffect(() => {
    let cancelled = false;
    (async () => {
      try {
        await load();
      } finally {
        if (!cancelled) setLoading(false);
      }
    })();
    return () => {
      cancelled = true;
    };
  }, [load]);

  async function create() {
    setCreating(true);
    setError(null);
    try {
      const res = await apiFetch("/api/keys", {
        method: "POST",
        body: JSON.stringify({ label: label.trim() }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.error ?? "Could not create a key.");
      setJustCreated({ key: data.key, label: data.label });
      setLabel("");
      await load();
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create a key.");
    } finally {
      setCreating(false);
    }
  }

  async function revoke(id: string) {
    const res = await apiFetch(`/api/keys/${id}/revoke`, { method: "POST" });
    if (res.ok) await load();
  }

  return (
    <div className="mt-8 rounded-card border border-line bg-card p-6">
      <Eyebrow>Agent API keys</Eyebrow>
      <p className="mt-3 max-w-xl text-[14px] leading-[1.6] text-ink-soft">
        For calling <code className="font-mono text-[12px]">POST /api/capability/pay-by-email</code>{" "}
        from your own tooling or an agent. Each key acts as this company.
      </p>

      {justCreated && (
        <div className="mt-5 rounded-card border border-emerald-100 bg-emerald-50 p-5">
          <div className="text-[13px] font-semibold text-emerald">
            {justCreated.label} — copy it now
          </div>
          <p className="mt-1 text-[13px] text-emerald">
            This is the only time it is shown. We store a hash, not the key.
          </p>
          <div className="mt-3 flex flex-wrap items-center gap-3">
            <code className="min-w-0 break-all font-mono text-[12px] text-ink">
              {justCreated.key}
            </code>
            <button
              onClick={async () => {
                try {
                  await navigator.clipboard.writeText(justCreated.key);
                  setCopied(true);
                  setTimeout(() => setCopied(false), 2000);
                } catch {
                  // Clipboard can be blocked; the key is on screen regardless.
                }
              }}
              className={buttonClasses("secondary", "sm")}
            >
              {copied ? "Copied" : "Copy"}
            </button>
            <button
              onClick={() => setJustCreated(null)}
              className={buttonClasses("quiet", "sm")}
            >
              Done
            </button>
          </div>
        </div>
      )}

      <div className="mt-5 flex flex-wrap items-end gap-3">
        <div className="flex flex-col gap-1.5">
          <label htmlFor="key-label" className="text-[13px] font-medium text-ink-soft">
            New key label
          </label>
          <input
            id="key-label"
            value={label}
            onChange={(e) => setLabel(e.target.value)}
            placeholder="Payroll bot"
            className="w-56 rounded-btn border border-line bg-card px-3 py-2 text-sm text-ink outline-none placeholder:text-ink-mute focus:border-emerald"
          />
        </div>
        <button
          onClick={create}
          disabled={creating || !label.trim()}
          className={buttonClasses("primary", "md")}
        >
          {creating ? "Creating…" : "Create key"}
        </button>
      </div>
      {error && <p className="mt-2 text-[13px] text-amber-text">{error}</p>}

      <div className="mt-6 border-t border-line-soft pt-4">
        {loading ? (
          <p className="text-[13px] text-ink-mute">Loading keys…</p>
        ) : keys.length === 0 ? (
          <p className="text-[13px] text-ink-mute">No keys yet.</p>
        ) : (
          <ul className="flex flex-col gap-3">
            {keys.map((k) => (
              <li key={k.id} className="flex flex-wrap items-center justify-between gap-3">
                <div className="min-w-0">
                  <div className="flex items-center gap-2">
                    <span className="font-medium text-ink">{k.label}</span>
                    {k.revokedAt ? (
                      <Chip tone="amber">Revoked</Chip>
                    ) : (
                      <Chip tone="emerald">Active</Chip>
                    )}
                  </div>
                  <div className="mt-0.5 text-[12px] text-ink-mute">
                    {k.rateLimitPerMinute}/min
                    {k.maxAmountUsdc != null && ` · max ${k.maxAmountUsdc} USDC per call`}
                    {" · "}
                    {k.lastUsedAt
                      ? `last used ${new Date(k.lastUsedAt).toLocaleString()}`
                      : "never used"}
                  </div>
                </div>
                {!k.revokedAt && (
                  <button onClick={() => revoke(k.id)} className={buttonClasses("secondary", "sm")}>
                    Revoke
                  </button>
                )}
              </li>
            ))}
          </ul>
        )}
      </div>
    </div>
  );
}
