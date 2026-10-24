"""SQLAlchemy models shared by both roles. Must match migrations/ (tests/test_migrations.py checks drift)."""

import uuid
from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    REAL,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    SmallInteger,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, CITEXT, JSONB, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

ARTICLE_STATUSES = (
    "fetched", "deduped", "linked", "scored", "aggregated",
    "duplicate", "irrelevant", "dropped", "dead_letter",
)  # fmt: skip
# statuses the pipeline still has to move forward
PENDING_STATUSES = ("fetched", "deduped", "linked", "scored")
SENTIMENT_LABELS = ("positive", "neutral", "negative")
EVENT_TYPES = (
    "earnings", "guidance", "deal", "order_win", "regulatory", "legal", "management",
    "rating", "dividend", "capital", "macro", "operations", "other",
)  # fmt: skip
BUCKET_SIZES = ("5m", "1h", "1d")
CANDLE_INTERVALS = ("5m", "1d")
SOURCE_STATES = ("healthy", "degraded", "circuit_open", "paused")
ENTITY_TYPES = ("stock", "sector", "market")
EXPLANATION_SOURCES = ("template", "llm")


def _enum(values: tuple[str, ...], name: str) -> Enum:
    return Enum(*values, name=name, create_type=False)


ArticleStatus = _enum(ARTICLE_STATUSES, "article_status")
SentimentLabel = _enum(SENTIMENT_LABELS, "sentiment_label")
EventType = _enum(EVENT_TYPES, "event_type")
BucketSize = _enum(BUCKET_SIZES, "bucket_size")
CandleInterval = _enum(CANDLE_INTERVALS, "candle_interval")
SourceState = _enum(SOURCE_STATES, "source_state")
EntityType = _enum(ENTITY_TYPES, "entity_type")
ExplanationSource = _enum(EXPLANATION_SOURCES, "explanation_source")

TS = DateTime(timezone=True)


class Base(DeclarativeBase):
    pass


def _created() -> Mapped[datetime]:
    return mapped_column(TS, server_default=func.now())


def _updated() -> Mapped[datetime]:
    return mapped_column(TS, server_default=func.now())


# ---------- reference (0002) ----------


class Sector(Base):
    __tablename__ = "sectors"
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = _created()


class Company(Base):
    __tablename__ = "companies"
    ticker: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    sector_id: Mapped[str] = mapped_column(ForeignKey("sectors.id"))
    isin: Mapped[str | None] = mapped_column(Text, unique=True)
    yf_symbol: Mapped[str] = mapped_column(Text)
    market_cap_cr: Mapped[Decimal] = mapped_column(Numeric(14, 2), server_default="0")
    group_name: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[bool] = mapped_column(Boolean, server_default="true")
    updated_at: Mapped[datetime] = _updated()


class CompanyAlias(Base):
    __tablename__ = "company_aliases"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    ticker: Mapped[str] = mapped_column(ForeignKey("companies.ticker", ondelete="CASCADE"))
    alias: Mapped[str] = mapped_column(Text)
    case_sensitive: Mapped[bool] = mapped_column(Boolean, server_default="false")
    is_ambiguous: Mapped[bool] = mapped_column(Boolean, server_default="false")


class TradingDay(Base):
    __tablename__ = "trading_calendar"
    date: Mapped[date] = mapped_column(Date, primary_key=True)
    is_trading_day: Mapped[bool] = mapped_column(Boolean)
    note: Mapped[str | None] = mapped_column(Text)


# ---------- news (0003) ----------


