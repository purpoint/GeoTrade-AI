# GeoTrade-AI: Implementation Plan (v2)

*Prepared from design documents 01 to 06 (written under the working name NiftyPulse; the product is now GeoTrade-AI). Version 2 applies the decisions confirmed by the project owner (section 2.4). Documents 07 and 08 are not used: there is no separate AI/ML design layer, and sentiment scoring is done by Qwen3-32B through Groq's free API.*

---

## 0. How to read this plan

| Section | What it covers |
| --- | --- |
| 1 | Executive summary |
| 2 | Decisions that reconcile the request with the existing design (read this first) |
| 3 | Target architecture with the three services |
| 4 | Phase overview, timeline and team split |
| 5 to 7 | Phase 1, 2 and 3 in detail, broken down per service |
| 8 | Daily email digest: full feature design |
| 9 | Cross-cutting: testing, CI/CD, observability, security |
| 10 | Free hosting recommendations |
| 11 | Further AI features to consider |
| 12 | Risks, open questions and appendices |

Task IDs follow the pattern `P<phase>-<service>-<nn>`, where service is `UI`, `BE` (backend) or `DB` (database). Use them as ticket keys.

---

## 1. Executive summary

GeoTrade-AI ingests Indian business news, deduplicates it, links it to NIFTY 50 companies, scores sentiment and event type, aggregates it into per-stock and per-sector indices, overlays it on prices, and personalises everything to a user's portfolio.

This is a college final-year project. The build is split into **three services** and **three phases of about four weeks each**. There is one developer: Claude writes the code, tests, configuration and setup guides; the project owner runs the code, creates the accounts (Render, Railway, Brevo, Groq), holds the API keys and deploys. Week numbers are indicative and depend on how quickly each slice is run and reviewed.

| Phase | Theme | Outcome |
| --- | --- | --- |
| Phase 1 (weeks 1 to 4) | Foundation and core news pipeline | Live public product: overview, stock pages, sectors, news explorer, real-time feed. Matches release v0 in the overview. |
| Phase 2 (weeks 5 to 8) | Users, portfolios and personalisation | Accounts, portfolio import, Needs Attention feed, related stocks, alerts, evaluation page, operator panels. Matches release v1. |
| Phase 3 (weeks 9 to 12) | Daily email digest, AI extras, hardening and deployment | Daily and weekly Pulse emails, Qwen explanations, news-spike detection, rumour and credibility scoring, plain-English alert rules, testing, deployment on Render and Railway. |

---

## 2. Key decisions (read first)

### 2.1 Mapping the existing design onto three services

The HLD describes five containers (web, api, worker, postgres, redis). The request is three services. They map cleanly:

| Requested service | Contains | Notes |
| --- | --- | --- |
| **1. UI service** | Next.js app (SSR pages, charts, SSE client) | Talks only to the backend over HTTPS JSON and SSE. Never touches the database. |
| **2. Backend service** | One Python codebase, one Docker image, **two process roles**: `api` (FastAPI) and `worker` (APScheduler pipeline, ML, digest sender) | Same image, different entrypoint (`backend api` / `backend worker`). They share models, repositories and config but the API never imports pipeline stages (HLD section 13 still holds). In Compose these run as two containers of the same service. |
| **3. Database service** | PostgreSQL 16 with `pg_trgm` and `citext` | Owns durability, LISTEN/NOTIFY event channel, backups. Schema migrations are authored in the backend repo (Alembic) but are run by a one-shot `migrate` job against this service. |

**Redis is deferred.** The HLD already allows a Redis-free first release: Postgres `LISTEN/NOTIFY` wakes the SSE stream, an in-process TTL cache serves hot reads, and the status-column pipeline needs no queue. This keeps the system at exactly three services. Redis becomes a fourth service only if a Phase 3 load test shows the API cache or the single worker saturating (HLD section 10, stage 2).

**Why the worker lives inside the backend service and not on its own:** it shares 80 percent of its code with the API (models, repositories, config, reference data), and splitting it would mean a fourth deployable with duplicated dependencies. Keeping it as a second process role preserves the ability to scale it separately later without a rewrite.

**No local ML models.** Sentiment, event hints and explanations come from Qwen3-32B called through Groq's OpenAI-compatible API, with the deterministic keyword scorer as the fallback. There is no PyTorch, no FinBERT and no embedding model in the image, so the worker needs only about 250 to 350 MB of RAM. This is what makes the Railway trial (1 GB per service) workable.

### 2.2 The "stocks to buy and sell" email conflicts with the product's own compliance rules

Document 01, section 3, is explicit: in India, giving buy or sell recommendations to the public generally requires SEBI registration as a Research Analyst or Investment Adviser, and the product's vocabulary rules ban Buy, Sell and Recommended. An email that says "buy X, sell Y" would be the single most regulated artefact in the product, and it would be pushed into inboxes rather than viewed on request.

**What this plan builds instead (same user value, compliant framing):**

| Requested | Built as | Source of the signal |
| --- | --- | --- |
| Insight into their stocks | **Your holdings today**: portfolio sentiment, biggest movers, events, what changed since yesterday | Portfolio exposure, attention score |
| Stocks to sell | **Holdings to review**: holdings carrying risk flags (negative shift, severe event, concentration) with the reason and the stories behind it | Risk flags (LLD 13.3) |
| Stocks to buy | **Positive momentum to watch**: stocks not held, related to the user's holdings, with rising sentiment and enough independent coverage | Related stocks (LLD 13.4), extended in section 8.5 |

Every section of the email shows *why* (stories, sources, numbers), carries the disclaimer, and never uses buy, sell, target or will-rise language. The wording lives in a single vocabulary file so it can only change with a deliberate, reviewed commit.

If the business later wants explicit buy and sell calls, that is a regulatory decision, not an engineering one: it needs SEBI registration and legal sign-off first. The data model in section 8 does not need to change for that, only the copy. Get advice from a securities lawyer before any public launch either way, because even "momentum to watch" emails sent at scale can attract scrutiny.

### 2.3 Other assumptions

1. One developer (Claude) builds all three services; work is sequenced so each week ends with something runnable locally.
2. Golden set: Phase 1 targets 150 labelled headlines, Phase 2 grows it to 300. It is used to compare Qwen against the keyword baseline on the evaluation page.
3. The LLM is reached through a provider interface (`LlmClient`), so the model or provider can change by config. With `ENABLE_LLM=false` every feature still works using the keyword scorer and templates.
4. Email digests are **opt-in** (consent checkbox), consistent with India's Digital Personal Data Protection Act, 2023, and with good deliverability practice.
5. No legal review is planned, because this is a college project with a small set of test users. The compliant wording from 2.2 is kept anyway.

### 2.4 Confirmed decisions (project owner, v2)

| Topic | Decision |
| --- | --- |
| Project type | College final-year project |
| Team | One developer (Claude writes the code; the owner runs, configures and deploys) |
| Name | GeoTrade-AI |
| AI/ML | No separate AI/ML layer or local models. Qwen3-32B on Groq's free tier scores headlines and writes summaries; keyword rules are the fallback |
| Login | Email and password only |
| Portfolio import | Zerodha, Groww and generic CSV (all free: file parsing only) |
| Concentration flags | 25 percent for one stock, 40 percent for one sector |
| Alert throttle | At most 2 alerts per user per hour |
| UI hosting | Render free web service, on its free `onrender.com` subdomain (no custom domain) |
| Backend and database hosting | Railway 30-day free trial |
| Email provider | Brevo free plan, HTTP API |
| Sender | samvam0821@gmail.com, display name "GeoTrade-AI Daily Pulse" |
| Daily email | 17:00 IST on NSE trading days |
| Weekly recap | Yes, Saturday 09:00 IST |
| Holdings outside NIFTY 50 in emails | Left out |
| Email wording | "Holdings to review" and "Positive momentum to watch", never buy or sell |
| Summary writer | Qwen3-32B on Groq, template fallback |
| Extra features | News-spike detection, rumour and credibility scoring, plain-English alert rules |
| Legal review | Not needed (college project) |

---

## 3. Target architecture

### 3.1 Service diagram

