"use client";

import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { ErrorState, SkeletonList } from "@/components/states";
import { api, ApiError, type BacktestReport, type Coverage, type EvalReport } from "@/lib/api/client";
import { fmtIst } from "@/lib/format";

type Cls = { n: number; accuracy: number; macro_f1: number; per_class: Record<string, { precision: number; recall: number; f1: number; support: number }>; confusion: Record<string, Record<string, number>> };
const LABELS = ["positive", "neutral", "negative"];
const pct = (v: number | null | undefined) => (v === null || v === undefined ? "—" : `${(v * 100).toFixed(1)}%`);
const optional = async <T,>(p: Promise<T>) => p.catch((e) => (e instanceof ApiError && e.status === 404 ? null : Promise.reject(e)));

function Card({ label, value, hint }: { label: string; value: string; hint?: string }) {
  return (
    <div className="card p-3">
      <p className="text-xs text-muted">{label}</p>
      <p className="num text-xl font-semibold">{value}</p>
      {hint ? <p className="text-xs text-muted">{hint}</p> : null}
    </div>
  );
}

function Confusion({ m }: { m: Cls }) {
  const max = Math.max(...LABELS.flatMap((g) => LABELS.map((p) => m.confusion[g]?.[p] ?? 0)), 1);
  return (
    <table className="num text-xs">
      <caption className="mb-1 text-left text-muted">Rows: gold label. Columns: predicted.</caption>
      <thead>
        <tr>
          <th />
          {LABELS.map((l) => (
            <th key={l} className="p-1 font-normal text-muted">
              {l}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {LABELS.map((g) => (
          <tr key={g}>
            <th className="p-1 pr-2 text-left font-normal text-muted">{g}</th>
            {LABELS.map((p) => {
              const v = m.confusion[g]?.[p] ?? 0;
              return (
                <td key={p} className="h-10 w-16 border border-line text-center" style={{ backgroundColor: `rgb(var(${g === p ? "--pos" : "--neg"}) / ${(0.08 + (v / max) * 0.4).toFixed(2)})` }}>
                  {v}
                </td>
              );
            })}
          </tr>
        ))}
      </tbody>
    </table>
  );
}

export default function EvaluationPage() {
  const report = useQuery({ queryKey: ["eval"], queryFn: () => optional(api<EvalReport>("/evaluation/latest")) });
  const backtest = useQuery({ queryKey: ["backtest"], queryFn: () => optional(api<BacktestReport>("/evaluation/backtest")) });
  const coverage = useQuery({ queryKey: ["coverage"], queryFn: () => api<Coverage>("/evaluation/coverage") });
  const [model, setModel] = useState<string | null>(null);
  if (report.error) return <ErrorState error={report.error} onRetry={() => report.refetch()} />;
  if (report.isLoading) return <SkeletonList rows={6} />;
  const r = report.data?.report as Record<string, any> | undefined; // eslint-disable-line @typescript-eslint/no-explicit-any
  const models = Object.keys(r?.sentiment ?? {});
  const current = model ?? models[models.length - 1] ?? "keyword-v1";
  const m = r?.sentiment?.[current] as Cls | undefined;
  const bt = backtest.data?.results as Record<string, any> | undefined; // eslint-disable-line @typescript-eslint/no-explicit-any
  const maxQ = Math.max(...((bt?.quintiles ?? []) as { mean_next_return_pct: number }[]).map((q) => Math.abs(q.mean_next_return_pct)), 0.0001);

  return (
    <div className="space-y-4">
      <h1 className="text-xl font-semibold">How well does it work?</h1>
      <div className="card border-warn/40 bg-warn/5 p-3 text-sm">
        <p className="font-medium">Read these numbers with care</p>
        <ul className="ml-4 list-disc text-muted">
          <li>The golden set is small and was labelled by the project team, so its scores are optimistic; the independent SEntFiN check below uses human labels from outside the project.</li>
          <li>News sentiment usually has weak predictive power for returns. Past behaviour is not a guide, and nothing here is advice.</li>
          <li>Anyone can reproduce these numbers with <code className="num">backend evaluate</code> and <code className="num">backend backtest</code>.</li>
        </ul>
      </div>
      {!r ? (
        <p className="text-sm text-muted">No evaluation has been run yet.</p>
      ) : (
        <>
          <p className="text-xs text-muted">
            {r.golden_set} · {m?.n ?? 0} headlines · run {fmtIst(report.data!.created_at)}
          </p>
          <div className="grid grid-cols-2 gap-2 md:grid-cols-4">
            {models.map((k) => (
              <Card key={k} label={`Sentiment macro F1 · ${k}`} value={pct(r.sentiment[k].macro_f1)} hint={`accuracy ${pct(r.sentiment[k].accuracy)}`} />
            ))}
            <Card label="Company linking F1" value={pct(r.linking.f1)} hint={`precision ${pct(r.linking.precision)} · recall ${pct(r.linking.recall)}`} />
            <Card label="Event type accuracy" value={pct(r.events.accuracy)} />
            <Card label="Dedupe precision" value={pct(r.dedupe?.precision)} hint={`recall ${pct(r.dedupe?.recall)} on ${r.dedupe?.pairs ?? 0} pairs`} />
            <Card label="Annotator agreement" value={r.agreement?.status === "done" ? `κ ${r.agreement.cohen_kappa}` : "pending"} hint={r.agreement?.status === "done" ? `${r.agreement.n} shared items` : "second annotator not done yet"} />
          </div>
          {models.length < 2 ? (
            <p className="text-sm text-muted">Only the keyword baseline was evaluated. Qwen appears here once the evaluation runs with a Groq key.</p>
          ) : (
            <p className="text-sm">
              Qwen vs keyword baseline (macro F1): <span className="num">{pct(r.sentiment[models.find((k) => k.startsWith("qwen")) ?? ""]?.macro_f1)}</span> vs{" "}
              <span className="num">{pct(r.sentiment["keyword-v1"]?.macro_f1)}</span>
            </p>
          )}
          {m ? (
            <section className="card space-y-3 p-4">
              <div className="flex gap-1">
                {models.map((k) => (
                  <button key={k} onClick={() => setModel(k)} aria-pressed={k === current} className={`rounded px-2 py-1 text-xs ${k === current ? "bg-accent text-on-accent" : "border border-line"}`}>
                    {k}
                  </button>
                ))}
              </div>
              <div className="flex flex-wrap gap-6">
                <Confusion m={m} />
                <table className="num text-xs">
                  <thead className="text-muted">
                    <tr>
                      <th className="p-1 text-left font-normal">class</th>
                      <th className="p-1 font-normal">precision</th>
                      <th className="p-1 font-normal">recall</th>
                      <th className="p-1 font-normal">F1</th>
                      <th className="p-1 font-normal">n</th>
                    </tr>
                  </thead>
                  <tbody>
                    {LABELS.map((l) => (
                      <tr key={l} className="border-t border-line">
                        <td className="p-1">{l}</td>
                        <td className="p-1 text-right">{pct(m.per_class[l]?.precision)}</td>
                        <td className="p-1 text-right">{pct(m.per_class[l]?.recall)}</td>
                        <td className="p-1 text-right">{pct(m.per_class[l]?.f1)}</td>
                        <td className="p-1 text-right">{m.per_class[l]?.support}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            </section>
          ) : null}
          {r.external?.models ? (
            <section className="card space-y-2 p-4 text-sm">
              <h2 className="font-semibold">Independent check: {r.external.dataset}</h2>
              <p className="text-xs text-muted">
                {r.external.n} Economic Times headlines labelled by three MBA annotators with expert curation, not by this project. Cohen&apos;s κ measures agreement with
                those human labels beyond chance (0 = chance, 1 = perfect).
              </p>
              <table className="num text-xs">
                <thead className="text-muted">
                  <tr>
                    <th className="p-1 text-left font-normal">model</th>
                    <th className="p-1 font-normal">accuracy</th>
                    <th className="p-1 font-normal">macro F1</th>
                    <th className="p-1 font-normal">κ vs humans</th>
                  </tr>
                </thead>
                <tbody>
                  {Object.entries(r.external.models as Record<string, { accuracy: number; macro_f1: number; cohen_kappa_vs_humans: number }>).map(([k, v]) => (
                    <tr key={k} className="border-t border-line">
                      <td className="p-1">{k}</td>
                      <td className="p-1 text-right">{pct(v.accuracy)}</td>
                      <td className="p-1 text-right">{pct(v.macro_f1)}</td>
                      <td className="p-1 text-right">{v.cohen_kappa_vs_humans.toFixed(2)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </section>
          ) : null}
          <section className="card p-4 text-sm">
            <h2 className="mb-2 font-semibold">Where the {current} model gets it wrong (sample)</h2>
            <ul className="space-y-1">
              {((r.errors?.[current] ?? []) as { id: string; headline: string; gold: string; pred: string }[]).slice(0, 10).map((e) => (
                <li key={e.id} className="text-xs">
                  {e.headline} <span className="text-muted">(gold {e.gold}, predicted {e.pred})</span>
                </li>
              ))}
            </ul>
          </section>
        </>
      )}
      <section className="card space-y-2 p-4 text-sm">
        <h2 className="font-semibold">Backtest: news signal vs next-session return</h2>
        {!bt ? (
          <p className="text-muted">No backtest yet.</p>
        ) : bt.status !== "ok" ? (
          <p className="text-muted">
            Not enough data yet ({bt.n} stock-sessions with both real news and prices; at least 30 needed). {bt.note}
          </p>
        ) : (
          <>
            <p className="num text-xs text-muted">
              n {bt.n} · Pearson {bt.pearson} · Spearman {bt.spearman} · hit rate {pct(bt.hit_rate)} (95% CI {pct(bt.hit_rate_ci95?.[0])}–{pct(bt.hit_rate_ci95?.[1])}) vs baseline {pct(bt.baseline)}
            </p>
            <ul className="space-y-1" aria-label="Mean next-session return by signal quintile">
              {(bt.quintiles as { quintile: number; n: number; mean_next_return_pct: number }[]).map((q) => (
                <li key={q.quintile} className="flex items-center gap-2 text-xs">
                  <span className="w-20">Quintile {q.quintile}</span>
                  <div className="relative h-3 flex-1" aria-hidden>
                    <div className="absolute left-1/2 h-3 w-px bg-line" />
                    <div className={`absolute h-3 rounded ${q.mean_next_return_pct >= 0 ? "left-1/2 bg-pos/70" : "right-1/2 bg-neg/70"}`} style={{ width: `${(Math.abs(q.mean_next_return_pct) / maxQ) * 50}%` }} />
                  </div>
                  <span className="num w-20 text-right">{q.mean_next_return_pct.toFixed(3)}%</span>
                </li>
              ))}
            </ul>
            <p className="text-xs text-muted">{bt.note}</p>
          </>
        )}
      </section>
      {coverage.data ? (
        <p className="text-xs text-muted">
          Real-news coverage, last 24h: {coverage.data.stocks_with_news_24h} stocks, {coverage.data.sectors_with_news_24h} sectors. Sample (simulated) stories are excluded from all statistics.
        </p>
      ) : null}
    </div>
  );
}
