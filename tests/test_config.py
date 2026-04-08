import os

def test_settings_defaults():
    from src.config import Settings
    s = Settings()
    assert s.HOST == os.getenv("HOST", "0.0.0.0")
    assert s.PORT == int(os.getenv("PORT", "8000"))
    assert s.MAX_CONNECTIONS == 3
    assert s.INSTRUMENTS_PER_CONNECTION == 5000
    assert s.SCRIP_CACHE_DIR == "cache"
    assert not hasattr(s, "FEED_MODE")

def test_total_slots():
    from src.config import Settings
    s = Settings()
    assert s.total_slots == s.MAX_CONNECTIONS * s.INSTRUMENTS_PER_CONNECTION
