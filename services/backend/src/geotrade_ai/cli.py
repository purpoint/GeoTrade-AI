"""`backend api | worker | migrate | seed | evaluate | openapi` - one image, several roles."""

import argparse
import json
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

from geotrade_ai.core.config import get_settings
from geotrade_ai.core.logging import setup_logging


def cmd_api(args: argparse.Namespace) -> None:
    import uvicorn

    uvicorn.run(
        "geotrade_ai.api.app:create_app",
        factory=True,
        host=args.host,
        port=args.port,
        workers=args.workers,
        log_config=None,
    )


def cmd_migrate(args: argparse.Namespace) -> None:
    from alembic import command
    from alembic.config import Config

    command.upgrade(Config(str(Path(__file__).resolve().parents[2] / "alembic.ini")), args.revision)


def cmd_seed(args: argparse.Namespace) -> None:
    import logging

    from geotrade_ai.core.db import get_sessionmaker
    from geotrade_ai.repos.reference import seed_reference

    with get_sessionmaker()() as session:
        logging.getLogger("seed").info("reference seeded", extra={"extra": seed_reference(session)})
    if args.demo:
        from geotrade_ai.core.config import get_settings
        from geotrade_ai.repos.accounts import seed_demo_accounts

        with get_sessionmaker()() as session:
            s = get_settings()
            seed_demo_accounts(session, s.operator_email, s.operator_password)
            logging.getLogger("seed").info("demo accounts seeded")
    if args.history:
        from geotrade_ai.worker.jobs import seed_history

        seed_history(get_sessionmaker(), days=args.days)


def cmd_worker(args: argparse.Namespace) -> None:
    from geotrade_ai.worker.main import main as worker_main

    worker_main()


def cmd_prices(args: argparse.Namespace) -> None:
    from geotrade_ai.core.config import get_settings
    from geotrade_ai.core.db import get_sessionmaker
    from geotrade_ai.worker import prices

    if args.export:
        prices.export_csv(get_settings().data_dir / "fixtures" / "prices" / "daily.csv")
        return
    with get_sessionmaker()() as session:
        prices.sync(session, "1d", args.period)


def cmd_evaluate(args: argparse.Namespace) -> None:
    from geotrade_ai.eval.golden import evaluate

    r = evaluate(args.golden)
    print(f"report: {r['path']}")
    print(f"linking  P={r['linking']['precision']} R={r['linking']['recall']} F1={r['linking']['f1']}")
    for model, m in r["sentiment"].items():
        print(f"{model:20s} accuracy={m['accuracy']} macro_f1={m['macro_f1']}")
    print(f"events   accuracy={r['events']['accuracy']}")
    print(f"dedupe   {r['dedupe']}")
    print(f"agreement {r['agreement']}")


def cmd_backtest(args: argparse.Namespace) -> None:
    from geotrade_ai.core.db import get_sessionmaker
    from geotrade_ai.core.ids import uuid7
    from geotrade_ai.eval.backtest import backtest
    from geotrade_ai.models import BacktestRun

    with get_sessionmaker()() as session:
        results = backtest(session)
        session.add(
            BacktestRun(
                id=uuid7(), params={"signal": "daily impact sum", "horizon": "next session"}, results=results
            )
        )
        session.commit()
    print(json.dumps(results, indent=2))


def cmd_backfill(args: argparse.Namespace) -> None:
    from geotrade_ai.core.db import get_sessionmaker
    from geotrade_ai.repos.reference import seed_reference
    from geotrade_ai.worker.backfill import backfill

    with get_sessionmaker()() as session:
        seed_reference(session)  # makes sure the google_news source row exists
    print(json.dumps(backfill(get_sessionmaker(), args.days)))


def cmd_digest(args: argparse.Namespace) -> None:
    """Build and/or send a digest run by hand (the worker does this on schedule)."""
    from datetime import date

    from geotrade_ai.core.db import get_sessionmaker
    from geotrade_ai.digest import jobs
    from geotrade_ai.digest.sender import get_sender
    from geotrade_ai.normalize import IST

    day = date.fromisoformat(args.date) if args.date else datetime.now(IST).date()
    with get_sessionmaker()() as session:
        if args.action in ("build", "run"):
            run = jobs.build(session, args.kind, day, rebuild=args.rebuild)
            print(json.dumps({"run": run.stats if run else "not a trading day"}, default=str))
        if args.action in ("send", "run"):
            print(
                json.dumps(
                    jobs.send_due(
                        session, get_sender(), now=datetime.now(UTC) + timedelta(days=1) if args.now else None
                    )
                )
            )


