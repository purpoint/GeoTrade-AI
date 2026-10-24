"""Prometheus metrics (HLD 8.2). The api serves them on /metrics; the worker on its own port."""

from prometheus_client import Counter, Gauge, Histogram

ARTICLES_FETCHED = Counter("articles_fetched_total", "New articles stored", ["source"])
ARTICLES_SKIPPED = Counter("articles_skipped_total", "Feed items not stored", ["source", "reason"])
SOURCE_FETCHES = Counter("source_fetch_total", "Feed fetches", ["source", "result"])
STAGE_SECONDS = Histogram("pipeline_stage_seconds", "Time per stage batch", ["stage"])
STAGE_ARTICLES = Counter("pipeline_stage_articles_total", "Articles leaving a stage", ["stage", "outcome"])
DEAD_LETTERS = Counter("pipeline_dead_letters_total", "Articles dead-lettered", ["stage"])
INGEST_TO_VISIBLE = Histogram(
    "ingest_to_visible_seconds",
    "Feed publish time (or fetch time) to publicly visible",
    buckets=(5, 15, 30, 60, 90, 120, 180, 300, 600, 1800),
)
LLM_REQUESTS = Counter("llm_requests_total", "LLM requests", ["purpose", "result"])
LLM_FALLBACKS = Counter("llm_fallback_total", "Articles scored by the keyword fallback", ["reason"])
PIPELINE_BACKLOG = Gauge("pipeline_backlog", "Articles waiting per status", ["status"])
HTTP_REQUESTS = Histogram("http_request_seconds", "API request latency", ["route", "status"])
SSE_CLIENTS = Gauge("sse_clients", "Connected SSE clients")
DIGEST_BUILT = Counter("digest_built_total", "Digest snapshots built", ["kind", "result"])
DIGEST_SENT = Counter("digest_sent_total", "Digest deliveries leaving the outbox", ["provider", "status"])
DIGEST_LLM_FALLBACK = Counter("digest_llm_fallback_total", "Digest narratives that fell back to the template")
DIGEST_BUILD_SECONDS = Histogram("digest_build_seconds", "Time to build one digest run", ["kind"])
