"use client";

import Link from "next/link";
import Image from "next/image";
import { IconRobot, IconWallet } from "@tabler/icons-react";
import { motion, fadeUp, stagger, scaleIn, slideInLeft } from "@/components/motion";

export function BauhausShowcase() {
  return (
    <motion.section
      id="architecture"
      initial="hidden"
      whileInView="visible"
      viewport={{ once: true, margin: "-80px" }}
      variants={stagger}
      className="py-12 sm:py-16 md:py-24 px-4 sm:px-6 md:px-12 max-w-[1360px] mx-auto scroll-mt-24"
    >
      {/* Outer rounded dark canvas */}
      <motion.div variants={fadeUp} className="relative w-full rounded-3xl sm:rounded-[40px] bg-neutral-950 p-6 sm:p-10 md:p-12 lg:p-16 overflow-hidden">
        {/* Perfectly Balanced Dot Matrix Background Pattern */}
        <div className="absolute inset-0 bg-[radial-gradient(rgba(255,255,255,0.18)_1.1px,transparent_1.1px)] [background-size:22px_22px] pointer-events-none opacity-45 [mask-image:radial-gradient(ellipse_at_center,black_80%,transparent_100%)] z-0" />

        <div className="relative z-10 grid grid-cols-1 lg:grid-cols-12 gap-8 sm:gap-12 lg:gap-16 items-center">
          {/* Left Column: Editorial & Bauhaus Geometric Composition */}
          <motion.div variants={slideInLeft} className="lg:col-span-5 flex flex-col justify-between h-full min-h-0 lg:min-h-[580px]">
            <div>
              <div className="flex items-center gap-4 text-xs font-mono text-neutral-400 mb-6 sm:mb-8">
                <span>Architecture</span>
                <span>●</span>
                <span>Multi-Chain</span>
              </div>

              <h2 className="text-3xl sm:text-5xl lg:text-6xl font-normal tracking-tight text-white leading-[1.1] mb-4 sm:mb-6">
                It&apos;s never too late to deploy something new
              </h2>

              <p className="text-sm text-neutral-400 leading-relaxed mb-6 sm:mb-8 max-w-md">
                Three paths lead to liquidity: the path of reflection is the noblest, the path of imitation is the easiest, and the path of innovation is the most rewarding.
              </p>

              <Link
                href="/launch"
                className="inline-flex items-center gap-2 px-6 py-2.5 rounded-full bg-white/10 hover:bg-white/20 text-white text-xs font-mono transition-colors cursor-pointer"
              >
                <span>Start Deploying</span>
                <span>→</span>
              </Link>
            </div>

            {/* Launchpads illustrations */}
            <div className="w-full h-44 sm:h-52 mt-8 rounded-2xl bg-neutral-900 flex items-center justify-center gap-3 sm:gap-5 px-4">
              <div className="w-11 h-11 sm:w-12 sm:h-12 relative flex items-center justify-center">
                <Image src="/meteora.png" alt="Meteora" width={48} height={48} className="w-full h-full object-contain" />
              </div>
              <div className="w-11 h-11 sm:w-12 sm:h-12 relative flex items-center justify-center">
                <Image src="/pumpfun.png" alt="Pump.fun" width={48} height={48} className="w-full h-full object-contain" />
              </div>
              <div className="w-11 h-11 sm:w-12 sm:h-12 relative flex items-center justify-center">
                <Image src="/bags.png" alt="Bags" width={48} height={48} className="w-full h-full object-contain" />
              </div>
              <div className="w-11 h-11 sm:w-12 sm:h-12 relative flex items-center justify-center">
                <Image src="/four-meme.png" alt="Four.meme" width={48} height={48} className="w-full h-full object-contain" />
              </div>
              <div className="w-11 h-11 sm:w-12 sm:h-12 relative flex items-center justify-center">
                <Image src="/pons.png" alt="Pons" width={48} height={48} className="w-full h-full object-contain" />
              </div>
            </div>
          </motion.div>

          {/* Right Column: 2x2 Grid of 4 rounded colored feature tiles */}
          <motion.div variants={stagger} className="lg:col-span-7 grid grid-cols-1 sm:grid-cols-2 gap-4">
            {/* Tile 1: Explore (Electric Blue) */}
            <motion.div variants={scaleIn}>
              <Link
                href="/dashboard/explore"
                className="h-72 sm:h-80 rounded-3xl bg-[#2b4fff] p-6 sm:p-8 flex flex-col justify-between group transition-transform duration-300 hover:scale-[1.02] cursor-pointer"
              >
                <div className="flex justify-between items-start">
                  {/* Explore Launchpad / Meme illustration */}
                  <div className="w-12 h-12 relative">
                    <Image
                      src="/meteora.png"
                      alt="Meteora"
                      width={48}
                      height={48}
                      className="w-full h-full object-contain"
                    />
                  </div>
                  <span className="text-xl font-mono text-white group-hover:translate-x-1 group-hover:-translate-y-1 transition-transform">
                    ↗
                  </span>
                </div>

                <div>
                  <h3 className="text-2xl font-bold text-white mb-2">Explore</h3>
                  <p className="text-xs text-white/80 leading-relaxed">
                    Discover trending bonding curves and new tokens across Solana, BNB, and Robinhood Chain.
                  </p>
                </div>
              </Link>
            </motion.div>

            {/* Tile 2: Launches (Vibrant Warm Orange) */}
            <motion.div variants={scaleIn}>
              <Link
                href="/dashboard/launches"
                className="h-72 sm:h-80 rounded-3xl bg-[#ff5520] p-8 flex flex-col justify-between group transition-transform duration-300 hover:scale-[1.02] cursor-pointer"
              >
                <div className="flex justify-between items-start">
                  {/* Launches Meme illustration */}
                  <div className="w-12 h-12 relative">
                    <Image
                      src="/pumpfun.png"
                      alt="Pump.fun"
                      width={48}
                      height={48}
                      className="w-full h-full object-contain"
                    />
                  </div>
                  <span className="text-xl font-mono text-white group-hover:translate-x-1 group-hover:-translate-y-1 transition-transform">
                    ↗
                  </span>
                </div>

                <div>
                  <h3 className="text-2xl font-bold text-white mb-2">Launches</h3>
                  <p className="text-xs text-white/80 leading-relaxed">
                    Simultaneous push to Meteora, Pump.fun, Bags, Four.meme, and Pons.
                  </p>
                </div>
              </Link>
            </motion.div>

            {/* Tile 3: Agents (Soft Ice / Lavender Tint) */}
            <motion.div variants={scaleIn}>
              <Link
                href="/dashboard"
                className="h-72 sm:h-80 rounded-3xl bg-[#ede9fe] p-8 flex flex-col justify-between group transition-transform duration-300 hover:scale-[1.02] cursor-pointer"
              >
                <div className="flex justify-between items-start">
                  {/* Existing Agent illustration */}
                  <div className="w-12 h-12 flex items-center justify-center text-neutral-900">
                    <IconRobot size={32} stroke={1.75} />
                  </div>
                  <span className="text-xl font-mono text-neutral-900 group-hover:translate-x-1 group-hover:-translate-y-1 transition-transform">
                    ↗
                  </span>
                </div>

                <div>
                  <h3 className="text-2xl font-bold text-neutral-900 mb-2">Agents</h3>
                  <p className="text-xs text-neutral-700 leading-relaxed">
                    OlaXBT signals and automated KeeperHub arbitrage execution right in your terminal.
                  </p>
                </div>
              </Link>
            </motion.div>

            {/* Tile 4: Earnings (Periwinkle Violet) */}
            <motion.div variants={scaleIn}>
              <Link
                href="/dashboard/earnings"
                className="h-72 sm:h-80 rounded-3xl bg-[#7c65c1] p-8 flex flex-col justify-between group transition-transform duration-300 hover:scale-[1.02] cursor-pointer"
              >
                <div className="flex justify-between items-start">
                  {/* Existing Wallet illustration */}
                  <div className="w-12 h-12 flex items-center justify-center text-white">
                    <IconWallet size={32} stroke={1.75} />
                  </div>
                  <span className="text-xl font-mono text-white group-hover:translate-x-1 group-hover:-translate-y-1 transition-transform">
                    ↗
                  </span>
                </div>

                <div>
                  <h3 className="text-2xl font-bold text-white mb-2">Earnings</h3>
                  <p className="text-xs text-white/80 leading-relaxed">
                    Creator royalties and protocol fees collected across every launchpad in real time.
                  </p>
                </div>
              </Link>
            </motion.div>
          </motion.div>
        </div>
      </motion.div>
    </motion.section>
  );
}
