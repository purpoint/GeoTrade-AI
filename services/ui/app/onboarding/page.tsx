"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useRouter } from "next/navigation";
import { useState } from "react";
import { RequireAuth } from "@/components/RequireAuth";
import { post, upload, type ImportPreview, type PortfolioOut, type RuleOut } from "@/lib/api/client";
import { useAlertRules } from "@/lib/api/hooks";

type Row = { symbol: string; ticker: string | null; quantity: number | null; avg_price: number | null; status: string; issue: string | null };
const STEPS = ["Add holdings", "Review", "Alerts"] as const;
const cell = "w-24 rounded border border-line bg-surface px-1 py-0.5 text-right text-sm";
const RULE_TEXT: Record<string, string> = {
  severe_event: "Severe negative news about a stock I hold",
  negative_shift: "News sentiment for a holding falls sharply in 24 hours",
  concentration: "One stock above 25% or one sector above 40% of my portfolio",
};

function Dropzone({ onPreview }: { onPreview: (p: ImportPreview) => void }) {
  const [drag, setDrag] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const send = async (file?: File) => {
    if (!file) return;
    setBusy(true);
    setError(null);
    try {
      onPreview(await upload<ImportPreview>("/portfolio/import", file));
    } catch (e) {
      setError(e instanceof Error ? e.message : "Upload failed");
    } finally {
      setBusy(false);
    }
  };
  return (
    <div>
      <label
        onDragOver={(e) => (e.preventDefault(), setDrag(true))}
        onDragLeave={() => setDrag(false)}
        onDrop={(e) => (e.preventDefault(), setDrag(false), void send(e.dataTransfer.files[0]))}
        className={`flex cursor-pointer flex-col items-center gap-1 rounded-lg border-2 border-dashed p-8 text-center text-sm ${drag ? "border-accent bg-accent/5" : "border-line"}`}
      >
        <span className="font-medium">{busy ? "Reading your file…" : "Drop a CSV or XLSX here, or click to choose"}</span>
        <span className="text-xs text-muted">Zerodha (Kite or Console), Groww, or any file with symbol, quantity and average price. Max 1 MB.</span>
        <input type="file" accept=".csv,.xlsx" className="sr-only" onChange={(e) => void send(e.target.files?.[0])} aria-label="Holdings file" />
      </label>
      {error ? <p className="mt-2 text-sm text-neg" role="alert">{error}</p> : null}
    </div>
  );
}

function Manual({ onAdd }: { onAdd: (row: Row) => void }) {
  const [symbol, setSymbol] = useState("");
  const [qty, setQty] = useState("");
  const [price, setPrice] = useState("");
  return (
    <form
      className="flex flex-wrap items-end gap-2 text-sm"
      onSubmit={(e) => {
        e.preventDefault();
        onAdd({ symbol: symbol.toUpperCase(), ticker: null, quantity: Number(qty), avg_price: Number(price), status: "manual", issue: null });
        setSymbol("");
        setQty("");
        setPrice("");
      }}
    >
      <label className="text-xs text-muted">
        Symbol
        <input value={symbol} onChange={(e) => setSymbol(e.target.value)} required className="mt-1 block w-28 rounded border border-line bg-surface px-2 py-1 text-sm text-fg" />
      </label>
      <label className="text-xs text-muted">
        Quantity
        <input type="number" min="0.0001" step="any" value={qty} onChange={(e) => setQty(e.target.value)} required className="mt-1 block w-24 rounded border border-line bg-surface px-2 py-1 text-sm text-fg" />
      </label>
      <label className="text-xs text-muted">
        Avg price
        <input type="number" min="0" step="any" value={price} onChange={(e) => setPrice(e.target.value)} required className="mt-1 block w-28 rounded border border-line bg-surface px-2 py-1 text-sm text-fg" />
      </label>
      <button className="rounded border border-line px-3 py-1 hover:bg-raised">Add</button>
    </form>
  );
}

