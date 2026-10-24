"use client";

import { useEffect, useState } from "react";
import { Toasts } from "@/components/Toasts";
import { useOverview } from "@/lib/api/hooks";
import { useLive } from "@/lib/sse/live";
import { CommandPalette } from "./CommandPalette";
import { Footer } from "./Footer";
import { FreshnessPill } from "./FreshnessPill";
import { Sidebar } from "./Sidebar";
import { ThemeToggle, useTheme } from "./ThemeToggle";
import { TickerTape } from "./TickerTape";

const typing = (el: EventTarget | null) =>
  el instanceof HTMLElement && (el.isContentEditable || ["INPUT", "TEXTAREA", "SELECT"].includes(el.tagName));

export function AppShell({ children }: { children: React.ReactNode }) {
  const { status } = useLive();
  const [palette, setPalette] = useState(false);
  const { theme, toggle } = useTheme();
  const { data: overview } = useOverview();

  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (typing(e.target) || e.metaKey || e.ctrlKey || e.altKey) return;
      if (e.key === "/") {
        e.preventDefault();
        setPalette(true);
      } else if (e.key === "t") {
        toggle();
      }
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [toggle]);

  return (
    <div className="flex min-h-screen">
      <a href="#main" className="sr-only focus:not-sr-only focus:absolute focus:z-50 focus:bg-surface focus:p-2">
        Skip to content
      </a>
      <Sidebar />
      <div className="flex min-w-0 flex-1 flex-col">
        <header className="sticky top-0 z-30 bg-bg/95 backdrop-blur">
          <div className="flex h-14 items-center gap-3 border-b border-line px-4">
            <button
              onClick={() => setPalette(true)}
              className="flex min-w-0 flex-1 items-center justify-between rounded-md border border-line bg-surface px-3 py-1.5 text-left text-sm text-muted sm:max-w-sm"
              aria-label="Search (shortcut /)"
            >
              <span className="truncate">Search stocks…</span>
              <kbd className="num rounded border border-line px-1 text-xs">/</kbd>
            </button>
            <div className="ml-auto flex items-center gap-2">
              <FreshnessPill status={status} lastArticleAt={overview?.freshness.last_article_at} />
              <ThemeToggle theme={theme} toggle={toggle} />
            </div>
          </div>
          <TickerTape />
        </header>
        {status === "offline" ? (
          <p className="bg-neg/10 px-4 py-1 text-center text-xs text-neg" role="alert">
            You are offline. Showing the last data loaded; it will refresh when the connection returns.
          </p>
        ) : null}
        <main id="main" className="mx-auto w-full max-w-7xl flex-1 px-4 py-4">
          {children}
        </main>
        <Footer />
      </div>
      <CommandPalette open={palette} onClose={() => setPalette(false)} />
      <Toasts />
    </div>
  );
}
