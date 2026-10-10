"""Pick today's app and bank item. Pure functions of the date."""
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone

EPOCH = date(2026, 10, 11)  # first scheduled run: Waypoint
ORDER = ("waypoint", "scoremybiz")


@dataclass(frozen=True)
class Selection:
    app: str
    item: dict
    bank_index: int
    day: date


def lagos_date(now_utc: datetime) -> date:
    """Lagos is UTC+1 all year (no DST)."""
    return (now_utc.astimezone(timezone.utc) + timedelta(hours=1)).date()


def pick(day: date, banks: dict, skip: int = 0) -> Selection:
    n = (day - EPOCH).days
    app = ORDER[n % 2]
    bank = banks[app]
    if not bank:
        raise ValueError(f"bank for {app} is empty")
    idx = (n // 2 + skip) % len(bank)
    return Selection(app=app, item=bank[idx], bank_index=idx, day=day)
