"""IST timezone helpers and expiry math."""
from datetime import date, datetime, timezone, timedelta

IST = timezone(timedelta(hours=5, minutes=30))


def ist_now() -> datetime:
    """Current datetime in IST."""
    return datetime.now(IST)


def time_to_expiry_years(expiry: date, today: date | None = None) -> float:
    """Days to expiry / 365.0, clamped to min 1 day."""
    if today is None:
        today = ist_now().date()
    days = (expiry - today).days
    return max(days, 1) / 365.0


def next_refresh_delay_seconds(target_hour: int = 8, target_minute: int = 45) -> float:
    """Seconds until the next occurrence of target_hour:target_minute IST."""
    now = ist_now()
    target = now.replace(hour=target_hour, minute=target_minute, second=0, microsecond=0)
    if target <= now:
        target += timedelta(days=1)
    return (target - now).total_seconds()