function Wizard() {
  const qc = useQueryClient();
  const router = useRouter();
  const [step, setStep] = useState(0);
  const [token, setToken] = useState<string | null>(null);
  const [rows, setRows] = useState<Row[]>([]);
  const [error, setError] = useState<string | null>(null);
  const rules = useAlertRules(step === 2);

  const review = (p: ImportPreview) => {
    setToken(p.token);
    setRows(p.rows as Row[]);
    setStep(1);
  };
  // formula-looking symbols are never imported; anything else is fine once quantity and price are valid
  const usable = (r: Row) => !r.issue?.includes("formula") && (r.quantity ?? 0) > 0 && r.avg_price !== null && r.avg_price >= 0;
  const keep = rows.filter(usable);
  const done = (p: PortfolioOut) => {
    qc.setQueryData(["portfolio"], p);
    setStep(2);
  };
  const confirm = async () => {
    setError(null);
    try {
      const body = { rows: keep.map((r) => ({ symbol: r.ticker ?? r.symbol, quantity: r.quantity, avg_price: r.avg_price })), mode: "replace" };
      done(token ? await post<PortfolioOut>(`/portfolio/import/${token}/confirm`, body) : await addManual());
    } catch (e) {
      setError(e instanceof Error ? e.message : "Import failed");
    }
  };
  const addManual = async () => {
    let last: PortfolioOut | undefined;
    for (const r of keep) last = await post<PortfolioOut>("/portfolio/holdings", { symbol: r.symbol, quantity: r.quantity, avg_price: r.avg_price });
    if (!last) throw new Error("Add at least one holding");
    return last;
  };

  return (
    <div className="mx-auto max-w-3xl space-y-4">
      <h1 className="text-xl font-semibold">Set up your portfolio</h1>
      <ol className="flex gap-2 text-xs" aria-label="Steps">
        {STEPS.map((s, i) => (
          <li key={s} aria-current={i === step ? "step" : undefined} className={`rounded-full px-3 py-1 ${i === step ? "bg-accent text-on-accent" : i < step ? "bg-pos/15 text-pos" : "bg-raised text-muted"}`}>
            {i + 1}. {s}
          </li>
        ))}
      </ol>

      {step === 0 ? (
        <div className="space-y-4">
          <section className="card space-y-2 p-4">
            <h2 className="text-sm font-semibold">Upload a holdings file</h2>
            <Dropzone onPreview={review} />
          </section>
          <section className="card space-y-2 p-4">
            <h2 className="text-sm font-semibold">Or enter holdings by hand</h2>
            <Manual onAdd={(r) => (setRows((prev) => [...prev, r]), setToken(null))} />
            {rows.length ? (
              <button onClick={() => setStep(1)} className="rounded bg-accent px-3 py-1 text-sm text-on-accent">
                Review {rows.length} holding{rows.length > 1 ? "s" : ""}
              </button>
            ) : null}
          </section>
          <section className="card flex items-center justify-between p-4 text-sm">
            <span>Just exploring? Load a sample of 12 NIFTY 50 holdings.</span>
            <button onClick={async () => done(await post<PortfolioOut>("/portfolio/sample"))} className="rounded border border-line px-3 py-1 hover:bg-raised">
              Load sample
            </button>
          </section>
        </div>
      ) : null}

      {step === 1 ? (
        <section className="card space-y-3 p-4">
          <p className="text-sm text-muted">
            {rows.filter((r) => r.ticker).length} matched to NIFTY 50 · {rows.filter((r) => r.status === "unmatched").length} kept without news signals ·{" "}
            {rows.filter((r) => !usable(r)).length} need fixing or will be skipped
          </p>
          <div className="overflow-x-auto">
            <table className="w-full text-sm">
              <thead className="text-left text-xs text-muted">
                <tr>
                  <th className="p-1">Symbol</th>
                  <th className="p-1">Status</th>
                  <th className="p-1 text-right">Quantity</th>
                  <th className="p-1 text-right">Avg price</th>
                  <th className="p-1" />
                </tr>
              </thead>
              <tbody>
                {rows.map((r, i) => (
                  <tr key={`${r.symbol}-${i}`} className="border-t border-line">
                    <td className="num p-1">{r.ticker ?? r.symbol}</td>
                    <td className="p-1 text-xs">
                      {!usable(r) ? (
                        <span className="text-neg">will be skipped</span>
                      ) : r.ticker || r.status === "matched" ? (
                        <span className="text-pos">matched</span>
                      ) : (
                        <span className="text-warn">{r.status === "manual" ? "checked on import" : "no news signals"}</span>
                      )}
                      {r.issue && !usable(r) ? <span className="block text-muted">{r.issue}</span> : null}
                    </td>
                    {(["quantity", "avg_price"] as const).map((k) => (
                      <td key={k} className="p-1 text-right">
                        <input
                          type="number"
                          step="any"
                          min="0"
                          aria-label={`${k} for ${r.symbol}`}
                          value={r[k] ?? ""}
                          onChange={(e) => {
                            const value = e.target.value === "" ? null : Number(e.target.value);
                            setRows((prev) => prev.map((x, j) => (j === i ? { ...x, [k]: value } : x)));
                          }}
                          className={cell}
                        />
                      </td>
                    ))}
                    <td className="p-1 text-right">
                      <button onClick={() => setRows((prev) => prev.filter((_, j) => j !== i))} className="text-xs text-muted hover:text-neg" aria-label={`Remove ${r.symbol}`}>
                        Remove
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
          {error ? <p className="text-sm text-neg" role="alert">{error}</p> : null}
          <div className="flex gap-2">
            <button onClick={() => setStep(0)} className="rounded border border-line px-3 py-1 text-sm hover:bg-raised">
              Back
            </button>
            <button onClick={() => void confirm()} disabled={!keep.length} className="rounded bg-accent px-3 py-1 text-sm text-on-accent disabled:opacity-50">
              Import {keep.length} holding{keep.length === 1 ? "" : "s"}
            </button>
          </div>
        </section>
      ) : null}

      {step === 2 ? (
        <section className="card space-y-3 p-4 text-sm">
          <h2 className="font-semibold">Which alerts do you want?</h2>
          <p className="text-muted">At most two alerts an hour; extra updates are bundled into the next one. You can change this in Alerts later.</p>
          {(rules.data ?? []).map((r: RuleOut) => (
            <label key={r.kind} className="flex items-center gap-2">
              <input
                type="checkbox"
                defaultChecked={r.enabled}
                onChange={(e) => void post(`/alert-rules/${r.kind}`, { enabled: e.target.checked }, "PUT").then(() => qc.invalidateQueries({ queryKey: ["alert-rules"] }))}
              />
              {RULE_TEXT[r.kind] ?? r.kind}
            </label>
          ))}
          <button onClick={() => router.push("/portfolio")} className="rounded bg-accent px-3 py-1 text-on-accent">
            Go to my portfolio
          </button>
        </section>
      ) : null}
      <p className="text-xs text-muted">Holdings are private to your account and can be exported or deleted from Settings.</p>
    </div>
  );
}

export default function OnboardingPage() {
  return (
    <RequireAuth>
      <Wizard />
    </RequireAuth>
  );
}
