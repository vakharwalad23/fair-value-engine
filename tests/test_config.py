def test_settings_has_required_fields():
    from src.config import Settings
    s = Settings()
    assert isinstance(s.DHAN_CLIENT_ID, str)
    assert isinstance(s.DHAN_ACCESS_TOKEN, str)
    assert isinstance(s.HOST, str)
    assert isinstance(s.PORT, int)
    assert isinstance(s.MAX_CONNECTIONS, int)
    assert isinstance(s.INSTRUMENTS_PER_CONNECTION, int)
    assert isinstance(s.SCRIP_CACHE_DIR, str)
    assert isinstance(s.STALE_TTL_MINUTES, int)
    assert not hasattr(s, "FEED_MODE")

def test_total_slots():
    from src.config import Settings
    s = Settings()
    assert s.total_slots == s.MAX_CONNECTIONS * s.INSTRUMENTS_PER_CONNECTION
