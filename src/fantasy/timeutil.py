"""Dates and times.

ESPN sends epoch milliseconds. An NBA "day" (one fantasy scoring period) is
a US Eastern calendar date, so game days are always worked out in Eastern
time, while report timestamps use the reader's own timezone.
"""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable
from datetime import UTC, date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

EASTERN = ZoneInfo("America/New_York")


def ms_to_iso(ms: Any) -> str | None:
    if ms in (None, 0, ""):
        return None
    try:
        return datetime.fromtimestamp(float(ms) / 1000, UTC).isoformat()
    except (TypeError, ValueError, OverflowError, OSError):
        return None


def parse_iso(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def eastern_date(value: str) -> date:
    return parse_iso(value).astimezone(EASTERN).date()


def local_date(value: str, tz: ZoneInfo) -> date:
    return parse_iso(value).astimezone(tz).date()


def sp_dates_from(pairs: Iterable[tuple[int, str]]) -> dict[int, date]:
    """Scoring period -> NBA date, from (scoring period, ISO date) pairs."""
    counts: dict[int, Counter[str]] = {}
    for sp, day in pairs:
        counts.setdefault(sp, Counter())[day] += 1
    return {sp: date.fromisoformat(c.most_common(1)[0][0]) for sp, c in counts.items()}


def date_for_sp(sp_dates: dict[int, date], sp: int) -> date | None:
    """A scoring period is one day, so a period with no games (All-Star
    break) is dated by counting days from the nearest one that has games."""
    if sp in sp_dates:
        return sp_dates[sp]
    if not sp_dates:
        return None
    nearest = min(sp_dates, key=lambda k: abs(k - sp))
    return sp_dates[nearest] + timedelta(days=sp - nearest)


def day_label(day: date) -> str:
    return day.strftime("%a %m/%d")
