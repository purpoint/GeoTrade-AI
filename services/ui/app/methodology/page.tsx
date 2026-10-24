export const metadata = { title: "Methodology" };

export default function MethodologyPage() {
  return (
    <article className="prose-sm mx-auto max-w-3xl space-y-4 text-sm leading-relaxed">
      <h1 className="text-xl font-semibold">How GeoTrade-AI works</h1>
      <p>
        GeoTrade-AI reads public business news, links each story to NIFTY 50 companies, scores its tone and event type, and turns
        that into indices from -100 to +100. It shows <strong>signals, not advice</strong>: it never says buy, sell or target.
      </p>
      <h2 className="text-base font-semibold">Pipeline</h2>
      <ol className="list-decimal space-y-1 pl-5">
        <li><strong>Fetch</strong>: RSS feeds from Economic Times, Mint, Business Standard and Moneycontrol, polled about every minute.</li>
        <li><strong>Deduplicate</strong>: identical links, identical normalised titles within 48 hours, and near-identical titles about the same company within 6 hours are grouped into one story.</li>
        <li><strong>Link</strong>: company names and aliases are matched with rules for ambiguous names (for example “Reliance Power” is not Reliance Industries). At most three companies are primary per story.</li>
        <li><strong>Score</strong>: Qwen 3.8 27B (via Groq) labels tone when enabled; a keyword model is the fallback and the baseline. Rules assign an event type and severity, discounted for hedged headlines (“may”, “reportedly”).</li>
        <li><strong>Aggregate</strong>: each story’s impact is tone × severity × link confidence, decayed with a 12-hour half-life and squashed to -100..100 with tanh. Sector and market indices are market-cap weighted.</li>
      </ol>
      <h2 className="text-base font-semibold">Limits</h2>
      <ul className="list-disc space-y-1 pl-5">
        <li>Sentiment is model output and can be wrong; check the story and the “How we scored this” box.</li>
        <li>News sentiment has weak predictive power for returns. Past behaviour is not a guide.</li>
        <li>Prices come from Yahoo Finance and may be delayed. Items marked “sample” are simulated for demos.</li>
      </ul>
      <h2 className="text-base font-semibold">Vocabulary rules</h2>
      <p>The product never uses “buy”, “sell”, “target price”, “will rise” or “recommended”. Movers are described as rising or falling sentiment.</p>
    </article>
  );
}
