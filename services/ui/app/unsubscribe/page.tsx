"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { ApiError, post } from "@/lib/api/client";

/** One-click unsubscribe landing (P3-UI-04): works without signing in. A button (not page load) does the
 * unsubscribe, so mail scanners that prefetch links cannot unsubscribe people by accident. */
export default function UnsubscribePage() {
  const [token, setToken] = useState<string | null>(null);
  const [state, setState] = useState<"ready" | "working" | "done" | "error">("ready");
  const [msg, setMsg] = useState("");
  useEffect(() => setToken(new URLSearchParams(window.location.search).get("token")), []);
  const confirm = async () => {
    if (!token) return;
    setState("working");
    try {
      const r = await post<{ email_hint: string }>(`/email/unsubscribe?token=${encodeURIComponent(token)}`);
      setMsg(`${r.email_hint} will no longer receive the Daily Pulse.`);
      setState("done");
    } catch (e) {
      setMsg(e instanceof ApiError && e.status === 409 ? "This link was already used: you are unsubscribed." : e instanceof Error ? e.message : "Something went wrong");
      setState(e instanceof ApiError && e.status === 409 ? "done" : "error");
    }
  };
  return (
    <div className="card mx-auto max-w-md space-y-3 p-6 text-center">
      <h1 className="text-lg font-semibold">Unsubscribe from the Daily Pulse</h1>
      {!token ? <p className="text-sm text-muted">This page needs the link from a Daily Pulse email.</p> : null}
      {token && state !== "done" ? (
        <>
          <p className="text-sm text-muted">Stop the daily and weekly Pulse emails. Alerts in the app are not affected.</p>
          <button onClick={confirm} disabled={state === "working"} className="rounded bg-accent px-4 py-1.5 text-sm text-on-accent disabled:opacity-50">
            {state === "working" ? "Unsubscribing…" : "Unsubscribe"}
          </button>
        </>
      ) : null}
      {msg ? (
        <p role="status" className={`text-sm ${state === "error" ? "text-neg" : ""}`}>
          {msg}
        </p>
      ) : null}
      {state === "done" ? (
        <p className="text-sm">
          Changed your mind?{" "}
          <Link href="/settings?tab=email" className="text-accent hover:underline">
            Resubscribe in settings
          </Link>{" "}
          (sign in required).
        </p>
      ) : null}
    </div>
  );
}
