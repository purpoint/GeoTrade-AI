-- P1-DB-08: plans for the hot queries. Output is recorded in docs/perf/phase1-query-plans.md.
\echo '--- news explorer first page'
EXPLAIN (ANALYZE, BUFFERS, COSTS OFF)
SELECT * FROM articles WHERE status = 'aggregated' ORDER BY published_at DESC, id DESC LIMIT 21;

\echo '--- news for one ticker'
EXPLAIN (ANALYZE, BUFFERS, COSTS OFF)
SELECT a.* FROM articles a WHERE a.status = 'aggregated' AND a.id IN (
  SELECT article_id FROM article_entities WHERE entity_type = 'stock' AND entity_id = 'INFY')
ORDER BY a.published_at DESC, a.id DESC LIMIT 21;

\echo '--- pipeline claim'
EXPLAIN (ANALYZE, BUFFERS, COSTS OFF)
SELECT * FROM articles WHERE status = 'fetched' AND next_attempt_at <= now()
ORDER BY next_attempt_at LIMIT 50 FOR UPDATE SKIP LOCKED;

\echo '--- dedupe L3 trigram candidates'
EXPLAIN (ANALYZE, BUFFERS, COSTS OFF)
SELECT id FROM articles WHERE cluster_id IS NOT NULL
  AND published_at BETWEEN now() - interval '6 hours' AND now()
  AND title_norm % 'infosys wins 2 billion deal from us bank'
ORDER BY similarity(title_norm, 'infosys wins 2 billion deal from us bank') DESC LIMIT 20;

\echo '--- latest 1h bucket per stock'
EXPLAIN (ANALYZE, BUFFERS, COSTS OFF)
SELECT DISTINCT ON (ticker) ticker, raw_sum, bucket_start FROM sentiment_buckets
WHERE bucket_size = '1h' AND bucket_start <= now() AND bucket_start > now() - interval '72 hours'
ORDER BY ticker, bucket_start DESC;
