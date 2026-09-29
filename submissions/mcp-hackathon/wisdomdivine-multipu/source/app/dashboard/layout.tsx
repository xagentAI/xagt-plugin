"use client";

import Link from "next/link";
import Image from "next/image";
import { useState, useEffect, useCallback } from "react";
import { useRouter, usePathname } from "next/navigation";
import { motion, AnimatePresence } from "framer-motion";
import {
  IconTrendingUp,
  IconCoins,
  IconRocket,
  IconLayoutGrid,
  IconSearch,
  IconKey,
  IconX,
  IconBell,
  IconLogout,
  IconArrowsExchange,
  IconLoader2,
} from "@tabler/icons-react";
import { cn } from "@/lib/utils";
import { useAuth } from "@/hooks/use-auth";
import { WalletButton } from "@/components/wallet-button";
import { DashboardHeader } from "@/components/dashboard/dashboard-header";
import { TradingAgentCopilot } from "@/components/dashboard/trading-agent-copilot";
import { DisconnectModal } from "@/components/dashboard/disconnect-modal";
import { toast } from "sonner";

const navItems = [
  { label: "Dashboard", icon: IconLayoutGrid, href: "/dashboard" },
  { label: "Tokens", icon: IconCoins, href: "/dashboard/tokens" },
  { label: "Launches", icon: IconRocket, href: "/dashboard/launches" },
  { label: "Earnings", icon: IconTrendingUp, href: "/dashboard/earnings" },
  { label: "API Keys", icon: IconKey, href: "/dashboard/api" },
  { label: "Trade", icon: IconArrowsExchange, href: "/dashboard/explore" },
];

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const { session, signOut, isLoading } = useAuth();
  const [mobileOpen, setMobileOpen] = useState(false);
  const [notificationsOpen, setNotificationsOpen] = useState(false);
  const [disconnectModalOpen, setDisconnectModalOpen] = useState(false);
  const [hasUnread, setHasUnread] = useState(true);

  // Close mobile sidebar on route change
  useEffect(() => {
    setMobileOpen(false);
  }, [pathname]);

  // Auth guard: redirect unauthenticated users to /signin immediately
  useEffect(() => {
    if (!isLoading && !session.isLoggedIn) {
      router.replace("/signin");
    }
  }, [isLoading, session.isLoggedIn, router]);

  // Check unread notifications count only when authenticated
  useEffect(() => {
    if (!session.isLoggedIn) return;
    fetch("/api/notifications")
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (!data?.notifications) {
          setHasUnread(false);
          return;
        }
        let readIds = new Set<string>();
        if (data.walletAddress && typeof window !== "undefined") {
          try {
            const saved = localStorage.getItem(`multipu_read_notifs_${data.walletAddress}`);
            if (saved) readIds = new Set(JSON.parse(saved));
          } catch {}
        }
        const hasUnreadItems = data.notifications.some((n: any) => !readIds.has(n.id));
        setHasUnread(hasUnreadItems);
      })
      .catch(() => {
        setHasUnread(false);
      });
  }, [session.isLoggedIn]);

  // Close on escape key
  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        setMobileOpen(false);
        setNotificationsOpen(false);
        setDisconnectModalOpen(false);
      }
    };
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, []);

  const handleDisconnect = useCallback(async () => {
    try {
      await signOut();
      setMobileOpen(false);
      toast.success("Wallet disconnected");
      router.push("/signin");
    } catch (err) {
      console.error("Failed to disconnect:", err);
      toast.error("Failed to disconnect wallet");
    }
  }, [signOut, router]);

  const isItemActive = (href: string) => {
    if (href === "/dashboard") {
      return pathname === "/dashboard";
    }
    if (href === "/dashboard/explore") {
      return pathname === "/dashboard/explore" || pathname.startsWith("/dashboard/trade");
    }
    return pathname.startsWith(href);
  };

  const walletShort = session.isLoggedIn
    ? `${session.walletAddress.slice(0, 4)}...${session.walletAddress.slice(-4)}`
    : null;

  if (isLoading) {
    return (
      <div className="min-h-screen bg-black flex items-center justify-center">
        <div className="flex flex-col items-center gap-4">
          <div className="w-12 h-12 rounded-2xl bg-white/[0.04] border border-white/[0.08] flex items-center justify-center animate-pulse">
            <Image
              src="/logo.png"
              alt="Multipu"
              width={28}
              height={28}
              className="w-7 h-7 object-contain"
            />
          </div>
          <IconLoader2 className="w-5 h-5 text-accent animate-spin" />
        </div>
      </div>
    );
  }

  if (!session.isLoggedIn) {
    return null;
  }

  return (
    <div className="h-screen overflow-hidden bg-background">
      <div className="flex h-full">
        {/* Desktop Sidebar */}
        <aside className="hidden lg:flex flex-col w-64 border-r border-white/[0.06] h-full flex-shrink-0 bg-[#121212]">
          {/* Clean Logo Header aligned with header */}
          <div className="h-16 px-6 border-b border-white/[0.06] flex items-center">
            <Link href="/" className="flex items-center gap-2.5 group">
              <div className="relative w-7 h-7 flex-shrink-0">
                <Image src="/logo.png" alt="Multipu" fill sizes="28px" className="object-contain" />
              </div>
              <span className="text-base font-semibold text-white tracking-tight">
                Multipu
              </span>
            </Link>
          </div>

          <nav className="flex-1 px-3 py-3 space-y-1 overflow-y-auto">
            {navItems.map((item) => {
              const isActive = isItemActive(item.href);
              return (
                <Link
                  key={item.label}
                  href={item.href}
                  className={cn(
                    "w-full flex items-center gap-3 px-3.5 py-2.5 text-sm rounded-xl transition-colors font-medium",
                    isActive
                      ? "bg-white/[0.09] text-white"
                      : "text-neutral-400 hover:text-white hover:bg-white/[0.04]"
                  )}
                >
                  <item.icon size={18} className={cn(isActive ? "text-white" : "text-neutral-400")} />
                  <span>{item.label}</span>
                </Link>
              );
            })}
          </nav>

          {/* Wallet info with Disconnect */}
          <div className="p-3 border-t border-white/[0.06]">
            {session.isLoggedIn ? (
              <div className="flex items-center justify-between p-2.5 bg-white/[0.04] rounded-xl">
                <div className="flex items-center gap-2.5 min-w-0 flex-1">
                  <div className="w-2 h-2 rounded-full bg-emerald-500 flex-shrink-0" />
                  <div className="min-w-0">
                    <div className="font-mono text-xs text-white truncate font-medium">
                      {walletShort}
                    </div>
                    <div className="font-mono text-[10px] text-neutral-400 capitalize">
                      {session.walletKind || "Connected"}
                    </div>
                  </div>
                </div>
                <button
                  type="button"
                  onClick={() => setDisconnectModalOpen(true)}
                  className="p-1.5 text-neutral-400 hover:text-red-400 hover:bg-red-500/10 rounded-lg transition-colors cursor-pointer flex-shrink-0 ml-2"
                  title="Disconnect session"
                  aria-label="Disconnect session"
                >
                  <IconLogout size={16} />
                </button>
              </div>
            ) : (
              <WalletButton className="w-full justify-center text-xs" />
            )}
          </div>
        </aside>

        {/* Mobile Sidebar & Backdrop Drawer */}
        <AnimatePresence>
          {mobileOpen && (
            <>
              {/* Backdrop */}
              <motion.div
                initial={{ opacity: 0 }}
                animate={{ opacity: 1 }}
                exit={{ opacity: 0 }}
                transition={{ duration: 0.2 }}
                onClick={() => setMobileOpen(false)}
                className="fixed inset-0 z-50 bg-black/75 backdrop-blur-sm lg:hidden"
                aria-hidden="true"
              />

              {/* Slide-out Drawer */}
              <motion.aside
                initial={{ x: "-100%" }}
                animate={{ x: 0 }}
                exit={{ x: "-100%" }}
                transition={{ type: "spring", damping: 25, stiffness: 300 }}
                className="fixed top-0 left-0 bottom-0 w-72 max-w-[85vw] bg-[#121212] border-r border-white/[0.06] z-50 flex flex-col lg:hidden"
              >
                {/* Header */}
                <div className="h-16 px-5 border-b border-white/[0.06] flex items-center justify-between">
                  <Link
                    href="/"
                    onClick={() => setMobileOpen(false)}
                    className="flex items-center gap-2.5"
                  >
                    <div className="relative w-7 h-7 flex-shrink-0">
                      <Image src="/logo.png" alt="Multipu" fill sizes="28px" className="object-contain" />
                    </div>
                    <span className="text-base font-semibold text-white tracking-tight">
                      Multipu
                    </span>
                  </Link>

                  <button
                    onClick={() => setMobileOpen(false)}
                    className="p-1.5 text-neutral-400 hover:text-white rounded-lg transition-colors"
                    aria-label="Close menu"
                  >
                    <IconX size={20} />
                  </button>
                </div>

                {/* Navigation Items */}
                <nav className="flex-1 p-3 space-y-1 overflow-y-auto">
                  {navItems.map((item) => {
                    const isActive = isItemActive(item.href);
                    return (
                      <Link
                        key={item.label}
                        href={item.href}
                        onClick={() => setMobileOpen(false)}
                        className={cn(
                          "w-full flex items-center gap-3 px-3.5 py-2.5 text-sm rounded-xl transition-colors font-medium",
                          isActive
                            ? "bg-white/[0.09] text-white"
                            : "text-neutral-400 hover:text-white hover:bg-white/[0.04]"
                        )}
                      >
                        <item.icon size={18} className={cn(isActive ? "text-white" : "text-neutral-400")} />
                        <span>{item.label}</span>
                      </Link>
                    );
                  })}

                  {/* Activity & Notifications Drawer Button */}
                  <button
                    type="button"
                    onClick={() => {
                      setMobileOpen(false);
                      setNotificationsOpen(true);
                      setHasUnread(false);
                    }}
                    className="w-full flex items-center justify-between px-3.5 py-2.5 text-sm rounded-xl transition-colors font-medium text-neutral-400 hover:text-white hover:bg-white/[0.04] cursor-pointer"
                  >
                    <div className="flex items-center gap-3">
                      <IconBell size={18} />
                      <span>Activity &amp; Tracking</span>
                    </div>
                    {hasUnread && (
                      <span className="w-2 h-2 rounded-full bg-accent" />
                    )}
                  </button>

                  {/* Launch Token Action */}
                  <div className="pt-3 mt-3 border-t border-white/[0.06]">
                    <Link
                      href="/launch"
                      onClick={() => setMobileOpen(false)}
                      className="w-full flex items-center justify-center gap-2 px-4 py-2.5 rounded-xl bg-accent text-white font-medium text-sm hover:bg-accent-hover transition-colors font-sans"
                    >
                      <IconRocket size={16} />
                      Launch Token
                    </Link>
                  </div>
                </nav>

                {/* Single Connected Account Widget at Base */}
                <div className="p-3 border-t border-white/[0.06]">
                  {session.isLoggedIn ? (
                    <div className="flex items-center justify-between p-2.5 bg-white/[0.04] rounded-xl">
                      <div className="flex items-center gap-2.5 min-w-0 flex-1">
                        <div className="w-2 h-2 rounded-full bg-emerald-500 flex-shrink-0" />
                        <div className="min-w-0">
                          <div className="font-mono text-xs text-white truncate font-medium">
                            {walletShort}
                          </div>
                          <div className="font-mono text-[10px] text-neutral-400 capitalize">
                            {session.walletKind || "Connected"}
                          </div>
                        </div>
                      </div>
                      <button
                        type="button"
                        onClick={() => {
                          setMobileOpen(false);
                          setDisconnectModalOpen(true);
                        }}
                        className="p-1.5 text-neutral-400 hover:text-red-400 hover:bg-red-500/10 rounded-lg transition-colors cursor-pointer flex-shrink-0 ml-2"
                        title="Disconnect session"
                        aria-label="Disconnect session"
                      >
                        <IconLogout size={16} />
                      </button>
                    </div>
                  ) : (
                    <WalletButton className="w-full justify-center text-xs" />
                  )}
                </div>
              </motion.aside>
            </>
          )}
        </AnimatePresence>

        {/* Main content */}
        <main className="flex-1 h-full overflow-y-auto min-w-0 flex flex-col">
          {/* Unified Header with Balances and Floating Notifications on Mobile and Desktop */}
          <DashboardHeader
            onOpenMobileMenu={() => setMobileOpen(true)}
            notificationsOpen={notificationsOpen}
            onOpenNotifications={() => {
              setNotificationsOpen((prev) => !prev);
              setHasUnread(false);
            }}
            onCloseNotifications={() => {
              setNotificationsOpen(false);
            }}
            hasUnreadNotifications={hasUnread}
          />

          <div className="flex-1 min-w-0">
            {children}
          </div>
        </main>
      </div>

      {/* Live AI Trading Agent Copilot */}
      <TradingAgentCopilot />

      {/* Custom Disconnect Confirmation Modal */}
      <DisconnectModal
        isOpen={disconnectModalOpen}
        onClose={() => setDisconnectModalOpen(false)}
        onConfirm={handleDisconnect}
        walletAddress={session.walletAddress}
        walletKind={session.walletKind}
      />
    </div>
  );
}
