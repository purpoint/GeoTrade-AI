"use client";

import { useQueryClient } from "@tanstack/react-query";
import Link from "next/link";
import { useState } from "react";
import { RequireAuth } from "@/components/RequireAuth";
import { EmptyState, ErrorState, SkeletonList } from "@/components/states";
import { post, type AlertOut, type Me, type RuleOut } from "@/lib/api/client";
import { PlainRules } from "@/components/PlainRules";
import { useAlertRules, useAlerts } from "@/lib/api/hooks";
import { useMe } from "@/lib/auth/session";
import { fmtIst } from "@/lib/format";

const RULE_TITLE: Record<string, string> = {
  severe_event: "Severe negative news",
  negative_shift: "Sharp fall in news sentiment",
  concentration: "Concentration",
  coverage_spike: "Unusual news coverage (news spike)",
};

function Inbox() {
  const qc = useQueryClient();
  const { data, error, refetch } = useAlerts(false);
  const refresh = () => qc.invalidateQueries({ queryKey: ["alerts"] });
  if (error) return <ErrorState error={error} onRetry={() => refetch()} />;
  if (!data) return <SkeletonList />;
  if (!data.items.length) return <EmptyState title="No alerts yet" hint="Alerts appear here when news about your holdings crosses your rules." />;
  const read = async (a: AlertOut) => {
    if (!a.read_at) await post(`/alerts/${a.id}/read`).then(refresh);
  };
  return (
    <div className="space-y-2">
      <div className="flex justify-between text-sm">
        <span className="text-muted">{data.unread_count} unread</span>
        <button onClick={() => void post("/alerts/read-all").then(refresh)} disabled={!data.unread_count} className="text-accent hover:underline disabled:opacity-40">
          Mark all read
        </button>
      </div>
      {data.items.map((a) => (
        <article key={a.id} className={`card p-3 text-sm ${a.read_at ? "opacity-70" : "border-accent/50"}`} onClick={() => void read(a)}>
          <div className="flex flex-wrap items-baseline justify-between gap-2">
            <h3 className="font-medium">
              {!a.read_at ? <span className="mr-1 inline-block h-2 w-2 rounded-full bg-accent" aria-label="unread" /> : null}
              {a.title}
            </h3>
            <time className="text-xs text-muted">{fmtIst(a.created_at)}</time>
          </div>
          <p className="mt-1 text-muted">{a.body}</p>
          <div className="mt-1 flex flex-wrap gap-2 text-xs">
            {a.ticker ? (
              <Link href={`/stocks/${encodeURIComponent(a.ticker)}`} className="num text-accent hover:underline">
                {a.ticker}
              </Link>
            ) : null}
            {a.article_ids.slice(0, 3).map((id, i) => (
              <Link key={id} href={`/news/${id}`} className="text-accent hover:underline">
                Story {i + 1}
              </Link>
            ))}
            {a.merged_count ? <span className="text-muted">includes {a.merged_count} bundled update(s)</span> : null}
          </div>
        </article>
      ))}
    </div>
  );
}

