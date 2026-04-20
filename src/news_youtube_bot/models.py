from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any


@dataclass
class NewsItem:
    """Normalized RSS entry."""

    id: str
    title: str
    link: str
    summary: str
    published: datetime | None
    feed_name: str | None = None
    raw: dict[str, Any] = field(default_factory=dict)

    def to_llm_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "title": self.title,
            "link": self.link,
            "summary": (self.summary or "")[:2000],
            "published": self.published.isoformat() if self.published else None,
            "feed_name": self.feed_name,
        }
