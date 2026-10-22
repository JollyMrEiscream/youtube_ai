from __future__ import annotations

import logging
from datetime import datetime
from email.utils import parsedate_to_datetime
from typing import Any

import feedparser
import httpx

from news_youtube_bot.config import Settings
from news_youtube_bot.media import USER_AGENT
from news_youtube_bot.models import NewsItem
from news_youtube_bot.textutil import html_to_text, stable_id

logger = logging.getLogger(__name__)


def _parse_published(entry: dict[str, Any]) -> datetime | None:
    for key in ("published_parsed", "updated_parsed"):
        t = entry.get(key)
        if t:
            try:
                return datetime(*t[:6])
            except (TypeError, ValueError):
                pass
    for key in ("published", "updated"):
        raw = entry.get(key)
        if raw and isinstance(raw, str):
            try:
                return parsedate_to_datetime(raw)
            except (TypeError, ValueError):
                try:
                    return datetime.fromisoformat(raw.replace("Z", "+00:00"))
                except ValueError:
                    pass
    return None


def _normalize_entry(
    entry: dict[str, Any],
    feed_name: str | None,
) -> NewsItem | None:
    link = (entry.get("link") or entry.get("id") or "").strip()
    title = (entry.get("title") or "Untitled").strip()
    if not link:
        return None
    summary = entry.get("summary") or entry.get("description") or ""
    if not isinstance(summary, str):
        summary = str(summary)
    summary = html_to_text(summary)
    published = _parse_published(entry)
    return NewsItem(
        id=stable_id(link),
        title=title,
        link=link,
        summary=summary,
        published=published,
        feed_name=feed_name,
        raw={"guid": entry.get("id"), "tech": True, "source_kind": "rss"},
    )


def fetch_feed(
    client: httpx.Client,
    url: str,
    feed_name: str | None,
    timeout: float,
) -> list[NewsItem]:
    logger.info("Fetching feed %s", url)
    try:
        resp = client.get(url, timeout=timeout)
        resp.raise_for_status()
    except httpx.HTTPError as e:
        logger.warning("Feed fetch failed %s: %s", url, e)
        return []

    parsed = feedparser.parse(resp.content)
    items: list[NewsItem] = []
    for entry in parsed.entries:
        if isinstance(entry, dict):
            ni = _normalize_entry(entry, feed_name)
            if ni:
                items.append(ni)
    return items


def ingest_all(
    settings: Settings,
    feed_pairs: list[tuple[str, str | None]],
) -> list[NewsItem]:
    if not feed_pairs:
        logger.error("No RSS feeds configured. Set RSS_FEED_URLS or config/feeds.yaml")
        return []

    out: list[NewsItem] = []
    with httpx.Client(headers={"User-Agent": USER_AGENT}, follow_redirects=True) as client:
        for url, name in feed_pairs:
            out.extend(fetch_feed(client, url, name, settings.fetch_timeout_seconds))
    return out
