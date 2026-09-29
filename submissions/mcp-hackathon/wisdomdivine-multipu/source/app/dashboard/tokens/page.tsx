"use client";

import Link from "next/link";
import Image from "next/image";
import { motion, AnimatePresence } from "framer-motion";
import { fadeUp, stagger } from "@/components/motion";
import {
  IconCopy,
  IconExternalLink,
  IconSearch,
  IconEdit,
  IconTrash,
  IconX,
  IconUpload,
  IconLoader2,
  IconCheck,
  IconChevronDown,
} from "@tabler/icons-react";
import { cn } from "@/lib/utils";
import { useApi } from "@/hooks/use-api";
import { ListSkeleton } from "@/components/skeleton";
import { DataError } from "@/components/error-boundary";
import { toast } from "sonner";
import { useState, useMemo, useCallback } from "react";
import { useConfirm } from "@/components/ui/custom-confirm";

interface Token {
  id: string;
  name: string;
  symbol: string;
  mint_address: string | null;
  image_url?: string | null;
  supply: string;
  decimals: number;
  description?: string | null;
  status: string;
  created_at: string;
  launches: { id: string; launchpad: string; status: string }[];
}

interface TokensResponse {
  tokens: Token[];
}

function formatAddress(addr: string | null) {
  if (!addr) return "—";
  return `${addr.slice(0, 4)}...${addr.slice(-4)}`;
}

function timeAgo(dateStr: string) {
  const seconds = Math.floor(
    (Date.now() - new Date(dateStr).getTime()) / 1000
  );
  if (seconds < 60) return "just now";
  if (seconds < 3600) return `${Math.floor(seconds / 60)}m ago`;
  if (seconds < 86400) return `${Math.floor(seconds / 3600)}h ago`;
  return `${Math.floor(seconds / 86400)}d ago`;
}

