"use client";

import { useState, useEffect, useRef } from "react";
import Link from "next/link";
import { motion, AnimatePresence } from "framer-motion";
import {
  IconX,
  IconRefresh,
  IconCheck,
  IconChecks,
  IconArrowRight,
} from "@tabler/icons-react";
import { cn } from "@/lib/utils";
import type { NotificationItem } from "@/app/api/notifications/route";

interface NotificationsPopupProps {
  isOpen: boolean;
  onClose: () => void;
  onUnreadChange?: (hasUnread: boolean) => void;
}

type TabType = "ALL" | "UNREAD" | "LAUNCHES" | "SIGNALS";

export function NotificationsPopup({
  isOpen,
  onClose,
  onUnreadChange,
}: NotificationsPopupProps) {
  const [notifications, setNotifications] = useState<NotificationItem[]>([]);
  const [loading, setLoading] = useState(false);
  const [activeTab, setActiveTab] = useState<TabType>("ALL");
  const [walletAddress, setWalletAddress] = useState<string | null>(null);
  const [readIds, setReadIds] = useState<Set<string>>(new Set());
  const popupRef = useRef<HTMLDivElement>(null);

  // Fetch live notifications
  const fetchNotifications = async () => {
    setLoading(true);
    try {
      const res = await fetch("/api/notifications");
      if (res.ok) {
        const data = await res.json();
        const items: NotificationItem[] = data.notifications || [];
        setNotifications(items);

        if (data.walletAddress) {
          setWalletAddress(data.walletAddress);
          try {
            const saved = localStorage.getItem(`multipu_read_notifs_${data.walletAddress}`);
            if (saved) {
              setReadIds(new Set(JSON.parse(saved)));
            }
          } catch {}
        }
      }
    } catch {
      // Ignore network errors
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    if (isOpen) {
      fetchNotifications();
      const interval = setInterval(fetchNotifications, 10000);
      return () => clearInterval(interval);
    }
  }, [isOpen]);

  // Handle outside click to close
  useEffect(() => {
    const handleClickOutside = (e: MouseEvent) => {
      const target = e.target as HTMLElement;
      if (target.closest('[data-notification-trigger="true"]')) {
        return;
      }
      if (popupRef.current && !popupRef.current.contains(target)) {
        onClose();
      }
    };
    if (isOpen) {
      document.addEventListener("mousedown", handleClickOutside);
    }
    return () => document.removeEventListener("mousedown", handleClickOutside);
  }, [isOpen, onClose]);

  // Handle Escape key
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    if (isOpen) {
      window.addEventListener("keydown", handleKeyDown);
    }
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isOpen, onClose]);

  // Notify parent of unread changes
  useEffect(() => {
    const unreadRemaining = notifications.some((n) => !readIds.has(n.id));
    onUnreadChange?.(unreadRemaining);
  }, [notifications, readIds, onUnreadChange]);

  const markAllAsRead = () => {
    const allIds = new Set(notifications.map((n) => n.id));
    setReadIds(allIds);
    if (walletAddress) {
      try {
        localStorage.setItem(
          `multipu_read_notifs_${walletAddress}`,
          JSON.stringify(Array.from(allIds))
        );
      } catch {}
    }
    onUnreadChange?.(false);
  };

  const markSingleAsRead = (id: string, e?: React.MouseEvent) => {
    e?.stopPropagation();
    setReadIds((prev) => {
      const updated = new Set(prev);
      updated.add(id);
      if (walletAddress) {
        try {
          localStorage.setItem(
            `multipu_read_notifs_${walletAddress}`,
            JSON.stringify(Array.from(updated))
          );
        } catch {}
      }
      return updated;
    });
  };

  // Filter items based on active tab
  const filteredNotifications = notifications.filter((item) => {
    if (activeTab === "UNREAD") return !readIds.has(item.id);
    if (activeTab === "LAUNCHES") return item.category === "LAUNCH";
    if (activeTab === "SIGNALS") return item.category === "SIGNAL" || item.category === "TRADE";
    return true;
  });

  const unreadCount = notifications.filter((n) => !readIds.has(n.id)).length;
  const launchCount = notifications.filter((n) => n.category === "LAUNCH").length;
  const signalCount = notifications.filter(
    (n) => n.category === "SIGNAL" || n.category === "TRADE"
  ).length;

  return (
    <AnimatePresence>
      {isOpen && (
        <>
          {/* Mobile backdrop */}
          <motion.div
            initial={{ opacity: 0 }}
            animate={{ opacity: 1 }}
            exit={{ opacity: 0 }}
            className="fixed inset-0 bg-black/80 backdrop-blur-sm z-[95] sm:hidden"
            onClick={onClose}
          />

          {/* Spacious Floating Responsive Popup Card with Full Opacity and High z-index */}
          <motion.div
            ref={popupRef}
            initial={{ opacity: 0, y: 8, scale: 0.98 }}
            animate={{ opacity: 1, y: 0, scale: 1 }}
            exit={{ opacity: 0, y: 8, scale: 0.98 }}
            transition={{ duration: 0.18, ease: [0.16, 1, 0.3, 1] }}
            className={cn(
              "fixed sm:absolute top-18 sm:top-full inset-x-3 sm:inset-x-auto sm:right-0 sm:mt-2.5 z-[100]",
              "w-auto sm:w-[500px] md:w-[540px] max-w-[560px]",
              "bg-[#0c0c0e] opacity-100",
              "border border-white/[0.12]",
              "shadow-[0_24px_70px_rgba(0,0,0,0.95)]",
              "rounded-2xl sm:rounded-3xl",
              "overflow-hidden flex flex-col font-[family-name:var(--font-geist-sans)]",
              "max-h-[calc(100dvh-5.5rem)] sm:max-h-[640px]"
            )}
          >
            {/* Header */}
            <div className="px-4 sm:px-6 pt-4 sm:pt-5 pb-3 sm:pb-3.5 border-b border-white/[0.06] flex items-center justify-between">
              <div className="flex items-center gap-2.5 sm:gap-3">
                <h3 className="text-sm sm:text-lg font-bold text-white tracking-tight font-[family-name:var(--font-geist-sans)]">
                  Notifications
                </h3>
                {unreadCount > 0 && (
                  <span className="px-2 sm:px-2.5 py-0.5 rounded-full text-[10px] sm:text-xs font-semibold font-[family-name:var(--font-geist-mono)] bg-purple-500/15 text-purple-300">
                    {unreadCount} unread
                  </span>
                )}
              </div>

              <div className="flex items-center gap-1.5 sm:gap-2">
                {unreadCount > 0 && (
                  <button
                    onClick={markAllAsRead}
                    className="text-[11px] sm:text-xs font-medium text-neutral-400 hover:text-white transition-colors flex items-center gap-1 sm:gap-1.5 px-2 sm:px-2.5 py-1 rounded-lg hover:bg-white/[0.05] cursor-pointer"
                    title="Mark all as read"
                  >
                    <IconChecks size={14} className="text-purple-400 sm:w-[15px] sm:h-[15px]" />
                    <span>Mark all read</span>
                  </button>
                )}

                <button
                  onClick={fetchNotifications}
                  disabled={loading}
                  className="p-1.5 text-neutral-400 hover:text-white hover:bg-white/[0.06] rounded-lg transition-colors cursor-pointer"
                  title="Refresh activity"
                  aria-label="Refresh"
                >
                  <IconRefresh
                    size={15}
                    className={cn(loading && "animate-spin text-purple-400")}
                  />
                </button>

                <button
                  onClick={onClose}
                  className="p-1.5 text-neutral-400 hover:text-white hover:bg-white/[0.06] rounded-lg transition-colors cursor-pointer"
                  title="Close popup"
                  aria-label="Close"
                >
                  <IconX size={15} />
                </button>
              </div>
            </div>

            {/* Filter Navigation Tabs */}
            <div className="px-4 sm:px-6 pt-2.5 sm:pt-3 pb-2 sm:pb-2.5 flex items-center gap-1.5 sm:gap-2 border-b border-white/[0.05] overflow-x-auto scrollbar-none touch-pan-x">
              <button
                onClick={() => setActiveTab("ALL")}
                className={cn(
                  "px-3 sm:px-3.5 py-1.5 rounded-lg text-xs font-medium transition-all whitespace-nowrap cursor-pointer",
                  activeTab === "ALL"
                    ? "bg-white/[0.08] text-white font-semibold"
                    : "text-neutral-400 hover:text-neutral-200 hover:bg-white/[0.03]"
                )}
              >
                All
                <span className="ml-1.5 text-[11px] opacity-70 font-mono">
                  {notifications.length}
                </span>
              </button>

              <button
                onClick={() => setActiveTab("UNREAD")}
                className={cn(
                  "px-3 sm:px-3.5 py-1.5 rounded-lg text-xs font-medium transition-all whitespace-nowrap flex items-center gap-1.5 cursor-pointer",
                  activeTab === "UNREAD"
                    ? "bg-white/[0.08] text-white font-semibold"
                    : "text-neutral-400 hover:text-neutral-200 hover:bg-white/[0.03]"
                )}
              >
                <span>Unread</span>
                {unreadCount > 0 && (
                  <span className="w-1.5 h-1.5 rounded-full bg-purple-500 shadow-[0_0_6px_rgba(139,92,246,0.8)]" />
                )}
              </button>

              <button
                onClick={() => setActiveTab("LAUNCHES")}
                className={cn(
                  "px-3 sm:px-3.5 py-1.5 rounded-lg text-xs font-medium transition-all whitespace-nowrap cursor-pointer",
                  activeTab === "LAUNCHES"
                    ? "bg-white/[0.08] text-white font-semibold"
                    : "text-neutral-400 hover:text-neutral-200 hover:bg-white/[0.03]"
                )}
              >
                Launches
                <span className="ml-1.5 text-[11px] opacity-70 font-mono">
                  {launchCount}
                </span>
              </button>

              <button
                onClick={() => setActiveTab("SIGNALS")}
                className={cn(
                  "px-3 sm:px-3.5 py-1.5 rounded-lg text-xs font-medium transition-all whitespace-nowrap cursor-pointer",
                  activeTab === "SIGNALS"
                    ? "bg-white/[0.08] text-white font-semibold"
                    : "text-neutral-400 hover:text-neutral-200 hover:bg-white/[0.03]"
                )}
              >
                Signals &amp; Trades
                <span className="ml-1.5 text-[11px] opacity-70 font-mono">
                  {signalCount}
                </span>
              </button>
            </div>

            {/* Notification Items List - Clean, Icon-free & Spacious */}
            <div className="max-h-[calc(100dvh-13.5rem)] sm:max-h-[480px] overflow-y-auto divide-y divide-white/[0.03] p-2.5 sm:p-4">
              {filteredNotifications.length === 0 ? (
                <div className="py-12 sm:py-16 px-4 sm:px-6 flex flex-col items-center justify-center text-center">
                  <h4 className="text-sm font-semibold text-white">All caught up</h4>
                  <p className="text-xs text-neutral-400 mt-1 max-w-[260px] leading-relaxed">
                    {activeTab === "UNREAD"
                      ? "You have read all pending notifications."
                      : "No activity records found in this view."}
                  </p>
                </div>
              ) : (
                filteredNotifications.map((item) => {
                  const isUnread = !readIds.has(item.id);

                  const content = (
                    <div
                      onClick={() => markSingleAsRead(item.id)}
                      className={cn(
                        "group relative flex items-start justify-between gap-3 sm:gap-4 p-3 sm:p-4 rounded-xl transition-all cursor-pointer",
                        isUnread
                          ? "bg-white/[0.035] hover:bg-white/[0.06]"
                          : "hover:bg-white/[0.02]"
                      )}
                    >
                      {/* Left Column: Title, Detail & Metric */}
                      <div className="flex-1 min-w-0">
                        <div className="flex items-center gap-2">
                          <h4
                            className={cn(
                              "text-xs sm:text-sm font-semibold tracking-tight truncate",
                              isUnread ? "text-white" : "text-neutral-300"
                            )}
                          >
                            {item.title}
                          </h4>
                        </div>

                        <p className="text-[11px] sm:text-xs text-neutral-400 leading-relaxed mt-1 font-[family-name:var(--font-geist-sans)] line-clamp-2 sm:line-clamp-none">
                          {item.detail}
                        </p>

                        {/* Metric Badge */}
                        {item.metric && (
                          <div className="mt-1.5 sm:mt-2 flex items-center gap-2">
                            <span className="px-2 py-0.5 rounded text-[10px] sm:text-[11px] font-mono font-medium bg-white/[0.05] text-neutral-300">
                              {item.metric}
                            </span>
                          </div>
                        )}
                      </div>

                      {/* Right Column: Time & Unread Status */}
                      <div className="shrink-0 flex flex-col items-end gap-1.5 sm:gap-2 pt-0.5">
                        <span className="text-[10px] sm:text-xs text-neutral-400 font-mono whitespace-nowrap">
                          {item.timeAgo}
                        </span>

                        {isUnread && (
                          <div className="flex items-center">
                            <button
                              onClick={(e) => markSingleAsRead(item.id, e)}
                              className="hidden group-hover:flex items-center justify-center w-5 h-5 rounded-full bg-white/[0.08] hover:bg-purple-500/20 text-neutral-400 hover:text-purple-300 transition-colors"
                              title="Mark as read"
                            >
                              <IconCheck size={12} />
                            </button>
                            <span className="group-hover:hidden w-2 h-2 rounded-full bg-purple-500 shadow-[0_0_8px_rgba(139,92,246,0.8)]" />
                          </div>
                        )}
                      </div>
                    </div>
                  );

                  if (item.link) {
                    return (
                      <Link
                        key={item.id}
                        href={item.link}
                        onClick={() => {
                          markSingleAsRead(item.id);
                          onClose();
                        }}
                      >
                        {content}
                      </Link>
                    );
                  }

                  return <div key={item.id}>{content}</div>;
                })
              )}
            </div>

            {/* Simple Minimalist Footer Bar */}
            <div className="px-4 sm:px-6 py-2.5 sm:py-3 border-t border-white/[0.06] bg-white/[0.01] flex items-center justify-end text-xs">
              <Link
                href="/dashboard/explore"
                onClick={onClose}
                className="text-neutral-300 hover:text-white font-medium flex items-center gap-1.5 transition-colors hover:translate-x-0.5 cursor-pointer font-[family-name:var(--font-geist-sans)]"
              >
                <span>View all activity</span>
                <IconArrowRight size={13} />
              </Link>
            </div>
          </motion.div>
        </>
      )}
    </AnimatePresence>
  );
}
