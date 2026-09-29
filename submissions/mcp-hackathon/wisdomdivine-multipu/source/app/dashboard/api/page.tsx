"use client";

import { useState, useEffect } from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  IconKey,
  IconCopy,
  IconCheck,
  IconTrash,
  IconPlus,
  IconLock,
  IconArrowUpRight,
  IconBook,
  IconCode,
} from "@tabler/icons-react";
import { fadeUp, stagger } from "@/components/motion";
import { useAuth } from "@/hooks/use-auth";
import { toast } from "sonner";
import { useConfirm } from "@/components/ui/custom-confirm";

interface ApiKeyData {
  id: string;
  name: string;
  api_key: string;
  created_at: string;
  revoked: boolean;
}

export default function ApiKeysPage() {
  const { session } = useAuth();
  const confirm = useConfirm();
  const [keys, setKeys] = useState<ApiKeyData[]>([]);
  const [loading, setLoading] = useState(true);
  const [newKeyName, setNewKeyName] = useState("");
  const [isGenerating, setIsGenerating] = useState(false);

  // State for newly generated key banner
  const [generatedKey, setGeneratedKey] = useState<string | null>(null);
  const [copiedKey, setCopiedKey] = useState(false);
  const [copiedMcp, setCopiedMcp] = useState(false);

  const fetchKeys = async () => {
    try {
      const res = await fetch("/api/developer/api-keys");
      if (!res.ok) throw new Error("Failed to fetch API keys");
      const data = await res.json();
      setKeys(data.keys || []);
    } catch (err) {
      toast.error("Could not fetch API keys");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (session.isLoggedIn) {
      fetchKeys();
    }
  }, [session.isLoggedIn]);

  const handleCreateKey = async (e: React.FormEvent) => {
    e.preventDefault();
    if (!newKeyName.trim()) {
      toast.error("Please enter a name for the key");
      return;
    }

    setIsGenerating(true);
    try {
      const res = await fetch("/api/developer/api-keys", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ name: newKeyName }),
      });

      if (!res.ok) {
        const data = await res.json();
        throw new Error(data.error || "Failed to generate key");
      }

      const data = await res.json();
      setGeneratedKey(data.key.api_key);
      setNewKeyName("");
      toast.success("API key generated successfully!");
      fetchKeys();
    } catch (err: any) {
      toast.error(err.message || "Could not generate API key");
    } finally {
      setIsGenerating(false);
    }
  };

  const handleRevokeKey = async (id: string) => {
    const keyToRevoke = keys.find((k) => k.id === id);
    const confirmed = await confirm({
      title: "Revoke API Key",
      message: `Are you sure you want to revoke "${keyToRevoke?.name || "this API key"}"? Any automated trading bots or MCP sidecars using this key will immediately lose access.`,
      variant: "danger",
      confirmText: "Revoke Key",
      cancelText: "Keep Active",
    });
    if (!confirmed) return;

    try {
      const res = await fetch(`/api/developer/api-keys?id=${id}`, {
        method: "DELETE",
      });

      if (!res.ok) throw new Error("Failed to revoke key");

      toast.success("API key revoked");
      fetchKeys();
    } catch (err) {
      toast.error("Could not revoke key");
    }
  };

  const copyToClipboard = (text: string) => {
    navigator.clipboard.writeText(text);
    setCopiedKey(true);
    toast.success("API Key copied to clipboard");
    setTimeout(() => setCopiedKey(false), 2000);
  };

  const copyMcpConfig = (keySample: string) => {
    const config = JSON.stringify(
      {
        mcpServers: {
          multipu: {
            command: "npx",
            args: ["-y", "multipu-mcp@latest"],
            env: {
              MULTIPU_API_KEY: keySample,
            },
          },
        },
      },
      null,
      2
    );
    navigator.clipboard.writeText(config);
    setCopiedMcp(true);
    toast.success("MCP configuration copied to clipboard");
    setTimeout(() => setCopiedMcp(false), 2000);
  };

  return (
    <div className="p-6 md:p-10 max-w-[1400px] mx-auto">
      {/* Header */}
      <motion.div
        initial="hidden"
        animate="visible"
        variants={stagger}
        className="mb-8"
      >
        <motion.div
          variants={fadeUp}
          className="flex flex-col sm:flex-row sm:items-center sm:justify-between gap-4"
        >
          <div>
            <h1 className="text-2xl md:text-3xl font-bold tracking-tight text-white font-sans">
              API Keys &amp; Developer Access
            </h1>
            <p className="mt-1 text-sm text-neutral-400 font-sans">
              Manage developer authentication keys for programmatic and autonomous agent access.
            </p>
          </div>
          <a
            href="https://docs.multipu.fun"
            target="_blank"
            rel="noopener noreferrer"
            className="inline-flex items-center gap-2 px-4 py-2 bg-white/[0.05] hover:bg-white/[0.1] text-white text-xs font-sans font-medium rounded-full border border-white/[0.06] transition-colors cursor-pointer self-start sm:self-auto"
          >
            <IconBook size={14} className="text-neutral-400" />
            <span>Open Documentation</span>
            <IconArrowUpRight size={13} className="text-neutral-400" />
          </a>
        </motion.div>
      </motion.div>

      {/* Generated key warning banner */}
      <AnimatePresence>
        {generatedKey && (
          <motion.div
            initial={{ opacity: 0, y: -10 }}
            animate={{ opacity: 1, y: 0 }}
            exit={{ opacity: 0, y: -10 }}
            className="mb-6 p-5 sm:p-6 bg-[#181818] rounded-2xl border border-emerald-500/30 space-y-4"
          >
            <div className="flex items-start gap-3.5">
              <div className="p-2 bg-emerald-500/10 rounded-xl flex-shrink-0">
                <IconLock size={18} className="text-emerald-400" />
              </div>
              <div className="space-y-1">
                <h3 className="text-sm font-semibold text-white font-sans">
                  Store Your New API Key Securely
                </h3>
                <p className="text-xs text-neutral-400 font-sans leading-relaxed">
                  For security, we only display this API key once. You cannot recover it later. If you lose it, revoke it and generate a new one.
                </p>
              </div>
            </div>

            <div className="bg-[#141414] border border-white/[0.06] rounded-xl p-4 flex flex-col sm:flex-row sm:items-center justify-between gap-3">
              <span className="font-mono text-xs text-emerald-400 break-all select-all font-semibold">
                {generatedKey}
              </span>
              <button
                onClick={() => copyToClipboard(generatedKey)}
                className="flex-shrink-0 inline-flex items-center justify-center gap-1.5 px-4 py-2 bg-white text-black hover:bg-neutral-200 text-xs font-semibold font-sans rounded-full transition-colors cursor-pointer"
              >
                {copiedKey ? <IconCheck size={14} /> : <IconCopy size={14} />}
                <span>{copiedKey ? "Copied" : "Copy Key"}</span>
              </button>
            </div>

            <div className="text-right">
              <button
                onClick={() => setGeneratedKey(null)}
                className="text-xs text-neutral-400 hover:text-white font-sans transition-colors cursor-pointer"
              >
                Dismiss notification
              </button>
            </div>
          </motion.div>
        )}
      </AnimatePresence>

      <div className="space-y-6">
        {/* Main API Key Controls Card */}
        <div className="bg-[#181818] rounded-2xl p-6 md:p-8 border border-white/[0.04] space-y-6">
          <div className="flex items-center justify-between">
            <h2 className="text-sm font-semibold text-white font-sans flex items-center gap-2">
              <IconKey size={16} className="text-neutral-400" />
              API Key Management
            </h2>
            <span className="text-xs font-mono text-neutral-400 bg-white/[0.04] px-2.5 py-1 rounded-full border border-white/[0.04]">
              {keys.length} active
            </span>
          </div>

          {/* Create API Key Form */}
          <form onSubmit={handleCreateKey} className="space-y-3 max-w-xl">
            <label className="text-xs font-sans font-medium text-neutral-300 block">
              Create New API Key
            </label>
            <div className="flex flex-col sm:flex-row gap-2.5">
              <input
                type="text"
                placeholder="e.g. Trading Bot / Agent Worker"
                value={newKeyName}
                onChange={(e) => setNewKeyName(e.target.value)}
                className="flex-1 h-12 bg-[#141414] border border-white/[0.08] focus:border-white/30 rounded-xl px-4 text-sm text-white placeholder:text-neutral-500 font-mono transition-colors focus:outline-none"
              />
              <button
                type="submit"
                disabled={isGenerating}
                className="h-12 bg-white text-black hover:bg-neutral-200 font-semibold text-xs sm:text-sm px-6 rounded-full transition-colors cursor-pointer font-sans inline-flex items-center justify-center gap-2 flex-shrink-0 disabled:opacity-50"
              >
                {isGenerating ? (
                  "Generating..."
                ) : (
                  <>
                    <IconPlus size={14} />
                    <span>Create Key</span>
                  </>
                )}
              </button>
            </div>
          </form>

          {/* Active Keys List */}
          <div className="space-y-3 pt-6 border-t border-white/[0.04]">
            <div className="flex items-center justify-between">
              <span className="text-xs font-sans font-medium text-neutral-300">
                Active Keys
              </span>
              <span className="text-[11px] font-mono text-neutral-500">
                Non-custodial bearer tokens
              </span>
            </div>

            {loading ? (
              <div className="text-xs text-neutral-500 font-mono py-6 text-center">
                Loading keys...
              </div>
            ) : keys.length === 0 ? (
              <div className="text-xs text-neutral-400 font-sans py-10 bg-[#141414] rounded-xl border border-dashed border-white/[0.06] text-center">
                No active keys. Create a key above to authenticate your API and MCP requests.
              </div>
            ) : (
              <div className="space-y-2.5">
                {keys.map((key) => (
                  <div
                    key={key.id}
                    className="bg-[#141414] rounded-xl p-4 border border-white/[0.04] hover:border-white/[0.08] transition-colors flex flex-col sm:flex-row sm:items-center justify-between gap-3 group"
                  >
                    <div className="space-y-1 min-w-0">
                      <div className="text-xs font-semibold text-white font-sans">
                        {key.name}
                      </div>
                      <div className="font-mono text-xs text-neutral-400 select-all break-all">
                        {key.api_key}
                      </div>
                    </div>
                    <div className="flex items-center gap-2 self-end sm:self-auto flex-shrink-0">
                      <button
                        onClick={() => copyToClipboard(key.api_key)}
                        className="px-3 py-1.5 text-xs text-neutral-300 hover:text-white bg-white/[0.05] hover:bg-white/[0.1] rounded-lg transition-colors flex items-center gap-1.5 font-mono cursor-pointer"
                        title="Copy Key"
                      >
                        <IconCopy size={13} />
                        <span>Copy</span>
                      </button>
                      <button
                        onClick={() => handleRevokeKey(key.id)}
                        className="p-1.5 text-neutral-500 hover:text-red-400 hover:bg-red-500/10 rounded-lg transition-colors cursor-pointer"
                        title="Revoke Key"
                      >
                        <IconTrash size={15} />
                      </button>
                    </div>
                  </div>
                ))}
              </div>
            )}
          </div>
        </div>

        {/* MCP & Autonomous Agents Card */}
        <div className="bg-[#181818] rounded-2xl p-6 md:p-8 border border-white/[0.04] space-y-4">
          <div className="flex items-center justify-between">
            <div className="flex items-center gap-2">
              <IconCode size={16} className="text-neutral-400" />
              <h2 className="text-sm font-semibold text-white font-sans">
                MCP &amp; Agent Configuration
              </h2>
            </div>
            <button
              onClick={() =>
                copyMcpConfig(keys.length > 0 ? keys[0].api_key : "YOUR_MULTIPU_API_KEY")
              }
              className="px-3 py-1.5 text-xs text-neutral-300 hover:text-white bg-white/[0.05] hover:bg-white/[0.1] rounded-full transition-colors flex items-center gap-1.5 font-sans cursor-pointer"
            >
              {copiedMcp ? <IconCheck size={13} /> : <IconCopy size={13} />}
              <span>{copiedMcp ? "Copied" : "Copy Config"}</span>
            </button>
          </div>

          <p className="text-xs text-neutral-400 font-sans leading-relaxed">
            Integrate Multipu capabilities directly into Claude Desktop, Cursor, Antigravity, or your custom autonomous trading bot using the Model Context Protocol (MCP).
          </p>

          <div className="bg-[#141414] rounded-xl p-4 border border-white/[0.06] font-mono text-xs text-neutral-300 overflow-x-auto">
            <pre>
{JSON.stringify(
  {
    mcpServers: {
      multipu: {
        command: "npx",
        args: ["-y", "multipu-mcp@latest"],
        env: {
          MULTIPU_API_KEY: keys.length > 0 ? keys[0].api_key : "YOUR_MULTIPU_API_KEY",
        },
      },
    },
  },
  null,
  2
)}
            </pre>
          </div>
        </div>
      </div>
    </div>
  );
}
