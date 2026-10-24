import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { render, screen } from "@testing-library/react";
import { SpikeBadge } from "@/components/Extras";
import { Gauge } from "@/components/Gauge";
import { NewsCard } from "@/components/NewsCard";
import { SentimentBadge } from "@/components/SentimentBadge";
import type { NewsItem } from "@/lib/api/client";
import { fmtIndex, timeAgo, tone } from "@/lib/format";

const wrap = (ui: React.ReactNode) => render(<QueryClientProvider client={new QueryClient()}>{ui}</QueryClientProvider>);

const item: NewsItem = {
  id: "01a16ef0-a466-7e58-9f3c-9f41cbde23cf",
  title: "Infosys bags $1.5 billion deal",
  url: "https://example.com/a",
  summary: null,
  source: { id: "et", name: "Economic Times Markets" },
  published_at: new Date(Date.now() - 5 * 60_000).toISOString(),
  time_estimated: false,
  tickers: [{ ticker: "INFY", is_primary: true }],
  sectors: ["it"],
  sentiment: { label: "positive", score: 0.7, confidence: 0.8 },
  event: { type: "order_win", severity: 0.5, hedged: false },
  cluster: { id: null, size: 3, source_count: 2 },
  credibility: { score: 0.8, hedge_score: 0, unconfirmed: false },
  model_version: "keyword-v1",
  is_simulated: true,
};

describe("SentimentBadge", () => {
  it("shows an icon and a text label, not colour alone", () => {
    render(<SentimentBadge label="negative" />);
    expect(screen.getByText("Negative")).toBeInTheDocument();
    expect(screen.getByLabelText("Negative sentiment")).toHaveTextContent("▼");
  });

  it("derives tone from an index with a dead band", () => {
    render(<SentimentBadge index={3} />);
    expect(screen.getByLabelText("Neutral sentiment +3")).toBeInTheDocument();
  });
});

describe("NewsCard", () => {
  it("renders cluster size, sample flag, event and ticker links", () => {
    wrap(<NewsCard item={item} />);
    expect(screen.getByRole("link", { name: item.title })).toHaveAttribute("href", `/news/${item.id}`);
    expect(screen.getByText("+2 similar")).toBeInTheDocument();
    expect(screen.getByText("sample")).toBeInTheDocument();
    expect(screen.getByText("order win")).toBeInTheDocument();
    expect(screen.getByRole("link", { name: "INFY" })).toHaveAttribute("href", "/stocks/INFY");
    expect(screen.getByText("5m ago")).toBeInTheDocument();
  });
});

describe("Gauge and format", () => {
  it("labels the gauge for screen readers", () => {
    render(<Gauge value={-42} label="Market" />);
    expect(screen.getByRole("img", { name: "Market: -42 on a scale of -100 to 100" })).toBeInTheDocument();
  });

  it("formats values", () => {
    expect(fmtIndex(12.4)).toBe("+12");
    expect(fmtIndex(-0.3)).toBe("0");
    expect(tone(-6)).toBe("negative");
    expect(timeAgo(new Date(Date.now() - 7200_000).toISOString())).toBe("2h ago");
  });
});

describe("Phase 3 extras", () => {
  it("flags single-source hedged stories and leaves others alone", () => {
    wrap(<NewsCard item={{ ...item, credibility: { score: 0.25, hedge_score: 0.7, unconfirmed: true } }} />);
    expect(screen.getByText("single source, unconfirmed")).toBeInTheDocument();
  });
  it("shows no chip for confirmed stories", () => {
    wrap(<NewsCard item={item} />);
    expect(screen.queryByText("single source, unconfirmed")).toBeNull();
  });
  it("labels a news spike in words", () => {
    render(<SpikeBadge spike={{ ticker: "INFY", detected_at: "2026-10-22T10:00:00Z", z_score: 4.2, n_stories: 9, baseline_mean: 1.5 }} />);
    expect(screen.getByText("news spike")).toBeInTheDocument();
  });
});