class Source(Base):
    __tablename__ = "sources"
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text)
    adapter: Mapped[str] = mapped_column(Text)
    url: Mapped[str] = mapped_column(Text)
    domain: Mapped[str] = mapped_column(Text)
    enabled: Mapped[bool] = mapped_column(Boolean, server_default="true")
    poll_interval_s: Mapped[int] = mapped_column(Integer, server_default="60")
    priority: Mapped[int] = mapped_column(SmallInteger, server_default="50")
    etag: Mapped[str | None] = mapped_column(Text)
    last_modified: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class SourceHealth(Base):
    __tablename__ = "source_health"
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id", ondelete="CASCADE"), primary_key=True)
    state: Mapped[str] = mapped_column(SourceState, server_default="healthy")
    consecutive_failures: Mapped[int] = mapped_column(Integer, server_default="0")
    last_success_at: Mapped[datetime | None] = mapped_column(TS)
    last_failure_at: Mapped[datetime | None] = mapped_column(TS)
    last_error: Mapped[str | None] = mapped_column(Text)
    circuit_open_until: Mapped[datetime | None] = mapped_column(TS)
    last_item_count: Mapped[int | None] = mapped_column(Integer)
    fetched_total: Mapped[int] = mapped_column(BigInteger, server_default="0")
    updated_at: Mapped[datetime] = _updated()


class StoryCluster(Base):
    __tablename__ = "story_clusters"
    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True)
    canonical_article_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("articles.id", deferrable=True, initially="DEFERRED", use_alter=True)
    )
    first_seen_at: Mapped[datetime] = mapped_column(TS)
    last_seen_at: Mapped[datetime] = mapped_column(TS)
    article_count: Mapped[int] = mapped_column(Integer, server_default="1")
    source_count: Mapped[int] = mapped_column(Integer, server_default="1")
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class Article(Base):
    __tablename__ = "articles"
    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.id"))
    cluster_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("story_clusters.id"))
    url: Mapped[str] = mapped_column(Text)
    url_hash: Mapped[str] = mapped_column(Text, unique=True)
    title: Mapped[str] = mapped_column(Text)
    title_norm: Mapped[str] = mapped_column(Text)
    title_hash: Mapped[str] = mapped_column(Text)
    summary: Mapped[str | None] = mapped_column(Text)
    language: Mapped[str] = mapped_column(Text, server_default="en")
    published_at: Mapped[datetime] = mapped_column(TS)
    time_estimated: Mapped[bool] = mapped_column(Boolean, server_default="false")
    fetched_at: Mapped[datetime] = mapped_column(TS, server_default=func.now())
    status: Mapped[str] = mapped_column(ArticleStatus, server_default="fetched")
    attempts: Mapped[int] = mapped_column(SmallInteger, server_default="0")
    next_attempt_at: Mapped[datetime] = mapped_column(TS, server_default=func.now())
    last_error: Mapped[str | None] = mapped_column(Text)
    stage_timestamps: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    relevance: Mapped[float | None] = mapped_column(REAL)
    link_trace: Mapped[Any | None] = mapped_column(JSONB)
    is_simulated: Mapped[bool] = mapped_column(Boolean, server_default="false")
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class ArticleEntity(Base):
    __tablename__ = "article_entities"
    article_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("articles.id", ondelete="CASCADE"), primary_key=True
    )
    entity_type: Mapped[str] = mapped_column(EntityType, primary_key=True)
    entity_id: Mapped[str] = mapped_column(Text, primary_key=True)
    is_primary: Mapped[bool] = mapped_column(Boolean, server_default="false")
    confidence: Mapped[float] = mapped_column(REAL)


class ModelVersion(Base):
    __tablename__ = "model_versions"
    id: Mapped[str] = mapped_column(Text, primary_key=True)
    kind: Mapped[str] = mapped_column(Text)
    provider: Mapped[str] = mapped_column(Text)
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = _created()