```
                     +--------------------------------------+
   Browser  -------> |  1. UI SERVICE  (Next.js 14+, TS)    |
   (users, operator) |  SSR pages, charts, SSE client,      |
                     |  typed API client from OpenAPI       |
                     +------------------+-------------------+
                                        | HTTPS JSON + SSE  (/api/v1)
                     +------------------v-------------------+
                     |  2. BACKEND SERVICE (Python 3.11)    |
                     |                                      |
                     |  role: api     FastAPI routers ->    |
                     |                services -> repos     |
                     |                SSE fan-out           |
                     |                                      |
                     |  role: worker  scheduler, adapters,  |
                     |                pipeline stages, ML,  |
                     |                aggregation, prices,  |
                     |                alerts, DIGEST jobs   |
                     +------------------+-------------------+
                                        | SQLAlchemy (asyncpg / psycopg)
                                        | LISTEN/NOTIFY
                     +------------------v-------------------+
                     |  3. DATABASE SERVICE (PostgreSQL 16) |
                     |  pg_trgm, citext                     |
                     +--------------------------------------+

   Outbound from worker: RSS feeds, yfinance, Groq API (Qwen3-32B), Brevo HTTP API

   Hosting: UI on Render (free) -> proxies /api/v1/* to Railway (backend-api, backend-worker, Postgres)
```

### 3.2 Contracts between services

| From | To | Contract | Rule |
| --- | --- | --- | --- |
| Browser | UI | Same-origin calls to `https://<app>.onrender.com/api/v1/*`; Next.js rewrites forward them to the Railway backend, so login cookies stay first-party | No cross-site cookies; the browser never calls the Railway URL directly |
| UI | Backend | OpenAPI 3.1 file in `packages/shared/openapi.json` | Generated from FastAPI on every build; UI types generated from it; contract tests in CI |
| UI | Backend | SSE `GET /api/v1/stream` | Versioned envelope `{type, version, ts, data}` (API spec section 14) |
| Backend worker | Backend api | Database rows plus `NOTIFY article_scored`, `NOTIFY alert_created`, `NOTIFY bucket_updated` | API never imports `worker/` packages; enforced by an import-linter rule |
| Backend | Database | Alembic migrations, SQLAlchemy 2 models | One migration per change, never edited after merge (DB doc section 14) |

### 3.3 Repository layout (monorepo, adapted to three services)

```
geotrade-ai/
  services/
    ui/                         Next.js app (App Router)
      app/                      routes from Wireframes section 4
      components/               component inventory (Wireframes section 11)
      lib/api/                  generated client + TanStack Query hooks
      lib/sse/                  useEventStream hook with Last-Event-ID resume
      emails/                   React Email templates for the digest (rendered by backend, see 8.7)
      tests/                    Vitest unit, Playwright e2e
    backend/
      src/geotrade-ai/
        core/                   config, logging, security, errors, db session
        models/                 SQLAlchemy models (shared by both roles)
        repos/                  all SQL lives here
        api/                    routers, schemas, deps   (role: api)
        worker/                 scheduler, pipeline, sources, nlp, market, aggregation
        portfolio/              parsers, exposure, attention, related (used by both roles)
        digest/                 snapshot builder, ranking, narrative, renderer, sender
        eval/                   golden loader, metrics, backtest
        cli.py                  `backend api | worker | migrate | seed | evaluate | digest`
      migrations/               Alembic
      tests/
      Dockerfile
    database/
      init/                     00-extensions.sql (pg_trgm, citext, vector)
      config/                   postgresql.conf overrides (shared_buffers, work_mem)
      scripts/                  backup.sh, restore.sh, verify-integrity.sql
      Dockerfile                postgres:16 (local only; Railway uses its managed Postgres)
  packages/shared/              openapi.json, JSON fixtures for the mock server
  data/reference|golden|fixtures/
  infra/compose/                docker-compose.yml, compose.override for dev, compose.prod.yml
  .github/workflows/            ci.yml, deploy.yml, digest-smoke.yml
  docs/                         the design set, ADRs, this plan
```

### 3.4 Docker Compose (local and single-VM deployment)

```yaml
services:
  database:
    build: ./services/database
    environment: [POSTGRES_DB=geotrade-ai, POSTGRES_USER, POSTGRES_PASSWORD]
    volumes: [pgdata:/var/lib/postgresql/data, ./backups:/backups]
    healthcheck: { test: ["CMD", "pg_isready"], interval: 5s }

  backend-migrate:            # one-shot
    image: geotrade-ai/backend
    command: ["sh", "-c", "backend migrate && backend seed --reference"]
    depends_on: { database: { condition: service_healthy } }

  backend-api:
    image: geotrade-ai/backend
    command: backend api --workers 2
    depends_on: [backend-migrate]
    ports: ["8000:8000"]

  backend-worker:
    image: geotrade-ai/backend
    command: backend worker
    depends_on: [backend-migrate]
    environment: [LLM_PROVIDER=groq, LLM_MODEL=qwen/qwen3-32b, GROQ_API_KEY]

  ui:
    build: ./services/ui
    environment: [NEXT_PUBLIC_API_BASE=/api/v1, API_INTERNAL_URL=http://backend-api:8000]
    ports: ["3000:3000"]

  mailpit:                    # dev profile only: catches digest emails locally
    image: axllent/mailpit
    profiles: [dev]
    ports: ["8025:8025"]
```

---

## 4. Phase overview, timeline and team split

### 4.1 Timeline

```
Week:            1    2    3    4  |  5    6    7    8  |  9   10   11   12
Phase:           [---- Phase 1 ----]  [---- Phase 2 ----]  [---- Phase 3 ----]
DB               schema  seeds  idx   users  eval  views   digest  extras    backup
BE               scaffold ingest qwen agg | auth port attn alerts | digest extras test deploy
UI               shell  comps  pages  live | auth onboard port admin| digest-ui email polish
Gate:                              G1                   G2                    G3
```

### 4.2 Phase gates

| Gate | Must be true to proceed |
| --- | --- |
| G1 (end of week 4) | A real RSS headline appears on the overview within about 2 minutes; injected headline traverses every stage; golden set v0 evaluated; CI green; `docker compose up` works on a clean machine |
| G2 (end of week 8) | User journeys 1 to 5 from the overview work end to end; contract tests pass; Playwright suite covers sign-up to attention feed; delete-my-data verified |
| G3 (end of week 12) | Daily and weekly digests delivered to opted-in users with no duplicates over a 5-day soak; Render and Railway deployment live; load test meets HLD 8.4 targets; demo recording exists |

### 4.3 Working agreement for parallel development

1. **Contracts first.** Week 1 ends with `openapi.json` covering all Phase 1 endpoints and a fixture-backed mock server, so UI pages can be built and reviewed before every backend handler exists.
2. **Vertical slices.** Each week ends with one slice usable in the UI, even if other parts are mocked.
3. **Feature flags** (`ENABLE_LLM`, `ENABLE_ALERTS`, `ENABLE_DIGEST`, `ENABLE_WEEKLY_DIGEST`) let unfinished work merge to main safely.
4. **Definition of done per task:** code, tests, migration (if any), OpenAPI updated, docs line in the changelog.

---

## 5. Phase 1: Foundation and core news pipeline (weeks 1 to 4)

**Goal:** a public, real-time market-news product for NIFTY 50 with honest measurement, running from one command.

### 5.1 Database service (Phase 1)

| ID | Task | Detail | Week |
| --- | --- | --- | --- |
| P1-DB-01 | Database image | `postgres:16`; `init/00-extensions.sql` enables `pg_trgm` and `citext` (both available on Railway Postgres) | 1 |
| P1-DB-02 | Alembic baseline | Migration `0001_enums`: all enum types from DB doc section 3 | 1 |
| P1-DB-03 | Reference tables | `0002_reference`: sectors, companies, aliases, trading_calendar with indexes | 1 |
| P1-DB-04 | News tables | `0003_news`: sources, source_health, story_clusters, articles (all six indexes incl. trigram and partial status index), deferred FK to canonical article, article_entities, model_versions, article_scores, pipeline_events, dead_letters | 1 to 2 |
| P1-DB-05 | Market and aggregate tables | `0004_market`: price_candles, sentiment_buckets, sector_sentiment_buckets, market_sentiment_buckets | 2 |
| P1-DB-06 | Triggers | `set_updated_at` on mutable tables; `notify_article_scored`; add `notify_bucket_updated` for the SSE `bucket_updated` event | 2 |
| P1-DB-07 | Idempotent seeds | Upsert-based loaders for 50 companies, sectors, several hundred aliases, NSE holidays, sources, model_versions; `seed --history` with 7 days of articles, scores, buckets and daily candles | 2 to 3 |
| P1-DB-08 | Query verification | `EXPLAIN ANALYZE` for every query in DB doc section 10 against seeded data; record plans in `docs/perf/` | 4 |
| P1-DB-09 | Integrity checks | `verify-integrity.sql`: one canonical article per cluster, no score without article, no simulated rows in public stats views | 4 |
| P1-DB-10 | Backup scripts | Nightly `pg_dump` (custom format) to the mounted volume; restore script tested once | 4 |

