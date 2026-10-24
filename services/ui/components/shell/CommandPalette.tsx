"use client";

import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import { useStocks } from "@/lib/api/hooks";
import { NAV } from "./nav";

type Item = { label: string; hint: string; href: string };

export function CommandPalette({ open, onClose }: { open: boolean; onClose: () => void }) {
  const router = useRouter();
  const { data: stocks } = useStocks();
  const [q, setQ] = useState("");
  const [cursor, setCursor] = useState(0);
  const input = useRef<HTMLInputElement>(null);

  const items = useMemo<Item[]>(() => {
    const all: Item[] = [
      ...NAV.map((n) => ({ label: n.label, hint: "page", href: n.href })),
      ...(stocks ?? []).map((s) => ({ label: `${s.ticker} · ${s.name}`, hint: s.sector_name, href: `/stocks/${encodeURIComponent(s.ticker)}` })),
    ];
    const needle = q.trim().toLowerCase();
    return (needle ? all.filter((i) => i.label.toLowerCase().includes(needle)) : all).slice(0, 12);
  }, [q, stocks]);

  useEffect(() => {
    if (open) {
      setQ("");
      setCursor(0);
      setTimeout(() => input.current?.focus(), 0);
    }
  }, [open]);

  if (!open) return null;
  const go = (item?: Item) => {
    if (!item) return;
    router.push(item.href);
    onClose();
  };
  return (
    <div className="fixed inset-0 z-50 flex items-start justify-center bg-black/40 p-4 pt-24" onClick={onClose}>
      <div role="dialog" aria-modal="true" aria-label="Search stocks and pages" className="card w-full max-w-lg overflow-hidden shadow-xl" onClick={(e) => e.stopPropagation()}>
        <input
          ref={input}
          value={q}
          onChange={(e) => {
            setQ(e.target.value);
            setCursor(0);
          }}
          onKeyDown={(e) => {
            if (e.key === "Escape") onClose();
            if (e.key === "ArrowDown") setCursor((c) => Math.min(c + 1, items.length - 1));
            if (e.key === "ArrowUp") setCursor((c) => Math.max(c - 1, 0));
            if (e.key === "Enter") go(items[cursor]);
          }}
          placeholder="Search a stock, alias or page…"
          className="w-full border-b border-line bg-transparent px-4 py-3 text-sm outline-none"
          aria-controls="palette-results"
        />
        <ul id="palette-results" role="listbox" className="max-h-80 overflow-y-auto py-1">
          {items.map((item, i) => (
            <li
              key={item.href}
              role="option"
              aria-selected={i === cursor}
              onMouseEnter={() => setCursor(i)}
              onClick={() => go(item)}
              className={`flex cursor-pointer justify-between px-4 py-2 text-sm ${i === cursor ? "bg-accent/10" : ""}`}
            >
              <span>{item.label}</span>
              <span className="text-xs text-muted">{item.hint}</span>
            </li>
          ))}
          {!items.length ? <li className="px-4 py-3 text-sm text-muted">No matches</li> : null}
        </ul>
      </div>
    </div>
  );
}
