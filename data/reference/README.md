# Reference data

Loaded by `backend seed --reference` with upserts, so re-running is safe.

| File | Notes |
| --- | --- |
| `companies.csv` | NIFTY 50 constituents (mid-2025 list). `market_cap_cr` is an approximate weight for sector and market indices, not a live figure. ISINs are left out until portfolio import (Phase 2) loads them from NSE's equity list. `TATAMOTORS` points at `TMPV.NS` after the 2025 demerger. |
| `aliases.csv` | `case_sensitive` aliases must match exactly (acronyms such as `ITC`, `BEL`); `is_ambiguous` aliases only count when another alias or a ticker for the same company also appears. |
| `negative_contexts.csv` | Phrases that cancel an overlapping alias match (for example `Reliance Power` is not `RELIANCE`). |
| `nse_holidays.csv` | Trading holidays; check against the NSE circular each December. |
| `sources.csv` | RSS feeds. Moneycontrol's public RSS has served April 2024 items for a long time; the max-age filter drops them, and the source is kept for health monitoring. |
