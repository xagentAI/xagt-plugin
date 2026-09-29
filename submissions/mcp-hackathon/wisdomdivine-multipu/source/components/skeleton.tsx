import { cn } from "@/lib/utils";

function Skeleton({ className, ...props }: React.HTMLAttributes<HTMLDivElement>) {
  return (
    <div
      className={cn("animate-pulse rounded-sm bg-white/[0.04]", className)}
      {...props}
    />
  );
}

/** Grid of stat cards skeleton */
function StatsSkeleton({ count = 4 }: { count?: number }) {
  return (
    <div
      className="grid gap-px bg-border border border-border mb-10"
      style={{ gridTemplateColumns: `repeat(${Math.min(count, 4)}, 1fr)` }}
    >
      {Array.from({ length: count }).map((_, i) => (
        <div key={i} className="bg-background p-6 space-y-3">
          <Skeleton className="h-3 w-20" />
          <Skeleton className="h-7 w-16" />
          <Skeleton className="h-3 w-24" />
        </div>
      ))}
    </div>
  );
}

/** Single card row skeleton */
function CardSkeleton() {
  return (
    <div className="border border-border p-5 md:p-6 flex items-center gap-4">
      <Skeleton className="w-10 h-10 rounded-lg flex-shrink-0" />
      <div className="flex-1 space-y-2">
        <Skeleton className="h-4 w-32" />
        <Skeleton className="h-3 w-48" />
      </div>
      <Skeleton className="h-4 w-16" />
    </div>
  );
}

/** List of card skeletons */
function ListSkeleton({ count = 3 }: { count?: number }) {
  return (
    <div className="space-y-3">
      {Array.from({ length: count }).map((_, i) => (
        <CardSkeleton key={i} />
      ))}
    </div>
  );
}

export { Skeleton, StatsSkeleton, CardSkeleton, ListSkeleton };
