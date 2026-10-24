import Link from "next/link";
import type { NewsItem, Spike } from "@/lib/api/client";

/** "Single source, unconfirmed" chip for hedged stories only one outlet carries (P3-BE-12). */
export function CredibilityChip({ credibility }: { credibility: NewsItem["credibility"] }) {
  if (!credibility?.unconfirmed) return null;
  return (
    <span
      className="inline-flex items-center rounded border border-warn/40 px-1.5 py-0.5 text-xs text-warn"
      title={`Credibility ${Math.round(credibility.score * 100)}%: one source and hedged wording (hedge score ${credibility.hedge_score.toFixed(2)}). Severity is discounted.`}
    >
      single source, unconfirmed
    </span>
  );
}

/** Badge for a stock whose 24-hour story count is far above its usual level (P3-BE-08). */
export function SpikeBadge({ spike }: { spike: Spike | null | undefined }) {
  if (!spike) return null;
  return (
    <span
      className="inline-flex items-center gap-1 rounded bg-accent/10 px-1.5 py-0.5 text-xs text-accent"
      title={`${spike.n_stories} stories in 24h against a usual ${spike.baseline_mean.toFixed(1)} a day (z = ${spike.z_score.toFixed(1)})`}
    >
      <span aria-hidden>▲</span> news spike
    </span>
  );
}

export function SpikeList({ spikes }: { spikes: Spike[] }) {
  if (!spikes.length) return null;
  return (
    <section className="card p-4">
      <h2 className="mb-2 text-sm font-semibold">Unusual news coverage (24h)</h2>
      <ul className="flex flex-wrap gap-2 text-sm">
        {spikes.map((s) => (
          <li key={s.ticker}>
            <Link href={`/stocks/${encodeURIComponent(s.ticker)}`} className="num rounded border border-line px-2 py-1 hover:border-accent" title={`z = ${s.z_score.toFixed(1)}`}>
              {s.ticker} <span className="text-xs text-muted">{s.n_stories} stories, usually {s.baseline_mean.toFixed(1)}</span>
            </Link>
          </li>
        ))}
      </ul>
    </section>
  );
}
