# Deploying GeoTrade-AI (P3-BE-11, P3-UI-07)

Topology (plan section 10): the UI on Render's free plan; the backend api, the backend worker and
PostgreSQL on Railway. The browser only talks to the Render origin; Next.js rewrites `/api/v1/*`
(including the SSE stream) to the Railway api, so login cookies stay first-party.

Start the Railway trial 2 to 3 weeks before the final evaluation: the $5 credit lasts about that long
with three always-on services. Keep the laptop Compose stack ready as the demo-day backup.

## 1. Railway: database, api, worker

1. New project, then **Add PostgreSQL**. In its Data tab run, once:
   ```sql
   CREATE EXTENSION IF NOT EXISTS pg_trgm;
   CREATE EXTENSION IF NOT EXISTS citext;
   ALTER SYSTEM SET work_mem = '8MB';
   ALTER SYSTEM SET idle_in_transaction_session_timeout = '60s';
   SELECT pg_reload_conf();
   ```
2. **New service from GitHub repo** (`purpoint/GeoTrade-AI`), name it `api`. Settings, Config-as-code
   path: `infra/railway/api.json` (Dockerfile build, `backend api`, pre-deploy `backend migrate && backend seed --demo`,
   health check `/api/v1/health/ready`). Generate a public domain under Networking.
3. Same repo again, name it `worker`, config path `infra/railway/worker.json` (`backend worker`, no domain).
4. Shared variables (Project Settings, Shared Variables), referenced by both services:

| Variable | Value |
| --- | --- |
| `DATABASE_URL` | `${{Postgres.DATABASE_URL}}` with the scheme changed to `postgresql+psycopg://` |
| `JWT_SECRET`, `REFRESH_TOKEN_PEPPER`, `UNSUBSCRIBE_TOKEN_SECRET` | 48 random characters each: `python -c "import secrets;print(secrets.token_urlsafe(48))"` |
| `COOKIE_SECURE` | `true` |
| `PUBLIC_WEB_URL`, `CORS_ORIGINS` | `https://geotrade-ai.onrender.com` |
| `OPERATOR_EMAIL`, `OPERATOR_PASSWORD` | your operator login |
| `ENABLE_LLM`, `GROQ_API_KEY`, `LLM_MODEL` | `true`, your Groq key, `qwen/qwen3.8-27b` |
| `EMAIL_PROVIDER`, `BREVO_API_KEY` | `brevo`, your Brevo API key (Railway blocks SMTP, so never `smtp`) |
| `EMAIL_FROM`, `EMAIL_FROM_NAME`, `EMAIL_DAILY_QUOTA` | `samvam0821@gmail.com`, `GeoTrade-AI Daily Pulse`, `300` |
| `EMAIL_WEBHOOK_SECRET` | random; also used in the Brevo webhook URL below |

   Per service: `DB_POOL_SIZE=10` on api, `DB_POOL_SIZE=5` on worker.

## 2. Render: UI

New, Blueprint, pick the repo: `render.yaml` creates the `geotrade-ai` web service (free plan,
Docker). Set `BACKEND_URL` to the Railway api domain (`https://<api>.up.railway.app`). Rewrites are
compiled at build time, so redeploy the UI after changing `BACKEND_URL`.

## 3. Brevo

1. Senders: add and verify `samvam0821@gmail.com`. Without a domain Brevo rewrites the visible sender
   and adds its footer; test users should mark the first Pulse "Not spam". `/digest` is the reliable copy.
2. Transactional, Webhooks: add `https://geotrade-ai.onrender.com/api/v1/webhooks/email/brevo?token=<EMAIL_WEBHOOK_SECRET>`
   for hard bounce, spam and unsubscribed. Bounces and complaints become suppressions.

## 4. Check it

```bash
curl -s https://geotrade-ai.onrender.com/api/v1/health/ready
```

Sign in as the operator, open Admin, Daily Pulse, and use "Send today's demo digest to me". Opt a test
account in from Settings, Email, then watch the 16:30 IST build and the send at the chosen time.
Run the k6 scripts in `docs/perf/` against the Railway api domain for the G3 numbers.

## 5. Backups

`.github/workflows/backup.yml` dumps the Railway database nightly (03:00 IST) and stores it as an
encrypted artifact for 14 days. Add repository secrets `RAILWAY_DATABASE_URL` (the public connection
URL, `postgresql://` scheme) and `BACKUP_PASSPHRASE`. The repository is public, so never upload an
unencrypted dump. Restore drill: `docs/runbook.md`.

## Self-hosted alternative

One VM with Docker: `DOMAIN=pulse.example.com docker compose -f compose.yaml -f infra/compose/compose.prod.yml up -d --build`.
Caddy gets a certificate for `DOMAIN`; only ports 80 and 443 are published; Mailpit is not started.
Set `BACKUP_RCLONE_REMOTE` (for example a Cloudflare R2 remote) to copy each nightly dump off the box.
