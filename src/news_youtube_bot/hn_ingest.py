from __future__ import annotations

import logging
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timezone

import httpx

from news_youtube_bot.models import NewsItem
from news_youtube_bot.rank_local import TECH_TOKENS, tech_score
from news_youtube_bot.textutil import stable_id

logger = logging.getLogger(__name__)

_HN_ITEM = "https://hacker-news.firebaseio.com/v0/item/{item_id}.json"
_HN_LISTS = (
    "https://hacker-news.firebaseio.com/v0/topstories.json",
    "https://hacker-news.firebaseio.com/v0/newstories.json",
)
_UA = "NewsYouTubeBot/0.2 (technology shorts; hacker-news ingest) python-httpx"


def _story_from_payload(data: dict) -> NewsItem | None:
    if not data or data.get("type") != "story":
        return None
    url = (data.get("url") or "").strip()
    title = (data.get("title") or "").strip()
    if not url or not title:
        return None
    if title.lower().startswith("ask hn"):
        return None
    score = int(data.get("score") or 0)
    if score < 15:
        return None
    published = None
    if data.get("time"):
        published = datetime.fromtimestamp(int(data["time"]), tz=timezone.utc)
    summary = (data.get("text") or "").strip()
    tokens = set(re.findall(r"[a-z0-9+]+", title.lower()))
    return NewsItem(
        id=stable_id(url),
        title=title,
        link=url,
        summary=summary,
        published=published,
        feed_name="Hacker News",
        raw={
            "hn_score": score,
            "hn_comments": data.get("descendants") or 0,
            "tech": bool(tokens & TECH_TOKENS) or tech_score(title) > 0,
            "source_kind": "hackernews",
        },
    )


def fetch_hacker_news(timeout: float, limit: int = 30) -> list[NewsItem]:
    headers = {"User-Agent": _UA}
    ids: list[int] = []
    with httpx.Client(headers=headers, timeout=timeout, follow_redirects=True) as client:
        for endpoint in _HN_LISTS:
            try:
                response = client.get(endpoint)
                response.raise_for_status()
                batch = response.json()
            except (httpx.HTTPError, ValueError) as exc:
                logger.warning("Hacker News list failed %s: %s", endpoint, exc)
                continue
            if isinstance(batch, list):
                ids.extend(int(i) for i in batch[:limit])
        # Preserve order, drop dupes.
        seen: set[int] = set()
        ordered: list[int] = []
        for item_id in ids:
            if item_id in seen:
                continue
            seen.add(item_id)
            ordered.append(item_id)

    def _load(item_id: int) -> NewsItem | None:
        try:
            with httpx.Client(headers=headers, timeout=timeout, follow_redirects=True) as item_client:
                response = item_client.get(_HN_ITEM.format(item_id=item_id))
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            logger.debug("HN item %s failed: %s", item_id, exc)
            return None
        if not isinstance(payload, dict):
            return None
        return _story_from_payload(payload)

    stories: list[NewsItem] = []
    with ThreadPoolExecutor(max_workers=8) as pool:
        futures = [pool.submit(_load, item_id) for item_id in ordered[: limit * 2]]
        for future in as_completed(futures):
            story = future.result()
            if story:
                stories.append(story)
    logger.info("Hacker News: %d stories", len(stories))
    return stories
