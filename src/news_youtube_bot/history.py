from __future__ import annotations

import logging
import sqlite3
from datetime import datetime, timezone
from difflib import SequenceMatcher
from pathlib import Path

from news_youtube_bot.dedupe import canonicalize_url, _normalize_title
from news_youtube_bot.models import NewsItem

logger = logging.getLogger(__name__)

_TITLE_THRESHOLD = 0.86


class StoryHistory:
    """Stories already turned into a Short, so tomorrow's batch does not repeat them."""

    def __init__(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        self.conn = sqlite3.connect(path)
        self.conn.execute(
            """
            CREATE TABLE IF NOT EXISTS used (
                story_id TEXT PRIMARY KEY,
                url TEXT,
                title TEXT,
                title_norm TEXT,
                used_on TEXT
            )
            """
        )
        self.conn.execute("CREATE INDEX IF NOT EXISTS idx_used_url ON used(url)")
        self.conn.commit()

    def close(self) -> None:
        self.conn.close()

    def filter_fresh(self, items: list[NewsItem], title_lookback: int = 400) -> list[NewsItem]:
        urls = {
            row[0]
            for row in self.conn.execute("SELECT url FROM used")
            if row[0]
        }
        recent = [
            row[0]
            for row in self.conn.execute(
                "SELECT title_norm FROM used ORDER BY used_on DESC LIMIT ?",
                (title_lookback,),
            )
            if row[0]
        ]
        fresh: list[NewsItem] = []
        for item in items:
            url = canonicalize_url(item.link)
            if url in urls:
                logger.debug("History dropped url %s", url)
                continue
            title_norm = _normalize_title(item.title)
            if any(SequenceMatcher(None, title_norm, prev).ratio() >= _TITLE_THRESHOLD for prev in recent):
                logger.debug("History dropped similar title %s", item.title[:80])
                continue
            fresh.append(item)
        logger.info("History filter: %d -> %d", len(items), len(fresh))
        return fresh

    def mark_used(self, item: NewsItem, when: datetime | None = None) -> None:
        moment = when or datetime.now(timezone.utc)
        self.conn.execute(
            """
            INSERT INTO used (story_id, url, title, title_norm, used_on)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(story_id) DO UPDATE SET
                url=excluded.url,
                title=excluded.title,
                title_norm=excluded.title_norm,
                used_on=excluded.used_on
            """,
            (
                item.id,
                canonicalize_url(item.link),
                item.title,
                _normalize_title(item.title),
                moment.isoformat(),
            ),
        )
        self.conn.commit()
