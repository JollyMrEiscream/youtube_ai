from __future__ import annotations

import logging
from datetime import datetime

import httpx

from news_youtube_bot.media import USER_AGENT
from news_youtube_bot.models import NewsItem
from news_youtube_bot.textutil import html_to_text, stable_id

logger = logging.getLogger(__name__)


def fetch_newsapi(api_key: str, timeout: float) -> list[NewsItem]:
    params = {
        "category": "technology",
        "language": "en",
        "pageSize": 40,
        "apiKey": api_key,
    }
    try:
        response = httpx.get(
            "https://newsapi.org/v2/top-headlines",
            params=params,
            headers={"User-Agent": USER_AGENT},
            timeout=timeout,
            follow_redirects=True,
        )
        response.raise_for_status()
        payload = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        logger.warning("NewsAPI fetch failed: %s", exc)
        return []
    items: list[NewsItem] = []
    for article in payload.get("articles") or []:
        url = (article.get("url") or "").strip()
        title = (article.get("title") or "").strip()
        if not url or not title or title.lower() == "[removed]":
            continue
        published = None
        raw_date = article.get("publishedAt")
        if isinstance(raw_date, str):
            try:
                published = datetime.fromisoformat(raw_date.replace("Z", "+00:00"))
            except ValueError:
                published = None
        source = ((article.get("source") or {}).get("name")) or "NewsAPI"
        summary = html_to_text(article.get("description") or article.get("content") or "")
        items.append(
            NewsItem(
                id=stable_id(url),
                title=title,
                link=url,
                summary=summary,
                published=published,
                feed_name=str(source),
                raw={"tech": True, "source_kind": "newsapi"},
            )
        )
    logger.info("NewsAPI: %d stories", len(items))
    return items
