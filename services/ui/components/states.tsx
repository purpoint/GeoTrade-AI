export function Skeleton({ className = "h-4 w-full" }: { className?: string }) {
  return <div className={`animate-pulse rounded bg-raised ${className}`} aria-hidden />;
}

export function SkeletonList({ rows = 5 }: { rows?: number }) {
  return (
    <div className="space-y-2" role="status" aria-label="Loading">
      {Array.from({ length: rows }, (_, i) => (
        <Skeleton key={i} className="h-16 w-full" />
      ))}
    </div>
  );
}

export function EmptyState({ title, hint }: { title: string; hint?: string }) {
  return (
    <div className="card p-6 text-center">
      <p className="font-medium">{title}</p>
      {hint ? <p className="mt-1 text-sm text-muted">{hint}</p> : null}
    </div>
  );
}

export function ErrorState({ error, onRetry }: { error: unknown; onRetry?: () => void }) {
  const message = error instanceof Error ? error.message : "Something went wrong";
  return (
    <div className="card border-neg/40 p-4 text-sm" role="alert">
      <p className="font-medium text-neg">Could not load this data</p>
      <p className="mt-1 text-muted">{message}</p>
      {onRetry ? (
        <button onClick={onRetry} className="mt-2 rounded border border-line px-2 py-1 text-xs hover:bg-raised">
          Retry
        </button>
      ) : null}
    </div>
  );
}

/** Stale banner: data is shown but older than expected. */
export function StaleNote({ children }: { children: React.ReactNode }) {
  return <p className="rounded bg-warn/10 px-2 py-1 text-xs text-warn">{children}</p>;
}
