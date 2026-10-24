# Runbook

Local commands assume the Compose stack (`docker compose ...` from the repo root). On Railway use the
service's shell or `railway run`.

## Restart

```bash
docker compose restart backend-api backend-worker
docker compose logs -f --tail 100 backend-worker
```

The worker is safe to restart at any time: pipeline stages and the digest outbox claim rows with
`FOR UPDATE SKIP LOCKED`, and a digest marked `sending` is never sent twice (the 21:00 sweep marks a
stuck one failed instead).

## Pause or resume a feed

Admin, Pipeline health, the source's Pause button, or
`POST /api/v1/admin/sources/{source_id}/pause` (`resume`, `refresh`) as the operator.

## Resend or rebuild a digest

- Rebuild unsent digests for a date (idempotent, never resends): Admin, Daily Pulse, "Build / rebuild",
  or `docker compose exec backend-worker backend digest build --date 2026-10-26 --rebuild`.
- Send queued digests now instead of at their send time: `backend digest send --now`.
- A digest marked `failed` stays failed (the user can read it on `/digest`). To resend one on purpose,
  set it back to queued: `UPDATE digest_deliveries SET status='queued', attempts=0, send_after=now() WHERE id='...';`

## Backup and restore drill

Nightly dumps land in `./backups` (local) or as encrypted GitHub artifacts (Railway). To rehearse a
restore into a scratch database:

```bash
docker compose exec database createdb -U geotrade restore_drill
docker compose exec database pg_restore --no-owner -U geotrade -d restore_drill /backups/<file>.dump
docker compose exec database psql -U geotrade -d restore_drill -f /usr/local/bin/geotrade/verify-integrity.sql
docker compose exec database dropdb -U geotrade restore_drill
```

For a GitHub artifact: download it, then
`gpg --batch --pinentry-mode loopback --passphrase "$BACKUP_PASSPHRASE" -d <file>.dump.gpg > <file>.dump`
and `pg_restore --clean --if-exists --no-owner -d "$DATABASE_URL" <file>.dump`.

## Rotate a secret

- `JWT_SECRET` or `REFRESH_TOKEN_PEPPER`: everyone is signed out; nothing else breaks.
- `UNSUBSCRIBE_TOKEN_SECRET`: links in emails already sent stop working; users can still unsubscribe
  from Settings, Email.
- `GROQ_API_KEY`, `BREVO_API_KEY`: replace and restart; failures in between fall back (keyword scorer)
  or retry (digest outbox).
