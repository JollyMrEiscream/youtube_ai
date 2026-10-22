from __future__ import annotations

import logging
import re
from datetime import datetime, timezone

from news_youtube_bot.models import NewsItem

logger = logging.getLogger(__name__)

TECH_TOKENS = {
    "ai",
    "llm",
    "gpt",
    "chip",
    "chips",
    "gpu",
    "cpu",
    "apple",
    "google",
    "microsoft",
    "meta",
    "amazon",
    "openai",
    "anthropic",
    "nvidia",
    "intel",
    "amd",
    "samsung",
    "tesla",
    "robot",
    "robots",
    "robotics",
    "software",
    "security",
    "linux",
    "android",
    "iphone",
    "ios",
    "macos",
    "windows",
    "cloud",
    "startup",
    "app",
    "apps",
    "browser",
    "quantum",
    "battery",
    "satellite",
    "semiconductor",
    "model",
    "hack",
    "hacker",
    "privacy",
    "data",
    "phone",
    "gadget",
    "developer",
    "github",
    "cyber",
    "encryption",
    "wifi",
    "5g",
    "server",
    "database",
    "api",
    "code",
    "programming",
    "spacex",
    "nasa",
    "rocket",
    "ev",
    "autonomous",
    "drone",
    "chatgpt",
    "gemini",
    "claude",
}

_SKIP_TITLE = re.compile(
    r"^(ask hn|who is hiring|hiring\b)|is hiring|launch hn|please (ask|help)|show hn:\s*who",
    re.I,
)


def is_skippable_title(title: str) -> bool:
    return bool(_SKIP_TITLE.search(title or ""))


def tech_score(title: str) -> float:
    tokens = set(re.findall(r"[a-z0-9+]+", (title or "").lower()))
    hits = tokens & TECH_TOKENS
    return min(0.45, 0.15 * len(hits))


def _age_hours(item: NewsItem, now: datetime) -> float:
    pub = item.published
    if pub is None:
        return 72.0
    if pub.tzinfo is None:
        pub = pub.replace(tzinfo=timezone.utc)
    return max(0.0, (now - pub).total_seconds() / 3600.0)


def score_item(item: NewsItem, now: datetime) -> float:
    age = _age_hours(item, now)
    recency = max(0.0, 48.0 - age) / 48.0
    summary_len = min(len(item.summary or ""), 800) / 800.0
    hn = min(int(item.raw.get("hn_score") or 0), 400) / 400.0
    tech = 0.2 if item.raw.get("tech") else tech_score(item.title)
    return recency * 0.55 + summary_len * 0.2 + hn * 0.35 + tech


def select_stories(items: list[NewsItem], count: int, now: datetime | None = None) -> list[NewsItem]:
    """Pick a diverse set: prefer tech-flagged items, then cap repeats from one outlet."""
    moment = now or datetime.now(timezone.utc)
    pool = [item for item in items if not is_skippable_title(item.title)]
    ranked = sorted(pool, key=lambda item: score_item(item, moment), reverse=True)
    preferred = [item for item in ranked if item.raw.get("tech") or tech_score(item.title) > 0]
    rest = [item for item in ranked if item not in preferred]
    ordered = preferred + rest

    def _take(source: list[NewsItem], per_feed: int) -> list[NewsItem]:
        picked: list[NewsItem] = []
        per: dict[str, int] = {}
        for item in source:
            feed = item.feed_name or item.link
            if per.get(feed, 0) >= per_feed:
                continue
            picked.append(item)
            per[feed] = per.get(feed, 0) + 1
            if len(picked) >= count:
                break
        return picked

    picked = _take(ordered, per_feed=1)
    if len(picked) < count:
        seen = {item.id for item in picked}
        picked.extend(item for item in _take(ordered, per_feed=2) if item.id not in seen)
        picked = picked[:count]
    if len(picked) < count:
        seen = {item.id for item in picked}
        for item in ordered:
            if item.id in seen:
                continue
            picked.append(item)
            if len(picked) >= count:
                break
    logger.info("Local rank selected %d of %d stories", len(picked), len(items))
    return picked[:count]
