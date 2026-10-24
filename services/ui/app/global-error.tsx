"use client";

/** Last-resort boundary when the root layout itself fails; it must render its own html and body. */
export default function GlobalError({ reset }: { error: Error; reset: () => void }) {
  return (
    <html lang="en">
      <body style={{ fontFamily: "system-ui, sans-serif", padding: 32, textAlign: "center" }}>
        <h1 style={{ fontSize: 18 }}>GeoTrade-AI could not load</h1>
        <p>Please try again in a moment.</p>
        <button onClick={reset}>Try again</button>
      </body>
    </html>
  );
}
