"use client";

import { useState } from "react";
import { NewsFeed } from "@/components/NewsFeed";
import { useSectors, useSources, useStocks, type NewsFilters } from "@/lib/api/hooks";

const EVENTS = ["earnings", "guidance", "deal", "order_win", "regulatory", "legal", "management", "rating", "dividend", "capital", "macro", "operations"];

function Select({ label, value, onChange, options }: { label: string; value?: string; onChange: (v: string) => void; options: { value: string; label: string }[] }) {
  return (
    <label className="flex flex-col gap-1 text-xs text-muted">
      {label}
      <select value={value ?? ""} onChange={(e) => onChange(e.target.value)} className="rounded border border-line bg-surface px-2 py-1 text-sm text-fg">
        <option value="">Any</option>
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </label>
  );
}

export default function NewsPage() {
  const [f, setF] = useState<NewsFilters>({});
  const [q, setQ] = useState("");
  const { data: stocks } = useStocks();
  const { data: sectors } = useSectors();
  const { data: sources } = useSources();
  const set = (k: keyof NewsFilters) => (v: string) => setF((prev) => ({ ...prev, [k]: v || undefined }));
  return (
    <div className="space-y-3">
      <h1 className="text-xl font-semibold">News explorer</h1>
      <form
        className="card grid grid-cols-2 gap-2 p-3 sm:grid-cols-4 lg:grid-cols-8"
        onSubmit={(e) => {
          e.preventDefault();
          set("q")(q);
        }}
      >
        <label className="col-span-2 flex flex-col gap-1 text-xs text-muted">
          Search headlines
          <input value={q} onChange={(e) => setQ(e.target.value)} onBlur={() => set("q")(q)} className="rounded border border-line bg-surface px-2 py-1 text-sm text-fg" />
        </label>
        <Select label="Stock" value={f.ticker} onChange={set("ticker")} options={(stocks ?? []).map((s) => ({ value: s.ticker, label: s.ticker }))} />
        <Select label="Sector" value={f.sector} onChange={set("sector")} options={(sectors ?? []).map((s) => ({ value: s.id, label: s.name }))} />
        <Select label="Sentiment" value={f.sentiment} onChange={set("sentiment")} options={["positive", "neutral", "negative"].map((v) => ({ value: v, label: v }))} />
        <Select label="Event" value={f.event} onChange={set("event")} options={EVENTS.map((v) => ({ value: v, label: v.replace("_", " ") }))} />
        <Select label="Source" value={f.source} onChange={set("source")} options={[...(sources ?? []).map((s) => ({ value: s.id, label: s.name })), { value: "demo", label: "Demo / sample" }]} />
        <label className="flex flex-col gap-1 text-xs text-muted">
          From
          <input type="date" onChange={(e) => set("from")(e.target.value ? `${e.target.value}T00:00:00+05:30` : "")} className="rounded border border-line bg-surface px-2 py-1 text-sm text-fg" />
        </label>
      </form>
      <NewsFeed filters={f} />
    </div>
  );
}