### 5.2 Backend service (Phase 1)

**Week 1: scaffold and contracts**

| ID | Task | Detail |
| --- | --- | --- |
| P1-BE-01 | Project scaffold | `uv` or Poetry, ruff, mypy (strict on `core`, `repos`), pytest, pre-commit; Pydantic Settings for all config in HLD 8.6 |
| P1-BE-02 | Core | JSON logging with context vars (`article_id`, `stage`, `run_id`), request ID middleware, unified error format (API spec section 3), `/health/live`, `/health/ready`, `/meta/version`, `/meta/disclaimer` |
| P1-BE-03 | Models and repos | SQLAlchemy 2 models for Phase 1 tables; repositories as the only SQL location; UUID v7 generator |
| P1-BE-04 | OpenAPI first draft | Response schemas for market, stocks, sectors, news, sources; export to `packages/shared/openapi.json`; fixture mock server (Prism or a tiny FastAPI app serving fixtures) |
| P1-BE-05 | CLI | `backend api|worker|migrate|seed|evaluate` entrypoints in one image |

**Week 2: ingestion, normalisation, dedupe, linking**

| ID | Task | Detail |
| --- | --- | --- |
| P1-BE-06 | HTTP utility | Honest User-Agent, timeouts 3 s / 8 s, conditional GET, retry with jitter, 429 Retry-After, per-domain spacing, size cap, circuit breaker (1, 2, 5, 15 minutes) |
| P1-BE-07 | Source adapters | `rss_generic` plus overrides for ET, Moneycontrol, Mint, Business Standard; record fixtures for each feed into `data/fixtures/` |
| P1-BE-08 | Normaliser | URL canonicalisation and `url_hash`; `normalize_title`, `strip_html`; IST-to-UTC with `time_estimated`; future-time clamp; English-only filter with metric |
| P1-BE-09 | Pipeline runner and state machine | Batch claim with `FOR UPDATE SKIP LOCKED`, one transaction per stage, `stage_timestamps`, retry schedule 10 s, 30 s, 2 min, 10 min, 30 min, dead-letter after attempt 5, per-article timeout |
| P1-BE-10 | Deduplicator L1 to L3 | URL hash, title hash in 48 h window, rapidfuzz `token_set_ratio` plus Jaccard with threshold about 88 inside 6 h and shared entity; false-merge guards (conflicting numbers, disjoint tickers); canonical selection; cluster stats |
| P1-BE-11 | Entity linker | Aho-Corasick alias index (`pyahocorasick`), title 3x weighting, negative contexts, overlap resolution, all disambiguation rules from LLD 7.4 as individually tested functions, cap 3 primary tickers, sector and market inference, `link_trace` |
| P1-BE-12 | Relevance filter | Hard drops, soft relevance, `< 0.25` stored but excluded |

**Week 3: scoring, aggregation, prices**

| ID | Task | Detail |
| --- | --- | --- |
| P1-BE-13 | Qwen scorer (Groq) | `LlmClient` over Groq's OpenAI-compatible endpoint, model `qwen/qwen3-32b`, thinking mode off, temperature 0; batches of up to 10 headline-entity pairs per request; strict JSON output (label, p_pos, p_neu, p_neg, event hint, one-line rationale) validated with Pydantic; invalid JSON retried once then sent to fallback; `llm_cache` keyed by prompt version plus text; daily request budget and per-minute throttle (section 10.3); model version row `qwen3-32b-groq-v1` |
| P1-BE-14 | Keyword baseline scorer | Lexicon and rule scorer for Indian finance headlines. Used when Groq is disabled, rate-limited or down (article marked with the model actually used), and as the baseline on the evaluation page. A nightly `rescore_fallbacks` job re-scores fallback articles with Qwen when budget allows |
| P1-BE-15 | Event classifier and severity | Priority-ordered rule table from LLD 9.3, hedging discount for "may / likely / reportedly", magnitude adjustments |
| P1-BE-16 | Template explanations | `explanation_source = 'template'` for every score |
| P1-BE-17 | Aggregator | Impact formula, 12 h half-life decay, 5 min / 1 h / 1 d buckets, tanh squash to -100..100, session-date mapping, recompute only touched buckets, sector (market-cap weighted) and market indices |
| P1-BE-18 | Market calendar and prices | Calendar functions; yfinance batched download, validation, upsert, staleness flag, CSV-seed fallback provider behind the same interface |
| P1-BE-19 | Scheduler | All Phase 1 jobs from LLD section 3 with `max_instances=1`, `coalesce=True`, jitter |

**Week 4: read API, live stream, evaluation v0**

| ID | Task | Detail |
| --- | --- | --- |
| P1-BE-20 | Public read endpoints | `/market/overview`, `/market/ticker-tape`, `/market/movers`, all `/stocks/*`, `/sectors/*`, `/news`, `/news/{id}`, `/news/{id}/cluster`, `/news/latest`, `/sources`; cursor pagination; ETag; in-process TTL cache (15 to 30 s) invalidated on `bucket_updated` |
| P1-BE-21 | SSE stream (public topics) | `LISTEN` on a dedicated connection, fan-out with per-topic filters, `Last-Event-ID` replay from a small in-memory ring buffer, heartbeat every 15 s, `retry: 3000` |
| P1-BE-22 | Minimal demo injection | `POST /admin/demo/inject` and `GET /admin/demo/trace/{id}` behind a static operator token (full auth comes in Phase 2) so the G1 demo works |
| P1-BE-23 | Evaluation v0 | `backend evaluate` runs linking and sentiment on golden-v0 (150 headlines) for keyword baseline and Qwen; writes JSON report to `data/golden/reports/` |
| P1-BE-24 | Metrics | Prometheus counters and histograms from HLD 8.2 on `/metrics` (internal only) |

### 5.3 UI service (Phase 1)

| ID | Task | Detail | Week |
| --- | --- | --- | --- |
| P1-UI-01 | Scaffold | Next.js App Router, TypeScript strict, Tailwind, shadcn/ui, ESLint, Vitest, Playwright | 1 |
| P1-UI-02 | Design tokens | Light and dark tokens from Wireframes 2.1 as CSS variables; Inter and JetBrains Mono with tabular figures; theme toggle with `t` shortcut | 1 |
| P1-UI-03 | API client | `openapi-typescript` plus a thin fetch wrapper; TanStack Query hooks; points at the mock server until week 4 | 1 |
| P1-UI-04 | App shell | Sidebar (collapses to icons, then bottom tab bar on phones), top bar, scrolling ticker tape, disclaimer footer, freshness pill, command palette (`/`) | 1 to 2 |
| P1-UI-05 | Core components | Sentiment badge (icon plus label, never colour alone), event chip, ticker chip with hover card, news card with cluster count, gauge, sparkline, skeletons, empty and error states | 2 |
| P1-UI-06 | Price and sentiment chart | lightweight-charts candles or line with sentiment histogram on a synced pane, event markers, range chips, crosshair sync, "view as table" accessible toggle | 2 to 3 |
| P1-UI-07 | Pages | Overview, stock list, stock detail, sectors (heat map plus table), sector detail, news explorer with all filters, article drawer and `/news/[id]`, methodology | 3 |
| P1-UI-08 | Live updates | `useEventStream` hook: reconnect with `Last-Event-ID`, refetch on reconnect, polling fallback to `/news/latest?since=` every 10 s, "New items" pill, toast grouping (max 3) | 4 |
| P1-UI-09 | State matrix | Apply loading, empty, error, stale, partial, live-update and offline states (Wireframes section 6) to every data component | 4 |
| P1-UI-10 | Minimal demo panel | Inject form plus live stage trace (the centrepiece of the technical demo) | 4 |

### 5.4 Phase 1 testing

1. Unit: URL canonicalisation (property tests for idempotence), title normalisation, bucket flooring, every disambiguation rule, impact formula, session mapping across IST boundaries and holidays.
2. Fixture tests: each source adapter against recorded RSS.
3. Pipeline integration: fixtures through all stages into a throwaway Postgres (Testcontainers) with assertions on final rows and idempotency (run twice, same rows).
4. Failure injection: fetch errors, model exception, DB disconnect, verifying retry and dead-letter paths.
5. UI: component tests for badges and cards; one Playwright smoke test (overview loads, open stock, open article).

### 5.5 Phase 1 exit criteria (G1)

