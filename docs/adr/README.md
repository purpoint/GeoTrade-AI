# Architecture decisions (deviations from the HLD)

**ADR-11: three services.** UI (Next.js), backend (one image, `backend api` and `backend worker`
roles) and PostgreSQL. The worker shares models, repositories and config with the api; an
import-linter contract keeps the api from importing worker code.

**ADR-12: Redis deferred.** LISTEN/NOTIFY wakes SSE, an in-process TTL cache serves hot reads, the
status column is the pipeline queue and the digest outbox uses `SKIP LOCKED`. The Phase 3 load test
(docs/perf/phase3-load.md) shows one api process far inside the targets, so Redis is only needed if the
api scales out (rate limits, cache and SSE caps are per process).

**ADR-13: digest design and compliant framing.** The Daily Pulse says "holdings to review" and
"positive momentum to watch", never buy or sell; every section shows its evidence and the disclaimer.
Each delivery freezes a snapshot (and its narrative) at build time, so the email, `/digest` and any
resend are the same document. Qwen may write the summary only from the snapshot facts, and a validator
rejects unknown tickers or numbers and banned words (`data/reference/vocabulary.json`). Email is
opt-in with recorded consent, one-click unsubscribe uses signed expiring tokens, and there is no
tracking. The plan put email templates in `services/ui/emails` as React Email; they are Jinja2 in
`services/backend/src/geotrade_ai/digest/templates` instead, which avoids a Node build step for the
backend with the same inline-CSS, 600 px, light-only design.

**ADR-14: hosting on Render and Railway.** Render's free plan serves the UI and proxies the API so
cookies stay first-party; Railway's trial runs api, worker and Postgres. Railway blocks SMTP, so
production email uses Brevo's HTTP API. `infra/compose/compose.prod.yml` is the self-hosted fallback.

**ADR-15: Qwen on Groq instead of local FinBERT.** No ML libraries in the image keeps the worker near
300 MB. Every LLM feature (scoring, "why this matters", linking fallback, digest summary, plain-English
rules) has a deterministic fallback, a daily cap per purpose in `llm_usage`, and a cache in `llm_cache`.
Groq shut down Qwen3-32B on 17 July 2026; the model is `qwen/qwen3.8-27b` by config.
