import time
import threading
from unittest.mock import MagicMock, patch
from src.subscription.rotation_manager import RotationManager


def _make_bare_rm(**overrides):
    """Create a RotationManager without calling __init__, with minimal attrs."""
    rm = RotationManager.__new__(RotationManager)
    rm._stale = {}
    rm._stale_ttl = 1800
    rm._last_atm = {}
    rm._lock = threading.Lock()
    for k, v in overrides.items():
        setattr(rm, k, v)
    return rm


def test_compute_atm_strike():
    rm = _make_bare_rm()
    strikes = [23300, 23350, 23400, 23450, 23500, 23550, 23600, 23650, 23700]
    atm = rm._nearest_strike(23512.0, strikes)
    assert atm == 23500


def test_strikes_in_range():
    rm = _make_bare_rm()
    strikes = [23300, 23350, 23400, 23450, 23500, 23550, 23600, 23650, 23700]
    in_range = rm._strikes_in_range(23500, strikes, 3)
    assert 23500 in in_range
    assert 23350 in in_range
    assert 23650 in in_range
    assert 23300 not in in_range


def test_mark_stale():
    rm = _make_bare_rm()
    rm._mark_stale("42528")
    assert "42528" in rm._stale
    assert rm._stale["42528"] > 0


def test_evict_stale():
    engine = MagicMock()
    engine._lock = threading.Lock()
    engine._contracts = {}
    pool = MagicMock()
    slot_tracker = MagicMock()
    rm = _make_bare_rm(
        _engine=engine,
        _pool=pool,
        _slot_tracker=slot_tracker,
    )
    rm._stale = {"42528": time.time() - 3600}
    evicted = rm._evict_expired_stale()
    assert "42528" in evicted
    assert "42528" not in rm._stale


def test_evict_stale_skips_tier1():
    """Tier 1 contracts should never be evicted even if they appear stale."""
    meta = MagicMock()
    meta.tier = 1
    meta.exchange_segment = "NSE_FO"

    engine = MagicMock()
    engine._lock = threading.Lock()
    engine._contracts = {"100": meta}
    pool = MagicMock()
    slot_tracker = MagicMock()

    rm = _make_bare_rm(
        _engine=engine,
        _pool=pool,
        _slot_tracker=slot_tracker,
    )
    rm._stale = {"100": time.time() - 3600}
    evicted = rm._evict_expired_stale()
    assert "100" not in evicted
    pool.unsubscribe.assert_not_called()
    engine.deregister_contract.assert_not_called()


def test_check_rotation_skips_tier1():
    """_check_rotation should be a no-op for Tier 1 symbols."""
    tier_config = MagicMock()
    tier_config.tier1_underlyings = ["NIFTY", "BANKNIFTY"]
    scrip_master = MagicMock()

    rm = _make_bare_rm(
        _tier_config=tier_config,
        _scrip_master=scrip_master,
    )
    # Should return immediately without calling get_expiries
    rm._check_rotation("NIFTY", 23500.0)
    scrip_master.get_expiries.assert_not_called()


def test_apply_tier1_subscribes_underlying():
    """apply_tier1 should subscribe the underlying index instrument."""
    engine = MagicMock()
    pool = MagicMock()
    pool.subscribe.return_value = True
    scrip_master = MagicMock()
    scrip_master.get_expiries.return_value = ["2026-04-24"]
    scrip_master.get_chain.return_value = []
    scrip_master._underlying_map = {"NIFTY": "13"}
    slot_tracker = MagicMock()
    tier_config = MagicMock()
    tier_config.tier1_underlyings = ["NIFTY"]
    tier_config.tier2_expiry_count = 2

    rm = RotationManager(engine, pool, scrip_master, slot_tracker, tier_config)
    rm.apply_tier1()

    pool.subscribe.assert_called_with("13", "IDX_I")
    slot_tracker.add.assert_called_with("13", tier=1)


def test_apply_tier2_subscribes_underlying():
    """apply_tier2 should subscribe the underlying stock instrument."""
    engine = MagicMock()
    pool = MagicMock()
    pool.subscribe.return_value = True
    scrip_master = MagicMock()
    scrip_master.get_expiries.return_value = ["2026-04-24"]
    scrip_master.get_chain.return_value = []
    scrip_master._underlying_map = {"RELIANCE": "500325"}
    slot_tracker = MagicMock()
    tier_config = MagicMock()
    tier_config.tier2_stocks = ["RELIANCE"]
    tier_config.tier2_expiry_count = 2

    rm = RotationManager(engine, pool, scrip_master, slot_tracker, tier_config)
    rm.apply_tier2()

    pool.subscribe.assert_called_with("500325", "NSE_EQ")
    slot_tracker.add.assert_called_with("500325", tier=2)


def test_resolve_underlying_segment_for_symbol():
    assert RotationManager._resolve_underlying_segment_for_symbol("NIFTY") == "IDX_I"
    assert RotationManager._resolve_underlying_segment_for_symbol("BANKNIFTY") == "IDX_I"
    assert RotationManager._resolve_underlying_segment_for_symbol("SENSEX") == "IDX_I"
    assert RotationManager._resolve_underlying_segment_for_symbol("RELIANCE") == "NSE_EQ"
    assert RotationManager._resolve_underlying_segment_for_symbol("TCS") == "NSE_EQ"