- [ ] Real headlines appear on the overview within about 2 minutes of appearing in a feed (median logged on `/metrics`).
- [ ] Injected headline traverses fetched, deduped, linked, scored, aggregated and becomes visible with stage timings.
- [ ] Golden-v0 report generated; Qwen beats the keyword baseline on macro F1 (if not, revise the prompt before proceeding).
- [ ] Groq outage simulated: scoring continues on the keyword fallback and re-scores later.
- [ ] Killing the worker mid-run and restarting resumes without duplicates.
- [ ] CI green: lint, type check, unit, integration, migration-drift check, UI build.

---

## 6. Phase 2: Users, portfolios and personalisation (weeks 5 to 8)

**Goal:** every authenticated and operator feature in Overview sections 7.2 and 7.3 working end to end.

### 6.1 Database service (Phase 2)

| ID | Task | Detail | Week |
| --- | --- | --- | --- |
| P2-DB-01 | User tables | `0005_users`: users (citext email), refresh_tokens, portfolios, holdings, import_previews, watchlist_items | 5 |
| P2-DB-02 | Alert tables | `0006_alerts`: alert_rules (partial index on enabled), alerts with `UNIQUE (user_id, dedupe_key)` and unread partial index | 6 |
| P2-DB-03 | Related-stocks support | `0007_co_mentions` plus nightly co-mention job input | 6 |
| P2-DB-04 | Evaluation tables | `0008_eval`: golden_examples, eval_runs, backtest_runs, llm_cache | 7 |
| P2-DB-05 | Materialised views | `mv_market_movers`, `mv_stock_news_24h`, `mv_sector_summary` with unique indexes so `REFRESH ... CONCURRENTLY` works; refreshed by worker | 7 |
| P2-DB-06 | Privacy mechanics | Verify cascade delete across all user tables with a test; import previews expire after 30 minutes (housekeeping job); logs scrubbed of holdings | 8 |
| P2-DB-07 | Demo and operator seeds | Demo user with about 12 holdings across sectors and default alert rules; one operator account | 5 |

### 6.2 Backend service (Phase 2)

| ID | Task | Detail | Week |
| --- | --- | --- | --- |
| P2-BE-01 | Authentication | Argon2id hashing, 15-minute JWT access tokens, rotating opaque refresh tokens (hashed in DB) in HTTP-only Secure SameSite cookies, reuse detection revokes the token family, CSRF double-submit token on cookie-authenticated mutations, `POST /auth/demo` | 5 |
| P2-BE-02 | Me endpoints | `GET/PATCH /me`, password change, `DELETE /me` with `confirm: true`, `GET /me/export` CSV | 5 |
| P2-BE-03 | Rate limiting | Token bucket per IP and per user (in-process store; single API replica) with limits from API spec section 18 and `X-RateLimit-*` headers | 5 |
| P2-BE-04 | Portfolio import | `detect_format`, Zerodha parser (CSV and XLSX via openpyxl read-only), Groww holdings parser, generic mapping parser, symbol normalisation (-EQ, -BE, renames, ISIN), duplicate merge by weighted average, formula-character neutralisation, 1 MB and 500-row caps, preview token flow | 5 to 6 |
| P2-BE-05 | Portfolio endpoints | All `/portfolio/*` endpoints; sample loader; exposure and concentration flags (25 percent stock, 40 percent sector); contributors | 6 |
| P2-BE-06 | Attention engine | Component computation per LLD 13.3 with stored components; per-user weight overrides; article feed ranking | 6 |
| P2-BE-07 | Related stocks | Same sector, same group, co-mentions; filters (not held, positive momentum, adequate volume); reasons array; disclaimer field | 6 |
| P2-BE-08 | Watchlist | Idempotent `PUT`, `DELETE`, list with price and sentiment | 6 |
| P2-BE-09 | Alert engine | Default rules at onboarding; evaluation on each scored article plus 60 s sweep; dedupe keys; per-user throttle of 2 alerts per hour with extra events merged into the next alert; quiet hours; `NOTIFY alert_created` | 7 |
| P2-BE-10 | Private SSE topics | Token-authenticated stream adds `alert_created` and `attention_changed`; connection caps (3 per user, 10 per IP) | 7 |
| P2-BE-11 | Evaluation and backtest | Golden-v1 (300 headlines, two annotators on a 50-headline overlap to report agreement); metrics (accuracy, macro F1, confusion, per-class), entity-linking precision and recall, event accuracy, dedupe precision and recall; backtest of sentiment index vs next-session return with correlation, quintile returns, hit rate vs baseline, bootstrap confidence interval; `/evaluation/*` endpoints | 7 |
| P2-BE-12 | Admin endpoints | Full `/admin/*` set: pipeline stats, source pause/resume/refresh, dead-letter retry/discard, demo replay and reset; operator role check | 8 |
| P2-BE-13 | Contract tests | Schemathesis against the running API in CI | 8 |

### 6.3 UI service (Phase 2)

| ID | Task | Detail | Week |
| --- | --- | --- | --- |
| P2-UI-01 | Auth screens | Login, signup with required disclaimer checkbox, inline validation, "Try the demo account", silent refresh with retry-once on 401 | 5 |
| P2-UI-02 | Onboarding wizard | Three steps: dropzone (CSV/XLSX), manual entry, sample loader; review table with matched/unmatched rows and edit/remove; alert toggles | 5 to 6 |
| P2-UI-03 | Portfolio dashboard | Value strip, portfolio sentiment gauge, sector donut, concentration card, flagged holdings, sortable holdings table with attention bar and flag tooltips, contributors bar chart | 6 |
| P2-UI-04 | Needs Attention feed | Scope and window controls, ranked groups with collapsible articles, "Why these?" rail, advanced weights dialog, related stocks to watch with reasons | 6 to 7 |
| P2-UI-05 | Watchlist | Table, add via search, remove, empty state | 7 |
| P2-UI-06 | Alerts | Inbox with mark read and mark all, rules tab with thresholds and quiet hours; bell counter driven by SSE; high-severity toasts persist | 7 |
| P2-UI-07 | Settings | Profile, preferences, data tab (export, delete with typed confirmation) | 7 |
| P2-UI-08 | Evaluation page | Metric cards, confusion matrix, per-class table, baseline comparison, quintile chart, caveat box, error-analysis sample | 8 |
| P2-UI-09 | Admin pages | Pipeline health (latency histogram, sources table, backlog, throughput, errors with retry), full demo panel, dead-letter viewer | 8 |
| P2-UI-10 | E2E suite | Playwright for journeys 1 to 5 against seeded data, including phone viewport | 8 |

### 6.4 Phase 2 exit criteria (G2)

- [ ] Sign up, upload a Zerodha CSV, confirm, land on a populated portfolio dashboard.
- [ ] Injected negative regulatory headline on a held stock produces a toast, bell increment and attention reorder within 2 seconds of scoring.
- [ ] Evaluation page shows numbers produced by `backend evaluate`, re-runnable by anyone.
- [ ] Delete-my-data removes every user row (verified by test query).
- [ ] Contract tests and Playwright suite green in CI.

---

## 7. Phase 3: Daily email digest, AI depth, hardening and deployment (weeks 9 to 12)

**Goal:** add the end-of-day email, deepen the AI where it improves quality measurably, and ship publicly on free infrastructure.

### 7.1 Database service (Phase 3)

| ID | Task | Detail | Week |
| --- | --- | --- | --- |
| P3-DB-01 | Digest tables | `0009_digest`: email_preferences, digest_runs, digest_deliveries, email_suppressions (full DDL in section 8.3) | 9 |
| P3-DB-02 | Extras tables | `0010_extras`: `coverage_spikes` (ticker, bucket_start, z_score, n_stories, baseline_mean, baseline_std), `article_scores.hedge_score` and `credibility` columns, `llm_usage` (date, purpose, requests, tokens) for the daily Groq budget | 10 |
| P3-DB-03 | Retention jobs | 5 min candles 90 days, 5 min buckets 30 days, pipeline_events 14 days, llm_cache 30 days, digest_deliveries payload 30 days (payload nulled, row kept for idempotency) | 11 |
| P3-DB-04 | Tuning for target host | `shared_buffers`, `work_mem`, `max_connections` sized to the chosen host (section 10); connection pooling via SQLAlchemy pool sizes per role (api 10, worker 5) | 11 |
| P3-DB-05 | Backup off-box | Nightly dump pushed to free object storage (for example Cloudflare R2 free tier or a private GitHub release artifact for small dumps); restore drill documented | 12 |

### 7.2 Backend service (Phase 3)

