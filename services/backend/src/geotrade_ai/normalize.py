"""Normaliser (P1-BE-08): URL canonicalisation, title and HTML cleanup, timestamps, language filter."""

import hashlib
import html
import re
import unicodedata
from datetime import UTC, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

IST = timezone(timedelta(hours=5, minutes=30), "IST")
FUTURE_TOLERANCE = timedelta(minutes=5)
TRACKING_PARAMS = {"fbclid", "gclid", "ref", "from", "cmpid", "source", "ito", "utm"}
_TAG = re.compile(r"<[^>]+>")
_SPACE = re.compile(r"\s+")
_NON_WORD = re.compile(r"[^\w\s%.]")


def canonical_url(url: str) -> str:
    parts = urlsplit(url.strip())
    host = (parts.hostname or "").lower()
    if parts.port and parts.port not in (80, 443):
        host = f"{host}:{parts.port}"
    query = sorted(
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=True)
        if not k.lower().startswith("utm_") and k.lower() not in TRACKING_PARAMS
    )
    path = re.sub(r"/{2,}", "/", parts.path) or "/"
    if len(path) > 1:
        path = path.rstrip("/")
    return urlunsplit(("https", host, path, urlencode(query), ""))


def sha_hex(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()[:32]


def url_hash(url: str) -> str:
    return sha_hex(canonical_url(url))


def strip_html(text: str | None) -> str:
    if not text:
        return ""
    # some feeds double-escape entities and drop the ampersand ("company#39;s")
    text = re.sub(r"(?<!&)#(\d+);", r"&#\1;", text)
    text = html.unescape(html.unescape(text))
    return _SPACE.sub(" ", _TAG.sub(" ", text)).strip()


def clean_title(title: str) -> str:
    return strip_html(title)


def normalize_title(title: str) -> str:
    t = unicodedata.normalize("NFKC", clean_title(title)).lower()
    t = t.replace("₹", " rs ").replace("rs.", "rs ")
    t = _NON_WORD.sub(" ", t)
    return _SPACE.sub(" ", t).strip(" .")


def title_hash(title: str) -> str:
    return sha_hex(normalize_title(title))


def parse_published(raw: str | None, fetched_at: datetime) -> tuple[datetime, bool]:
    """Returns (UTC timestamp, time_estimated). Naive times are IST; future times are clamped."""
    parsed: datetime | None = None
    if raw:
        try:
            parsed = parsedate_to_datetime(raw.strip())
        except (TypeError, ValueError):
            try:
                parsed = datetime.fromisoformat(raw.strip())
            except ValueError:
                parsed = None
    if parsed is None:
        return fetched_at, True
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=IST)
    parsed = parsed.astimezone(UTC)
    if parsed > fetched_at + FUTURE_TOLERANCE:
        return fetched_at, True
    return parsed, False


def is_english(text: str, threshold: float = 0.85) -> bool:
    letters = [c for c in text if c.isalpha()]
    if not letters:
        return False
    return sum(c.isascii() for c in letters) / len(letters) >= threshold
