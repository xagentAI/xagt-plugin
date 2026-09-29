"use client";

import React, {
  createContext,
  useContext,
  useState,
  useCallback,
  useRef,
  useEffect,
} from "react";
import { motion, AnimatePresence } from "framer-motion";
import {
  IconAlertTriangle,
  IconAlertCircle,
  IconInfoCircle,
  IconX,
  IconLoader2,
  IconLogout,
  IconTrash,
} from "@tabler/icons-react";
import { cn } from "@/lib/utils";

export type ConfirmVariant = "danger" | "warning" | "info";

export interface ConfirmOptions {
  title: string;
  message: string | React.ReactNode;
  variant?: ConfirmVariant;
  confirmText?: string;
  cancelText?: string;
  icon?: React.ReactNode;
  details?: React.ReactNode;
}

type ConfirmFn = (options: ConfirmOptions) => Promise<boolean>;

const ConfirmContext = createContext<ConfirmFn | null>(null);

let globalConfirmHandler: ConfirmFn | null = null;

/**
 * Imperative helper that can be called anywhere on the client.
 */
export async function customConfirm(options: ConfirmOptions): Promise<boolean> {
  if (globalConfirmHandler) {
    return globalConfirmHandler(options);
  }
  // Fallback if provider is not mounted
  if (typeof window !== "undefined") {
    const text = typeof options.message === "string" ? options.message : options.title;
    return window.confirm(text);
  }
  return false;
}

