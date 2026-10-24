"""Digest snapshot builder (P3-BE-01, plan 8.4): one frozen JSON per user and session date, assembled
from the same exposure, attention, risk-flag and related-stock code as the dashboard, so the email can
never disagree with it. The email, the /digest page and the narrative all read only this JSON."""

from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from geotrade_ai import reference
from geotrade_ai.core.config import get_settings
from geotrade_ai.digest import ranking, tokens
from geotrade_ai.market_calendar import is_trading_day, previous_trading_day
from geotrade_ai.models import Alert, BacktestRun, DigestDelivery, EmailPreferences, User
from geotrade_ai.portfolio import attention as att
from geotrade_ai.portfolio import exposure as ex
from geotrade_ai.portfolio import related as rel
from geotrade_ai.repos import portfolio as portfolio_repo
from geotrade_ai.repos import read

VERSION = 1
DISCLAIMER = (
    "Not investment advice. GeoTrade-AI summarises public news and signals; it does not recommend buying "
    "or selling any security. Past behaviour of these signals is not a guide to the future."
)


class Context:
    """Market-wide inputs loaded once per run and shared by every user's snapshot."""

    def __init__(self, session: Session, now: datetime) -> None:
        self.now = now
        self.signals = read.stock_signals(session, now)
        self.prices = read.prices_now(session, now)
        self.spikes = read.active_spikes(session, now)
        self.week = read.article_counts(session, now - timedelta(days=7))
        self.coverage_3d = read.coverage(session, now - timedelta(hours=72))
        self.companies = {c["ticker"]: c for c in reference.companies()}
        self.sector_names = {s["id"]: s["name"] for s in reference.sectors()}
        latest = session.scalar(select(BacktestRun).order_by(BacktestRun.created_at.desc()).limit(1))
        self.backtest = latest.results if latest else None


def first_name(user: User) -> str:
    if user.display_name:
        return user.display_name.split()[0][:40]
    return user.email.split("@")[0].split(".")[0].capitalize()[:40]


def links(user: User, session_date: date) -> dict[str, str]:
    web = get_settings().public_web_url.rstrip("/")
    token = tokens.sign(user.id)
    return {
        "dashboard": f"{web}/portfolio",
        "digest": f"{web}/digest?date={session_date.isoformat()}",
        "preferences": f"{web}/settings?tab=email",
        "unsubscribe": f"{web}/unsubscribe?token={token}",
        "one_click": f"{web}/api/v1/email/unsubscribe?token={token}",
    }


def _stories(session: Session, ticker: str, since: datetime, limit: int = 2) -> list[dict[str, Any]]:
    """Canonical stories only (one per cluster), most severe and strongly toned first."""
    rows = read.stock_articles(session, [ticker], since, per_ticker=20)
    extras = read.article_extras(session, [a for _, a, _ in rows])
    seen: set[object] = set()
    ranked = sorted(rows, key=lambda r: -(r[2].severity * (0.3 + abs(r[2].score))))
    out = []
    for _, a, sc in ranked:
        key = a.cluster_id or a.id
        if key in seen:
            continue
        seen.add(key)
        x = extras[a.id]
        out.append(
            {
                "article_id": str(a.id),
                "title": a.title,
                "source": x.source.name,
                "source_count": x.cluster.source_count if x.cluster else 1,
                "url": a.url,
                "tone": sc.label,
            }
        )
        if len(out) == limit:
            break
    return out


def _market(ctx: Context) -> dict[str, Any]:
    def weighted(tickers: list[str], attr: str) -> float:
        w = [(float(ctx.companies[t]["market_cap_cr"]), getattr(ctx.signals[t], attr)) for t in tickers]
        total = sum(x for x, _ in w)
        return round(sum(x * v for x, v in w) / total, 1) if total else 0.0

    known = [t for t in ctx.companies if t in ctx.signals]
    sectors: dict[str, list[str]] = {}
    for t in known:
        sectors.setdefault(ctx.companies[t]["sector_id"], []).append(t)
    top = sorted(
        (
            {"id": s, "name": ctx.sector_names.get(s, s), "index": weighted(ts, "index")}
            for s, ts in sectors.items()
        ),
        key=lambda x: -float(x["index"]),  # type: ignore[arg-type]
    )
    return {
        "index": weighted(known, "index"),
        "delta_24h": weighted(known, "delta_24h"),
        "top_sectors": top[:3],
    }


