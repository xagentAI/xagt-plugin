"use client";

import Link from "next/link";
import Image from "next/image";
import { useState, useEffect } from "react";
import { cn } from "@/lib/utils";
import { useAuth } from "@/hooks/use-auth";
import { SignInModal } from "@/components/signin-modal";
import { useConfirm } from "@/components/ui/custom-confirm";
import { toast } from "sonner";
import { IconLogout } from "@tabler/icons-react";

const navLinks = [
  { href: "#hero", label: "Overview" },
  { href: "#architecture", label: "Architecture" },
  { href: "#launchpads", label: "Launchpads" },
  { href: "#terminal", label: "Terminal" },
];

export function MinimalNav() {
  const confirm = useConfirm();
  const { session, signOut } = useAuth();
  const [scrolled, setScrolled] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);
  const [showSignInModal, setShowSignInModal] = useState(false);
  const [accountMenuOpen, setAccountMenuOpen] = useState(false);

  useEffect(() => {
    const onScroll = () => setScrolled(window.scrollY > 20);
    window.addEventListener("scroll", onScroll, { passive: true });
    return () => window.removeEventListener("scroll", onScroll);
  }, []);

  const shortAddress = session.isLoggedIn
    ? `${session.walletAddress.slice(0, 4)}...${session.walletAddress.slice(-4)}`
    : null;

  const handleConfirmDisconnect = async () => {
    setAccountMenuOpen(false);
    setMobileOpen(false);
    const confirmed = await confirm({
      title: "Disconnect Wallet",
      message: "Are you sure you want to end your active session? You will need to sign in again to access the dashboard or launch tokens.",
      variant: "danger",
      confirmText: "Disconnect",
      cancelText: "Stay Connected",
      icon: <IconLogout size={22} className="text-rose-400" />,
      details: session.isLoggedIn ? (
        <div className="flex items-center justify-between font-mono text-xs">
          <span className="text-neutral-400 capitalize">{session.walletKind}</span>
          <span className="text-white">{session.walletAddress.slice(0, 6)}...{session.walletAddress.slice(-4)}</span>
        </div>
      ) : undefined,
    });
    if (!confirmed) return;
    try {
      await signOut();
      toast.success("Wallet session ended");
    } catch {
      toast.error("Failed to disconnect");
    }
  };

  return (
    <>
      <nav
        className={cn(
          "fixed top-0 left-0 right-0 z-50 transition-all duration-300 ease-out",
          scrolled
            ? "translate-y-0 opacity-100 bg-black/90 backdrop-blur-xl border-b border-white/[0.08]"
            : "-translate-y-full opacity-0 pointer-events-none"
        )}
      >
        <div className="mx-auto max-w-[1360px] px-6 md:px-12">
          <div className="flex h-20 items-center justify-between">
            {/* Logo */}
            <Link href="/" className="flex items-center gap-2.5 text-white group">
              <div className="relative w-7 h-7 flex-shrink-0">
                <Image src="/logo.png" alt="Multipu" fill sizes="28px" className="object-contain" />
              </div>
              <span className="text-lg font-bold tracking-tight">multipu</span>
            </Link>

            {/* Desktop Nav Links */}
            <div className="hidden md:flex items-center gap-10">
              {navLinks.map((link) => (
                <Link
                  key={link.label}
                  href={link.href}
                  className="text-sm font-medium text-neutral-400 hover:text-white transition-colors"
                >
                  {link.label}
                </Link>
              ))}
            </div>

            {/* Desktop Actions: Sign In / Authenticated Account + Launch App */}
            <div className="hidden md:flex items-center gap-3">
              <Link
                href="/dashboard"
                className="text-sm font-medium text-neutral-400 hover:text-white transition-colors px-2 py-2"
              >
                Dashboard
              </Link>

              {/* Authenticated Account Display OR Sign In Button */}
              {session.isLoggedIn ? (
                <div className="relative">
                  <button
                    onClick={() => setAccountMenuOpen(!accountMenuOpen)}
                    className="inline-flex items-center gap-2 px-4 py-2 text-xs font-mono rounded-full bg-neutral-900 hover:bg-neutral-800 text-neutral-200 transition-colors cursor-pointer select-none"
                    aria-label="Account details"
                  >
                    <span className="w-2 h-2 rounded-full bg-emerald-500" />
                    <span>{shortAddress}</span>
                    <span className="text-[10px] text-neutral-500 font-mono">⌵</span>
                  </button>

                  {accountMenuOpen && (
                    <>
                      <div
                        className="fixed inset-0 z-40"
                        onClick={() => setAccountMenuOpen(false)}
                      />
                      <div className="absolute right-0 top-full mt-2 w-56 rounded-2xl bg-neutral-900 text-white p-3 z-50 overflow-hidden">
                        <div className="px-3 py-2">
                          <div className="text-[10px] font-mono text-neutral-500 uppercase tracking-wider">
                            Connected ({session.walletKind.toUpperCase()})
                          </div>
                          <div className="text-xs font-mono text-white truncate mt-0.5">
                            {session.walletAddress}
                          </div>
                        </div>
                        <div className="pt-2 flex flex-col gap-1">
                          <Link
                            href="/dashboard"
                            onClick={() => setAccountMenuOpen(false)}
                            className="w-full px-3 py-2 text-xs font-mono text-neutral-300 hover:text-white hover:bg-neutral-800 rounded-xl transition-colors text-left"
                          >
                            Open Dashboard
                          </Link>
                          <button
                            onClick={handleConfirmDisconnect}
                            className="w-full px-3 py-2 text-xs font-mono text-red-400 hover:text-red-300 hover:bg-red-500/10 rounded-xl transition-colors text-left cursor-pointer"
                          >
                            Disconnect
                          </button>
                        </div>
                      </div>
                    </>
                  )}
                </div>
              ) : (
                <button
                  onClick={() => setShowSignInModal(true)}
                  className="px-5 py-2 text-sm font-semibold tracking-tight rounded-full bg-accent hover:bg-accent-hover text-white transition-colors cursor-pointer select-none font-sans"
                >
                  Sign In
                </button>
              )}

              <Link
                href="/launch"
                className="px-5 py-2 text-sm font-semibold tracking-tight rounded-full bg-white text-black hover:bg-neutral-200 transition-colors cursor-pointer select-none font-sans"
              >
                Launch App
              </Link>
            </div>

            {/* Mobile menu trigger */}
            <button
              onClick={() => setMobileOpen(!mobileOpen)}
              className="md:hidden p-2 text-neutral-400 hover:text-white cursor-pointer"
              aria-label="Toggle navigation menu"
            >
              {mobileOpen ? (
                <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <line x1="18" y1="6" x2="6" y2="18" />
                  <line x1="6" y1="6" x2="18" y2="18" />
                </svg>
              ) : (
                <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
                  <line x1="4" y1="7" x2="20" y2="7" />
                  <line x1="4" y1="17" x2="20" y2="17" />
                </svg>
              )}
            </button>
          </div>
        </div>

        {/* Mobile Drawer */}
        {mobileOpen && (
          <div className="md:hidden bg-black/95 px-6 py-6 flex flex-col gap-4">
            {navLinks.map((link) => (
              <Link
                key={link.label}
                href={link.href}
                onClick={() => setMobileOpen(false)}
                className="text-base font-medium text-neutral-300 hover:text-white py-2 font-sans"
              >
                {link.label}
              </Link>
            ))}
            <div className="pt-4 flex flex-col gap-3">
              {session.isLoggedIn ? (
                <div className="flex items-center justify-between p-3 rounded-2xl bg-neutral-900">
                  <div className="flex items-center gap-2">
                    <span className="w-2 h-2 rounded-full bg-emerald-500" />
                    <span className="font-mono text-xs text-white">{shortAddress}</span>
                  </div>
                  <button
                    onClick={handleConfirmDisconnect}
                    className="text-xs font-mono text-red-400 hover:text-red-300 cursor-pointer"
                  >
                    Disconnect
                  </button>
                </div>
              ) : (
                <button
                  onClick={() => {
                    setMobileOpen(false);
                    setShowSignInModal(true);
                  }}
                  className="w-full py-2.5 text-sm font-semibold tracking-tight text-white bg-accent rounded-full text-center cursor-pointer font-sans"
                >
                  Sign In
                </button>
              )}
              <Link
                href="/dashboard"
                onClick={() => setMobileOpen(false)}
                className="text-center py-2.5 text-sm font-medium tracking-tight text-neutral-300 hover:text-white bg-neutral-900 rounded-full font-sans"
              >
                Dashboard
              </Link>
              <Link
                href="/launch"
                onClick={() => setMobileOpen(false)}
                className="text-center py-2.5 text-sm font-semibold tracking-tight text-black bg-white rounded-full font-sans"
              >
                Launch App
              </Link>
            </div>
          </div>
        )}
      </nav>

      {/* Global Sign In Modal Trigger */}
      <SignInModal
        isOpen={showSignInModal}
        onClose={() => setShowSignInModal(false)}
      />
    </>
  );
}
