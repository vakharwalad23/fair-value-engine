"""Market hours awareness — NSE trading hours + holiday calendar."""
import json
import logging
from datetime import date, time, timedelta
from pathlib import Path
from typing import Optional

import requests

from src.utils.time_utils import ist_now

logger = logging.getLogger(__name__)

NSE_OPEN = time(9, 15)
NSE_CLOSE = time(15, 30)
NSE_PRE_OPEN = time(9, 0)
HOLIDAY_URL = "https://www.nseindia.com/api/holiday-master?type=trading"
HOLIDAY_HEADERS = {"user-agent": "Mozilla/5.0"}


class MarketCalendar:
    def __init__(self, cache_dir: str = "cache"):
        self._cache_path = Path(cache_dir) / "nse_holidays.json"
        self._holidays: set[date] = set()
        self._loaded = False

    def load(self):
        """Fetch holidays from NSE or use cache."""
        # Try NSE API first
        try:
            resp = requests.get(HOLIDAY_URL, headers=HOLIDAY_HEADERS, timeout=10)
            resp.raise_for_status()
            data = resp.json()
            fo_holidays = data.get("FO", [])
            self._holidays = set()
            for h in fo_holidays:
                try:
                    self._holidays.add(date.fromisoformat(h["tradingDate"]))
                except (KeyError, ValueError):
                    continue
            # Cache to disk
            self._cache_path.parent.mkdir(parents=True, exist_ok=True)
            self._cache_path.write_text(json.dumps([d.isoformat() for d in sorted(self._holidays)]))
            logger.info(f"Loaded {len(self._holidays)} NSE F&O holidays from API")
            self._loaded = True
            return
        except Exception as e:
            logger.warning(f"Failed to fetch NSE holidays: {e}")

        # Fallback to cache
        if self._cache_path.exists():
            try:
                dates = json.loads(self._cache_path.read_text())
                self._holidays = {date.fromisoformat(d) for d in dates}
                logger.info(f"Loaded {len(self._holidays)} NSE holidays from cache")
                self._loaded = True
                return
            except Exception as e:
                logger.warning(f"Failed to read holiday cache: {e}")

        # No holidays — assume weekdays only
        logger.warning("No holiday data available, using weekday-only calendar")
        self._loaded = True

    def is_holiday(self, dt: Optional[date] = None) -> bool:
        if dt is None:
            dt = ist_now().date()
        return dt in self._holidays

    def is_trading_day(self, dt: Optional[date] = None) -> bool:
        if dt is None:
            dt = ist_now().date()
        if dt.weekday() >= 5:  # Saturday/Sunday
            return False
        return not self.is_holiday(dt)


# Module-level singleton
_calendar = MarketCalendar()


def load_holidays(cache_dir: str = "cache"):
    global _calendar
    _calendar = MarketCalendar(cache_dir)
    _calendar.load()


def is_market_open() -> bool:
    now = ist_now()
    if not _calendar.is_trading_day(now.date()):
        return False
    t = now.time()
    return NSE_OPEN <= t <= NSE_CLOSE


def is_pre_open() -> bool:
    now = ist_now()
    if not _calendar.is_trading_day(now.date()):
        return False
    t = now.time()
    return NSE_PRE_OPEN <= t < NSE_OPEN


def seconds_until_market_open() -> float:
    now = ist_now()
    # Find next trading day
    target = now.date()
    if now.time() > NSE_CLOSE:
        target += timedelta(days=1)
    # Skip weekends and holidays
    for _ in range(10):  # max 10 days ahead
        if _calendar.is_trading_day(target):
            break
        target += timedelta(days=1)
    # Combine with market open time
    from datetime import datetime
    open_dt = datetime.combine(target, NSE_OPEN, tzinfo=now.tzinfo)
    diff = (open_dt - now).total_seconds()
    return max(0, diff)


def next_market_open():
    now = ist_now()
    secs = seconds_until_market_open()
    return now + timedelta(seconds=secs)


def market_status() -> str:
    """Returns 'LIVE', 'PRE_OPEN', 'CLOSED'."""
    if is_market_open():
        return "LIVE"
    if is_pre_open():
        return "PRE_OPEN"
    return "CLOSED"
