"""Alert engine (P2-BE-09). Severe events are checked as articles become visible; negative shifts and
concentration in a 60 s sweep. Each user gets at most 2 delivered alerts per hour: extra ones are held
and folded into the next delivered alert. Quiet hours deliver silently (no live push)."""

import logging
import uuid
from collections import defaultdict
from datetime import UTC, datetime, time, timedelta
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from geotrade_ai import reference
from geotrade_ai.market_calendar import session_date
from geotrade_ai.models import (
    Alert,
    AlertRule,
    Article,
    ArticleEntity,
    ArticleScore,
    CoverageSpike,
    Holding,
    Portfolio,
    User,
    WatchlistItem,
)
from geotrade_ai.normalize import IST
from geotrade_ai.portfolio import exposure as ex
from geotrade_ai.repos import alerts as repo
from geotrade_ai.repos import read

log = logging.getLogger(__name__)
FRESH = timedelta(hours=6)  # older stories (backfill, seeded history) never alert


def in_quiet_hours(prefs: dict[str, Any], now: datetime) -> bool:
    q = prefs.get("quiet_hours")
    if not q:
        return False
    start, end = time.fromisoformat(q["start"]), time.fromisoformat(q["end"])
    t = now.astimezone(IST).time()
    return start <= t < end if start <= end else (t >= start or t < end)  # window may cross midnight


def emit(
    session: Session, user: User, rule: AlertRule | None, values: dict[str, Any], now: datetime
) -> Alert | None:
    if user.preferences.get("alerts_enabled") is False:
        return None
    alert = repo.insert_alert(
        session, {"user_id": user.id, "rule_id": rule.id if rule else None, "created_at": now, **values}
    )
    if alert is None:  # same event already alerted (dedupe key)
        return None
    if repo.delivered_last_hour(session, user.id, now) - 1 >= repo.THROTTLE_PER_HOUR:
        alert.held = True
        return alert
    deliver(session, user, alert, now)
    return alert


def deliver(session: Session, user: User, alert: Alert, now: datetime) -> None:
    """Fold any held alerts into this one, then push it unless the user is in quiet hours."""
    held = [h for h in repo.held_alerts(session, user.id) if h.id != alert.id]
    if held:
        alert.article_ids = list(
            dict.fromkeys([*alert.article_ids, *(a for h in held for a in h.article_ids)])
        )
        alert.merged_count += sum(1 + h.merged_count for h in held)
        alert.severity = max([alert.severity, *(h.severity for h in held)])
        others = ", ".join(dict.fromkeys(h.ticker or h.kind for h in held))
        alert.body = f"{alert.body} Also: {len(held)} more update(s) on {others}."
        session.execute(delete(Alert).where(Alert.id.in_([h.id for h in held])))
    if alert.held:  # released from the throttle: it is delivered now and counts toward this hour
        alert.created_at = now
    alert.held = False
    if not in_quiet_hours(user.preferences, now):
        alert.notified = True
        repo.notify(session, alert)


# ---------- audiences ----------


def audience(session: Session, tickers: set[str], include_watchlist: bool) -> dict[uuid.UUID, set[str]]:
    """user id -> which of `tickers` they hold (or watch)."""
    out: dict[uuid.UUID, set[str]] = defaultdict(set)
    for uid, ticker in session.execute(
        select(Portfolio.user_id, Holding.ticker)
        .join(Holding, Holding.portfolio_id == Portfolio.id)
        .where(Holding.ticker.in_(tickers))
    ):
        if ticker:
            out[uid].add(ticker)
    if include_watchlist:
        for uid, ticker in session.execute(
            select(WatchlistItem.user_id, WatchlistItem.ticker).where(WatchlistItem.ticker.in_(tickers))
        ):
            out[uid].add(ticker)
    return out


# ---------- severe events (per article) ----------


def on_articles(session: Session, articles: list[Article], now: datetime | None = None) -> int:
    now = now or datetime.now(UTC)
    fresh = [a for a in articles if now - a.published_at <= FRESH]
    if not fresh:
        return 0
    rows = session.execute(
        select(Article, ArticleScore, ArticleEntity.entity_id)
        .join(ArticleScore, ArticleScore.article_id == Article.id)
        .join(ArticleEntity, ArticleEntity.article_id == Article.id)
        .where(
            Article.id.in_([a.id for a in fresh]),
            ArticleEntity.entity_type == "stock",
            ArticleEntity.is_primary,
            ArticleScore.label == "negative",
        )
    ).all()
    if not rows:
        return 0
    rules = {r.user_id: r for r in repo.enabled_rules(session, "severe_event")}
    users = {u.id: u for u in session.scalars(select(User).where(User.id.in_(list(rules))))}
    created = 0
    for article, score, ticker in rows:
        holders = audience(session, {ticker}, include_watchlist=False)
        for uid in audience(session, {ticker}, include_watchlist=True):
            rule = rules.get(uid)
            if (
                rule is None
                or uid not in users
                or score.severity < float(rule.params.get("min_severity", 0.7))
            ):
                continue
            if rule.params.get("scope", "holdings") == "holdings" and uid not in holders:
                continue
            alert = emit(
                session, users[uid], rule,
                {
                    "kind": "severe_event", "ticker": ticker, "severity": score.severity,
                    "title": f"{ticker}: {score.event_type.replace('_', ' ')} news, negative tone",
                    "body": article.title, "article_ids": [article.id],
                    "dedupe_key": f"severe_event:{ticker}:{article.cluster_id or article.id}",
                },
                now,
            )  # fmt: skip
            created += alert is not None
    return created


