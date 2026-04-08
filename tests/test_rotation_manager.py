import time
from unittest.mock import MagicMock
from src.subscription.rotation_manager import RotationManager

def test_compute_atm_strike():
    rm = RotationManager.__new__(RotationManager)
    strikes = [23300, 23350, 23400, 23450, 23500, 23550, 23600, 23650, 23700]
    atm = rm._nearest_strike(23512.0, strikes)
    assert atm == 23500

def test_strikes_in_range():
    rm = RotationManager.__new__(RotationManager)
    strikes = [23300, 23350, 23400, 23450, 23500, 23550, 23600, 23650, 23700]
    in_range = rm._strikes_in_range(23500, strikes, 3)
    assert 23500 in in_range
    assert 23350 in in_range
    assert 23650 in in_range
    assert 23300 not in in_range

def test_mark_stale():
    rm = RotationManager.__new__(RotationManager)
    rm._stale = {}
    rm._stale_ttl = 1800
    rm._mark_stale("42528")
    assert "42528" in rm._stale
    assert rm._stale["42528"] > 0

def test_evict_stale():
    rm = RotationManager.__new__(RotationManager)
    rm._stale = {"42528": time.time() - 3600}
    rm._stale_ttl = 1800
    rm._engine = MagicMock()
    evicted = rm._evict_expired_stale()
    assert "42528" in evicted
    assert "42528" not in rm._stale