class ArticleScore(Base):
    __tablename__ = "article_scores"
    article_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("articles.id", ondelete="CASCADE"), primary_key=True
    )
    model_version_id: Mapped[str] = mapped_column(ForeignKey("model_versions.id"))
    label: Mapped[str] = mapped_column(SentimentLabel)
    p_pos: Mapped[float] = mapped_column(REAL)
    p_neu: Mapped[float] = mapped_column(REAL)
    p_neg: Mapped[float] = mapped_column(REAL)
    score: Mapped[float] = mapped_column(REAL)
    confidence: Mapped[float] = mapped_column(REAL)
    event_type: Mapped[str] = mapped_column(EventType)
    severity: Mapped[float] = mapped_column(REAL)
    hedged: Mapped[bool] = mapped_column(Boolean, server_default="false")
    rationale: Mapped[str | None] = mapped_column(Text)
    explanation: Mapped[str] = mapped_column(Text)
    explanation_source: Mapped[str] = mapped_column(ExplanationSource, server_default="template")
    is_fallback: Mapped[bool] = mapped_column(Boolean, server_default="false")
    scored_at: Mapped[datetime] = mapped_column(TS, server_default=func.now())
    updated_at: Mapped[datetime] = _updated()


class PipelineEvent(Base):
    __tablename__ = "pipeline_events"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    article_id: Mapped[uuid.UUID | None] = mapped_column(UUID)
    stage: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    detail: Mapped[Any | None] = mapped_column(JSONB)
    created_at: Mapped[datetime] = _created()


class DeadLetter(Base):
    __tablename__ = "dead_letters"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    article_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("articles.id", ondelete="CASCADE"))
    stage: Mapped[str] = mapped_column(Text)
    error: Mapped[str] = mapped_column(Text)
    attempts: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = _created()
    resolved_at: Mapped[datetime | None] = mapped_column(TS)


class LlmCache(Base):
    __tablename__ = "llm_cache"
    key: Mapped[str] = mapped_column(Text, primary_key=True)
    model: Mapped[str] = mapped_column(Text)
    response: Mapped[Any] = mapped_column(JSONB)
    created_at: Mapped[datetime] = _created()


class LlmUsage(Base):
    __tablename__ = "llm_usage"
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    purpose: Mapped[str] = mapped_column(Text, primary_key=True)
    requests: Mapped[int] = mapped_column(Integer, server_default="0")
    tokens: Mapped[int] = mapped_column(Integer, server_default="0")


# ---------- market and aggregates (0004) ----------


class PriceCandle(Base):
    __tablename__ = "price_candles"
    ticker: Mapped[str] = mapped_column(ForeignKey("companies.ticker"), primary_key=True)
    interval: Mapped[str] = mapped_column(CandleInterval, primary_key=True)
    ts: Mapped[datetime] = mapped_column(TS, primary_key=True)
    open: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    high: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    low: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    close: Mapped[Decimal] = mapped_column(Numeric(12, 2))
    volume: Mapped[int] = mapped_column(BigInteger, server_default="0")
    source: Mapped[str] = mapped_column(Text)
    is_simulated: Mapped[bool] = mapped_column(Boolean, server_default="false")


class SentimentBucket(Base):
    __tablename__ = "sentiment_buckets"
    ticker: Mapped[str] = mapped_column(ForeignKey("companies.ticker"), primary_key=True)
    bucket_size: Mapped[str] = mapped_column(BucketSize, primary_key=True)
    bucket_start: Mapped[datetime] = mapped_column(TS, primary_key=True)
    session_date: Mapped[date] = mapped_column(Date)
    index_value: Mapped[float] = mapped_column(REAL)
    raw_sum: Mapped[float] = mapped_column(REAL)
    article_count: Mapped[int] = mapped_column(Integer)
    pos_count: Mapped[int] = mapped_column(Integer)
    neg_count: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[datetime] = _updated()


class SectorSentimentBucket(Base):
    __tablename__ = "sector_sentiment_buckets"
    sector_id: Mapped[str] = mapped_column(ForeignKey("sectors.id"), primary_key=True)
    bucket_size: Mapped[str] = mapped_column(BucketSize, primary_key=True)
    bucket_start: Mapped[datetime] = mapped_column(TS, primary_key=True)
    index_value: Mapped[float] = mapped_column(REAL)
    article_count: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[datetime] = _updated()


