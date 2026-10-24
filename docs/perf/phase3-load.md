# Phase 3 load and soak results (P3-BE-09)

Measured on 25 Oct 2026 against the local Docker Compose stack (Apple silicon laptop, 10 cores,
one API process, seeded data plus live feeds). Re-run the same scripts on the Railway host for the G3
gate; the laptop numbers are the "before deploy" baseline.

| Test | Script | Result | Target |
| --- | --- | --- | --- |
| Cached reads (`/market/overview`, `/sectors`), 20 VUs for 45 s | `docs/perf/k6/api.js` | p95 9.2 ms, p50 6.3 ms | p95 < 100 ms |
| Uncached stock summary (`/stocks/{t}`, cache-busted), 20 req/s | `docs/perf/k6/api.js` | p95 82.6 ms, p50 48.9 ms | p95 < 400 ms |
| Errors across 122,219 requests (2,715 req/s) | `docs/perf/k6/api.js` | 0 | < 1% |
| 200 concurrent SSE clients for 40 s | `docs/perf/k6/sse.js` | `sse_clients` reached 200; API 117 MiB RSS, under 1% CPU | 200 clients |
| Pipeline flood, 500 articles through every stage | `backend flood -n 500` | 3.9 s, 130 articles/s (keyword scorer) | well above the feed rate |

Notes

- The first API run returned 99.7% `429`s: the per-IP rate limit (300 a minute) works. The scripts now
  send a distinct `X-Forwarded-For` per virtual user, which the API trusts because the UI proxy sets it.
  SSE is capped at 10 connections per IP for the same reason.
- With `ENABLE_LLM=true` the pipeline is bound by the Groq budget (5 requests a minute, 10 headlines
  each), not by the database; anything over budget is keyword-scored and re-scored overnight.
- Redis stays deferred (ADR-12): one API process held the cached and SSE targets with large headroom.

Run them

```bash
docker run --rm -i -e BASE_URL=http://host.docker.internal:8000 grafana/k6:1.3.0 run - < docs/perf/k6/api.js
docker run --rm -i -e BASE_URL=http://host.docker.internal:8000 grafana/k6:1.3.0 run - < docs/perf/k6/sse.js
DATABASE_URL=postgresql+psycopg://geotrade:geotrade-dev@localhost:5433/geotrade_test uv run backend flood -n 500
```

Run `flood` against a scratch database: it writes simulated (sample-marked) stories timestamped now.
