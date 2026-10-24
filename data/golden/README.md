# Golden sets

| File | What |
| --- | --- |
| `golden-v0.csv` | 150 labelled headlines (Phase 1). |
| `golden-v1.csv` | golden-v0 plus 150 more (300). Columns: id, headline, primary tickers (`;`-separated), sentiment label, event type. |
| `golden-v1-annotator2.csv` | 50 headlines from golden-v1 for a second, independent annotator. Fill the `label` column without looking at golden-v1; `backend evaluate --golden golden-v1` then reports Cohen's kappa. Until it is filled, agreement is reported as pending. |
| `dedupe-pairs-v1.csv` | Labelled title pairs (same story or not) for dedupe precision and recall. |
| `reports/` | JSON written by `backend evaluate` and `backend backtest` (not committed). |

All labels so far come from one annotator (the project team); treat the scores as optimistic until the second annotation is done.
