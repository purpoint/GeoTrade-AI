-- P1-DB-09. Run: psql -v ON_ERROR_STOP=1 -f verify-integrity.sql   (fails if any check finds violations)
CREATE TEMP TABLE integrity AS
SELECT 'cluster canonical missing or outside cluster' AS check_name, count(*) AS violations
  FROM story_clusters c LEFT JOIN articles a ON a.id = c.canonical_article_id
 WHERE a.id IS NULL OR a.cluster_id IS DISTINCT FROM c.id
UNION ALL
SELECT 'more than one canonical article per cluster', count(*) FROM (
  SELECT cluster_id FROM articles WHERE cluster_id IS NOT NULL AND status <> 'duplicate'
  GROUP BY cluster_id HAVING count(*) > 1) x
UNION ALL
SELECT 'cluster article_count drift', count(*) FROM story_clusters c
 WHERE c.article_count <> (SELECT count(*) FROM articles a WHERE a.cluster_id = c.id)
UNION ALL
SELECT 'score on an article that never reached scoring', count(*)
  FROM article_scores s JOIN articles a ON a.id = s.article_id
 WHERE a.status NOT IN ('scored', 'aggregated', 'dead_letter')
UNION ALL
SELECT 'visible article without a score', count(*)
  FROM articles a LEFT JOIN article_scores s ON s.article_id = a.id
 WHERE a.status = 'aggregated' AND s.article_id IS NULL
UNION ALL
SELECT 'simulated flag on a real feed article', count(*)
  FROM articles a JOIN sources src ON src.id = a.source_id
 WHERE a.is_simulated AND src.adapter <> 'demo'
UNION ALL
SELECT 'real article attributed to the demo source', count(*)
  FROM articles a WHERE a.source_id = 'demo' AND NOT a.is_simulated
UNION ALL
SELECT 'simulated price candles', count(*) FROM price_candles WHERE is_simulated;

SELECT * FROM integrity ORDER BY violations DESC, check_name;

DO $$
BEGIN
  IF EXISTS (SELECT 1 FROM integrity WHERE violations > 0) THEN
    RAISE EXCEPTION 'integrity check failed';
  END IF;
END $$;