export function ConfirmProvider({ children }: { children: React.ReactNode }) {
  const [isOpen, setIsOpen] = useState(false);
  const [options, setOptions] = useState<ConfirmOptions | null>(null);
  const [loading, setLoading] = useState(false);
  const resolverRef = useRef<((value: boolean) => void) | null>(null);

  const confirm = useCallback((opts: ConfirmOptions): Promise<boolean> => {
    return new Promise((resolve) => {
      resolverRef.current = resolve;
      setOptions(opts);
      setIsOpen(true);
      setLoading(false);
    });
  }, []);

  useEffect(() => {
    globalConfirmHandler = confirm;
    return () => {
      globalConfirmHandler = null;
    };
  }, [confirm]);

  const handleClose = useCallback((value: boolean) => {
    setIsOpen(false);
    if (resolverRef.current) {
      resolverRef.current(value);
      resolverRef.current = null;
    }
  }, []);

  // Keyboard navigation: Escape cancels, Enter confirms
  useEffect(() => {
    if (!isOpen) return;

    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Escape") {
        e.preventDefault();
        handleClose(false);
      } else if (e.key === "Enter" && !loading) {
        e.preventDefault();
        handleClose(true);
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [isOpen, loading, handleClose]);

  // Lock body scroll while open
  useEffect(() => {
    if (isOpen) {
      document.body.style.overflow = "hidden";
    } else {
      document.body.style.overflow = "";
    }
    return () => {
      document.body.style.overflow = "";
    };
  }, [isOpen]);

  const variant = options?.variant || "info";

  const getDefaultIcon = () => {
    if (options?.icon) return options.icon;
    switch (variant) {
      case "danger":
        return <IconAlertTriangle size={22} className="text-rose-400" />;
      case "warning":
        return <IconAlertCircle size={22} className="text-amber-400" />;
      case "info":
      default:
        return <IconInfoCircle size={22} className="text-purple-400" />;
    }
  };

  const getVariantStyles = () => {
    switch (variant) {
      case "danger":
        return {
          iconContainer: "bg-rose-500/10 border-rose-500/20",
          confirmBtn:
            "bg-rose-600 hover:bg-rose-500 text-white shadow-lg shadow-rose-600/20 hover:scale-[1.02] active:scale-[0.98]",
        };
      case "warning":
        return {
          iconContainer: "bg-amber-500/10 border-amber-500/20",
          confirmBtn:
            "bg-amber-600 hover:bg-amber-500 text-white shadow-lg shadow-amber-600/20 hover:scale-[1.02] active:scale-[0.98]",
        };
      case "info":
      default:
        return {
          iconContainer: "bg-purple-500/10 border-purple-500/20",
          confirmBtn:
            "bg-accent hover:bg-accent-hover text-white shadow-lg shadow-purple-600/20 hover:scale-[1.02] active:scale-[0.98]",
        };
    }
  };

  const styles = getVariantStyles();

  return (
    <ConfirmContext.Provider value={confirm}>
      {children}

      <AnimatePresence>
        {isOpen && options && (
          <div className="fixed inset-0 z-[100] flex items-center justify-center p-4">
            {/* Backdrop */}
            <motion.div
              initial={{ opacity: 0 }}
              animate={{ opacity: 1 }}
              exit={{ opacity: 0 }}
              transition={{ duration: 0.15 }}
              onClick={() => handleClose(false)}
              className="fixed inset-0 bg-black/80 backdrop-blur-md"
            />

            {/* Modal Card */}
            <motion.div
              initial={{ opacity: 0, scale: 0.95, y: 8 }}
              animate={{ opacity: 1, scale: 1, y: 0 }}
              exit={{ opacity: 0, scale: 0.95, y: 8 }}
              transition={{ duration: 0.2, ease: [0.16, 1, 0.3, 1] }}
              className="relative z-10 w-full max-w-[420px] bg-[#0c0c0e]/95 backdrop-blur-2xl border border-white/[0.08] shadow-[0_24px_60px_-12px_rgba(0,0,0,0.9)] rounded-2xl sm:rounded-3xl p-6 sm:p-7 overflow-hidden font-[family-name:var(--font-geist-sans)] select-none"
            >
              {/* Dismiss cross */}
              <button
                onClick={() => handleClose(false)}
                className="absolute top-5 right-5 p-1.5 text-neutral-400 hover:text-white hover:bg-white/[0.06] rounded-lg transition-colors cursor-pointer"
                title="Dismiss"
                aria-label="Dismiss"
              >
                <IconX size={16} />
              </button>

              {/* Icon Container */}
              <div
                className={cn(
                  "w-12 h-12 rounded-2xl flex items-center justify-center border mb-4.5 transition-transform",
                  styles.iconContainer
                )}
              >
                {getDefaultIcon()}
              </div>

              {/* Content */}
              <div>
                <h3 className="text-base sm:text-lg font-bold text-white tracking-tight leading-snug">
                  {options.title}
                </h3>
                <div className="text-xs sm:text-sm text-neutral-400 leading-relaxed mt-2 font-[family-name:var(--font-geist-sans)]">
                  {options.message}
                </div>

                {/* Optional Details Box */}
                {options.details && (
                  <div className="mt-3.5 p-3 rounded-xl bg-white/[0.03] border border-white/[0.06] font-mono text-xs text-neutral-300">
                    {options.details}
                  </div>
                )}
              </div>

              {/* Actions Footer */}
              <div className="mt-6 flex items-center justify-end gap-2.5">
                <button
                  type="button"
                  onClick={() => handleClose(false)}
                  disabled={loading}
                  className="px-4 py-2.5 rounded-xl border border-white/[0.08] bg-white/[0.03] hover:bg-white/[0.06] text-neutral-300 hover:text-white font-medium text-xs transition-colors cursor-pointer disabled:opacity-50 font-[family-name:var(--font-geist-sans)]"
                >
                  {options.cancelText || "Cancel"}
                </button>

                <button
                  type="button"
                  onClick={() => handleClose(true)}
                  disabled={loading}
                  className={cn(
                    "px-4.5 py-2.5 rounded-xl font-semibold text-xs transition-all cursor-pointer disabled:opacity-50 flex items-center gap-1.5 font-[family-name:var(--font-geist-sans)]",
                    styles.confirmBtn
                  )}
                >
                  {loading && <IconLoader2 size={13} className="animate-spin" />}
                  <span>{options.confirmText || "Confirm"}</span>
                </button>
              </div>
            </motion.div>
          </div>
        )}
      </AnimatePresence>
    </ConfirmContext.Provider>
  );
}

export function useConfirm(): ConfirmFn {
  const context = useContext(ConfirmContext);
  if (!context) {
    // If used outside provider, fallback to customConfirm
    return customConfirm;
  }
  return context;
}