function RuleCard({ rule }: { rule: RuleOut }) {
  const qc = useQueryClient();
  const [params, setParams] = useState(rule.params as Record<string, number | string>);
  const [msg, setMsg] = useState<string | null>(null);
  const save = async (body: object) => {
    try {
      await post(`/alert-rules/${rule.kind}`, body, "PUT");
      await qc.invalidateQueries({ queryKey: ["alert-rules"] });
      setMsg("Saved");
    } catch (e) {
      setMsg(e instanceof Error ? e.message : "Could not save");
    }
  };
  const num = (k: string, label: string, min: number, max: number, step: number, pct = false) => (
    <label className="block text-xs text-muted">
      <span className="flex justify-between">
        {label}
        <span className="num">{pct ? `${Math.round(Number(params[k]) * 100)}%` : params[k]}</span>
      </span>
      <input type="range" min={min} max={max} step={step} value={Number(params[k])} onChange={(e) => setParams({ ...params, [k]: Number(e.target.value) })} className="w-full" />
    </label>
  );
  return (
    <section className="card space-y-2 p-4 text-sm">
      <label className="flex items-center justify-between font-medium">
        {RULE_TITLE[rule.kind] ?? rule.kind}
        <input type="checkbox" checked={rule.enabled} onChange={(e) => void save({ enabled: e.target.checked })} aria-label={`Enable ${RULE_TITLE[rule.kind]}`} />
      </label>
      {rule.kind === "severe_event" ? num("min_severity", "Minimum severity", 0.3, 1, 0.05) : null}
      {rule.kind === "negative_shift" ? num("threshold", "Points fallen in 24h", 5, 80, 1) : null}
      {rule.kind === "concentration" ? (
        <>
          {num("stock", "One stock above", 0.05, 0.9, 0.05, true)}
          {num("sector", "One sector above", 0.1, 0.95, 0.05, true)}
        </>
      ) : null}
      {"scope" in params ? (
        <label className="flex items-center gap-2 text-xs text-muted">
          <input type="checkbox" checked={params.scope === "both"} onChange={(e) => setParams({ ...params, scope: e.target.checked ? "both" : "holdings" })} />
          Include my watchlist
        </label>
      ) : null}
      <button onClick={() => void save({ params })} className="rounded border border-line px-3 py-1 text-xs hover:bg-raised">
        Save thresholds
      </button>
      {msg ? <span className="ml-2 text-xs text-muted">{msg}</span> : null}
    </section>
  );
}

function QuietHours({ me }: { me: Me }) {
  const qc = useQueryClient();
  const q = (me.preferences as { quiet_hours?: { start: string; end: string } }).quiet_hours;
  const [start, setStart] = useState(q?.start ?? "22:00");
  const [end, setEnd] = useState(q?.end ?? "07:00");
  return (
    <form
      className="card flex flex-wrap items-end gap-2 p-4 text-sm"
      onSubmit={async (e) => {
        e.preventDefault();
        qc.setQueryData(["me"], await post<Me>("/me", { preferences: { quiet_hours: { start, end } } }, "PATCH"));
      }}
    >
      <span className="w-full font-medium">Quiet hours (IST): alerts are kept but not pushed live</span>
      <input type="time" value={start} onChange={(e) => setStart(e.target.value)} aria-label="Quiet from" className="rounded border border-line bg-surface px-2 py-1" />
      <input type="time" value={end} onChange={(e) => setEnd(e.target.value)} aria-label="Quiet until" className="rounded border border-line bg-surface px-2 py-1" />
      <button className="rounded border border-line px-3 py-1 text-xs hover:bg-raised">Save</button>
    </form>
  );
}

function Alerts() {
  const [tab, setTab] = useState<"inbox" | "rules">("inbox");
  const rules = useAlertRules(tab === "rules");
  const { data: me } = useMe();
  return (
    <div className="mx-auto max-w-3xl space-y-4">
      <h1 className="text-xl font-semibold">Alerts</h1>
      <div role="tablist" className="flex gap-1 border-b border-line">
        {(["inbox", "rules"] as const).map((t) => (
          <button key={t} role="tab" aria-selected={tab === t} onClick={() => setTab(t)} className={`px-3 py-1.5 text-sm capitalize ${tab === t ? "border-b-2 border-accent" : "text-muted"}`}>
            {t}
          </button>
        ))}
      </div>
      {tab === "inbox" ? (
        <Inbox />
      ) : (
        <div className="space-y-3">
          <p className="text-xs text-muted">At most two alerts per hour are delivered; extra updates are bundled into the next one.</p>
          {(rules.data ?? []).map((r) => (
            <RuleCard key={r.kind} rule={r} />
          ))}
          <PlainRules />
          {me ? <QuietHours me={me} /> : null}
        </div>
      )}
    </div>
  );
}

export default function AlertsPage() {
  return (
    <RequireAuth>
      <Alerts />
    </RequireAuth>
  );
}
