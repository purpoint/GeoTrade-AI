# GeoTrade-AI

Indian business news for the NIFTY 50: ingested from RSS, deduplicated, linked to companies, scored for sentiment and event type, and aggregated into per-stock, per-sector and market indices shown next to prices, live.

**Not investment advice.** GeoTrade-AI summarises public news and signals. It never says buy, sell or target.

See [GeoTrade-AI_Implementation_Plan.md](GeoTrade-AI_Implementation_Plan.md) for the full plan. This repository implements **Phase 1** (release v0, the public news product) and **Phase 2** (release v1: accounts, portfolios and personalisation).

## Run it

```bash
cp .env.example .env        # set JWT_SECRET, REFRESH_TOKEN_PEPPER, OPERATOR_EMAIL/OPERATOR_PASSWORD; GROQ_API_KEY + ENABLE_LLM=true for Qwen
docker compose up --build
```

Open http://localhost:3000. The first start migrates the database, loads reference data and a week of sample history (marked "sample"), syncs prices and starts polling the feeds; real headlines appear within a couple of minutes. If a local Postgres already uses port 5432, set `POSTGRES_HOST_PORT` in `.env`.

| URL | What |
| --- | --- |
| http://localhost:3000 | UI (proxies `/api/v1/*` to the backend) |
| http://localhost:8000/api/v1/docs | API docs |
| http://localhost:8000/metrics | API metrics (worker metrics on :9101 inside the network) |
| http://localhost:3000/login | Sign in, sign up, or "Try the demo account" (12 sample holdings) |
| http://localhost:3000/portfolio | Portfolio dashboard; `/onboarding` imports Zerodha, Groww or generic files |
| http://localhost:3000/attention | Needs Attention feed and related stocks to watch |
| http://localhost:3000/alerts | Alert inbox and rules (live bell and toasts) |
| http://localhost:3000/evaluation | Golden-set metrics and backtest |
| http://localhost:3000/admin | Operator console: pipeline health, demo panel, dead letters (sign in with `OPERATOR_EMAIL`) |

## Architecture

```
ui (Next.js) ──/api/v1 + SSE──▶ backend-api (FastAPI) ──┐
                                                       ├──▶ database (PostgreSQL 16, LISTEN/NOTIFY)
           RSS, Yahoo Finance, Groq ◀── backend-worker ┘
```

The backend is one image with two roles (`backend api`, `backend worker`); the api never imports worker code (import-linter). The pipeline is a status column on `articles`: `fetched → deduped → linked → scored → aggregated` (or `duplicate`, `irrelevant`, `dropped`, `dead_letter`), with retries at 10 s, 30 s, 2 min, 10 min and 30 min.

```
services/database   PostgreSQL 16 image, backup/restore, integrity and EXPLAIN scripts
services/backend    FastAPI api + APScheduler worker, Alembic migrations, tests
services/ui         Next.js 15 App Router, Tailwind, TanStack Query, lightweight-charts
packages/shared     openapi.json (the UI's types are generated from it)
data/               reference CSVs, golden set, recorded feed and price fixtures
infra/compose       docker-compose.yml (the root compose.yaml includes it)
docs/perf           query plans
data/golden         golden sets, second-annotator sheet, dedupe pairs
```

## Develop

```bash
# database only (host port 5433 here)
POSTGRES_HOST_PORT=5433 docker compose up -d database

# backend
cd services/backend
uv sync
export DATABASE_URL=postgresql+psycopg://geotrade:geotrade-dev@localhost:5433/geotrade
uv run backend migrate && uv run backend seed --history
uv run backend api --port 8000      # and, in another shell: uv run backend worker
TEST_DATABASE_URL=postgresql+psycopg://geotrade:geotrade-dev@localhost:5433/geotrade_test uv run pytest
uv run backend seed --demo          # demo investor + operator (OPERATOR_EMAIL / OPERATOR_PASSWORD)
uv run backend evaluate             # golden-v1 report into data/golden/reports/ and the evaluation page
uv run backend backtest             # news signal vs next-session return
uv run pytest -m contract           # Schemathesis: every operation, no server errors (slow)

# ui
cd services/ui
npm install
BACKEND_URL=http://localhost:8000 npm run dev
npm test && npm run lint && npm run typecheck
# against a running stack; the operator journey needs E2E_OPERATOR_EMAIL / E2E_OPERATOR_PASSWORD
BASE_URL=http://localhost:3000 npm run e2e
```

After changing an API schema: `uv run backend openapi --out ../../packages/shared/openapi.json`, then `npm run gen:api` in `services/ui`. CI fails if either file is out of date.

## Scoring and indices

- **Sentiment**: Qwen3-32B on Groq when `ENABLE_LLM=true` (batched, cached, daily budget in `llm_usage`); otherwise, or when Groq fails, the keyword scorer. Fallback scores are re-scored nightly.
- **Events**: priority-ordered rules; severity is discounted for hedged headlines and raised for large moves.
- **Index**: impact = score × severity × link confidence (secondary links at half weight), decayed with a 12-hour half-life over 72 hours, squashed with `100·tanh(x/1.5)`. Sector and market indices are market-cap weighted.

## Accounts and privacy

- Email and password (Argon2id). A 15-minute access token and a rotating refresh token live in HTTP-only cookies; reusing an old refresh token signs out that whole login. Mutations need the CSRF header the UI sends automatically.
- Holdings are parsed from the uploaded file only (nothing is linked to a broker) and shown as a preview that expires after 30 minutes unless confirmed.
- Settings → Data exports everything stored about you as CSV, and "Delete everything" removes every row tied to the account.
- Alerts: severe negative news, a sharp 24-hour sentiment fall, and concentration (25% one stock, 40% one sector). At most two per hour; extra updates are bundled into the next one; quiet hours keep alerts without pushing them live.

## Phase 1 status

Baseline on golden-v0 (150 headlines): linking P 1.00 / R 0.98; keyword sentiment macro F1 0.66; event accuracy 0.65. Qwen is evaluated when a Groq key is configured.

Known limits:
- The golden set was written and labelled by the project team, so the linking score is optimistic. Phase 2 adds a second annotator.
- Moneycontrol's public RSS has served April 2024 items for a long time. The source stays enabled for health monitoring, and the 72-hour age filter drops its items.
- The first-seen article stays canonical for its cluster.
- The SSE replay buffer and response cache live in the API process (one replica). Redis is deferred until Phase 3 load tests show it is needed.
- Not yet built: the separate fixture mock server (the seeded API serves the same purpose) and the article drawer (stories open as pages).

## Phase 2 status

On golden-v1 (300 headlines): linking P 1.00 / R 0.99, keyword sentiment macro F1 0.65, event accuracy 0.58, dedupe precision 0.92 / recall 0.60 on 40 labelled pairs.

Known limits:
- Annotator agreement is pending until someone fills `data/golden/golden-v1-annotator2.csv`; until then scores are optimistic.
- The backtest needs real history: it reports "insufficient data" until at least 30 stock-sessions have both real news and a next-session price (sample history is excluded on purpose).
- Rate limits, the response cache and SSE connection caps are per API process (one replica). Redis is the documented upgrade if the API scales out.
- `X-Forwarded-For` is trusted for per-IP limits because the UI proxy sets it; restrict that if the API is exposed directly.

## Vocabulary rules

The product never uses "buy", "sell", "target price", "will rise" or "recommended". Movers are "rising" or "falling sentiment".
