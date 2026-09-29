"use client";

import { useState, useEffect } from "react";
import Link from "next/link";
import Image from "next/image";
import { IconRefresh, IconBell, IconMenu2 } from "@tabler/icons-react";
import { cn } from "@/lib/utils";
import { useWalletBalances } from "@/hooks/use-wallet-balances";
import { NotificationsPopup } from "@/components/dashboard/notifications-popup";

function formatBalance(val: number) {
  if (val === 0) return "0.00";
  if (val < 0.0001) return "<0.0001";
  if (val < 1) return val.toFixed(4);
  if (val < 1000) return val.toFixed(3);
  return val.toLocaleString("en-US", { maximumFractionDigits: 2 });
}

interface DashboardHeaderProps {
  notificationsOpen?: boolean;
  onOpenNotifications?: () => void;
  onCloseNotifications?: () => void;
  hasUnreadNotifications?: boolean;
  onOpenMobileMenu?: () => void;
}

export function DashboardHeader({
  notificationsOpen: controlledOpen,
  onOpenNotifications,
  onCloseNotifications,
  hasUnreadNotifications,
  onOpenMobileMenu,
}: DashboardHeaderProps) {
  const { balances, isLoading, refresh } = useWalletBalances();
  const [internalOpen, setInternalOpen] = useState(false);
  const [internalHasUnread, setInternalHasUnread] = useState(true);

  const isPopupOpen = controlledOpen !== undefined ? controlledOpen : internalOpen;

  useEffect(() => {
    fetch("/api/notifications")
      .then((res) => (res.ok ? res.json() : null))
      .then((data) => {
        if (!data?.notifications) {
          setInternalHasUnread(false);
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
        setInternalHasUnread(hasUnreadItems);
      })
      .catch(() => {
        setInternalHasUnread(false);
      });
  }, []);

  const hasUnread =
    hasUnreadNotifications !== undefined
      ? hasUnreadNotifications
      : internalHasUnread;

  const handleToggleNotifications = () => {
    if (isPopupOpen) {
      if (onCloseNotifications) onCloseNotifications();
      else setInternalOpen(false);
    } else {
      if (onOpenNotifications) onOpenNotifications();
      else setInternalOpen(true);
    }
  };

  const handleCloseNotifications = () => {
    if (onCloseNotifications) onCloseNotifications();
    else setInternalOpen(false);
  };

  const chains = [
    {
      key: "solana",
      label: "Solana",
      symbol: "SOL",
      data: balances.solana,
    },
    {
      key: "bsc",
      label: "BNB Chain",
      symbol: "BNB",
      data: balances.bsc,
    },
    {
      key: "robinhood",
      label: "Robinhood",
      symbol: "ETH",
      data: balances.robinhood,
    },
  ];

  return (
    <>
      <header
        className={cn(
          "sticky top-0 w-full h-16 flex-shrink-0 shrink-0 border-b border-white/[0.06] bg-[#121212]/95 backdrop-blur-md flex items-center transition-all",
          isPopupOpen ? "z-[100]" : "z-30"
        )}
      >
        <div className="flex items-center justify-between w-full px-4 sm:px-8 gap-3">
          {/* Left section: Mobile hamburger & logo + Supported Chain Balances */}
          <div className="flex items-center gap-2 sm:gap-3 min-w-0 flex-1">
            {onOpenMobileMenu && (
              <div className="flex items-center gap-2 lg:hidden flex-shrink-0">
                <button
                  onClick={onOpenMobileMenu}
                  className="p-1.5 -ml-1 text-neutral-400 hover:text-white hover:bg-white/[0.06] rounded-lg transition-colors cursor-pointer"
                  aria-label="Open navigation menu"
                >
                  <IconMenu2 size={20} />
                </button>

                <Link href="/" className="flex items-center flex-shrink-0" aria-label="Home">
                  <div className="relative w-7 h-7 flex-shrink-0">
                    <Image src="/logo.png" alt="Multipu" fill sizes="28px" className="object-contain" />
                  </div>
                </Link>
              </div>
            )}

            {/* Supported Chain Balances - Rounded Matte Card */}
            <div className="flex items-center gap-1 sm:gap-2 bg-white/[0.04] px-3 sm:px-4 py-1.5 rounded-xl overflow-x-auto scrollbar-none max-w-[calc(100vw-110px)] sm:max-w-none">
              {chains.map((chain, index) => {
                const hasBalance = chain.data.balance > 0;
                return (
                  <div
                    key={chain.key}
                    className={cn(
                      "flex items-baseline gap-1.5 sm:gap-2 px-1.5 sm:px-3 py-0.5 font-mono whitespace-nowrap transition-colors",
                      index > 0 && "border-l border-white/[0.06] pl-2 sm:pl-4",
                      hasBalance ? "text-white" : "text-neutral-400"
                    )}
                    title={`${chain.label}: ${chain.data.balance} ${chain.symbol}`}
                  >
                    <span className="text-[10px] sm:text-xs font-semibold uppercase tracking-wider text-neutral-400">
                      {chain.symbol}
                    </span>
                    <span
                      className={cn(
                        "text-xs sm:text-sm font-semibold font-mono tracking-tight",
                        hasBalance ? "text-accent" : "text-neutral-300"
                      )}
                    >
                      {formatBalance(chain.data.balance)}
                    </span>
                  </div>
                );
              })}

              {/* Refresh balances button */}
              <button
                onClick={refresh}
                disabled={isLoading}
                className="p-1 text-neutral-400 hover:text-white hover:bg-white/[0.06] rounded-lg transition-colors disabled:opacity-50 ml-1 sm:ml-2 flex-shrink-0 cursor-pointer"
                title="Refresh balances"
                aria-label="Refresh balances"
              >
                <IconRefresh
                  size={13}
                  className={cn(isLoading && "animate-spin text-accent")}
                />
              </button>
            </div>
          </div>

          {/* Activity Stream Notification Button & Floating Popup */}
          <div className="relative flex items-center gap-2 flex-shrink-0">
            <button
              onClick={handleToggleNotifications}
              data-notification-trigger="true"
              className={cn(
                "relative p-2 rounded-xl transition-all cursor-pointer",
                isPopupOpen
                  ? "bg-white/[0.08] text-white"
                  : "text-neutral-400 hover:text-white hover:bg-white/[0.06]"
              )}
              title="Activity Stream & Notifications"
              aria-label="Activity Stream & Notifications"
            >
              <IconBell size={20} />
              {hasUnread && (
                <span className="absolute top-1.5 right-1.5 w-2 h-2 rounded-full bg-accent animate-pulse" />
              )}
            </button>

            {/* Redesigned Floating Notifications Popup */}
            <NotificationsPopup
              isOpen={isPopupOpen}
              onClose={handleCloseNotifications}
              onUnreadChange={(unreadRemaining) => {
                setInternalHasUnread(unreadRemaining);
              }}
            />
          </div>
        </div>
      </header>
    </>
  );
}
