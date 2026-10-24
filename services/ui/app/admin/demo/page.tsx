"use client";

import Link from "next/link";
import { useEffect, useState } from "react";
import { AdminNav } from "@/components/AdminNav";
import { RequireAuth } from "@/components/RequireAuth";
import { SentimentBadge } from "@/components/SentimentBadge";
import { api, post, type Trace } from "@/lib/api/client";

const STAGES = ["fetched", "deduped", "linked", "scored", "aggregated"] as const;
const STAGE_OF: Record<string, string> = { dedupe: "deduped", link: "linked", score: "scored", aggregate: "aggregated" };
const SAMPLES = [
  "SEBI orders forensic audit of Adani Enterprises accounts",
  "Infosys wins $2 billion AI transformation deal from US bank",
  "RBI imposes penalty on Kotak Mahindra Bank for KYC lapses",
];

function DemoPanel() {
  const [title, setTitle] = useState(SAMPLES[0] ?? "");
  const [articleId, setArticleId] = useState<string | null>(null);
  const [trace, setTrace] = useState<Trace | null>(null);
  const [message, setMessage] = useState<string | null>(null);
  const [startedAt, setStartedAt] = useState(0);

  useEffect(() => {
    if (!articleId) return;
    let stop = false;
    const tick = async () => {
      try {
        const t = await api<Trace>(`/admin/demo/trace/${articleId}`);
        if (stop) return;
        setTrace(t);
        if (["aggregated", "dead_letter", "duplicate", "irrelevant", "dropped"].includes(t.status) || Date.now() - startedAt > 60_000) return;
      } catch (e) {
        setMessage(e instanceof Error ? e.message : String(e));
        return;
      }
      setTimeout(tick, 400);
    };
    void tick();
    return () => {
      stop = true;
    };
  }, [articleId, startedAt]);

  const run = async (fn: () => Promise<void>) => {
    setMessage(null);
    try {
      await fn();
    } catch (e) {
      setMessage(e instanceof Error ? e.message : String(e));
    }
  };
  const inject = () =>
    run(async () => {
      setTrace(null);
      const r = await post<{ article_id: string }>("/admin/demo/inject", { title });
      setStartedAt(Date.now());
      setArticleId(r.article_id);
    });

  const base = trace?.stage_timestamps.fetched ? new Date(trace.stage_timestamps.fetched).getTime() : 0;
  return (
    <div className="mx-auto max-w-3xl space-y-4">
      <p className="text-sm text-muted">Inject a headline and watch it move through every stage. Injected items are flagged as sample data and never enter statistics.</p>
      <form onSubmit={(e) => (e.preventDefault(), void inject())} className="card space-y-3 p-4">
        <label className="block text-xs text-muted">
          Headline
          <input value={title} onChange={(e) => setTitle(e.target.value)} className="mt-1 w-full rounded border border-line bg-surface px-2 py-1 text-sm text-fg" minLength={8} maxLength={300} required />
        </label>
        <div className="flex flex-wrap gap-1">
          {SAMPLES.map((s) => (
            <button type="button" key={s} onClick={() => setTitle(s)} className="rounded bg-raised px-2 py-0.5 text-xs text-muted hover:text-fg">
              {s.slice(0, 40)}…
            </button>
          ))}
        </div>
        <div className="flex flex-wrap gap-2">
          <button className="rounded bg-accent px-3 py-1.5 text-sm text-on-accent">Inject headline</button>
          <button type="button" onClick={() => void run(async () => setMessage(`Injected ${(await post<{ article_ids: string[] }>("/admin/demo/replay")).article_ids.length} scripted headlines`))} className="rounded border border-line px-3 py-1.5 text-sm hover:bg-raised">
            Replay demo script
          </button>
          <button type="button" onClick={() => void run(async () => (setTrace(null), setMessage(`Removed ${(await post<{ deleted: number }>("/admin/demo/reset")).deleted} injected stories and recomputed their indices`)))} className="rounded border border-line px-3 py-1.5 text-sm hover:bg-raised">
            Reset demo data
          </button>
        </div>
        {message ? <p className="text-sm text-muted" role="status">{message}</p> : null}
      </form>
      {trace ? (
        <section className="card p-4" aria-live="polite">
          <h2 className="mb-3 text-sm font-semibold">Stage trace · {trace.status}</h2>
          <ol className="space-y-2">
            {STAGES.map((stage) => {
              const at = trace.stage_timestamps[stage];
              const ev = trace.events.find((e) => STAGE_OF[e.stage] === stage);
              return (
                <li key={stage} className="flex items-center gap-3 text-sm">
                  <span className={`h-3 w-3 rounded-full ${at ? "bg-pos" : "animate-pulse bg-line"}`} aria-hidden />
                  <span className="w-24 font-medium">{stage}</span>
                  <span className="num text-xs text-muted">
                    {at ? `+${((new Date(at).getTime() - base) / 1000).toFixed(2)}s` : "waiting"}
                    {ev?.duration_ms !== undefined && ev.duration_ms !== null ? ` · ${ev.duration_ms} ms in stage` : ""}
                  </span>
                </li>
              );
            })}
          </ol>
          {trace.article ? (
            <div className="mt-4 border-t border-line pt-3 text-sm">
              <div className="flex flex-wrap items-center gap-2">
                {trace.article.sentiment ? <SentimentBadge label={trace.article.sentiment.label} /> : null}
                <span className="text-muted">{trace.article.tickers.map((t) => t.ticker).join(", ") || "no company linked"}</span>
                <Link href={`/news/${trace.article.id}`} className="text-accent hover:underline">
                  Open story
                </Link>
              </div>
              <p className="mt-2 text-xs text-muted">{trace.article.explanation}</p>
            </div>
          ) : trace.status === "duplicate" ? (
            <p className="mt-3 text-sm text-warn">Grouped with an earlier copy of the same story, so it was not scored again. Reset demo data to start fresh.</p>
          ) : trace.status === "irrelevant" || trace.status === "dropped" ? (
            <p className="mt-3 text-sm text-warn">Stopped at linking: the headline did not look relevant to NIFTY 50 companies.</p>
          ) : null}
        </section>
      ) : null}
    </div>
  );
}

export default function DemoPage() {
  return (
    <RequireAuth operator>
      <div className="space-y-4">
        <h1 className="text-xl font-semibold">Operator console</h1>
        <AdminNav current="/admin/demo" />
        <DemoPanel />
      </div>
    </RequireAuth>
  );
}