export default function TokensPage() {
  const confirm = useConfirm();
  const { data, loading, error, refetch } =
    useApi<TokensResponse>("/api/tokens");
  const [search, setSearch] = useState("");
  const [statusFilter, setStatusFilter] = useState<"all" | "active" | "pending">("all");

  // Edit Modal State
  const [editingToken, setEditingToken] = useState<Token | null>(null);
  const [editForm, setEditForm] = useState({
    name: "",
    symbol: "",
    supply: "",
    decimals: 9,
    description: "",
    imageUrl: "",
  });
  const [editImageFile, setEditImageFile] = useState<File | null>(null);
  const [editImagePreview, setEditImagePreview] = useState<string | null>(null);
  const [decimalsOpen, setDecimalsOpen] = useState(false);
  const [isSaving, setIsSaving] = useState(false);
  const [isDeleting, setIsDeleting] = useState<string | null>(null);

  const tokens = useMemo(() => {
    let all = data?.tokens || [];
    if (statusFilter !== "all") {
      all = all.filter((t) => t.status === statusFilter);
    }
    if (!search) return all;
    const q = search.toLowerCase();
    return all.filter(
      (t) =>
        t.name.toLowerCase().includes(q) ||
        t.symbol.toLowerCase().includes(q) ||
        t.mint_address?.toLowerCase().includes(q)
    );
  }, [data, search, statusFilter]);

  const openEditModal = (token: Token) => {
    setEditingToken(token);
    setEditForm({
      name: token.name,
      symbol: token.symbol,
      supply: token.supply,
      decimals: token.decimals || 9,
      description: token.description || "",
      imageUrl: token.image_url || "",
    });
    setEditImageFile(null);
    setEditImagePreview(token.image_url || null);
  };

  const handleImageSelect = useCallback(
    (e: React.ChangeEvent<HTMLInputElement>) => {
      const file = e.target.files?.[0];
      if (!file) return;

      if (file.size > 5 * 1024 * 1024) {
        toast.error("Image must be under 5MB");
        return;
      }

      setEditImageFile(file);
      const reader = new FileReader();
      reader.onload = () => setEditImagePreview(reader.result as string);
      reader.readAsDataURL(file);
    },
    []
  );

  const handleSaveEdit = async () => {
    if (!editingToken) return;
    setIsSaving(true);
    try {
      let finalImageUrl = editForm.imageUrl || null;

      if (editImageFile) {
        const formData = new FormData();
        formData.append("file", editImageFile);
        const uploadRes = await fetch("/api/upload", {
          method: "POST",
          body: formData,
        });
        if (uploadRes.ok) {
          const { url } = await uploadRes.json();
          finalImageUrl = url;
        } else {
          toast.error("Image upload failed, preserving previous image.");
        }
      }

      const res = await fetch("/api/tokens", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          tokenId: editingToken.id,
          name: editForm.name,
          symbol: editForm.symbol.toUpperCase(),
          supply: editForm.supply,
          decimals: editForm.decimals,
          description: editForm.description,
          imageUrl: finalImageUrl,
        }),
      });

      if (!res.ok) {
        const errData = await res.json();
        throw new Error(errData.error || "Failed to update token");
      }

      toast.success("Draft token updated successfully");
      setEditingToken(null);
      refetch();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Update failed");
    } finally {
      setIsSaving(false);
    }
  };

  const handleDeleteDraft = async (tokenId: string) => {
    const ok = await confirm({
      title: "Delete Draft Token",
      message: "Are you sure you want to delete this draft token? Unconfirmed deployment configurations will be permanently removed.",
      variant: "danger",
      confirmText: "Delete Draft",
      cancelText: "Keep Token",
    });
    if (!ok) return;
    setIsDeleting(tokenId);
    try {
      const res = await fetch(`/api/tokens?id=${tokenId}`, {
        method: "DELETE",
      });
      if (!res.ok) {
        const err = await res.json();
        throw new Error(err.error || "Failed to delete token");
      }
      toast.success("Draft token deleted");
      refetch();
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "Delete failed");
    } finally {
      setIsDeleting(null);
    }
  };

  return (
    <div className="p-6 md:p-10 max-w-[1400px]">
      {/* Header */}
      <motion.div
        initial="hidden"
        animate="visible"
        variants={stagger}
        className="mb-8"
      >
        <motion.div
          variants={fadeUp}
          className="flex items-center justify-between"
        >
          <div>
            <h1 className="text-2xl md:text-3xl font-bold tracking-tight text-white font-sans">
              Tokens
            </h1>
            <p className="mt-1 text-sm text-neutral-400 font-sans">
              All your deployed and draft tokens in one place.
            </p>
          </div>
          <Link
            href="/launch"
            className="hidden md:inline-flex items-center px-5 py-2.5 text-sm font-semibold bg-white text-black hover:bg-neutral-200 rounded-full transition-colors cursor-pointer font-sans"
          >
            Create Token
          </Link>
        </motion.div>
      </motion.div>

      {/* Search & Filter bar */}
      <motion.div
        initial="hidden"
        animate="visible"
        variants={fadeUp}
        className="mb-6 flex flex-col sm:flex-row items-stretch sm:items-center gap-3"
      >
        <div className="flex-1 relative bg-[#181818] rounded-xl border border-white/[0.04]">
          <IconSearch
            size={16}
            className="absolute left-3.5 top-1/2 -translate-y-1/2 text-neutral-400"
          />
          <input
            type="text"
            placeholder="Search tokens by name, symbol, or mint address..."
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            className="w-full bg-transparent border-0 focus:outline-none pl-10 pr-4 py-2.5 text-xs text-white placeholder:text-neutral-500 font-mono"
          />
        </div>

        <div className="flex items-center gap-1.5 bg-[#181818] p-1 rounded-xl border border-white/[0.04]">
          {(["all", "active", "pending"] as const).map((st) => (
            <button
              key={st}
              onClick={() => setStatusFilter(st)}
              className={cn(
                "px-3.5 py-1.5 text-xs font-mono uppercase tracking-wider rounded-lg transition-colors cursor-pointer",
                statusFilter === st
                  ? "bg-white/[0.1] text-white font-semibold"
                  : "text-neutral-400 hover:text-white"
              )}
            >
              {st}
            </button>
          ))}
        </div>
      </motion.div>

      {/* Loading */}
      {loading && <ListSkeleton count={3} />}

      {/* Error */}
      {error && !loading && <DataError message={error} onRetry={refetch} />}

      {/* Token cards */}
      {!loading && !error && (
        <motion.div
          initial="hidden"
          animate="visible"
          variants={stagger}
          className="space-y-3"
        >
          {tokens.map((token) => {
            const isPending = token.status === "pending";

            return (
              <motion.div
                key={token.id}
                variants={fadeUp}
                className="bg-[#181818] rounded-2xl p-5 sm:p-6 border border-white/[0.04] hover:border-white/[0.08] transition-all"
              >
                <div className="flex flex-col sm:flex-row items-start sm:items-center gap-4">
                  <div className="relative w-12 h-12 rounded-xl bg-white/[0.05] border border-white/[0.08] flex items-center justify-center flex-shrink-0 overflow-hidden">
                    {token.image_url ? (
                      <Image
                        src={token.image_url}
                        alt={token.name}
                        fill
                        sizes="48px"
                        className="object-cover"
                      />
                    ) : (
                      <span className="font-mono text-xs font-semibold text-white">
                        {token.symbol?.slice(0, 3) || "TK"}
                      </span>
                    )}
                  </div>

                  <div className="flex-1 min-w-0">
                    <div className="flex items-center gap-2 mb-1 flex-wrap">
                      <span className="text-base font-semibold text-white truncate font-sans">
                        {token.name}
                      </span>
                      <span className="font-mono text-xs text-neutral-400">
                        ${token.symbol}
                      </span>
                      <span className="font-mono text-[11px] px-2.5 py-0.5 rounded-full bg-white/[0.06] text-neutral-300 capitalize">
                        {isPending ? "Draft / Pending" : "Active"}
                      </span>
                    </div>
                    <div className="flex items-center gap-4 text-xs text-neutral-400 font-mono flex-wrap">
                      <span className="flex items-center gap-1.5">
                        {isPending ? (
                          <span className="text-neutral-500">Un-minted</span>
                        ) : (
                          <>
                            <span>{formatAddress(token.mint_address)}</span>
                            {token.mint_address && (
                              <IconCopy
                                size={12}
                                className="text-neutral-400 hover:text-white cursor-pointer"
                                onClick={() => {
                                  navigator.clipboard.writeText(token.mint_address!);
                                  toast.success("Mint Address copied!");
                                }}
                              />
                            )}
                          </>
                        )}
                      </span>
                      <span>
                        Supply: {Number(token.supply).toLocaleString()}
                      </span>
                      <span>Decimals: {token.decimals}</span>
                    </div>
                  </div>

                  <div className="flex items-center gap-3 w-full sm:w-auto justify-between sm:justify-end mt-3 sm:mt-0 pt-3 sm:pt-0 border-t sm:border-t-0 border-white/[0.04]">
                    {isPending ? (
                      <div className="flex items-center gap-2">
                        <button
                          type="button"
                          onClick={() => openEditModal(token)}
                          className="px-3.5 py-1.5 rounded-xl bg-white/[0.05] hover:bg-white/[0.1] text-white text-xs font-medium font-sans transition-colors cursor-pointer inline-flex items-center gap-1.5"
                        >
                          <IconEdit size={13} />
                          <span>Edit Draft</span>
                        </button>
                        <Link
                          href={`/launch?resume=${token.id}`}
                          className="px-4 py-1.5 rounded-xl bg-white text-black hover:bg-neutral-200 text-xs font-semibold font-sans transition-colors cursor-pointer inline-flex items-center"
                        >
                          Launch
                        </Link>
                        <button
                          type="button"
                          onClick={() => handleDeleteDraft(token.id)}
                          disabled={isDeleting === token.id}
                          className="p-1.5 text-neutral-500 hover:text-red-400 hover:bg-red-500/10 rounded-lg transition-colors cursor-pointer"
                          title="Delete draft"
                        >
                          <IconTrash size={14} />
                        </button>
                      </div>
                    ) : (
                      <div className="flex items-center gap-3">
                        <div className="flex flex-col items-end gap-0.5">
                          <span className="text-xs font-mono text-neutral-400">
                            {timeAgo(token.created_at)}
                          </span>
                          <span className="font-mono text-[10px] text-neutral-500">
                            {token.launches?.length || 0} launchpad
                            {(token.launches?.length || 0) !== 1 ? "s" : ""}
                          </span>
                        </div>

                        {token.mint_address && (
                          <a
                            href={`https://explorer.solana.com/address/${token.mint_address}?cluster=${process.env.NEXT_PUBLIC_SOLANA_NETWORK || "devnet"}`}
                            target="_blank"
                            rel="noopener noreferrer"
                            className="p-1.5 text-neutral-400 hover:text-white rounded-lg transition-colors"
                          >
                            <IconExternalLink size={14} />
                          </a>
                        )}
                      </div>
                    )}
                  </div>
                </div>
              </motion.div>
            );
          })}
        </motion.div>
      )}

      {/* Empty state */}
      {!loading && !error && tokens.length === 0 && (
        <div className="bg-[#181818] rounded-2xl p-12 text-center border border-white/[0.04]">
          <h3 className="text-base font-semibold text-white mb-2 font-sans">
            {search ? "No matching tokens" : "No tokens yet"}
          </h3>
          <p className="text-sm text-neutral-400 mb-6 font-sans">
            {search
              ? "Try a different search term or filter."
              : "Deploy your first token to see it here."}
          </p>
          {!search && (
            <Link
              href="/launch"
              className="inline-flex items-center px-5 py-2.5 text-sm font-semibold bg-white text-black hover:bg-neutral-200 rounded-full transition-colors cursor-pointer font-sans"
            >
              Create Token
            </Link>
          )}
        </div>
      )}

      {/* Edit Pending Token Modal */}
      <AnimatePresence>
        {editingToken && (
          <div className="fixed inset-0 z-50 flex items-center justify-center p-4 sm:p-6">
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              onClick={() => setEditingToken(null)}
              className="absolute inset-0 bg-black/80 backdrop-blur-sm"
            />

            <motion.div
              initial={{ opacity: 0, scale: 0.95, y: 10 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.95, y: 10 }}
              className="relative w-full max-w-2xl bg-[#181818] border border-white/[0.08] p-8 md:p-10 rounded-3xl shadow-2xl z-10 space-y-6 max-h-[90vh] overflow-y-auto"
            >
              <div className="flex items-center justify-between pb-5 border-b border-white/[0.06]">
                <div>
                  <h3 className="text-xl md:text-2xl font-bold text-white font-sans tracking-tight">
                    Edit Draft Token
                  </h3>
                  <p className="text-xs sm:text-sm text-neutral-400 mt-1 font-sans">
                    Update token parameters before broadcasting on-chain.
                  </p>
                </div>
                <button
                  type="button"
                  onClick={() => setEditingToken(null)}
                  className="p-2 text-neutral-400 hover:text-white rounded-full hover:bg-white/[0.05] transition-colors cursor-pointer"
                >
                  <IconX size={20} />
                </button>
              </div>

              <div className="space-y-5">
                {/* Image Upload */}
                <div>
                  <label className="block text-xs font-sans font-semibold text-neutral-300 mb-2">
                    Token Logo
                  </label>
                  <div className="flex items-center gap-5">
                    <label className="relative w-20 h-20 border border-dashed border-white/20 hover:border-white/40 bg-[#141414] rounded-2xl flex flex-col items-center justify-center cursor-pointer overflow-hidden group transition-colors">
                      {editImagePreview ? (
                        <Image
                          src={editImagePreview}
                          alt="Preview"
                          fill
                          className="object-cover"
                        />
                      ) : (
                        <IconUpload size={22} className="text-neutral-400 group-hover:text-white transition-colors" />
                      )}
                      <input
                        type="file"
                        accept="image/png,image/jpeg,image/webp,image/gif"
                        className="absolute inset-0 opacity-0 cursor-pointer"
                        onChange={handleImageSelect}
                      />
                    </label>
                    <span className="text-xs text-neutral-400 font-sans max-w-xs leading-relaxed">
                      Click box to upload or replace logo (Max 5MB PNG/JPG/WEBP).
                    </span>
                  </div>
                </div>

                {/* Name & Symbol */}
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  <div>
                    <label className="block text-xs font-sans font-semibold text-neutral-300 mb-2">
                      Token Name
                    </label>
                    <input
                      type="text"
                      maxLength={32}
                      value={editForm.name}
                      onChange={(e) => setEditForm({ ...editForm, name: e.target.value })}
                      className="w-full h-12 bg-[#141414] border border-white/[0.08] focus:border-white/30 focus:outline-none px-4 text-sm text-white rounded-xl transition-colors font-sans"
                    />
                  </div>
                  <div>
                    <label className="block text-xs font-sans font-semibold text-neutral-300 mb-2">
                      Symbol
                    </label>
                    <input
                      type="text"
                      maxLength={10}
                      value={editForm.symbol}
                      onChange={(e) => setEditForm({ ...editForm, symbol: e.target.value.toUpperCase() })}
                      className="w-full h-12 bg-[#141414] border border-white/[0.08] focus:border-white/30 focus:outline-none px-4 text-sm text-white font-mono transition-colors uppercase rounded-xl"
                    />
                  </div>
                </div>

                {/* Supply & Custom Decimals Dropdown */}
                <div className="grid grid-cols-1 sm:grid-cols-2 gap-4">
                  <div>
                    <label className="block text-xs font-sans font-semibold text-neutral-300 mb-2">
                      Total Supply
                    </label>
                    <input
                      type="text"
                      inputMode="numeric"
                      value={editForm.supply}
                      onChange={(e) => {
                        const val = e.target.value.replace(/[^0-9]/g, "");
                        setEditForm({ ...editForm, supply: val });
                      }}
                      className="w-full h-12 bg-[#141414] border border-white/[0.08] focus:border-white/30 focus:outline-none px-4 text-sm text-white font-mono transition-colors rounded-xl"
                    />
                  </div>
                  <div>
                    <label className="block text-xs font-sans font-semibold text-neutral-300 mb-2">
                      Decimals
                    </label>
                    <div className="relative">
                      <button
                        type="button"
                        onClick={() => setDecimalsOpen(!decimalsOpen)}
                        className="w-full h-12 bg-[#141414] border border-white/[0.08] hover:border-white/20 focus:border-white/30 px-4 text-sm text-white transition-colors rounded-xl flex items-center justify-between font-mono cursor-pointer"
                      >
                        <span>{editForm.decimals} Decimals</span>
                        <IconChevronDown
                          size={16}
                          className={cn("text-neutral-400 transition-transform duration-200", decimalsOpen && "rotate-180")}
                        />
                      </button>
                      <AnimatePresence>
                        {decimalsOpen && (
                          <motion.div
                            initial={{ opacity: 0, y: -4 }}
                            animate={{ opacity: 1, y: 0 }}
                            exit={{ opacity: 0, y: -4 }}
                            className="absolute left-0 right-0 top-full mt-2 z-50 bg-[#141414] border border-white/[0.1] rounded-xl p-1.5 space-y-1 shadow-2xl"
                          >
                            {[6, 8, 9].map((d) => (
                              <button
                                key={d}
                                type="button"
                                onClick={() => {
                                  setEditForm({ ...editForm, decimals: d });
                                  setDecimalsOpen(false);
                                }}
                                className={cn(
                                  "w-full flex items-center justify-between px-3.5 py-2.5 rounded-lg text-xs font-mono transition-colors cursor-pointer",
                                  editForm.decimals === d
                                    ? "bg-white/[0.1] text-white font-semibold"
                                    : "text-neutral-400 hover:text-white hover:bg-white/[0.04]"
                                )}
                              >
                                <span>{d} Decimals</span>
                                {editForm.decimals === d && <IconCheck size={14} className="text-white" />}
                              </button>
                            ))}
                          </motion.div>
                        )}
                      </AnimatePresence>
                    </div>
                  </div>
                </div>

                {/* Description */}
                <div>
                  <label className="block text-xs font-sans font-semibold text-neutral-300 mb-2">
                    Description
                  </label>
                  <textarea
                    rows={3}
                    maxLength={500}
                    value={editForm.description}
                    onChange={(e) => setEditForm({ ...editForm, description: e.target.value })}
                    className="w-full bg-[#141414] border border-white/[0.08] focus:border-white/30 focus:outline-none p-4 text-sm text-white transition-colors resize-none rounded-xl font-sans"
                  />
                </div>
              </div>

              {/* Actions */}
              <div className="flex items-center justify-end gap-3 pt-5 border-t border-white/[0.06]">
                <button
                  type="button"
                  onClick={() => setEditingToken(null)}
                  className="px-6 py-2.5 text-xs font-sans font-semibold text-white bg-white/[0.05] hover:bg-white/[0.1] border border-white/[0.06] rounded-full transition-colors cursor-pointer"
                >
                  Cancel
                </button>
                <button
                  type="button"
                  disabled={isSaving || !editForm.name || !editForm.symbol || !editForm.supply}
                  onClick={handleSaveEdit}
                  className={cn(
                    "inline-flex items-center justify-center gap-2 px-6 py-2.5 text-xs font-sans font-semibold rounded-full transition-colors cursor-pointer",
                    isSaving
                      ? "bg-white/40 text-black cursor-not-allowed"
                      : "bg-white text-black hover:bg-neutral-200"
                  )}
                >
                  {isSaving ? (
                    <>
                      <IconLoader2 size={14} className="animate-spin" />
                      <span>Saving...</span>
                    </>
                  ) : (
                    <>
                      <IconCheck size={14} />
                      <span>Save Changes</span>
                    </>
                  )}
                </button>
              </div>
            </motion.div>
          </div>
        )}
      </AnimatePresence>
    </div>
  );
}