def _backtest_note(ctx: Context) -> dict[str, Any] | None:
    r = ctx.backtest
    if not r or r.get("status") != "ok" or r.get("hit_rate") is None:
        return None
    return {
        "hit_rate": r["hit_rate"],
        "baseline": r["baseline"],
        "n": r["hit_rate_n"],
        "window": "all sessions",
    }


def _watch(session: Session, ctx: Context, held: list[str], session_date: date) -> list[dict[str, Any]]:
    cands = rel.candidates(held, ctx.companies, read.co_mentions_for(session, held))
    if not cands:
        return []
    tickers = list(cands)
    three_ago = session_date
    for _ in range(3):
        three_ago = previous_trading_day(three_ago)
    daily = read.daily_index(session, tickers, three_ago)
    stories: dict[str, list[tuple[str, str, float]]] = {}
    for t, _, sc in read.stock_articles(session, tickers, ctx.now - timedelta(hours=72)):
        stories.setdefault(t, []).append((sc.label, sc.event_type, sc.severity))
    inputs = []
    for t, c in cands.items():
        sig = ctx.signals.get(t, read.StockSignal(0.0, 0.0, 0))
        series = daily.get(t, {})
        latest = series[max(series)] if series else sig.index
        momentum = latest - series.get(three_ago, 0.0)
        mine = stories.get(t, [])
        good = sum(lbl == "positive" and ev in ranking.GOOD_EVENTS for lbl, ev, _ in mine)
        n, n_src = ctx.coverage_3d.get(t, (0, 0))
        reasons = [*c.reasons]
        if t in ctx.spikes:
            reasons.append(f"Unusually heavy coverage ({ctx.spikes[t].n_stories} stories in 24h)")
        if good:
            reasons.append(
                f"{good} positive {'story' if good == 1 else 'stories'} on results, orders or ratings"
            )
        inputs.append(
            ranking.WatchInput(
                ticker=t, index=sig.index, momentum_3d=momentum,
                volume_z=ctx.spikes[t].z_score if t in ctx.spikes else 0.0,
                relatedness=c.relatedness, event_quality=good / len(mine) if mine else 0.0,
                max_negative_severity=max((s for lbl, _, s in mine if lbl == "negative"), default=0.0),
                n_stories=n, n_sources=n_src, reasons=reasons,
            )
        )  # fmt: skip
    return ranking.rank_watch(inputs, set(held))


def build(
    session: Session, user: User, session_date: date, ctx: Context, prefs: EmailPreferences | None = None
) -> dict[str, Any] | None:
    """The daily snapshot, or None when the user holds no NIFTY 50 stock (nothing to say)."""
    e = ex.for_user(session, user.id, ctx.now, ctx.prices, ctx.signals)
    matched = [h for h in e.holdings if h.ticker]  # holdings outside NIFTY 50 are left out entirely
    if not matched:
        return None
    by_delta = sorted(matched, key=lambda h: h.delta_24h or 0.0)
    tickers = [h.ticker for h in matched if h.ticker]
    severity = read.max_severity(session, tickers, ctx.now - timedelta(hours=24))
    weights = att.merged_weights(user.preferences.get("attention_weights"))
    review: list[dict[str, Any]] = []
    for h in e.flagged:
        if not h.ticker:
            continue
        sig = ctx.signals.get(h.ticker, read.StockSignal(0.0, 0.0, 0))
        comps = att.components(
            att.Inputs(
                weight=h.weight, index=sig.index, delta_24h=sig.delta_24h,
                max_severity=severity.get(h.ticker, 0.0), articles_24h=sig.articles_24h,
                avg_daily_articles_7d=ctx.week.get(h.ticker, 0) / 7,
                spike_z=ctx.spikes[h.ticker].z_score if h.ticker in ctx.spikes else 0.0,
            )
        )  # fmt: skip
        review.append(
            {
                "ticker": h.ticker,
                "attention": att.score(comps, weights),
                "weight": h.weight,
                "flags": [f.code for f in h.flags],
                "reason": "; ".join(f.reason for f in h.flags).capitalize(),
                "stories": _stories(session, h.ticker, ctx.now - timedelta(hours=48)),
            }
        )
    review.sort(key=lambda r: -r["attention"])
    want_watch = prefs.include_watch_ideas if prefs else True
    want_watchlist = prefs.include_watchlist if prefs else True
    want_market = prefs.include_market if prefs else True
    watchlist = []
    if want_watchlist:
        for t in portfolio_repo.watchlist(session, user.id):
            if t in tickers:
                continue
            sig = ctx.signals.get(t, read.StockSignal(0.0, 0.0, 0))
            watchlist.append(
                {"ticker": t, "index": round(sig.index, 1), "delta_24h": round(sig.delta_24h, 1)}
            )
    return {
        "version": VERSION,
        "kind": "daily",
        "session_date": session_date.isoformat(),
        "generated_at": ctx.now.isoformat(),
        "user": {"first_name": first_name(user)},
        "portfolio": {
            "value": e.value,
            "day_change_pct": e.day_change_pct,
            "holdings": len(matched),
            "sentiment": {"index": round(e.sentiment, 1), "delta_24h": round(e.delta_24h, 1)},
            "top_positive": {"ticker": by_delta[-1].ticker, "delta": round(by_delta[-1].delta_24h or 0, 1)}
            if (by_delta[-1].delta_24h or 0) > 0
            else None,
            "top_negative": {"ticker": by_delta[0].ticker, "delta": round(by_delta[0].delta_24h or 0, 1)}
            if (by_delta[0].delta_24h or 0) < 0
            else None,
        },
        "review": review[: ranking.MAX_REVIEW],
        "watch": _watch(session, ctx, tickers, session_date) if want_watch else [],
        "watchlist": watchlist,
        "market": _market(ctx) if want_market else None,
        "backtest_note": _backtest_note(ctx),
        "links": links(user, session_date),
        "disclaimer": DISCLAIMER,
    }


