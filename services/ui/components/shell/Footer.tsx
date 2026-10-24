export const DISCLAIMER =
  "GeoTrade-AI summarises public news and automated signals. It is not investment advice and makes no buy, sell or price-target recommendations.";

export function Footer() {
  return (
    <footer className="mt-8 border-t border-line px-4 py-4 pb-20 text-xs text-muted md:pb-4">
      <p>{DISCLAIMER}</p>
      <p className="mt-1">Prices may be delayed. Sentiment is model output and can be wrong.</p>
    </footer>
  );
}
