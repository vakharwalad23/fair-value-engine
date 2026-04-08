from datetime import date, datetime
from src.utils.time_utils import ist_now, time_to_expiry_years, next_refresh_delay_seconds

def test_ist_now_returns_ist():
    now = ist_now()
    assert now.tzinfo is not None
    assert now.utcoffset().total_seconds() == 19800

def test_time_to_expiry_years_future():
    today = date(2026, 4, 8)
    expiry = date(2026, 4, 29)
    T = time_to_expiry_years(expiry, today)
    assert 0.05 < T < 0.07

def test_time_to_expiry_years_past():
    today = date(2026, 4, 8)
    expiry = date(2026, 4, 1)
    T = time_to_expiry_years(expiry, today)
    assert T == 1 / 365.0

def test_time_to_expiry_years_same_day():
    today = date(2026, 4, 8)
    T = time_to_expiry_years(today, today)
    assert T == 1 / 365.0

def test_next_refresh_delay_seconds():
    delay = next_refresh_delay_seconds(target_hour=8, target_minute=45)
    assert 0 < delay <= 86400
