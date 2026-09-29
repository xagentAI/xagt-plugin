import { cn } from "@/lib/utils";

/**
 * The arc mark: a quarter sweep rising left-to-right, ending in a filled
 * dot — money travelling an arc to a destination. Drawn with round caps so
 * it still reads as a deliberate mark at 18px beside the wordmark.
 */
export function ArcMark({ className }: { className?: string }) {
  return (
    <svg
      viewBox="0 0 24 24"
      fill="none"
      aria-hidden="true"
      className={cn("h-4.5 w-4.5", className)}
    >
      <path
        d="M3 19.5A16.5 16.5 0 0 1 19.5 3"
        stroke="currentColor"
        strokeWidth="2.5"
        strokeLinecap="round"
      />
      <circle cx="19.5" cy="3" r="3" fill="currentColor" />
    </svg>
  );
}

export function Wordmark({
  className,
  markClassName,
}: {
  className?: string;
  markClassName?: string;
}) {
  return (
    <span className={cn("inline-flex items-baseline gap-1.5", className)}>
      <span className="font-display text-[26px] leading-none tracking-tight">
        Arcway
      </span>
      <ArcMark className={cn("translate-y-0.75 text-emerald", markClassName)} />
    </span>
  );
}