| ID | Task | Detail | Week |
| --- | --- | --- | --- |
| P3-BE-01 | Digest snapshot builder | Per user, per session date: frozen JSON of holdings summary, movers, risk flags, momentum-to-watch candidates, top stories, market context (section 8.4) | 9 |
| P3-BE-02 | Momentum-to-watch ranking | Transparent scoring formula with minimum evidence thresholds (section 8.5) | 9 |
| P3-BE-03 | Narrative generator | Template narrative always; optional LLM narrative grounded only in the snapshot, with validator and fallback (section 8.6) | 10 |
| P3-BE-04 | Renderer and sender | HTML plus plain-text rendering; `EmailSender` interface with Brevo, Resend and SMTP (Mailpit) implementations; outbox send loop; bounce and complaint webhook into suppressions | 10 |
| P3-BE-05 | Digest endpoints | Preferences, preview, history, one-click unsubscribe, admin test-send and run status (section 8.8) | 10 |
| P3-BE-06 | Qwen "why this matters" | Qwen turns template plus headline into one plain sentence; length cap, banned-vocabulary check, `llm_cache`, fallback to template; evaluated by a 50-item human rating sheet | 10 |
| P3-BE-07 | LLM entity-linking fallback | Triggered on no-link-high-relevance or close top-two scores; output validated against the ticker list; measured on golden-v1 (must not reduce precision) | 10 |
| P3-BE-08 | News-spike detection | Per ticker, compare story count in the latest hour and day with a 20-session rolling mean and standard deviation; flag z above 3 with at least 4 stories; feeds the attention score (volume component), an optional alert type `coverage_spike`, and a badge on stock pages | 10 |
| P3-BE-12 | Rumour and credibility scoring | Hedge-cue rules ("reportedly", "sources say", "may", "likely", "plans to", question headlines) give `hedge_score`; `credibility` rises with independent source count in the cluster and falls with hedge score; severity and impact are discounted for low credibility; shown as a "single source, unconfirmed" chip | 11 |
| P3-BE-13 | Plain-English alert rules | User types a rule ("tell me if any bank I hold gets RBI news"); Qwen converts it to the existing `alert_rules.params` JSON schema; the parsed rule is shown back for confirmation before saving; unknown fields or tickers rejected | 11 |
| P3-BE-09 | Load and soak testing | k6 against cached and uncached endpoints and 200 concurrent SSE clients; synthetic article flood for pipeline throughput; record before and after numbers in `docs/perf/` | 11 |
| P3-BE-10 | Security review | Dependency audit (pip-audit, npm audit), secret scanning, CORS and cookie flags, upload fuzzing, authorisation tests (user A cannot read user B), rate-limit tests | 11 |
| P3-BE-11 | Production config | `compose.prod.yml`, Caddy or the platform's TLS, environment-specific settings, Sentry free tier for errors (optional) | 12 |

### 7.3 UI service (Phase 3)

| ID | Task | Detail | Week |
| --- | --- | --- | --- |
| P3-UI-01 | Email preferences | Settings tab "Daily Pulse email": opt-in with consent text, send time, section toggles, watchlist inclusion, last sent status | 9 |
| P3-UI-02 | Digest preview and archive | `/digest` page shows today's digest exactly as emailed (same snapshot), plus last 30 days archive; useful on days the email is missed | 10 |
| P3-UI-03 | Email templates | React Email components following the design tokens (light theme only, inline CSS, 600 px column, dark-mode-safe colours), plain-text fallback | 9 to 10 |
| P3-UI-04 | Unsubscribe landing | Token-based page that confirms unsubscribe without login, with a resubscribe link | 10 |
| P3-UI-08 | Extras UI | Spike badge and spike list on stock and overview pages, credibility chip on news cards, plain-English rule box with parsed-rule confirmation in the alerts Rules tab | 11 |
| P3-UI-05 | Admin digest panel | Run status for today, counts (queued, sent, failed, skipped), send test to self, view any rendered digest for the demo user | 11 |
| P3-UI-06 | Polish pass | Accessibility audit (axe in Playwright), contrast, reduced motion, keyboard shortcuts, Lighthouse performance budget | 11 to 12 |
| P3-UI-07 | Deployment | Production build, `NEXT_PUBLIC_*` config, caching headers, error boundary reporting | 12 |

### 7.4 Phase 3 exit criteria (G3)

- [ ] Five consecutive trading days of digests and one Saturday recap sent to opted-in test users; zero duplicates; zero digests on a holiday; every email has the disclaimer and a working one-click unsubscribe.
- [ ] Qwen features improve or hold their metric versus the keyword baseline; everything works with `ENABLE_LLM=false`.
- [ ] Daily Groq usage stays inside the budget in section 10.3 for a full week.
- [ ] k6 shows cached p95 under 100 ms and uncached stock summary p95 under 400 ms on the deployed host.
- [ ] Render URL live with the Railway backend behind it; backups run nightly; recorded demo video stored.

---

## 8. Daily email digest ("Daily Pulse"): feature design

### 8.1 What the user receives

A single email per trading day, after market close, for users who opted in.

```
Subject: Daily Pulse, Thu 22 Oct: 2 holdings to review, portfolio sentiment +12 (down 3)

+------------------------------------------------------------+
| GeoTrade-AI  Daily Pulse  Thursday 22 Oct 2026              |
| Not investment advice. Summary of public news and signals. |
+------------------------------------------------------------+
| TODAY IN ONE PARAGRAPH                                     |
| Your portfolio's news sentiment eased to +12 as a SEBI     |
| order weighed on ADANIENT. IT holdings saw positive        |
| coverage after INFY's deal announcement. ...               |
+------------------------------------------------------------+
| YOUR HOLDINGS TODAY                                        |
| Value Rs 4.82L  Day +0.6%  Sentiment +12 (-3)              |
| Biggest positive: INFY +18   Biggest negative: ADANIENT -38|
+------------------------------------------------------------+
| HOLDINGS TO REVIEW (risk flags)                            |
| ! ADANIENT  Negative shift -38 in 24h, regulatory event    |
|   "SEBI order ..." Moneycontrol + 3 sources   [Open story] |
| ! TATAMOTORS Negative momentum, 9% of portfolio            |
+------------------------------------------------------------+
| POSITIVE MOMENTUM TO WATCH (not in your portfolio)         |
| HCLTECH  +24 over 3 days  Same sector as INFY, TCS         |
|   Based on 6 stories from 4 sources. Event: earnings       |
| WIPRO    +11 ...                                           |
| These are not recommendations.                             |
+------------------------------------------------------------+
| YOUR WATCHLIST       | MARKET CONTEXT                      |
| SBIN +9  ...         | Market sentiment +23, IT +31 ...    |
+------------------------------------------------------------+
| HOW THESE SIGNALS HAVE BEHAVED                             |
| Over the last 90 sessions, strong positive signals were    |
| followed by a positive next-session return 56% of the time |
| (n=212; baseline 51%). Past behaviour is not a guide.      |
+------------------------------------------------------------+
| [Open your dashboard]  Manage email  Unsubscribe (1 click) |
| Disclaimer ... Registered address ...                      |
+------------------------------------------------------------+
```

The "how these signals have behaved" box is pulled from the latest backtest run, so the email is honest about the signal's weak predictive power (Overview section 3, second reason). The numbers above are illustrative.

### 8.2 Schedule

| Step | Time (IST) | Job | Notes |
| --- | --- | --- | --- |
| EOD price sync | about 16:00 | `sync_prices_eod` (exists) | Final candles for the day |
| Daily buckets final | about 16:10 | `aggregate_buckets` for `1d` | Ensures today's session index is closed |
| Build snapshots | 16:30 | `digest_build` | Only if `is_trading_day(today)`; one `digest_runs` row per session date |
| Send | user's chosen time, default 17:00 | `digest_send` loop every minute | Sends deliveries whose send time has passed |
| Sweep | 21:00 | `digest_sweep` | Retries failures, marks remaining as failed with reason |
| Weekly recap | Saturday 09:00 | `weekly_build` and send | Covers the week's trading sessions: portfolio sentiment trend, the week's biggest stories per holding, flags raised and cleared, momentum names that persisted all week |

Weekends and NSE holidays: no daily email. The weekly recap uses the same tables with `kind = 'weekly'` (the `kind` column and unique key in 8.3 cover both).

### 8.3 Data model additions

