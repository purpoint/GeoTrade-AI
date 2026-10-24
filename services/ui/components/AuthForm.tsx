"use client";

import Link from "next/link";
import { useState } from "react";
import { ApiError } from "@/lib/api/client";
import { useAuthActions } from "@/lib/auth/session";
import { DISCLAIMER } from "./shell/Footer";

const input = "mt-1 w-full rounded border border-line bg-surface px-2 py-1.5 text-sm text-fg";

export function AuthForm({ mode, next }: { mode: "login" | "signup"; next?: string }) {
  const actions = useAuthActions();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [name, setName] = useState("");
  const [accepted, setAccepted] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const emailError = email && !/^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(email) ? "Enter a valid email address" : null;
  const passwordError = mode === "signup" && password && password.length < 10 ? "Use at least 10 characters" : null;

  const run = async (fn: () => Promise<void>) => {
    setBusy(true);
    setError(null);
    try {
      await fn();
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "Something went wrong, try again");
    } finally {
      setBusy(false);
    }
  };

  return (
    <div className="mx-auto max-w-sm space-y-4">
      <h1 className="text-xl font-semibold">{mode === "login" ? "Sign in" : "Create your account"}</h1>
      <form
        className="card space-y-3 p-4"
        onSubmit={(e) => {
          e.preventDefault();
          if (emailError || passwordError) return;
          void run(() =>
            mode === "login"
              ? actions.login(email, password, next)
              : actions.signup({ email, password, display_name: name || undefined, accept_disclaimer: accepted }),
          );
        }}
      >
        {mode === "signup" ? (
          <label className="block text-xs text-muted">
            Name (optional)
            <input value={name} onChange={(e) => setName(e.target.value)} className={input} autoComplete="name" maxLength={80} />
          </label>
        ) : null}
        <label className="block text-xs text-muted">
          Email
          <input type="email" value={email} onChange={(e) => setEmail(e.target.value)} className={input} autoComplete="email" required aria-invalid={Boolean(emailError)} />
          {emailError ? <span className="mt-1 block text-neg">{emailError}</span> : null}
        </label>
        <label className="block text-xs text-muted">
          Password
          <input
            type="password"
            value={password}
            onChange={(e) => setPassword(e.target.value)}
            className={input}
            autoComplete={mode === "login" ? "current-password" : "new-password"}
            required
            aria-invalid={Boolean(passwordError)}
          />
          {passwordError ? <span className="mt-1 block text-neg">{passwordError}</span> : null}
        </label>
        {mode === "signup" ? (
          <label className="flex items-start gap-2 text-xs text-muted">
            <input type="checkbox" checked={accepted} onChange={(e) => setAccepted(e.target.checked)} className="mt-0.5" required />
            <span>I understand: {DISCLAIMER}</span>
          </label>
        ) : null}
        {error ? (
          <p className="text-sm text-neg" role="alert">
            {error}
          </p>
        ) : null}
        <button disabled={busy || (mode === "signup" && !accepted)} className="w-full rounded bg-accent py-1.5 text-sm text-on-accent disabled:opacity-50">
          {busy ? "Please wait…" : mode === "login" ? "Sign in" : "Create account"}
        </button>
      </form>
      <button onClick={() => void run(actions.demo)} disabled={busy} className="w-full rounded border border-line py-1.5 text-sm hover:bg-raised">
        Try the demo account
      </button>
      <p className="text-center text-sm text-muted">
        {mode === "login" ? (
          <>
            New here?{" "}
            <Link href="/signup" className="text-accent hover:underline">
              Create an account
            </Link>
          </>
        ) : (
          <>
            Have an account?{" "}
            <Link href="/login" className="text-accent hover:underline">
              Sign in
            </Link>
          </>
        )}
      </p>
    </div>
  );
}
