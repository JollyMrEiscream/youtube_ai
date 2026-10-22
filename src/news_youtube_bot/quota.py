from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

# YouTube's quota day resets at midnight Pacific Time.
PACIFIC = ZoneInfo("America/Los_Angeles")


@dataclass
class QuotaState:
    date: str
    uploads: int = 0
    units: int = 0


def pacific_today(now: datetime | None = None) -> str:
    moment = now or datetime.now(PACIFIC)
    if moment.tzinfo is None:
        moment = moment.replace(tzinfo=PACIFIC)
    return moment.astimezone(PACIFIC).date().isoformat()


def load_quota(path: Path, today: str) -> QuotaState:
    if not path.is_file():
        return QuotaState(date=today)
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return QuotaState(date=today)
    state = QuotaState(
        date=str(raw.get("date") or today),
        uploads=int(raw.get("uploads") or 0),
        units=int(raw.get("units") or 0),
    )
    if state.date != today:
        return QuotaState(date=today)
    return state


def save_quota(path: Path, state: QuotaState) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps({"date": state.date, "uploads": state.uploads, "units": state.units}, indent=2),
        encoding="utf-8",
    )


def plan_slots(
    approved_count: int,
    state: QuotaState,
    *,
    today: str,
    max_uploads: int,
    unit_cost: int,
    daily_units: int,
) -> tuple[int, QuotaState]:
    """How many approved videos may upload right now.

    `max_uploads` is the product cap (default 6, from the classic 10,000 unit
    quota divided by a 1,600 unit videos.insert). `daily_units` and `unit_cost`
    are a second guard so the local counter matches whichever quota model the
    Cloud project is actually on.
    """
    if state.date != today:
        state = QuotaState(date=today)
    by_count = max(0, max_uploads - state.uploads)
    if unit_cost <= 0:
        by_units = by_count
    else:
        remaining = max(0, daily_units - state.units)
        by_units = remaining // unit_cost
    slots = min(by_count, by_units, max(0, approved_count))
    return slots, state
