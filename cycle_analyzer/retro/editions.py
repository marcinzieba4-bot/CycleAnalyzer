"""Edition calendar: information cutoffs, ALFRED vintages, training anchors."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import pandas as pd

WARSAW = ZoneInfo("Europe/Warsaw")


@dataclass(frozen=True)
class Edition:
    date: date                 # the edition Sunday
    cutoff_utc: datetime       # 00:00 Europe/Warsaw on the edition date, in UTC
    alfred_vintage: date       # Friday before the cutoff
    anchor: pd.Period          # last completed calendar month before the cutoff

    @property
    def iso(self) -> str:
        return self.date.isoformat()

    @property
    def cutoff_iso(self) -> str:
        return self.cutoff_utc.strftime("%Y-%m-%dT%H:%M:%SZ")

    @property
    def last_eligible_day(self) -> date:
        """Last calendar day wholly before the cutoff (the Saturday)."""
        return self.date - timedelta(days=1)


def make_edition(d: date) -> Edition:
    if d.weekday() != 6:
        raise ValueError(f"{d} is not a Sunday")
    local_midnight = datetime(d.year, d.month, d.day, tzinfo=WARSAW)
    cutoff = local_midnight.astimezone(timezone.utc)
    friday = d - timedelta(days=2)
    anchor = pd.Period(d, freq="M") - 1
    return Edition(date=d, cutoff_utc=cutoff, alfred_vintage=friday, anchor=anchor)


def biweekly_sundays(start: date, end: date, step_days: int = 14) -> list[date]:
    """Every ``step_days`` (14 = every second Sunday, 7 = weekly) from the first
    Sunday on/after ``start`` through ``end``."""
    if step_days % 7:
        raise ValueError("step must be a whole number of weeks")
    d = start + timedelta(days=(6 - start.weekday()) % 7)
    out = []
    while d <= end:
        out.append(d)
        d += timedelta(days=step_days)
    return out
