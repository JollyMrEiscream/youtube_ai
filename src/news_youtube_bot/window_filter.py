from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone

from news_youtube_bot.models import NewsItem

logger = logging.getLogger(__name__)


def filter_by_window(
    items: list[NewsItem],
    window_minutes: int,
    now: datetime | None = None,
) -> list[NewsItem]:
    """Keep items published within the last `window_minutes` (UTC-aware comparison)."""
    if now is None:
        now = datetime.now(timezone.utc)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    cutoff = now - timedelta(minutes=window_minutes)
    kept: list[NewsItem] = []
    skipped_no_date = 0

    for item in items:
        pub = item.published
        if pub is None:
            skipped_no_date += 1
            continue
        if pub.tzinfo is None:
            pub = pub.replace(tzinfo=timezone.utc)
        if pub >= cutoff:
            kept.append(item)

    if skipped_no_date:
        logger.debug("Skipped %d items without parseable published date", skipped_no_date)
    logger.info("Window filter: %d -> %d items (since %s)", len(items), len(kept), cutoff.isoformat())
    return kept
