"use client";

import { useEffect, useRef, useState, useCallback } from "react";
import Link from "next/link";
import Image from "next/image";
import { motion } from "@/components/motion";
import { useAuth } from "@/hooks/use-auth";
import { SignInModal } from "@/components/signin-modal";
import { useConfirm } from "@/components/ui/custom-confirm";
import { toast } from "sonner";
import { IconLogout } from "@tabler/icons-react";

interface Particle {
  baseX: number;
  baseY: number;
  x: number;
  y: number;
  vx: number;
  vy: number;
  baseRadius: number;
  isColored: boolean;
  color: string;
  glowColor?: string;
  baseAlpha: number;
}

export function HeroStatus() {
  const containerRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const mouseRef = useRef({
    x: -9999,
    y: -9999,
    prevX: -9999,
    prevY: -9999,
    vx: 0,
    vy: 0,
    isHovering: false,
  });

  const confirm = useConfirm();
  const { session, signOut } = useAuth();
  const [showSignInModal, setShowSignInModal] = useState(false);
  const [accountMenuOpen, setAccountMenuOpen] = useState(false);

  const shortAddress = session.isLoggedIn
    ? `${session.walletAddress.slice(0, 4)}...${session.walletAddress.slice(-4)}`
    : null;

  const handleConfirmDisconnect = async () => {
    setAccountMenuOpen(false);
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

  // Interactive background grain canvas with cursor physics & concentric wave distortion
  useEffect(() => {
    const canvas = canvasRef.current;
    const container = containerRef.current;
    if (!canvas || !container) return;

    const ctx = canvas.getContext("2d", { alpha: true });
    if (!ctx) return;

    let animationFrameId: number;
    let particles: Particle[] = [];
    let width = 0;
    let height = 0;
    let isVisible = true;
    let time = 0;

    const resize = () => {
      const rect = container.getBoundingClientRect();
      width = rect.width;
      height = rect.height;

      const dpr = Math.min(window.devicePixelRatio || 1, 2);
      canvas.width = width * dpr;
      canvas.height = height * dpr;
      ctx.scale(dpr, dpr);

      // Grid spacing
      const spacing = width < 640 ? 20 : 24;
      const cols = Math.floor(width / spacing);
      const rows = Math.floor(height / spacing);
      const offsetX = (width - cols * spacing) / 2;
      const offsetY = (height - rows * spacing) / 2;

      particles = [];

      // Upper-left vibrant colored constellation hotspot (matching reference screenshot)
      const hotspotX = width * 0.2;
      const hotspotY = height * 0.22;
      const hotspotRadius = Math.min(width, height) * 0.38;

      const colorPalette = [
        { r: 244, g: 63, b: 94 },   // rose-500
        { r: 236, g: 72, b: 153 },  // pink-500
        { r: 217, g: 70, b: 239 },  // fuchsia-500
        { r: 168, g: 85, b: 247 },  // purple-500
        { r: 139, g: 92, b: 246 },  // violet-500
        { r: 99, g: 102, b: 241 },  // indigo-500
      ];

      for (let r = 0; r <= rows; r++) {
        for (let c = 0; c <= cols; c++) {
          const baseX = offsetX + c * spacing;
          const baseY = offsetY + r * spacing;

          const distToHotspot = Math.hypot(baseX - hotspotX, baseY - hotspotY);
          const inHotspot = distToHotspot < hotspotRadius && baseX < width * 0.48 && baseY < height * 0.52;

          let isColored = false;
          let color = "rgba(255, 255, 255, 0.2)";
          let glowColor: string | undefined;
          let baseAlpha = 0.22;
          let baseRadius = 1.35;

          if (inHotspot) {
            isColored = true;
            const progress = distToHotspot / hotspotRadius;
            // Pick color according to distance and position
            const colorIdx = Math.min(
              colorPalette.length - 1,
              Math.floor((progress * 0.7 + (baseX / (width * 0.5)) * 0.3) * colorPalette.length)
            );
            const rgb = colorPalette[colorIdx];
            const alpha = 0.55 + Math.random() * 0.4 * (1 - progress);
            color = `rgba(${rgb.r}, ${rgb.g}, ${rgb.b}, ${alpha.toFixed(2)})`;
            glowColor = `rgba(${rgb.r}, ${rgb.g}, ${rgb.b}, 0.6)`;
            baseAlpha = alpha;
            baseRadius = 1.7;
          } else {
            // Subtle concentric ring pattern
            const distFromCenter = Math.hypot(baseX - width * 0.5, baseY - height * 0.5);
            const ringValue = Math.sin(distFromCenter * 0.04);
            baseAlpha = ringValue > 0.3 ? 0.32 : 0.16;
            baseRadius = ringValue > 0.3 ? 1.5 : 1.2;
            color = `rgba(255, 255, 255, ${baseAlpha})`;
          }

          particles.push({
            baseX,
            baseY,
            x: baseX,
            y: baseY,
            vx: 0,
            vy: 0,
            baseRadius,
            isColored,
            color,
            glowColor,
            baseAlpha,
          });
        }
      }
    };

    resize();
    const resizeObserver = new ResizeObserver(resize);
    resizeObserver.observe(container);

    // Visibility observer to pause loop when not on screen
    const io = new IntersectionObserver((entries) => {
      isVisible = entries[0].isIntersecting;
    });
    io.observe(container);

    // Mouse tracking over container
    const handleMouseMove = (e: MouseEvent) => {
      const rect = container.getBoundingClientRect();
      const currentX = e.clientX - rect.left;
      const currentY = e.clientY - rect.top;

      const m = mouseRef.current;
      if (m.prevX === -9999) {
        m.prevX = currentX;
        m.prevY = currentY;
      } else {
        m.vx = (currentX - m.prevX) * 0.5;
        m.vy = (currentY - m.prevY) * 0.5;
        m.prevX = currentX;
        m.prevY = currentY;
      }
      m.x = currentX;
      m.y = currentY;
      m.isHovering = true;
    };

    const handleMouseEnter = () => {
      mouseRef.current.isHovering = true;
    };

    const handleMouseLeave = () => {
      const m = mouseRef.current;
      m.isHovering = false;
      m.x = -9999;
      m.y = -9999;
      m.vx = 0;
      m.vy = 0;
    };

    const handleTouchMove = (e: TouchEvent) => {
      if (e.touches.length > 0) {
        const rect = container.getBoundingClientRect();
        const touch = e.touches[0];
        const currentX = touch.clientX - rect.left;
        const currentY = touch.clientY - rect.top;

        const m = mouseRef.current;
        m.vx = (currentX - (m.prevX === -9999 ? currentX : m.prevX)) * 0.4;
        m.vy = (currentY - (m.prevY === -9999 ? currentY : m.prevY)) * 0.4;
        m.prevX = currentX;
        m.prevY = currentY;
        m.x = currentX;
        m.y = currentY;
        m.isHovering = true;
      }
    };

    container.addEventListener("mousemove", handleMouseMove, { passive: true });
    container.addEventListener("mouseenter", handleMouseEnter);
    container.addEventListener("mouseleave", handleMouseLeave);
    container.addEventListener("touchmove", handleTouchMove, { passive: true });
    container.addEventListener("touchend", handleMouseLeave);

    // Animation Render Loop
    const render = () => {
      if (!isVisible) {
        animationFrameId = requestAnimationFrame(render);
        return;
      }

      time += 0.015;
      ctx.clearRect(0, 0, width, height);

      const m = mouseRef.current;
      const mouseRadius = 220; // Radius of cursor influence
      const spring = 0.08;
      const friction = 0.84;

      // Decay mouse velocity
      m.vx *= 0.9;
      m.vy *= 0.9;

      for (let i = 0; i < particles.length; i++) {
        const p = particles[i];

        // Distance to cursor
        const dx = p.x - m.x;
        const dy = p.y - m.y;
        const dist = Math.hypot(dx, dy);

        // Repel & fluid swirl when mouse is near
        if (m.isHovering && dist < mouseRadius && dist > 0) {
          const force = (1 - dist / mouseRadius) * 8.5;
          const angle = Math.atan2(dy, dx);

          // Push away from cursor
          p.vx += Math.cos(angle) * force * 0.8;
          p.vy += Math.sin(angle) * force * 0.8;

          // Swirl inertia from cursor movement
          p.vx += m.vx * (1 - dist / mouseRadius) * 0.45;
          p.vy += m.vy * (1 - dist / mouseRadius) * 0.45;
        }

        // Return force to original grid base position
        const returnForceX = (p.baseX - p.x) * spring;
        const returnForceY = (p.baseY - p.y) * spring;

        p.vx = (p.vx + returnForceX) * friction;
        p.vy = (p.vy + returnForceY) * friction;

        p.x += p.vx;
        p.y += p.vy;

        // Concentric wave ripple & illumination based on proximity to cursor
        let radius = p.baseRadius;
        let alpha = p.baseAlpha;

        if (m.isHovering && dist < mouseRadius) {
          const proximity = 1 - dist / mouseRadius;
          radius = p.baseRadius + proximity * 1.5;
          alpha = Math.min(1, p.baseAlpha + proximity * 0.5);
        } else {
          // Ambient organic micro-movement & concentric wave
          const wave = Math.sin(dist * 0.05 - time * 2);
          radius = p.baseRadius + wave * 0.15;
        }

        // Draw dot
        ctx.beginPath();
        ctx.arc(p.x, p.y, Math.max(0.6, radius), 0, Math.PI * 2);

        if (p.isColored) {
          if (p.glowColor && radius > 2.0) {
            ctx.shadowBlur = 8;
            ctx.shadowColor = p.glowColor;
          } else {
            ctx.shadowBlur = 0;
          }
          ctx.fillStyle = p.color;
        } else {
          ctx.shadowBlur = 0;
          ctx.fillStyle = `rgba(255, 255, 255, ${alpha.toFixed(2)})`;
        }

        ctx.fill();
      }

      animationFrameId = requestAnimationFrame(render);
    };

    animationFrameId = requestAnimationFrame(render);

    return () => {
      cancelAnimationFrame(animationFrameId);
      resizeObserver.disconnect();
      io.disconnect();
      container.removeEventListener("mousemove", handleMouseMove);
      container.removeEventListener("mouseenter", handleMouseEnter);
      container.removeEventListener("mouseleave", handleMouseLeave);
      container.removeEventListener("touchmove", handleTouchMove);
      container.removeEventListener("touchend", handleMouseLeave);
    };
  }, []);

  return (
    <section id="hero" className="relative w-full pt-2 sm:pt-4 pb-12 sm:pb-16 px-3 sm:px-6 md:px-10 overflow-hidden scroll-mt-24">
      {/* Hero Framed Stage Container */}
      <div
        ref={containerRef}
        className="relative z-10 max-w-[1360px] mx-auto rounded-[24px] sm:rounded-[32px] md:rounded-[40px] bg-[#030303] border border-white/[0.12] shadow-[0_25px_100px_-20px_rgba(0,0,0,0.95),inset_0_1px_0_rgba(255,255,255,0.12)] overflow-hidden min-h-[560px] md:min-h-[640px] lg:min-h-[700px] flex flex-col justify-between"
      >
        {/* Interactive Physics Grain Canvas */}
        <canvas
          ref={canvasRef}
          className="absolute inset-0 w-full h-full pointer-events-none z-0"
        />

        {/* Subtle Vignette & Radial Glow */}
        <div className="absolute inset-0 pointer-events-none z-[1] bg-[radial-gradient(ellipse_at_center,transparent_40%,rgba(3,3,3,0.85)_100%)]" />

        {/* 1. Top Integrated Navigation Bar (Mercury style) */}
        <header className="relative z-20 w-full px-6 sm:px-8 md:px-12 pt-6 sm:pt-8 flex items-center justify-between">
          {/* Logo */}
          <Link href="/" className="flex items-center gap-2.5 group">
            <div className="relative w-7 h-7 flex-shrink-0">
              <Image src="/logo.png" alt="Multipu" fill sizes="28px" className="object-contain" />
            </div>
            <span className="text-base sm:text-lg font-bold tracking-tight text-white group-hover:text-neutral-200 transition-colors">
              multipu
            </span>
          </Link>

          {/* Nav Links */}
          <nav className="hidden md:flex items-center gap-8 lg:gap-10 text-xs sm:text-sm font-medium text-neutral-400">
            <Link href="#hero" className="hover:text-white transition-colors">
              Overview
            </Link>
            <Link href="#architecture" className="hover:text-white transition-colors">
              Architecture
            </Link>
            <Link href="#launchpads" className="hover:text-white transition-colors">
              Launchpads
            </Link>
            <Link href="#terminal" className="hover:text-white transition-colors">
              Terminal
            </Link>
          </nav>

          {/* Right Header Actions */}
          <div className="flex items-center gap-3">
            <Link
              href="/dashboard"
              className="hidden sm:inline-block text-xs sm:text-sm font-medium text-neutral-400 hover:text-white transition-colors px-2 py-1"
            >
              Dashboard
            </Link>

            {session.isLoggedIn ? (
              <div className="relative">
                <button
                  onClick={() => setAccountMenuOpen(!accountMenuOpen)}
                  className="inline-flex items-center gap-2 px-3.5 py-1.5 text-xs font-mono rounded-full bg-neutral-900 hover:bg-neutral-800 text-neutral-200 border border-white/10 transition-colors cursor-pointer select-none"
                  aria-label="Account details"
                >
                  <span className="w-1.5 h-1.5 rounded-full bg-emerald-500" />
                  <span>{shortAddress}</span>
                </button>

                {accountMenuOpen && (
                  <>
                    <div
                      className="fixed inset-0 z-40"
                      onClick={() => setAccountMenuOpen(false)}
                    />
                    <div className="absolute right-0 top-full mt-2 w-52 rounded-2xl bg-neutral-900 border border-white/10 text-white p-2.5 z-50 shadow-2xl">
                      <div className="px-2 py-1.5">
                        <div className="text-[10px] font-mono text-neutral-500 uppercase tracking-wider">
                          Connected ({session.walletKind.toUpperCase()})
                        </div>
                        <div className="text-xs font-mono text-white truncate mt-0.5">
                          {session.walletAddress}
                        </div>
                      </div>
                      <div className="pt-2 flex flex-col gap-1 border-t border-white/5 mt-1">
                        <Link
                          href="/dashboard"
                          onClick={() => setAccountMenuOpen(false)}
                          className="w-full px-2 py-1.5 text-xs font-mono text-neutral-300 hover:text-white hover:bg-neutral-800 rounded-lg transition-colors text-left"
                        >
                          Open Dashboard
                        </Link>
                        <button
                          onClick={handleConfirmDisconnect}
                          className="w-full px-2 py-1.5 text-xs font-mono text-red-400 hover:text-red-300 hover:bg-red-500/10 rounded-lg transition-colors text-left cursor-pointer"
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
                className="hidden sm:inline-block text-xs sm:text-sm font-medium text-neutral-400 hover:text-white transition-colors px-2 py-1 cursor-pointer"
              >
                Log In
              </button>
            )}

            <Link
              href="/launch"
              className="px-4 sm:px-5 py-2 rounded-full bg-white hover:bg-neutral-200 text-black text-xs sm:text-sm font-semibold tracking-tight transition-all duration-200 shadow-md hover:scale-105 active:scale-95"
            >
              Launch App
            </Link>
          </div>
        </header>

        {/* 2. Main Hero Typography & Call-To-Action */}
        <div className="relative z-20 text-center px-4 sm:px-8 pt-12 sm:pt-16 pb-16 sm:pb-24 my-auto">
          {/* Centered Large Bold Headline */}
          <motion.h1
            initial={{ opacity: 0, y: 20 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6, ease: [0.16, 1, 0.3, 1] }}
            className="text-4xl sm:text-6xl md:text-7xl lg:text-[80px] font-bold tracking-tight text-white leading-[1.08] sm:leading-[1.03] max-w-4xl mx-auto select-none"
          >
            Launch on Your Terms
            <br />
            <span className="text-neutral-100">Scale Multi-Chain</span>
          </motion.h1>

          {/* Subtitle / Value Proposition */}
          <motion.p
            initial={{ opacity: 0, y: 15 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6, delay: 0.1, ease: [0.16, 1, 0.3, 1] }}
            className="mt-6 sm:mt-7 text-sm sm:text-base md:text-lg text-neutral-400 max-w-2xl mx-auto leading-relaxed font-normal"
          >
            Universal launchpad and liquidity routing protocol. Multipu deploys simultaneous bonding curves across Solana, BNB Chain, and Robinhood with autonomous execution.
          </motion.p>

          {/* Dual Action Buttons */}
          <motion.div
            initial={{ opacity: 0, y: 15 }}
            animate={{ opacity: 1, y: 0 }}
            transition={{ duration: 0.6, delay: 0.2, ease: [0.16, 1, 0.3, 1] }}
            className="mt-8 sm:mt-10 flex flex-wrap items-center justify-center gap-3 sm:gap-4"
          >
            <Link
              href="/launch"
              className="px-7 py-3 rounded-full bg-white hover:bg-neutral-200 text-black text-sm font-semibold tracking-tight transition-all duration-200 flex items-center justify-center gap-2 group shadow-xl hover:scale-105 active:scale-95 cursor-pointer"
            >
              <span>Launch Token</span>
              <span className="transition-transform group-hover:translate-x-0.5 text-base">→</span>
            </Link>

            <Link
              href="/dashboard/explore"
              className="px-6 py-3 rounded-full bg-neutral-900/80 hover:bg-neutral-800 text-neutral-300 hover:text-white border border-white/10 text-sm font-semibold tracking-tight transition-all duration-200 flex items-center justify-center gap-1.5 hover:scale-105 active:scale-95 cursor-pointer"
            >
              <span>Explore Memes</span>
              <span className="text-xs text-neutral-400 font-mono">↗</span>
            </Link>
          </motion.div>
        </div>
      </div>

      {/* Global Sign In Modal */}
      <SignInModal
        isOpen={showSignInModal}
        onClose={() => setShowSignInModal(false)}
      />
    </section>
  );
}
