import json
from src.subscription.tier_config import TierConfig

def test_defaults():
    tc = TierConfig()
    assert "NIFTY" in tc.tier1_underlyings
    assert tc.tier2_atm_range == 10
    assert tc.tier3_contracts == []

def test_save_and_load(tmp_path):
    path = str(tmp_path / "tier_config.json")
    tc = TierConfig(config_path=path)
    tc.tier1_underlyings = ["NIFTY", "BANKNIFTY"]
    tc.tier2_stocks = ["RELIANCE"]
    tc.tier3_contracts = [{"security_id": "50001", "exchange_segment": "NSE_FNO"}]
    tc.save()
    tc2 = TierConfig(config_path=path)
    tc2.load()
    assert tc2.tier1_underlyings == ["NIFTY", "BANKNIFTY"]
    assert tc2.tier2_stocks == ["RELIANCE"]
    assert len(tc2.tier3_contracts) == 1

def test_load_missing_file():
    tc = TierConfig(config_path="/nonexistent/path.json")
    tc.load()
    assert "NIFTY" in tc.tier1_underlyings

def test_add_tier3():
    tc = TierConfig()
    tc.add_tier3("50001", "NSE_FNO")
    assert len(tc.tier3_contracts) == 1
    tc.add_tier3("50001", "NSE_FNO")
    assert len(tc.tier3_contracts) == 1

def test_remove_tier3():
    tc = TierConfig()
    tc.add_tier3("50001", "NSE_FNO")
    tc.remove_tier3("50001")
    assert len(tc.tier3_contracts) == 0

def test_to_dict():
    tc = TierConfig()
    d = tc.to_dict()
    assert "tier1_underlyings" in d
    assert "tier1_expiry_count" in d
    assert "tier2_stocks" in d
    assert "tier3_contracts" in d

def test_tier1_expiry_count_default():
    tc = TierConfig()
    assert tc.tier1_expiry_count == 2

def test_tier1_expiry_count_save_load(tmp_path):
    path = str(tmp_path / "tier_config.json")
    tc = TierConfig(config_path=path)
    tc.tier1_expiry_count = 3
    tc.save()
    tc2 = TierConfig(config_path=path)
    tc2.load()
    assert tc2.tier1_expiry_count == 3

def test_update_method(tmp_path):
    path = str(tmp_path / "tier_config.json")
    tc = TierConfig(config_path=path)
    tc.update(tier1_underlyings=["NIFTY"], tier2_atm_range=5, tier1_expiry_count=4)
    assert tc.tier1_underlyings == ["NIFTY"]
    assert tc.tier2_atm_range == 5
    assert tc.tier1_expiry_count == 4
    # Unchanged fields should keep defaults
    assert tc.tier2_expiry_count == 2

def test_update_partial(tmp_path):
    path = str(tmp_path / "tier_config.json")
    tc = TierConfig(config_path=path)
    original_underlyings = list(tc.tier1_underlyings)
    tc.update(tier2_stocks=["RELIANCE"])
    assert tc.tier2_stocks == ["RELIANCE"]
    assert tc.tier1_underlyings == original_underlyings
