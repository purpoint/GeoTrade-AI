"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useMe } from "@/lib/auth/session";
import { ErrorState, SkeletonList } from "./states";

/** Renders children for signed-in users (optionally operators only); otherwise a sign-in prompt. */
export function RequireAuth({ children, operator = false }: { children: React.ReactNode; operator?: boolean }) {
  const { data: me, error, isLoading, refetch } = useMe();
  const path = usePathname();
  if (isLoading) return <SkeletonList rows={4} />;
  if (error) return <ErrorState error={error} onRetry={() => refetch()} />;
  if (!me)
    return (
      <div className="card mx-auto max-w-md p-6 text-center">
        <p className="font-medium">Sign in to see this page</p>
        <p className="mt-1 text-sm text-muted">Your portfolio, alerts and settings are private to your account.</p>
        <div className="mt-4 flex justify-center gap-2">
          <Link href={`/login?next=${encodeURIComponent(path)}`} className="rounded bg-accent px-3 py-1.5 text-sm text-on-accent">
            Sign in
          </Link>
          <Link href="/signup" className="rounded border border-line px-3 py-1.5 text-sm hover:bg-raised">
            Create account
          </Link>
        </div>
      </div>
    );
  if (operator && me.role !== "operator")
    return <ErrorState error={new Error("This page is for operators. Sign in with the operator account.")} />;
  return <>{children}</>;
}
