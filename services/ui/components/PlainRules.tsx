"use client";

import { useQueryClient } from "@tanstack/react-query";
import { useState } from "react";
import { post, type ParsedRule } from "@/lib/api/client";
import { useCustomRules } from "@/lib/api/hooks";

const EXAMPLES = ["Tell me if any bank I hold gets RBI news", "Negative earnings news on INFY or TCS", "Any order wins on my watchlist"];

/** Plain-English alert rules (P3-BE-13): type a sentence, check the parsed rule, then save it. */
export function PlainRules() {
  const qc = useQueryClient();
  const rules = useCustomRules();
  const [text, setText] = useState("");
  const [parsed, setParsed] = useState<ParsedRule | null>(null);
  const [msg, setMsg] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const run = async (fn: () => Promise<unknown>) => {
    setBusy(true);
    setMsg(null);
    try {
      await fn();
    } catch (e) {
      setMsg(e instanceof Error ? e.message : "Something went wrong");
    } finally {
      setBusy(false);
    }
  };
  const refresh = () => qc.invalidateQueries({ queryKey: ["custom-rules"] });
  return (
    <section className="card space-y-3 p-4 text-sm">
      <h2 className="font-medium">Your own rules, in plain English</h2>
      <form
        className="flex flex-wrap gap-2"
        onSubmit={(e) => {
          e.preventDefault();
          void run(async () => setParsed(await post<ParsedRule>("/alert-rules/parse", { text })));
        }}
      >
        <label className="sr-only" htmlFor="rule-text">
          Describe an alert
        </label>
        <input
          id="rule-text"
          value={text}
          onChange={(e) => (setText(e.target.value), setParsed(null))}
          placeholder={EXAMPLES[0]}
          minLength={5}
          maxLength={300}
          required
          className="min-w-0 flex-1 rounded border border-line bg-surface px-2 py-1.5"
        />
        <button disabled={busy} className="rounded border border-line px-3 py-1 hover:bg-raised disabled:opacity-50">
          Check
        </button>
      </form>
      <p className="text-xs text-muted">
        Try: {EXAMPLES.map((x, i) => (
          <button key={x} type="button" onClick={() => (setText(x), setParsed(null))} className="text-accent hover:underline">
            {x}
            {i < EXAMPLES.length - 1 ? "; " : ""}
          </button>
        ))}
      </p>
      {parsed ? (
        <div className="space-y-2 rounded bg-raised p-3" role="status">
          <p>
            <span className="text-xs text-muted">We understood: </span>
            {parsed.summary}
          </p>
          <p className="text-xs text-muted">Read by {parsed.parser === "llm" ? "Qwen" : "the keyword parser"}. Only this rule decides what alerts you; the model never does.</p>
          <div className="flex gap-2">
            <button
              disabled={busy}
              onClick={() =>
                void run(async () => {
                  await post("/alert-rules/custom", { text, params: parsed.params });
                  setParsed(null);
                  setText("");
                  await refresh();
                  setMsg("Rule saved");
                })
              }
              className="rounded bg-accent px-3 py-1 text-on-accent disabled:opacity-50"
            >
              Save this rule
            </button>
            <button onClick={() => setParsed(null)} className="rounded border border-line px-3 py-1 hover:bg-surface">
              Not right
            </button>
          </div>
        </div>
      ) : null}
      {msg ? <p className="text-xs text-muted" role="status">{msg}</p> : null}
      <ul className="space-y-2">
        {(rules.data ?? []).map((r) => (
          <li key={r.id} className="flex items-start justify-between gap-2 border-t border-line pt-2">
            <div>
              <p>&ldquo;{r.text}&rdquo;</p>
              <p className="text-xs text-muted">{r.summary}</p>
            </div>
            <div className="flex shrink-0 items-center gap-2">
              <input
                type="checkbox"
                checked={r.enabled}
                aria-label={`Enable rule: ${r.text}`}
                onChange={(e) => void run(async () => (await post(`/alert-rules/custom/${r.id}`, { enabled: e.target.checked }, "PATCH"), await refresh()))}
              />
              <button onClick={() => void run(async () => (await post(`/alert-rules/custom/${r.id}`, undefined, "DELETE"), await refresh()))} className="text-xs text-neg hover:underline">
                Delete
              </button>
            </div>
          </li>
        ))}
      </ul>
    </section>
  );
}