# ---------- coverage spikes (optional rule, off by default) ----------


def on_spikes(session: Session, spikes: list[CoverageSpike], now: datetime) -> int:
    if not spikes:
        return 0
    rules = {r.user_id: r for r in repo.enabled_rules(session, "coverage_spike")}
    if not rules:
        return 0
    users = {u.id: u for u in session.scalars(select(User).where(User.id.in_(list(rules))))}
    created = 0
    for spike in spikes:
        holders = audience(session, {spike.ticker}, include_watchlist=False)
        for uid in audience(session, {spike.ticker}, include_watchlist=True):
            rule = rules.get(uid)
            if rule is None or uid not in users:
                continue
            if rule.params.get("scope", "holdings") == "holdings" and uid not in holders:
                continue
            alert = emit(
                session, users[uid], rule,
                {
                    "kind": "coverage_spike", "ticker": spike.ticker,
                    "severity": min(spike.z_score / 10, 1.0),
                    "title": f"{spike.ticker}: unusually heavy news coverage",
                    "body": f"{spike.n_stories} stories in 24h against a usual {spike.baseline_mean:.1f} "
                            f"a day ({spike.z_score:.1f} standard deviations above normal).",
                    "dedupe_key": f"coverage_spike:{spike.ticker}:{session_date(now).isoformat()}",
                },
                now,
            )  # fmt: skip
            created += alert is not None
    return created


# ---------- sweep ----------


def sweep(session: Session, now: datetime | None = None) -> int:
    now = now or datetime.now(UTC)
    signals = read.stock_signals(session, now)
    created = _negative_shifts(session, signals, now) + _concentration(session, signals, now)
    _release_held(session, now)
    session.commit()
    return created


def _negative_shifts(session: Session, signals: dict[str, read.StockSignal], now: datetime) -> int:
    rules = repo.enabled_rules(session, "negative_shift")
    if not rules:
        return 0
    users = {u.id: u for u in session.scalars(select(User).where(User.id.in_([r.user_id for r in rules])))}
    day = session_date(now).isoformat()
    created = 0
    for rule in rules:
        threshold = float(rule.params.get("threshold", 15))
        scope_watch = rule.params.get("scope") == "both"
        mine = audience(session, set(signals), include_watchlist=scope_watch).get(rule.user_id, set())
        for ticker in sorted(mine):
            sig = signals[ticker]
            if sig.delta_24h > -threshold or rule.user_id not in users:
                continue
            alert = emit(
                session, users[rule.user_id], rule,
                {
                    "kind": "negative_shift", "ticker": ticker, "severity": min(abs(sig.delta_24h) / 50, 1.0),
                    "title": f"{ticker}: news sentiment fell {abs(sig.delta_24h):.0f} points in 24h",
                    "body": f"Sentiment index is now {sig.index:+.0f} ({sig.articles_24h} stories in 24h).",
                    "dedupe_key": f"negative_shift:{ticker}:{day}",
                },
                now,
            )  # fmt: skip
            created += alert is not None
    return created


def _concentration(session: Session, signals: dict[str, read.StockSignal], now: datetime) -> int:
    rules = {r.user_id: r for r in repo.enabled_rules(session, "concentration")}
    if not rules:
        return 0
    prices = read.prices_now(session, now)
    companies = {c["ticker"]: (c["name"], c["sector_id"]) for c in reference.companies()}
    sector_names = {s["id"]: s["name"] for s in reference.sectors()}
    week = now.astimezone(IST).strftime("%G-W%V")
    created = 0
    for user in session.scalars(select(User).where(User.id.in_(list(rules)))):
        holdings = session.scalars(
            select(Holding)
            .join(Portfolio, Portfolio.id == Holding.portfolio_id)
            .where(Portfolio.user_id == user.id)
        ).all()
        if not holdings:
            continue
        e = ex.compute(
            [ex.HoldingIn(h.id, h.symbol, h.ticker, float(h.quantity), float(h.avg_price)) for h in holdings],
            prices, signals, {}, companies,
        )  # fmt: skip
        limits = rules[user.id].params
        for h in e.holdings:
            if h.ticker and h.weight > float(limits.get("stock", ex.STOCK_LIMIT)):
                created += emit(session, user, rules[user.id], {
                    "kind": "concentration", "ticker": h.ticker, "severity": 0.4,
                    "title": f"{h.ticker} is {h.weight:.0%} of your portfolio",
                    "body": "One holding above 25% concentrates news risk. This is information, not advice.",
                    "dedupe_key": f"concentration:{h.ticker}:{week}",
                }, now) is not None  # fmt: skip
        for sector, weight in e.sectors.items():
            if sector != "other" and weight > float(limits.get("sector", ex.SECTOR_LIMIT)):
                created += emit(session, user, rules[user.id], {
                    "kind": "concentration", "ticker": None, "severity": 0.4,
                    "title": f"{sector_names.get(sector, sector)} is {weight:.0%} of your portfolio",
                    "body": "One sector above 40% concentrates news risk. This is information, not advice.",
                    "dedupe_key": f"concentration:sector:{sector}:{week}",
                }, now) is not None  # fmt: skip
    return created


def _release_held(session: Session, now: datetime) -> None:
    """Throttled alerts wait until the user is under the hourly cap, then go out as one merged alert."""
    for uid in repo.users_with_held(session):
        if repo.delivered_last_hour(session, uid, now) >= repo.THROTTLE_PER_HOUR:
            continue
        user = session.get(User, uid)
        held = repo.held_alerts(session, uid)
        if user is None or not held:
            continue
        deliver(session, user, held[-1], now)
