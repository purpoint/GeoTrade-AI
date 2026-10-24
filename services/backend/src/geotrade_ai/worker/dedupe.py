"""Deduplicator (P1-BE-10). L1 is the url_hash unique index at insert time; L2 is the same normalised
title within 48 h; L3 is a fuzzy title match within 6 h that shares a company, with false-merge guards."""

import re
from datetime import timedelta

from rapidfuzz import fuzz
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from geotrade_ai.core.ids import uuid7
from geotrade_ai.models import Article, StoryCluster
from geotrade_ai.worker.linker import get_linker

L2_WINDOW = timedelta(hours=48)
L3_WINDOW = timedelta(hours=6)
FUZZY_THRESHOLD = 88
JACCARD_THRESHOLD = 0.5
_NUMBER = re.compile(r"\d+(?:\.\d+)?")


def numbers(text: str) -> set[str]:
    return set(_NUMBER.findall(text.replace(",", "")))


def numbers_conflict(a: str, b: str) -> bool:
    na, nb = numbers(a), numbers(b)
    return bool(na and nb and not (na <= nb or nb <= na))


def tickers_disjoint(a: set[str], b: set[str]) -> bool:
    return bool(a and b and not (a & b))


def jaccard(a: str, b: str) -> float:
    sa, sb = set(a.split()), set(b.split())
    return len(sa & sb) / len(sa | sb) if sa and sb else 0.0


def is_near_duplicate(a_norm: str, b_norm: str, a_tickers: set[str], b_tickers: set[str]) -> bool:
    if numbers_conflict(a_norm, b_norm) or tickers_disjoint(a_tickers, b_tickers):
        return False
    if not (a_tickers & b_tickers):  # L3 needs a shared company
        return False
    return (
        fuzz.token_set_ratio(a_norm, b_norm) >= FUZZY_THRESHOLD
        and jaccard(a_norm, b_norm) >= JACCARD_THRESHOLD
    )


def _tickers(title: str) -> set[str]:
    return {t for t, _, _ in get_linker().link(title).stocks}


def find_cluster(session: Session, article: Article) -> StoryCluster | None:
    # L2: identical normalised title
    same = session.scalar(
        select(Article)
        .where(
            Article.title_hash == article.title_hash,
            Article.id != article.id,
            Article.cluster_id.is_not(None),
            Article.published_at >= article.published_at - L2_WINDOW,
            Article.published_at <= article.published_at + L2_WINDOW,
        )
        .limit(1)
    )
    if same is not None:
        return session.get(StoryCluster, same.cluster_id)
    # L3: trigram prefilter in SQL, exact rules in Python
    mine = _tickers(article.title)
    if not mine:
        return None
    candidates = session.scalars(
        select(Article)
        .where(
            Article.id != article.id,
            Article.cluster_id.is_not(None),
            Article.published_at >= article.published_at - L3_WINDOW,
            Article.published_at <= article.published_at + L3_WINDOW,
            Article.title_norm.op("%")(article.title_norm),
        )
        .order_by(func.similarity(Article.title_norm, article.title_norm).desc())
        .limit(20)
    )
    for cand in candidates:
        if is_near_duplicate(article.title_norm, cand.title_norm, mine, _tickers(cand.title)):
            return session.get(StoryCluster, cand.cluster_id)
    return None


def dedupe_one(session: Session, article: Article) -> str:
    """Assigns a cluster. Returns the next status: 'deduped' (canonical) or 'duplicate'."""
    cluster = find_cluster(session, article)
    if cluster is None:
        cluster = StoryCluster(
            id=uuid7(),
            canonical_article_id=article.id,
            first_seen_at=article.published_at,
            last_seen_at=article.published_at,
        )
        session.add(cluster)
        session.flush()
        article.cluster_id = cluster.id
        return "deduped"
    # shortcut: the first-seen article stays canonical; re-pick by source priority if editors ask for it
    article.cluster_id = cluster.id
    session.flush()
    cluster.article_count = (
        session.scalar(select(func.count()).select_from(Article).where(Article.cluster_id == cluster.id)) or 1
    )
    cluster.source_count = (
        session.scalar(
            select(func.count(func.distinct(Article.source_id))).where(Article.cluster_id == cluster.id)
        )
        or 1
    )
    cluster.first_seen_at = min(cluster.first_seen_at, article.published_at)
    cluster.last_seen_at = max(cluster.last_seen_at, article.published_at)
    return "duplicate"