```sql
CREATE TABLE email_preferences (
  user_id               uuid PRIMARY KEY REFERENCES users(id) ON DELETE CASCADE,
  daily_digest_enabled  boolean NOT NULL DEFAULT false,      -- opt-in only
  send_time_ist         time    NOT NULL DEFAULT '17:00',
  include_watch_ideas   boolean NOT NULL DEFAULT true,
  include_watchlist     boolean NOT NULL DEFAULT true,
  include_market        boolean NOT NULL DEFAULT true,
  consent_text_version  text,
  consented_at          timestamptz,
  unsubscribed_at       timestamptz,
  updated_at            timestamptz NOT NULL DEFAULT now()
);

CREATE TABLE digest_runs (
  id            uuid PRIMARY KEY,
  kind          text NOT NULL DEFAULT 'daily',
  session_date  date NOT NULL,
  status        text NOT NULL CHECK (status IN ('building','ready','sending','done','failed')),
  started_at    timestamptz NOT NULL DEFAULT now(),
  finished_at   timestamptz,
  stats         jsonb NOT NULL DEFAULT '{}'::jsonb,     -- counts, durations, llm usage
  UNIQUE (kind, session_date)
);

CREATE TABLE digest_deliveries (
  id                  uuid PRIMARY KEY,
  run_id              uuid NOT NULL REFERENCES digest_runs(id) ON DELETE CASCADE,
  user_id             uuid NOT NULL REFERENCES users(id) ON DELETE CASCADE,
  kind                text NOT NULL DEFAULT 'daily' CHECK (kind IN ('daily','weekly')),
  session_date        date NOT NULL,                 -- for weekly: the Saturday send date
  status              text NOT NULL CHECK (status IN
                        ('queued','rendered','sending','sent','failed','skipped')),
  skip_reason         text,                 -- no_holdings, suppressed, unsubscribed, quota
  send_after          timestamptz NOT NULL,
  snapshot            jsonb,                -- frozen inputs; nulled after 30 days
  narrative_source    text CHECK (narrative_source IN ('template','llm')),
  subject             text,
  provider            text,
  provider_message_id text,
  attempts            smallint NOT NULL DEFAULT 0,
  last_error          text,
  sent_at             timestamptz,
  created_at          timestamptz NOT NULL DEFAULT now(),
  UNIQUE (user_id, kind, session_date)           -- never two digests of a kind per user per day
);
CREATE INDEX ix_dd_sendable ON digest_deliveries(send_after)
  WHERE status IN ('queued','rendered');

CREATE TABLE email_suppressions (
  email       citext PRIMARY KEY,
  reason      text NOT NULL CHECK (reason IN ('hard_bounce','complaint','manual')),
  created_at  timestamptz NOT NULL DEFAULT now()
);
```

Unsubscribe uses a signed HMAC token (`user_id`, purpose, expiry) so no token table is needed. `DELETE /me` cascades through preferences and deliveries.

### 8.4 Snapshot contents (the single source of truth for the email and the preview page)

```json
{
  "version": 1,
  "session_date": "2026-10-22",
  "user": {"first_name": "Asha"},
  "portfolio": {"value": 482000.0, "day_change_pct": 0.6,
                "sentiment": {"index": 12.0, "delta_24h": -3.0},
                "top_positive": {"ticker": "INFY", "delta": 18.0},
                "top_negative": {"ticker": "ADANIENT", "delta": -38.0}},
  "review": [{"ticker": "ADANIENT", "flags": ["negative_shift","severe_event"],
              "reason": "Sentiment fell 38 points in 24h after a regulatory order",
              "stories": [{"article_id": "...", "title": "...", "source": "Moneycontrol",
                           "source_count": 4, "url": "https://..."}]}],
  "watch": [{"ticker": "HCLTECH", "index": 24.0, "momentum_3d": 14.0,
             "reasons": ["Same sector as INFY, TCS", "Earnings coverage"],
             "evidence": {"n_stories": 6, "n_sources": 4}}],
  "watchlist": [{"ticker": "SBIN", "index": 9.0, "delta_24h": 2.0}],
  "market": {"index": 23.0, "delta_24h": 6.0, "top_sectors": [{"id": "it", "index": 31.0}]},
  "backtest_note": {"hit_rate": 0.56, "baseline": 0.51, "n": 212, "window_sessions": 90},
  "links": {"dashboard": "...", "preferences": "...", "unsubscribe": "..."}
}
```

Holdings outside NIFTY 50 are left out of the email entirely (they have no sentiment). The snapshot is assembled by reusing existing services (exposure, attention, risk flags, related stocks) so the email can never disagree with the dashboard.

### 8.5 Ranking rules

**Holdings to review** (max 5): holdings with at least one risk flag, ordered by attention score. Each carries its flag reason and up to two canonical stories.

**Positive momentum to watch** (max 3, not held):

```
watch_score =
    0.35 * norm(sentiment_momentum_3d)          # change in daily index over 3 sessions
  + 0.20 * norm(news_volume_z)                  # unusual coverage
  + 0.25 * relatedness(candidate, holdings)     # same sector 0.6, same group 0.8, co-mention rate
  + 0.20 * event_quality                        # positive earnings, order wins, upgrades
  - penalty(max negative severity in 72h)       # excludes stocks with fresh severe negative events

Eligibility (all must hold):
  n_stories_3d >= 3 and n_sources_3d >= 2       # no single-article signals
  sentiment index > 0 and momentum_3d > 0
  not in holdings
```

All weights live in config and every component is stored in the snapshot, so "why is this here?" is always answerable.

### 8.6 Narrative generation (template first, LLM optional)

1. **Template narrative** always generated from the snapshot (deterministic, testable).
2. If `ENABLE_LLM` and the Groq budget allow: send *only the snapshot JSON* to Qwen3-32B with a prompt asking for a 60 to 90 word summary.
3. **Validator** rejects the LLM output and falls back to the template if any check fails:
   - mentions a ticker not present in the snapshot;
   - contains a number not present in the snapshot (after rounding tolerance);
   - contains banned vocabulary (`buy`, `sell`, `target price`, `will rise`, `guaranteed`, `recommend`, `should invest`) from the shared vocabulary file;
   - exceeds the length cap.
4. Result cached in `llm_cache` by `sha256(prompt_version + snapshot)`; `narrative_source` recorded per delivery.

### 8.7 Rendering and sending

- Templates are authored as React Email components in `services/ui/emails/`, compiled at build time to HTML templates with placeholders, and committed as artefacts the backend renders with Jinja2. This keeps design ownership with the UI developer while the backend owns sending, and avoids running Node in the worker.
- Each email has HTML and plain-text parts, a `List-Unsubscribe` header plus `List-Unsubscribe-Post: List-Unsubscribe=One-Click`, and tracking pixels disabled by default (privacy first).
- `EmailSender` interface: `BrevoSender` (HTTP API, used in production) and `SmtpSender` (Mailpit in dev only). Railway blocks outbound SMTP ports on free, trial and hobby plans, so production must use Brevo's HTTP API.
- Sender: samvam0821@gmail.com with display name "GeoTrade-AI Daily Pulse". Because there is no verified domain, Brevo rewrites the visible sender to its own address and free-plan emails carry a Brevo footer. Acceptable for a college demo; test users should mark the first email "Not spam". The `/digest` page in the app is the reliable copy.
- **Outbox loop:** claim deliveries with `FOR UPDATE SKIP LOCKED`, render, send, store `provider_message_id`, set `sent`. Retries with backoff, max 3 attempts. Provider quota guard: if the daily free quota would be exceeded, remaining deliveries are marked `skipped` with `quota` and an operator alert fires (the in-app `/digest` page still shows them).
- Deliverability upgrade path (optional): buying a domain and verifying it in Brevo (SPF, DKIM, DMARC) removes the sender rewrite.

### 8.8 API additions

| Method | Path | Auth | Description |
| --- | --- | --- | --- |
| GET | /me/email-preferences | user | Current preferences |
| PUT | /me/email-preferences | user | Update; enabling requires `consent: true` and records consent version |
| GET | /digest/today | user | Today's snapshot and rendered HTML (or "not yet built") |
| GET | /digest/history | user | Last 30 days, cursor paginated |
| GET | /digest/{session_date} | user | One past digest |
| POST | /email/unsubscribe | token | One-click unsubscribe (RFC 8058 compatible) |
| POST | /webhooks/email/{provider} | signature | Bounce and complaint events into suppressions |
| GET | /admin/digest/runs | operator | Run status and stats |
| POST | /admin/digest/test-send | operator | Send today's digest for a given user to the operator's address |
| POST | /admin/digest/rebuild | operator | Rebuild snapshots for a session date (idempotent; does not resend sent ones) |

### 8.9 Digest tests

