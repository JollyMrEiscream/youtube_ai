from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path


def _parse_day(value: str) -> date | None:
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


class UsedClipStore:
    """Clips already used in the last `days` days. One file, small on purpose."""

    def __init__(self, path: Path, days: int = 7) -> None:
        self.path = path
        self.days = max(1, days)
        self.rows: list[dict] = []
        if path.is_file():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                raw = {}
            clips = raw.get("clips") if isinstance(raw, dict) else None
            if isinstance(clips, list):
                self.rows = [row for row in clips if isinstance(row, dict)]

    def seen(self, clip_id: str, today: date) -> bool:
        for row in self.rows:
            if row.get("id") != clip_id:
                continue
            used = _parse_day(str(row.get("used_on") or ""))
            if used is None:
                continue
            if (today - used).days < self.days:
                return True
        return False

    def mark(self, clip_id: str, today: date, story_id: str) -> None:
        kept: list[dict] = []
        for row in self.rows:
            if row.get("id") == clip_id:
                continue
            used = _parse_day(str(row.get("used_on") or ""))
            if used is None or (today - used).days < self.days * 3:
                kept.append(row)
        kept.append({"id": clip_id, "used_on": today.isoformat(), "story": story_id})
        self.rows = kept
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps({"clips": self.rows}, indent=2) + "\n", encoding="utf-8")


class AiClipBudget:
    def __init__(self, path: Path, today: str, limit: int) -> None:
        self.path = path
        self.today = today
        self.limit = max(0, limit)
        self.count = 0
        if path.is_file():
            try:
                raw = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError):
                raw = {}
            if isinstance(raw, dict) and str(raw.get("date") or "") == today:
                try:
                    self.count = int(raw.get("count") or 0)
                except (TypeError, ValueError):
                    self.count = 0

    @classmethod
    def for_moment(cls, path: Path, when: datetime, limit: int) -> AiClipBudget:
        return cls(path, when.date().isoformat(), limit)

    def remaining(self) -> int:
        return max(0, self.limit - self.count)

    def consume(self) -> None:
        self.count += 1
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {"date": self.today, "count": self.count}
        self.path.write_text(json.dumps(payload) + "\n", encoding="utf-8")
