from datetime import date, time, datetime, timezone, timedelta
from src.utils.market_hours import MarketCalendar, is_market_open, market_status, NSE_OPEN, NSE_CLOSE

IST = timezone(timedelta(hours=5, minutes=30))

def test_calendar_weekend():
    cal = MarketCalendar()
    cal._loaded = True
    # Saturday
    assert not cal.is_trading_day(date(2026, 4, 11))
    # Sunday
    assert not cal.is_trading_day(date(2026, 4, 12))

def test_calendar_weekday():
    cal = MarketCalendar()
    cal._loaded = True
    # Monday
    assert cal.is_trading_day(date(2026, 4, 13))

def test_calendar_holiday():
    cal = MarketCalendar()
    cal._holidays = {date(2026, 1, 26)}
    cal._loaded = True
    assert not cal.is_trading_day(date(2026, 1, 26))
    assert cal.is_holiday(date(2026, 1, 26))

def test_market_status():
    # Just verify it returns one of the valid values
    status = market_status()
    assert status in ("LIVE", "PRE_OPEN", "CLOSED")