- Snapshot builder against a fixed seeded portfolio with a fake clock: golden JSON comparison.
- Holiday and weekend: no run is created.
- Idempotency: running `digest_build` and `digest_send` twice produces one email per user.
- Validator: table of LLM outputs that must be rejected (invented ticker, invented number, banned word).
- Rendering snapshot tests for HTML and text; link checker for all URLs; litmus-style check in Gmail, Outlook web and a mobile client manually once.
- Unsubscribe token: tampered, expired and replayed tokens rejected.

---

## 9. Cross-cutting engineering

### 9.1 CI/CD pipeline (GitHub Actions)

| Stage | UI service | Backend service | Database service |
| --- | --- | --- | --- |
| Lint and types | ESLint, `tsc --noEmit` | ruff, mypy, import-linter (api must not import worker) | sqlfluff on hand-written SQL |
| Unit | Vitest | pytest (no network, fixtures only) | n/a |
| Integration | n/a | pytest with Testcontainers Postgres; pipeline fixtures end to end | migrations up from empty, down one step, up again; autogenerate drift check |
| Contract | type generation from committed `openapi.json` must produce no diff | schemathesis against running API | n/a |
| ML quality gate | n/a | golden set run; fail if sentiment macro F1 or linking precision drops more than 2 points from the last accepted report | n/a |
| E2E | Playwright against `docker compose` stack with seeded data | (same run) | (same run) |
| Build | Docker image | Docker image (slim, no ML libraries) | Docker image (local and CI only) |
| Deploy (main only) | Render auto-deploy from GitHub | Railway auto-deploy from GitHub (two services from one repo: api and worker start commands) | Railway Postgres; `backend migrate` runs as the api service's pre-deploy command |

Branching: trunk-based with short-lived feature branches, required review, squash merge. Releases tagged `v0.x` (Phase 1), `v1.x` (Phase 2), `v1.5` (Phase 3).

### 9.2 Environments

| Env | Where | Data | Email |
| --- | --- | --- | --- |
| local | laptop, Docker Compose | seeded plus live feeds | Mailpit (nothing leaves the machine) |
| ci | GitHub runners | fixtures only; Groq calls mocked | fake sender |
| prod | Render (UI) and Railway trial (backend, Postgres) | live | Brevo HTTP API, opted-in users |

### 9.3 Observability

- Structured JSON logs from both backend roles; UI server logs request ID passthrough.
- Prometheus metrics from HLD 8.2 plus digest metrics: `digest_built_total`, `digest_sent_total{provider,status}`, `digest_llm_fallback_total`, `digest_build_seconds`.
- Dashboards: a Grafana board (local) or Grafana Cloud free tier (hosted) with pipeline latency, source health, inference time, API p95, SSE clients, digest status.
- Uptime checks on `/health/ready` and the UI home page with a free uptime monitor.
- Error tracking: Sentry free tier for both UI and backend (optional, behind config).

### 9.4 Security checklist (verified in P3-BE-10)

- [ ] Argon2id with sensible parameters; no plaintext secrets in logs; `.env` never committed.
- [ ] Refresh token rotation with reuse detection; cookies `HttpOnly; Secure; SameSite=Lax`; CSRF token on cookie-authenticated mutations.
- [ ] Browser talks only to the Render origin; Next.js rewrites proxy `/api/v1/*` (including the SSE stream, with response buffering disabled) to Railway, so cookies stay first-party without `SameSite=None`.
- [ ] `GROQ_API_KEY` and `BREVO_API_KEY` exist only in Railway environment variables.
- [ ] Every private query filters by the token's user ID in the repository layer; cross-user access tests.
- [ ] Upload: size, row, type caps; formula-character neutralisation; XLSX read-only, no macros.
- [ ] Rate limits on auth, upload and SSE.
- [ ] Email: unsubscribe tokens signed and expiring; webhook signatures verified; suppressions honoured before every send.
- [ ] Dependency and container image scanning in CI.

### 9.5 Documentation deliverables

README (setup, architecture diagram, known limitations, vocabulary rules), ADRs for every deviation from the HLD (ADR-11 three-service layout, ADR-12 Redis deferred, ADR-13 digest design and compliant framing, ADR-14 hosting on Render and Railway, ADR-15 Qwen on Groq instead of local FinBERT), runbook (restart, restore, pause a source, resend a digest), demo script.

---

## 10. Hosting plan: Render (UI) and Railway (backend and database)

Figures below come from the providers' public docs and pricing pages as checked in October 2026. Free tiers change often, so re-check before starting the trial.

### 10.1 Topology

| Piece | Where | Start command | RAM estimate |
| --- | --- | --- | --- |
| UI service | Render free web service, `geotrade-ai.onrender.com` | `next start` | about 200 to 300 MB (Render free limit 512 MB) |
| Backend api | Railway service from the repo | `backend api` (pre-deploy: `backend migrate`) | about 200 to 250 MB |
| Backend worker | Railway service from the same repo | `backend worker` | about 250 to 350 MB (no ML libraries) |
| Database | Railway Postgres | managed | about 200 to 300 MB |

This uses exactly three Railway services, within the trial's limits, plus one Render service.

### 10.2 What the free plans mean for this project

**Railway trial**
- 30 days with a one-time $5 credit; each service is limited to 1 GB RAM and shared CPU during the trial.
- After 30 days or once the $5 is spent, the account drops to the Free plan: $1 of credit a month and 0.5 GB RAM per service.
- RAM is billed at $10 per GB per month. At about 0.8 GB across the three services, RAM alone costs roughly $8 a month, so the $5 credit will likely last **about 2 to 3 weeks** of always-on running, not the full 30 days.
- Railway deletes volumes created by trial accounts 30 days after the credits expire, so the hosted database does not outlive the trial.
- Outbound SMTP is blocked on free, trial and hobby plans. The backend sends through Brevo's HTTP API, which is unaffected.

**Render free (UI)**
- 512 MB RAM; the service spins down after 15 minutes without traffic and takes about a minute to wake.
- 750 free instance hours per workspace per month, enough for one always-available service.
- The free `onrender.com` subdomain includes HTTPS.

### 10.3 Groq budget for Qwen3-32B

Groq's free tier is limited by rate, not money. For `qwen/qwen3-32b` it is reported at about 60 requests per minute and about 1,000 requests per day, with a per-minute token cap; limits apply per organisation, not per key. Check the limits page in the Groq console for the live numbers.

| Use | Batching | Daily requests (cap) |
| --- | --- | --- |
| Headline scoring | 10 headline-entity pairs per request | 150 |
| "Why this matters" | 10 articles per request, only for high-impact or held stocks | 50 |
| Entity-linking fallback | 5 ambiguous articles per request | 30 |
| Daily Pulse narratives | 1 per opted-in user | 300 |
| Plain-English alert rules | on demand | 50 |
| Re-scoring fallbacks overnight | 10 per request | 150 |
| Reserve | | 270 |

The `llm_usage` table enforces these caps. When a cap is hit, that purpose drops to its template or keyword fallback until midnight IST. Qwen3's thinking mode is switched off for all calls to save tokens and keep latency low.

### 10.4 Recommended timeline for the trial

1. Weeks 1 to 10: build and test everything locally with Docker Compose. This is free, has no limits, and uses Mailpit so no real emails go out.
2. Deploy the UI to Render early (week 4), pointed at a local tunnel or the mock server, to catch build problems.
3. Start the Railway trial **2 to 3 weeks before the final evaluation**, then deploy, seed and run the 5-day digest soak.
4. Keep the laptop Docker Compose setup ready on demo day as the backup.
5. Before the trial ends, export the database (`backend export` plus `pg_dump`) if you want to keep the data.

### 10.5 If the Railway credit runs out early

| Option | Change needed | Trade-off |
| --- | --- | --- |
| Laptop demo | None, same Compose file | Not reachable by others unless you use a tunnel such as Cloudflare Tunnel (free) |
| Supabase free Postgres plus Railway Free plan for api and worker | Change `DATABASE_URL` | Each Railway service limited to 0.5 GB; tight but feasible without ML libraries |
| Railway Hobby ($5 a month) | None | Small paid cost; keeps everything running |

---

## 11. More AI features to consider

Rows 5, 7 and 8 are **selected for Phase 3** (tasks P3-BE-08, P3-BE-12, P3-BE-13). The rest are future ideas. Ideas that need local ML models or embeddings are marked, since v2 has no local ML layer; they would need an API-based alternative or more RAM. Every feature keeps the "signals, not advice" framing, is measurable, and can be switched off.

