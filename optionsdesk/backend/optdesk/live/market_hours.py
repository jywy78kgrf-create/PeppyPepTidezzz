"""US equity/options market-hours awareness.

One question, answered honestly: is the market open right now? Regular
trading hours only — Mon-Fri 09:30-16:00 America/New_York, DST-correct.

Known limitation (documented, deliberate): the NYSE holiday calendar is NOT
modeled. On a market holiday this reports "open" during weekday RTH; the
cost is a handful of Alpha Vantage calls returning stale quotes, which the
mark/tape paths already label EOD when they fail to produce live data.
"""
from __future__ import annotations

from datetime import datetime, time, timezone
from zoneinfo import ZoneInfo

_NY = ZoneInfo("America/New_York")
_OPEN = time(9, 30)
_CLOSE = time(16, 0)


def market_open(now: datetime | None = None) -> bool:
    """True during regular US trading hours (Mon-Fri 09:30-16:00 ET).

    ``now`` may be naive (treated as UTC — the desk's convention) or
    timezone-aware; omitted means the real current time.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    ny = now.astimezone(_NY)
    if ny.weekday() >= 5:  # Sat/Sun
        return False
    return _OPEN <= ny.time() < _CLOSE
