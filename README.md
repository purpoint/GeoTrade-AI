# GeoTrade-AI

Indian business news for the NIFTY 50: ingested from RSS, deduplicated, linked to companies, scored for sentiment and event type, and aggregated into per-stock, per-sector and market indices shown next to prices.

**Not investment advice.** GeoTrade-AI summarises public news and signals. It never says buy, sell or target.

See [GeoTrade-AI_Implementation_Plan.md](GeoTrade-AI_Implementation_Plan.md) for the full plan. This repository currently implements **Phase 1** (release v0).

## Layout

```
services/database   PostgreSQL 16 image (pg_trgm, citext), backup and restore scripts
infra/compose       docker-compose.yml (the root compose.yaml includes it)
data/               reference data, golden set, recorded feed fixtures
```

## Run locally

```bash
cp .env.example .env
docker compose up --build
```