| # | Feature | What it does | How to build it | Effort | Compliance or quality note |
| --- | --- | --- | --- | --- | --- |
| 1 | **Ask GeoTrade-AI (grounded Q&A)** | Chat box: "What happened with HDFC Bank this week?" or "Why is my IT exposure negative?" answered only from stored stories, with citations | Needs embeddings (pgvector plus an embedding API). Retrieve top canonical stories plus the user's portfolio snapshot, LLM answer with mandatory citations, same validator as 8.6 | M | Refuse forward-looking questions ("will it go up?") with a polite explanation |
| 2 | **Fine-tuned Indian financial sentiment model** | Better accuracy on Indian phrasing (crore, lakh, PSU, SEBI order, promoter pledge) | Needs local ML (not in v2). Fine-tune a small model on the golden set plus Qwen-labelled data; compare on held-out golden data; register as a new `model_versions` row | M | Publish before and after numbers on the evaluation page |
| 3 | **Entity-targeted (aspect) sentiment** | Correct tone when one headline is good for one company and bad for another ("X wins contract over Y") | Sentence-pair classification with the entity as the first segment, trained on per-entity labels from the golden set | M | Directly improves impact accuracy for multi-company headlines |
| 4 | **Historical event studies** | "After the last 14 regulatory orders on NIFTY 50 banks, the median next-5-session move was ..." shown on the article drawer | Event-study maths on stored events and prices (abnormal return vs NIFTY), grouped by event type and sector, refreshed nightly | M | Present as history with sample size and spread, never as an expectation |
| 5 | **Anomaly detection on coverage and tone** (selected) | Flags unusual bursts ("news volume on TATAMOTORS is 4 sigma above normal") before sentiment fully reacts | Rolling z-scores per ticker as a baseline, then seasonal decomposition or isolation forest; feeds attention and alerts | S | Cheap and explainable |
| 6 | **Story timelines and narrative tracking** | Groups clusters about the same ongoing saga (a merger, a probe) into a timeline with a running summary | Cluster-of-clusters using embeddings plus shared entities over weeks; LLM summary updated incrementally | M | Great for Persona B (learners) |
| 7 | **Natural-language alert rules** (selected) | "Tell me if any bank I hold gets RBI news" becomes a structured alert rule | LLM converts text to the existing `alert_rules.params` JSON schema; user confirms the parsed rule before saving | S | The model only proposes; the deterministic engine decides |
| 8 | **Rumour, hedge and credibility scoring** (selected) | Down-weights "sources say", "may consider", single-outlet scoops; boosts confirmed multi-source stories | Classifier on hedging cues plus cluster source count; feeds the severity factor | S | Reduces false alarms in the digest |
| 9 | **Regional-language news** | Ingests Hindi and other Indian-language business coverage | Translation with an open model (for example AI4Bharat IndicTrans2) before linking and scoring, or multilingual embeddings for dedupe | L | Large coverage gain; needs its own golden set |
| 10 | **Filings and results summariser** | Plain-language summary of NSE corporate announcements and quarterly results | Ingest permitted public announcement data, extract key figures (revenue, PAT, margins vs last year) with a structured-output LLM, validate numbers against the source text | L | Check terms of use for each data source first |
| 11 | **Macro sensitivity explainer** | "Your portfolio's news exposure to crude oil is high: 3 holdings are commonly linked to crude headlines" | Co-occurrence of holdings with macro and commodity entities, plus sector mapping; displayed as exposure, not as a forecast | M | Matches the macro roadmap item in the overview |
| 12 | **Audio Daily Pulse** | 60-second spoken version of the digest for commuters | Open-source TTS on the template narrative, cached MP3 linked from the email | S | Same validated text as the email |
| 13 | **Human-in-the-loop labelling** | Admin screen to label low-confidence or disagreeing predictions, growing the golden set every week | Active-learning queue: pick items where Qwen and the keyword scorer disagree or confidence is low | S | Improves every model above over time |
| 14 | **Model and data drift monitoring** | Detects when feed style or vocabulary shifts degrade the model | Track prediction distribution, confidence and linking coverage weekly; alert when they move beyond thresholds | S | Turns "measures itself" into an ongoing practice |

A sensible order after the project: 13 (labelling), 4 (event studies), 12 (audio pulse), then the larger items.

---

## 12. Risks, open questions and appendices

### 12.1 Additional risks introduced by this plan

| Risk | Likelihood | Impact | Mitigation |
| --- | --- | --- | --- |
| Digest is read as investment advice | Medium | High | Compliant framing (2.2), banned-vocabulary validator, disclaimer in every email, legal review before public launch |
| Free email quota exceeded | Medium | Low | Quota guard marks overflow as skipped; in-app `/digest` page always available; upgrade path documented |
| Emails land in spam | Medium | Medium | Own domain, SPF, DKIM, DMARC, opt-in only, one-click unsubscribe, no tracking pixels, plain-text part |
| LLM invents facts in the narrative | Medium | High | Snapshot-only input, ticker and number validator, template fallback, `narrative_source` recorded |
| Railway credit runs out before evaluation | High | High | Start the trial late (10.4); laptop backup; fallback options in 10.5 |
| Groq rate limit or outage | Medium | Medium | Daily budget table, keyword fallback, overnight re-scoring |
| Groq retires or renames the Qwen model | Medium | Low | Model name in config; `LlmClient` interface; golden-set check after any change |
| Brevo sender rewrite sends emails to spam | High | Low | Mark as not spam; `/digest` page as the reliable copy; optional domain later |
| Duplicate or missing digests | Low | Medium | `UNIQUE (user_id, session_date)`, outbox pattern, sweep job, admin rebuild without resend |

### 12.2 Remaining questions

1. When is the final evaluation date? This fixes the Railway trial start date (10.4).
2. Which email addresses should be the test users for the digest soak?

### 12.3 Appendix A: new environment variables

| Variable | Service | Purpose |
| --- | --- | --- |
| `DATABASE_URL` | backend | Postgres connection |
| `JWT_SECRET`, `REFRESH_TOKEN_PEPPER` | backend | Auth |
| `CORS_ORIGINS`, `PUBLIC_WEB_URL` | backend | Web origin and links in emails |
| `ENABLE_LLM`, `LLM_PROVIDER=groq`, `LLM_MODEL=qwen/qwen3-32b`, `GROQ_API_KEY`, `LLM_DAILY_BUDGET` | backend | Qwen scoring, explanations, narratives, rule parsing |
| `ENABLE_DIGEST`, `DIGEST_BUILD_TIME_IST`, `DIGEST_DEFAULT_SEND_TIME_IST` | backend | Digest scheduling |
| `EMAIL_PROVIDER=brevo`, `BREVO_API_KEY`, `EMAIL_FROM=samvam0821@gmail.com`, `EMAIL_FROM_NAME=GeoTrade-AI Daily Pulse`, `EMAIL_DAILY_QUOTA=300` | backend | Sending |
| `ENABLE_WEEKLY_DIGEST`, `WEEKLY_DIGEST_TIME_IST=09:00` | backend | Saturday recap |
| `UNSUBSCRIBE_TOKEN_SECRET` | backend | Signed unsubscribe links |
| `NEXT_PUBLIC_API_BASE=/api/v1`, `BACKEND_URL` (Railway URL used by rewrites) | ui | Same-origin proxy to the backend |
| `POSTGRES_USER`, `POSTGRES_PASSWORD`, `POSTGRES_DB` | database | Instance credentials |

### 12.4 Appendix B: demo script (final review)

1. Open the overview: live ticker, freshness pill, top movers.
2. Open RELIANCE: price and sentiment chart, event markers, article drawer with "how we scored this".
3. Log in as demo user: portfolio dashboard, flagged holdings, Needs Attention.
4. Operator panel: inject a negative regulatory headline for a held stock; watch the stage trace, toast and reorder.
5. Open `/digest`: today's Daily Pulse; send a test email to yourself from the admin digest panel and open it on a phone.
6. Evaluation page: golden-set metrics, baseline comparison, backtest with caveats.
7. Pipeline health: latency median and p95, source states.

### 12.5 Appendix C: per-phase deliverable checklist

**Phase 1:** database image and migrations 0001 to 0004, idempotent seeds, full ingestion-to-aggregation pipeline, price sync, public API and SSE, all public pages, minimal demo panel, golden-v0 report, CI.

**Phase 2:** migrations 0005 to 0008, auth, portfolio import and dashboard, attention, related, watchlist, alerts with private SSE, evaluation and backtest, admin pages, contract and E2E tests.

**Phase 3:** migrations 0009 and 0010, daily and weekly Pulse emails, Qwen explanations and fallback linking, news-spike detection, rumour and credibility scoring, plain-English alert rules, retention, load and security testing, Render and Railway deployment, recorded demo.