def week_sessions(saturday: date) -> list[date]:
    return [d for d in (saturday - timedelta(days=i) for i in range(6, 0, -1)) if is_trading_day(d)]


def build_weekly(session: Session, user: User, saturday: date, ctx: Context) -> dict[str, Any] | None:
    """Saturday recap over the week's sessions: trend, biggest stories, flags, persistent momentum names."""
    e = ex.for_user(session, user.id, ctx.now, ctx.prices, ctx.signals)
    matched = [h for h in e.holdings if h.ticker]
    sessions = week_sessions(saturday)
    if not matched or not sessions:
        return None
    tickers = [h.ticker for h in matched if h.ticker]
    daily = read.daily_index(session, tickers, sessions[0])
    total = sum(h.value for h in matched) or 1.0
    trend = [
        {
            "date": d.isoformat(),
            "index": round(
                sum(h.value * daily.get(h.ticker or "", {}).get(d, 0.0) for h in matched) / total, 1
            ),
        }
        for d in sessions
    ]
    start = datetime.combine(sessions[0], datetime.min.time(), UTC) - timedelta(hours=6)
    stories = []
    for h in sorted(matched, key=lambda h: -h.value)[:5]:
        top = _stories(session, h.ticker or "", start, limit=1)
        if top:
            stories.append({"ticker": h.ticker, **top[0]})
    flags = list(
        session.scalars(
            select(Alert)
            .where(Alert.user_id == user.id, Alert.created_at >= start, Alert.held.is_(False))
            .order_by(Alert.created_at.desc())
        )
    )
    persisted: dict[str, int] = {}
    for snap in session.scalars(
        select(DigestDelivery.snapshot).where(
            DigestDelivery.user_id == user.id,
            DigestDelivery.kind == "daily",
            DigestDelivery.session_date.in_(sessions),
            DigestDelivery.snapshot.is_not(None),
        )
    ):
        for w in (snap or {}).get("watch", []):
            persisted[w["ticker"]] = persisted.get(w["ticker"], 0) + 1
    return {
        "version": VERSION,
        "kind": "weekly",
        "session_date": saturday.isoformat(),
        "week": {"from": sessions[0].isoformat(), "to": sessions[-1].isoformat(), "sessions": len(sessions)},
        "generated_at": ctx.now.isoformat(),
        "user": {"first_name": first_name(user)},
        "portfolio": {
            "value": e.value,
            "holdings": len(matched),
            "sentiment": {"index": round(e.sentiment, 1), "delta_24h": round(e.delta_24h, 1)},
            "trend": trend,
        },
        "stories": stories,
        "flags": {"count": len(flags), "items": [{"kind": a.kind, "title": a.title} for a in flags[:5]]},
        "persistent_momentum": [
            {"ticker": t, "days": n} for t, n in sorted(persisted.items(), key=lambda x: -x[1]) if n >= 3
        ],
        "links": links(user, saturday),
        "disclaimer": DISCLAIMER,
    }
