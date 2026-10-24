"use client";

import { useEffect, useRef, useState } from "react";
import type { Candle, EventMarker, SeriesPoint } from "@/lib/api/client";
import { fmtIndex, fmtIst, fmtPrice } from "@/lib/format";

type Props = { candles: Candle[]; sentiment: SeriesPoint[]; events: EventMarker[]; height?: number };

const css = (name: string) => `rgb(${getComputedStyle(document.documentElement).getPropertyValue(`--${name}`).trim().split(" ").join(",")})`;
const secs = (iso: string) => Math.floor(new Date(iso).getTime() / 1000);

/** Price candles on top, sentiment histogram on a second pane sharing the time scale (so the
 *  crosshair is synced), event markers on the candles, and an accessible table view. */
export function PriceSentimentChart({ candles, sentiment, events, height = 420 }: Props) {
  const box = useRef<HTMLDivElement>(null);
  const [asTable, setAsTable] = useState(false);
  const [theme, setTheme] = useState<string | undefined>();

  useEffect(() => {
    const obs = new MutationObserver(() => setTheme(document.documentElement.dataset.theme));
    obs.observe(document.documentElement, { attributes: true, attributeFilter: ["data-theme"] });
    return () => obs.disconnect();
  }, []);

  useEffect(() => {
    if (asTable || !box.current) return;
    let disposed = false;
    let cleanup = () => {};
    import("lightweight-charts").then(({ createChart, CandlestickSeries, HistogramSeries, createSeriesMarkers }) => {
      if (disposed || !box.current) return;
      const chart = createChart(box.current, {
        height,
        autoSize: true,
        layout: { background: { color: "transparent" }, textColor: css("muted"), fontFamily: "var(--font-sans)" },
        grid: { vertLines: { color: css("line") }, horzLines: { color: css("line") } },
        rightPriceScale: { borderColor: css("line") },
        timeScale: { borderColor: css("line"), timeVisible: true },
      });
      const price = chart.addSeries(CandlestickSeries, {
        upColor: css("pos"), downColor: css("neg"), wickUpColor: css("pos"), wickDownColor: css("neg"), borderVisible: false,
      });
      price.setData(
        candles.map((c) => ({ time: secs(c.ts) as never, open: c.open, high: c.high, low: c.low, close: c.close })),
      );
      const sent = chart.addSeries(
        HistogramSeries,
        { priceFormat: { type: "custom", formatter: (v: number) => fmtIndex(v) }, priceScaleId: "sentiment" },
        1,
      );
      sent.setData(
        sentiment.map((p) => ({ time: secs(p.ts) as never, value: p.index, color: p.index >= 0 ? css("pos") : css("neg") })),
      );
      chart.panes()[1]?.setHeight(Math.round(height * 0.3));
      const candleDays = new Set(candles.map((c) => c.ts.slice(0, 10)));
      createSeriesMarkers(
        price,
        events
          .filter((e) => candleDays.has(e.published_at.slice(0, 10)))
          .map((e) => ({
            time: secs(`${e.published_at.slice(0, 10)}T00:00:00Z`) as never,
            position: e.label === "negative" ? ("aboveBar" as const) : ("belowBar" as const),
            color: e.label === "negative" ? css("neg") : css("pos"),
            shape: e.label === "negative" ? ("arrowDown" as const) : ("arrowUp" as const),
            text: e.event_type.replace("_", " "),
          })),
      );
      chart.timeScale().fitContent();
      cleanup = () => chart.remove();
    });
    return () => {
      disposed = true;
      cleanup();
    };
  }, [candles, sentiment, events, height, asTable, theme]);

  return (
    <div>
      <div className="mb-2 flex justify-end">
        <button onClick={() => setAsTable((v) => !v)} className="rounded border border-line px-2 py-1 text-xs hover:bg-raised" aria-pressed={asTable}>
          {asTable ? "View as chart" : "View as table"}
        </button>
      </div>
      {asTable ? (
        <div className="max-h-96 overflow-auto">
          <table className="num w-full text-xs">
            <caption className="sr-only">Daily prices and sentiment</caption>
            <thead className="sticky top-0 bg-surface text-left text-muted">
              <tr>
                <th className="p-1">Date</th>
                <th className="p-1">Close</th>
                <th className="p-1">Sentiment</th>
              </tr>
            </thead>
            <tbody>
              {[...candles].reverse().map((c) => {
                const s = sentiment.filter((p) => p.ts.slice(0, 10) <= c.ts.slice(0, 10)).at(-1);
                return (
                  <tr key={c.ts} className="border-t border-line">
                    <td className="p-1">{fmtIst(c.ts)}</td>
                    <td className="p-1">{fmtPrice(c.close)}</td>
                    <td className="p-1">{s ? fmtIndex(s.index) : "—"}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        </div>
      ) : (
        <div ref={box} style={{ height }} role="figure" aria-label="Price candles with a news sentiment histogram below" />
      )}
    </div>
  );
}
