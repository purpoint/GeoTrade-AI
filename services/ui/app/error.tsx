"use client";

import { useEffect } from "react";

/** Route error boundary (P3-UI-07): a crash in one page shows a retry card instead of a blank screen. */
export default function RouteError({ error, reset }: { error: Error & { digest?: string }; reset: () => void }) {
  useEffect(() => {
    // the server logs carry the same digest, so a report can be matched to its stack trace
    console.error("page error", { message: error.message, digest: error.digest });
  }, [error]);
  return (
    <div className="card mx-auto max-w-md space-y-2 p-6 text-center" role="alert">
      <p className="font-medium">Something went wrong on this page</p>
      <p className="text-sm text-muted">{error.digest ? `Reference ${error.digest}. ` : ""}Your data is safe; try again.</p>
      <button onClick={reset} className="rounded bg-accent px-3 py-1.5 text-sm text-on-accent">
        Try again
      </button>
    </div>
  );
}