class MarketSentimentBucket(Base):
    __tablename__ = "market_sentiment_buckets"
    bucket_size: Mapped[str] = mapped_column(BucketSize, primary_key=True)
    bucket_start: Mapped[datetime] = mapped_column(TS, primary_key=True)
    index_value: Mapped[float] = mapped_column(REAL)
    article_count: Mapped[int] = mapped_column(Integer)
    updated_at: Mapped[datetime] = _updated()


# ---------- users and portfolios (0005) ----------


class User(Base):
    __tablename__ = "users"
    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True)
    email: Mapped[str] = mapped_column(CITEXT, unique=True)
    password_hash: Mapped[str] = mapped_column(Text)
    display_name: Mapped[str | None] = mapped_column(Text)
    role: Mapped[str] = mapped_column(Text, server_default="user")
    is_demo: Mapped[bool] = mapped_column(Boolean, server_default="false")
    disclaimer_accepted_at: Mapped[datetime] = mapped_column(TS)
    preferences: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class RefreshToken(Base):
    __tablename__ = "refresh_tokens"
    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    family_id: Mapped[uuid.UUID] = mapped_column(UUID)
    token_hash: Mapped[str] = mapped_column(Text, unique=True)
    expires_at: Mapped[datetime] = mapped_column(TS)
    revoked_at: Mapped[datetime | None] = mapped_column(TS)
    replaced_by: Mapped[uuid.UUID | None] = mapped_column(UUID)
    created_at: Mapped[datetime] = _created()


class Portfolio(Base):
    __tablename__ = "portfolios"
    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), unique=True)
    name: Mapped[str] = mapped_column(Text, server_default="My portfolio")
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class Holding(Base):
    __tablename__ = "holdings"
    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    portfolio_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("portfolios.id", ondelete="CASCADE"))
    symbol: Mapped[str] = mapped_column(Text)
    ticker: Mapped[str | None] = mapped_column(ForeignKey("companies.ticker"))
    isin: Mapped[str | None] = mapped_column(Text)
    quantity: Mapped[Decimal] = mapped_column(Numeric(18, 4))
    avg_price: Mapped[Decimal] = mapped_column(Numeric(14, 4))
    created_at: Mapped[datetime] = _created()


class ImportPreview(Base):
    __tablename__ = "import_previews"
    token: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    format: Mapped[str] = mapped_column(Text)
    rows: Mapped[Any] = mapped_column(JSONB)
    created_at: Mapped[datetime] = _created()
    expires_at: Mapped[datetime] = mapped_column(TS)


class WatchlistItem(Base):
    __tablename__ = "watchlist_items"
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"), primary_key=True)
    ticker: Mapped[str] = mapped_column(ForeignKey("companies.ticker"), primary_key=True)
    created_at: Mapped[datetime] = _created()


# ---------- alerts (0006) ----------


class AlertRule(Base):
    __tablename__ = "alert_rules"
    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    kind: Mapped[str] = mapped_column(Text)
    params: Mapped[dict[str, Any]] = mapped_column(JSONB, server_default="{}")
    enabled: Mapped[bool] = mapped_column(Boolean, server_default="true")
    created_at: Mapped[datetime] = _created()
    updated_at: Mapped[datetime] = _updated()


class Alert(Base):
    __tablename__ = "alerts"
    id: Mapped[uuid.UUID] = mapped_column(UUID, primary_key=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    rule_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("alert_rules.id", ondelete="SET NULL"))
    kind: Mapped[str] = mapped_column(Text)
    ticker: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str] = mapped_column(Text)
    body: Mapped[str] = mapped_column(Text)
    severity: Mapped[float] = mapped_column(REAL, server_default="0.5")
    article_ids: Mapped[list[uuid.UUID]] = mapped_column(ARRAY(UUID), server_default="{}")
    merged_count: Mapped[int] = mapped_column(Integer, server_default="0")
    dedupe_key: Mapped[str] = mapped_column(Text)
    held: Mapped[bool] = mapped_column(Boolean, server_default="false")
    notified: Mapped[bool] = mapped_column(Boolean, server_default="false")
    created_at: Mapped[datetime] = _created()
    read_at: Mapped[datetime | None] = mapped_column(TS)