def cmd_why_sheet(args: argparse.Namespace) -> None:
    """50-item human rating sheet for the 'why this matters' sentences (P3-BE-06)."""
    import csv

    from sqlalchemy import select

    from geotrade_ai.core.db import get_sessionmaker
    from geotrade_ai.models import Article, ArticleScore

    out = Path(args.out)
    with get_sessionmaker()() as session, out.open("w", newline="") as f:
        w = csv.writer(f)
        w.writerow(
            ["article_id", "headline", "why_this_matters", "template", "clear_1to5", "faithful_1to5", "notes"]
        )
        rows = session.execute(
            select(Article, ArticleScore)
            .join(ArticleScore, ArticleScore.article_id == Article.id)
            .where(ArticleScore.explanation_source == "llm")
            .order_by(Article.published_at.desc())
            .limit(args.n)
        ).all()
        for a, sc in rows:
            why, _, template = sc.explanation.partition("\n\n")
            w.writerow([a.id, a.title, why, template, "", "", ""])
    print(f"{len(rows)} rows written to {out}")


def cmd_openapi(args: argparse.Namespace) -> None:
    from geotrade_ai.api.app import create_app

    spec = json.dumps(create_app().openapi(), indent=2, sort_keys=True) + "\n"
    if args.out == "-":
        sys.stdout.write(spec)
    else:
        with open(args.out, "w") as f:
            f.write(spec)


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="backend")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("api", help="run the HTTP API")
    p.add_argument("--host", default="0.0.0.0")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--workers", type=int, default=1)
    p.set_defaults(fn=cmd_api)

    p = sub.add_parser("migrate", help="apply Alembic migrations")
    p.add_argument("revision", nargs="?", default="head")
    p.set_defaults(fn=cmd_migrate)

    p = sub.add_parser("seed", help="load reference data (idempotent)")
    p.add_argument("--reference", action="store_true", default=True)
    p.add_argument("--history", action="store_true", help="also add 7 days of simulated articles and candles")
    p.add_argument("--days", type=int, default=7)
    p.add_argument(
        "--demo", action="store_true", help="also create the demo investor and the operator account"
    )
    p.set_defaults(fn=cmd_seed)

    p = sub.add_parser("worker", help="run the scheduler and pipeline")
    p.set_defaults(fn=cmd_worker)

    p = sub.add_parser("prices", help="sync daily candles now, or --export the CSV fallback")
    p.add_argument("--period", default="3mo")
    p.add_argument("--export", action="store_true")
    p.set_defaults(fn=cmd_prices)

    p = sub.add_parser("evaluate", help="score the golden set and write a JSON report")
    p.add_argument("--golden", default="golden-v1")
    p.set_defaults(fn=cmd_evaluate)

    p = sub.add_parser("backfill", help="load N days of real headlines (Google News search) for the backtest")
    p.add_argument("--days", type=int, default=60)
    p.set_defaults(fn=cmd_backfill)

    p = sub.add_parser("backtest", help="news signal vs next-session return; saved for the evaluation page")
    p.set_defaults(fn=cmd_backtest)

    p = sub.add_parser("digest", help="build or send the Daily Pulse now (build | send | run)")
    p.add_argument("action", choices=["build", "send", "run"])
    p.add_argument("--kind", choices=["daily", "weekly"], default="daily")
    p.add_argument("--date", help="session date (default today, IST)")
    p.add_argument("--rebuild", action="store_true", help="refresh unsent snapshots")
    p.add_argument("--now", action="store_true", help="send queued digests now instead of at their send time")
    p.set_defaults(fn=cmd_digest)

    p = sub.add_parser("why-sheet", help="CSV of recent 'why this matters' sentences for human rating")
    p.add_argument("--out", default="why-this-matters-rating.csv")
    p.add_argument("-n", type=int, default=50)
    p.set_defaults(fn=cmd_why_sheet)

    p = sub.add_parser("openapi", help="export the OpenAPI document")
    p.add_argument("--out", default="-")
    p.set_defaults(fn=cmd_openapi)

    args = parser.parse_args(argv)
    setup_logging(get_settings().log_level)
    args.fn(args)


if __name__ == "__main__":
    main()
