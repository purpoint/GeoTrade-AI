"""Digest rendering (P3-BE-04): subject, HTML and plain text from the snapshot alone, so the email and the
in-app /digest page are the same document. Templates live in digest/templates (Jinja2, inline CSS)."""

from datetime import date
from typing import Any

from jinja2 import Environment, PackageLoader, StrictUndefined, select_autoescape

_env = Environment(
    loader=PackageLoader("geotrade_ai.digest", "templates"),
    autoescape=select_autoescape(["html", "html.j2"]),
    undefined=StrictUndefined,
    trim_blocks=True,
    lstrip_blocks=True,
)


def _day(d: str) -> str:
    return date.fromisoformat(d).strftime("%a %-d %b")


def _change(x: float) -> str:
    return "unchanged" if round(x) == 0 else f"{'up' if x > 0 else 'down'} {abs(x):.0f}"


def subject(s: dict[str, Any]) -> str:
    sent = s["portfolio"]["sentiment"]
    if s["kind"] == "weekly":
        trend = s["portfolio"]["trend"]
        move = trend[-1]["index"] - trend[0]["index"] if len(trend) > 1 else 0.0
        return (
            f"Weekly Pulse, week to {_day(s['week']['to'])}: portfolio sentiment {sent['index']:+.0f} "
            f"({_change(move)} over the week)"
        )
    n = len(s["review"])
    review = f"{n} {'holding' if n == 1 else 'holdings'} to review" if n else "no holdings to review"
    return (
        f"Daily Pulse, {_day(s['session_date'])}: {review}, portfolio sentiment {sent['index']:+.0f} "
        f"({_change(sent['delta_24h'])})"
    )


def render(s: dict[str, Any]) -> tuple[str, str, str]:
    """(subject, html, text). The narrative is frozen into the snapshot at build time."""
    subj = subject(s)
    d = date.fromisoformat(s["session_date"])
    heading = (
        f"Week to {date.fromisoformat(s['week']['to']):%A %-d %b %Y}"
        if s["kind"] == "weekly"
        else f"{d:%A %-d %b %Y}"
    )
    ctx = {"s": s, "subject": subj, "heading": heading, "narrative": s["narrative"]["text"]}
    return subj, _env.get_template("pulse.html.j2").render(ctx), _env.get_template("pulse.txt.j2").render(ctx)
