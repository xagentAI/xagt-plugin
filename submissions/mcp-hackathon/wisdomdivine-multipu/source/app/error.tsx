"use client";

import { useEffect } from "react";
import Link from "next/link";
import Image from "next/image";

export default function Error({
  error,
  reset,
}: {
  error: Error & { digest?: string };
  reset: () => void;
}) {
  useEffect(() => {
    console.error("Application runtime error:", error);
  }, [error]);

  return (
    <div className="min-h-screen flex flex-col justify-between bg-black text-white px-6 sm:px-12 py-8 sm:py-12 selection:bg-purple-600 selection:text-white font-[family-name:var(--font-geist-sans)]">
      {/* Top Header */}
      <header className="w-full max-w-[1280px] mx-auto flex items-center justify-between">
        <Link href="/" className="flex items-center gap-2.5 group">
          <div className="relative w-7 h-7 flex-shrink-0">
            <Image src="/logo.png" alt="Multipu" fill sizes="28px" className="object-contain" />
          </div>
          <span className="text-base sm:text-lg font-bold tracking-tight text-white group-hover:text-neutral-200 transition-colors">
            multipu
          </span>
        </Link>
        <span className="font-mono text-xs text-neutral-500 uppercase tracking-wider">
          500 Error
        </span>
      </header>

      {/* Center Error Content */}
      <main className="w-full max-w-2xl mx-auto py-20 text-center flex flex-col items-center">
        <div className="text-xs font-mono uppercase tracking-widest text-neutral-500 mb-6">
          02 / Runtime Exception
        </div>

        <h1 className="text-4xl sm:text-6xl md:text-7xl font-bold tracking-tight text-white leading-[1.05] select-none">
          Something went wrong.
        </h1>

        <p className="text-sm sm:text-base text-neutral-400 font-normal max-w-md mx-auto mt-5 mb-8 leading-relaxed">
          An unexpected runtime fault occurred while rendering this view. You can retry the operation or return to the main terminal.
        </p>

        {error.digest && (
          <div className="mb-8 px-4 py-2 rounded-xl bg-neutral-900 font-mono text-xs text-neutral-400">
            Digest: {error.digest}
          </div>
        )}

        {/* Action Buttons */}
        <div className="flex flex-wrap items-center justify-center gap-3">
          <button
            onClick={() => reset()}
            className="px-6 py-2.5 rounded-full bg-white text-black hover:bg-neutral-200 font-semibold text-xs tracking-tight transition-colors cursor-pointer"
          >
            Retry Execution →
          </button>
          <Link
            href="/"
            className="px-6 py-2.5 rounded-full bg-neutral-900 text-neutral-300 hover:text-white hover:bg-neutral-800 font-medium text-xs tracking-tight transition-colors"
          >
            Return Home
          </Link>
          <Link
            href="/dashboard"
            className="px-6 py-2.5 rounded-full bg-neutral-900 text-neutral-300 hover:text-white hover:bg-neutral-800 font-medium text-xs tracking-tight transition-colors"
          >
            Dashboard
          </Link>
        </div>
      </main>

      {/* Bottom Footer Telemetry */}
      <footer className="w-full max-w-[1280px] mx-auto flex flex-col sm:flex-row items-center justify-between gap-4 font-mono text-xs text-neutral-500">
        <div>
          Multipu Protocol
        </div>
        <div>
          Exception Handler Active
        </div>
      </footer>
    </div>
  );
}
