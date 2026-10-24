"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useEffect, useState } from "react";
import { post, type EmailPrefs, type EmailPrefsIn } from "@/lib/api/client";
import { useEmailPrefs } from "@/lib/api/hooks";
import { fmtIst } from "@/lib/format";
import { ErrorState, Skeleton } from "../states";

const input = "mt-1 rounded border border-line bg-surface px-2 py-1.5 text-sm text-fg";

/** Settings tab "Email": opt-in Daily Pulse with recorded consent, send time and section toggles (P3-UI-01). */
export function EmailSettings() {
  const qc = useQueryClient();
  const { data, error, refetch } = useEmailPrefs();
  const [form, setForm] = useState<EmailPrefsIn | null>(null);
  const [consent, setConsent] = useState(false);
  const [msg, setMsg] = useState<string | null>(null);
  useEffect(() => {
    if (data && !form) setForm({ ...data, consent: false });
  }, [data, form]);
  if (error) return <ErrorState error={error} onRetry={() => refetch()} />;
  if (!data || !form) return <Skeleton className="h-48 w-full" />;
  const turningOn = form.daily_digest_enabled && !data.daily_digest_enabled;
  const set = (patch: Partial<EmailPrefsIn>) => setForm({ ...form, ...patch });
  const last = data.last_delivery as { session_date?: string; status?: string; sent_at?: string | null; skip_reason?: string | null } | null;
  return (
    <form
      className="card space-y-3 p-4 text-sm"
      onSubmit={async (e) => {
        e.preventDefault();
        try {
          const saved = await post<EmailPrefs>("/me/email-preferences", { ...form, consent }, "PUT");
          qc.setQueryData(["email-prefs"], saved);
          setForm({ ...saved, consent: false });
          setConsent(false);
          setMsg(saved.daily_digest_enabled ? "Saved. Your next Daily Pulse arrives after the market closes." : "Saved. The Daily Pulse is off.");
        } catch (err) {
          setMsg(err instanceof Error ? err.message : "Could not save");
        }
      }}
    >
      <h2 className="font-semibold">Daily Pulse email</h2>
      <p className="text-muted">
        One email per NSE trading day after the close, plus a Saturday recap: your holdings&apos; news sentiment, holdings to review and positive momentum to watch. Not investment advice.
      </p>
      <label className="flex items-center gap-2">
        <input type="checkbox" checked={form.daily_digest_enabled} onChange={(e) => set({ daily_digest_enabled: e.target.checked })} /> Send me the Daily Pulse
      </label>
      {turningOn ? (
        <label className="flex items-start gap-2 rounded bg-raised p-2 text-xs">
          <input type="checkbox" checked={consent} onChange={(e) => setConsent(e.target.checked)} className="mt-0.5" required />
          <span>{data.consent_text}</span>
        </label>
      ) : null}
      <fieldset disabled={!form.daily_digest_enabled} className="space-y-2 disabled:opacity-50">
        <label className="block text-xs text-muted">
          Send time (IST, 16:30 to 22:00)
          <input type="time" min="16:30" max="22:00" value={form.send_time_ist} onChange={(e) => set({ send_time_ist: e.target.value })} className={`${input} block`} />
        </label>
        <label className="flex items-center gap-2">
          <input type="checkbox" checked={form.include_watch_ideas} onChange={(e) => set({ include_watch_ideas: e.target.checked })} /> Include &quot;positive momentum to watch&quot;
        </label>
        <label className="flex items-center gap-2">
          <input type="checkbox" checked={form.include_watchlist} onChange={(e) => set({ include_watchlist: e.target.checked })} /> Include my watchlist
        </label>
        <label className="flex items-center gap-2">
          <input type="checkbox" checked={form.include_market} onChange={(e) => set({ include_market: e.target.checked })} /> Include market context
        </label>
      </fieldset>
      <p className="text-xs text-muted" role="status">
        {last?.session_date
          ? `Last digest: ${last.session_date}, ${last.status}${last.sent_at ? ` at ${fmtIst(last.sent_at)}` : ""}${last.skip_reason ? ` (${last.skip_reason.replace("_", " ")})` : ""}`
          : "No digest yet."}
        {data.consented_at ? ` Consent recorded ${fmtIst(data.consented_at)}.` : ""}
        {data.unsubscribed_at ? ` Unsubscribed ${fmtIst(data.unsubscribed_at)}.` : ""}
      </p>
      <button className="rounded bg-accent px-3 py-1 text-on-accent" disabled={turningOn && !consent}>
        Save
      </button>
      {msg ? <p className="text-xs text-muted" role="status">{msg}</p> : null}
    </form>
  );
}
