"""Source adapters (P1-BE-07). `rss_generic` handles ET, Mint and Business Standard as-is;
adapters only override what a feed gets wrong."""

from collections.abc import Callable
from dataclasses import dataclass

import feedparser

from geotrade_ai.normalize import clean_title, strip_html


@dataclass
class RawItem:
    title: str
    url: str
    summary: str
    published_raw: str | None


def rss_generic(content: bytes) -> list[RawItem]:
    feed = feedparser.parse(content)
    items = []
    for entry in feed.entries:
        title = clean_title(entry.get("title", ""))
        url = (entry.get("link") or entry.get("id") or "").strip()
        if not title or not url.startswith("http"):
            continue
        items.append(
            RawItem(
                title=title,
                url=url,
                summary=strip_html(entry.get("summary") or entry.get("description")),
                published_raw=entry.get("published") or entry.get("updated"),
            )
        )
    return items


def moneycontrol(content: bytes) -> list[RawItem]:
    # descriptions start with an <img> whose alt/title repeat the headline; drop the repeat
    items = rss_generic(content)
    for item in items:
        if item.summary.startswith(item.title):
            item.summary = item.summary[len(item.title) :].strip()
    return items


def google_news(content: bytes) -> list[RawItem]:
    """Search feed used for history backfill: titles end with ' - Publisher' and the description is only
    a link list, so drop both; the publisher comes from the item's <source> element."""
    feed = feedparser.parse(content)
    items = []
    for entry in feed.entries:
        publisher = (entry.get("source") or {}).get("title", "")
        title = clean_title(entry.get("title", ""))
        if publisher and title.endswith(f" - {publisher}"):
            title = title[: -len(publisher) - 3].strip()
        url = (entry.get("link") or "").strip()
        if title and url.startswith("http"):
            items.append(RawItem(title=title, url=url, summary="", published_raw=entry.get("published")))
    return items


ADAPTERS: dict[str, Callable[[bytes], list[RawItem]]] = {
    "rss_generic": rss_generic,
    "et": rss_generic,
    "mint": rss_generic,
    "business_standard": rss_generic,
    "moneycontrol": moneycontrol,
    "google_news": google_news,
}
