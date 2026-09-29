import { cn } from "@/lib/utils";

type Variant = "primary" | "secondary" | "paper" | "quiet";
type Size = "sm" | "md" | "lg";

const VARIANTS: Record<Variant, string> = {
  primary: "bg-emerald text-white hover:bg-emerald-600",
  secondary: "border border-line bg-card text-ink hover:bg-paper",
  // For use on the dark band, where an emerald fill would disappear.
  paper: "bg-paper text-ink hover:bg-white",
  quiet: "text-ink-soft hover:text-ink",
};

const SIZES: Record<Size, string> = {
  sm: "px-3 py-1.5 text-[13px]",
  md: "px-4 py-2 text-sm",
  lg: "px-5 py-3 text-[15px]",
};

/**
 * Shared button styling, returned as a class string rather than a component
 * so `<button>`, `<Link>`, and `<a>` can all wear it without a polymorphic
 * `as` prop.
 */
export function buttonClasses(
  variant: Variant = "primary",
  size: Size = "md",
  className?: string
): string {
  return cn(
    "inline-flex items-center justify-center gap-2 rounded-btn font-semibold transition-colors",
    "disabled:cursor-not-allowed disabled:opacity-50",
    VARIANTS[variant],
    SIZES[size],
    className
  );
}

type ChipTone = "neutral" | "emerald" | "amber";

const CHIP_TONES: Record<ChipTone, string> = {
  neutral: "border-line bg-card text-ink-soft",
  emerald: "border-emerald-100 bg-emerald-50 text-emerald",
  amber: "border-amber-100 bg-amber-50 text-amber-text",
};

export function Chip({
  tone = "neutral",
  children,
  className,
}: {
  tone?: ChipTone;
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <span
      className={cn(
        "inline-flex items-center gap-1.5 rounded-chip border px-2.5 py-1 text-xs font-medium",
        CHIP_TONES[tone],
        className
      )}
    >
      {children}
    </span>
  );
}

/** Small uppercase label used above stats, table sections, and card groups. */
export function Eyebrow({
  children,
  className,
}: {
  children: React.ReactNode;
  className?: string;
}) {
  return (
    <div
      className={cn(
        "text-[11px] font-semibold uppercase tracking-[0.12em] text-ink-mute",
        className
      )}
    >
      {children}
    </div>
  );
}
