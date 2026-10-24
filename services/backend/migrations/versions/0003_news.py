"""news tables: sources, clusters, articles, entities, scores, pipeline bookkeeping

llm_cache and llm_usage are pulled forward from 0008/0010 because Phase 1 Qwen scoring needs them.

Revision ID: 0003_news
Revises: 0002_reference
"""

from alembic import op

revision = "0003_news"
down_revision = "0002_reference"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute("""
    CREATE TABLE sources (
      id               text PRIMARY KEY,
      name             text NOT NULL,
      adapter          text NOT NULL,
      url              text NOT NULL,
      domain           text NOT NULL,
      enabled          boolean NOT NULL DEFAULT true,
      poll_interval_s  integer NOT NULL DEFAULT 60,
      priority         smallint NOT NULL DEFAULT 50,
      etag             text,
      last_modified    text,
      created_at       timestamptz NOT NULL DEFAULT now(),
      updated_at       timestamptz NOT NULL DEFAULT now()
    );

    CREATE TABLE source_health (
      source_id             text PRIMARY KEY REFERENCES sources(id) ON DELETE CASCADE,
      state                 source_state NOT NULL DEFAULT 'healthy',
      consecutive_failures  integer NOT NULL DEFAULT 0,
      last_success_at       timestamptz,
      last_failure_at       timestamptz,
      last_error            text,
      circuit_open_until    timestamptz,
      last_item_count       integer,
      fetched_total         bigint NOT NULL DEFAULT 0,
      updated_at            timestamptz NOT NULL DEFAULT now()
    );

    CREATE TABLE story_clusters (
      id                    uuid PRIMARY KEY,
      canonical_article_id  uuid,
      first_seen_at         timestamptz NOT NULL,
      last_seen_at          timestamptz NOT NULL,
      article_count         integer NOT NULL DEFAULT 1,
      source_count          integer NOT NULL DEFAULT 1,
      created_at            timestamptz NOT NULL DEFAULT now(),
      updated_at            timestamptz NOT NULL DEFAULT now()
    );

    CREATE TABLE articles (
      id                uuid PRIMARY KEY,
      source_id         text NOT NULL REFERENCES sources(id),
      cluster_id        uuid REFERENCES story_clusters(id),
      url               text NOT NULL,
      url_hash          text NOT NULL,
      title             text NOT NULL,
      title_norm        text NOT NULL,
      title_hash        text NOT NULL,
      summary           text,
      language          text NOT NULL DEFAULT 'en',
      published_at      timestamptz NOT NULL,
      time_estimated    boolean NOT NULL DEFAULT false,
      fetched_at        timestamptz NOT NULL DEFAULT now(),
      status            article_status NOT NULL DEFAULT 'fetched',
      attempts          smallint NOT NULL DEFAULT 0,
      next_attempt_at   timestamptz NOT NULL DEFAULT now(),
      last_error        text,
      stage_timestamps  jsonb NOT NULL DEFAULT '{}'::jsonb,
      relevance         real,
      link_trace        jsonb,
      is_simulated      boolean NOT NULL DEFAULT false,
      created_at        timestamptz NOT NULL DEFAULT now(),
      updated_at        timestamptz NOT NULL DEFAULT now()
    );
    CREATE UNIQUE INDEX ux_articles_url_hash ON articles(url_hash);
    CREATE INDEX ix_articles_title_hash ON articles(title_hash, published_at);
    CREATE INDEX ix_articles_title_trgm ON articles USING gin (title_norm gin_trgm_ops);
    CREATE INDEX ix_articles_pending ON articles(next_attempt_at)
      WHERE status IN ('fetched','deduped','linked','scored');
    CREATE INDEX ix_articles_published ON articles(published_at DESC);
    CREATE INDEX ix_articles_cluster ON articles(cluster_id);

    -- one canonical article per cluster; deferred so both rows can be inserted in one transaction
    ALTER TABLE story_clusters ADD CONSTRAINT fk_story_clusters_canonical
      FOREIGN KEY (canonical_article_id) REFERENCES articles(id) DEFERRABLE INITIALLY DEFERRED;

    CREATE TABLE article_entities (
      article_id   uuid NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
      entity_type  entity_type NOT NULL,
      entity_id    text NOT NULL,
      is_primary   boolean NOT NULL DEFAULT false,
      confidence   real NOT NULL,
      PRIMARY KEY (article_id, entity_type, entity_id)
    );
    CREATE INDEX ix_article_entities_entity ON article_entities(entity_type, entity_id, article_id);

    CREATE TABLE model_versions (
      id           text PRIMARY KEY,
      kind         text NOT NULL,
      provider     text NOT NULL,
      description  text,
      created_at   timestamptz NOT NULL DEFAULT now()
    );

    CREATE TABLE article_scores (
      article_id          uuid PRIMARY KEY REFERENCES articles(id) ON DELETE CASCADE,
      model_version_id    text NOT NULL REFERENCES model_versions(id),
      label               sentiment_label NOT NULL,
      p_pos               real NOT NULL,
      p_neu               real NOT NULL,
      p_neg               real NOT NULL,
      score               real NOT NULL,
      confidence          real NOT NULL,
      event_type          event_type NOT NULL,
      severity            real NOT NULL,
      hedged              boolean NOT NULL DEFAULT false,
      rationale           text,
      explanation         text NOT NULL,
      explanation_source  explanation_source NOT NULL DEFAULT 'template',
      is_fallback         boolean NOT NULL DEFAULT false,
      scored_at           timestamptz NOT NULL DEFAULT now(),
      updated_at          timestamptz NOT NULL DEFAULT now()
    );
    CREATE INDEX ix_article_scores_fallback ON article_scores(scored_at) WHERE is_fallback;

    CREATE TABLE pipeline_events (
      id           bigserial PRIMARY KEY,
      article_id   uuid,
      stage        text NOT NULL,
      status       text NOT NULL,
      duration_ms  integer,
      detail       jsonb,
      created_at   timestamptz NOT NULL DEFAULT now()
    );
    CREATE INDEX ix_pipeline_events_article ON pipeline_events(article_id, created_at);

    CREATE TABLE dead_letters (
      id           bigserial PRIMARY KEY,
      article_id   uuid NOT NULL REFERENCES articles(id) ON DELETE CASCADE,
      stage        text NOT NULL,
      error        text NOT NULL,
      attempts     integer NOT NULL,
      created_at   timestamptz NOT NULL DEFAULT now(),
      resolved_at  timestamptz
    );

    CREATE TABLE llm_cache (
      key         text PRIMARY KEY,
      model       text NOT NULL,
      response    jsonb NOT NULL,
      created_at  timestamptz NOT NULL DEFAULT now()
    );

    CREATE TABLE llm_usage (
      day       date NOT NULL,
      purpose   text NOT NULL,
      requests  integer NOT NULL DEFAULT 0,
      tokens    integer NOT NULL DEFAULT 0,
      PRIMARY KEY (day, purpose)
    );
    """)


def downgrade() -> None:
    op.execute("""
    DROP TABLE llm_usage, llm_cache, dead_letters, pipeline_events, article_scores, model_versions,
      article_entities;
    ALTER TABLE story_clusters DROP CONSTRAINT fk_story_clusters_canonical;
    DROP TABLE articles, story_clusters, source_health, sources;
    """)
