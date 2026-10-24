# Phase 1 query plans (P1-DB-08)

Captured on 2026-10-24 against the local Compose database after `backend seed --history` plus about a minute of live feeds (261 articles). At this size the planner could pick sequential scans; every hot query still uses the intended index. Re-run on the Railway database after the 5-day soak in Phase 3, when the tables are realistically sized.

```bash
psql -f services/database/scripts/explain-queries.sql
```

| Query | Index used | Execution time |
| --- | --- | --- |
| News explorer first page | `ix_articles_published` | 0.23 ms |
| News for one ticker | `ix_article_entities_entity`, then `articles_pkey` | 0.17 ms |
| Pipeline claim (`FOR UPDATE SKIP LOCKED`) | `ix_articles_pending` (partial) | 0.02 ms |
| Dedupe L3 candidates | `ix_articles_published` (the trigram GIN takes over once the 6-hour window is large) | 0.15 ms |
| Latest 1h bucket per stock | `ix_sentiment_buckets_latest` | 0.15 ms |

## Raw output

```
 articles 
----------
      261
(1 row)

--- news explorer first page
                                                QUERY PLAN                                                 
-----------------------------------------------------------------------------------------------------------
 Limit (actual time=0.205..0.209 rows=21 loops=1)
   Buffers: shared hit=45
   ->  Incremental Sort (actual time=0.203..0.205 rows=21 loops=1)
         Sort Key: published_at DESC, id DESC
         Presorted Key: published_at
         Full-sort Groups: 1  Sort Method: quicksort  Average Memory: 58kB  Peak Memory: 58kB
         Buffers: shared hit=45
         ->  Index Scan using ix_articles_published on articles (actual time=0.014..0.142 rows=22 loops=1)
               Filter: (status = 'aggregated'::article_status)
               Rows Removed by Filter: 17
               Buffers: shared hit=36
 Planning:
   Buffers: shared hit=112
 Planning Time: 0.405 ms
 Execution Time: 0.231 ms
(15 rows)

--- news for one ticker
                                                    QUERY PLAN                                                     
-------------------------------------------------------------------------------------------------------------------
 Limit (actual time=0.115..0.118 rows=8 loops=1)
   Buffers: shared hit=29
   ->  Sort (actual time=0.114..0.116 rows=8 loops=1)
         Sort Key: a.published_at DESC, a.id DESC
         Sort Method: quicksort  Memory: 37kB
         Buffers: shared hit=29
         ->  Nested Loop (actual time=0.050..0.088 rows=8 loops=1)
               Buffers: shared hit=29
               ->  Bitmap Heap Scan on article_entities (actual time=0.035..0.039 rows=8 loops=1)
                     Recheck Cond: ((entity_type = 'stock'::entity_type) AND (entity_id = 'INFY'::text))
                     Heap Blocks: exact=3
                     Buffers: shared hit=5
                     ->  Bitmap Index Scan on ix_article_entities_entity (actual time=0.029..0.030 rows=8 loops=1)
                           Index Cond: ((entity_type = 'stock'::entity_type) AND (entity_id = 'INFY'::text))
                           Buffers: shared hit=2
               ->  Index Scan using articles_pkey on articles a (actual time=0.005..0.005 rows=1 loops=8)
                     Index Cond: (id = article_entities.article_id)
                     Filter: (status = 'aggregated'::article_status)
                     Buffers: shared hit=24
 Planning:
   Buffers: shared hit=132
 Planning Time: 0.601 ms
 Execution Time: 0.172 ms
(23 rows)

--- pipeline claim
                                               QUERY PLAN                                               
--------------------------------------------------------------------------------------------------------
 Limit (actual time=0.008..0.008 rows=0 loops=1)
   Buffers: shared hit=2
   ->  LockRows (actual time=0.008..0.008 rows=0 loops=1)
         Buffers: shared hit=2
         ->  Index Scan using ix_articles_pending on articles (actual time=0.008..0.008 rows=0 loops=1)
               Index Cond: (next_attempt_at <= now())
               Filter: (status = 'fetched'::article_status)
               Buffers: shared hit=2
 Planning:
   Buffers: shared hit=31
 Planning Time: 0.104 ms
 Execution Time: 0.019 ms
(12 rows)

--- dedupe L3 trigram candidates
                                                      QUERY PLAN                                                      
----------------------------------------------------------------------------------------------------------------------
 Limit (actual time=0.140..0.140 rows=0 loops=1)
   Buffers: shared hit=16
   ->  Sort (actual time=0.139..0.139 rows=0 loops=1)
         Sort Key: (similarity(title_norm, 'infosys wins 2 billion deal from us bank'::text)) DESC
         Sort Method: quicksort  Memory: 25kB
         Buffers: shared hit=16
         ->  Bitmap Heap Scan on articles (actual time=0.135..0.135 rows=0 loops=1)
               Recheck Cond: ((published_at >= (now() - '06:00:00'::interval)) AND (published_at <= now()))
               Filter: ((cluster_id IS NOT NULL) AND (title_norm % 'infosys wins 2 billion deal from us bank'::text))
               Rows Removed by Filter: 17
               Heap Blocks: exact=12
               Buffers: shared hit=13
               ->  Bitmap Index Scan on ix_articles_published (actual time=0.003..0.003 rows=21 loops=1)
                     Index Cond: ((published_at >= (now() - '06:00:00'::interval)) AND (published_at <= now()))
                     Buffers: shared hit=1
 Planning:
   Buffers: shared hit=27
 Planning Time: 1.006 ms
 Execution Time: 0.151 ms
(19 rows)

--- latest 1h bucket per stock
                                                                     QUERY PLAN                                                                      
-----------------------------------------------------------------------------------------------------------------------------------------------------
 Unique (actual time=0.124..0.135 rows=42 loops=1)
   Buffers: shared hit=12
   ->  Sort (actual time=0.123..0.127 rows=145 loops=1)
         Sort Key: ticker, bucket_start DESC
         Sort Method: quicksort  Memory: 31kB
         Buffers: shared hit=12
         ->  Bitmap Heap Scan on sentiment_buckets (actual time=0.027..0.069 rows=145 loops=1)
               Recheck Cond: ((bucket_size = '1h'::bucket_size) AND (bucket_start <= now()) AND (bucket_start > (now() - '72:00:00'::interval)))
               Heap Blocks: exact=7
               Buffers: shared hit=9
               ->  Bitmap Index Scan on ix_sentiment_buckets_latest (actual time=0.021..0.022 rows=155 loops=1)
                     Index Cond: ((bucket_size = '1h'::bucket_size) AND (bucket_start <= now()) AND (bucket_start > (now() - '72:00:00'::interval)))
                     Buffers: shared hit=2
 Planning:
   Buffers: shared hit=54
 Planning Time: 0.101 ms
 Execution Time: 0.149 ms
(17 rows)

```
