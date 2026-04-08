from datetime import date
from src.core.models import ContractType, ContractMeta, Tick, FairResult

def test_contract_type_enum():
    assert ContractType.CALL == "CE"
    assert ContractType.PUT == "PE"
    assert ContractType.FUTURE == "FUT"
    assert ContractType("CE") == ContractType.CALL

def test_contract_meta_defaults():
    meta = ContractMeta(
        security_id="42528",
        symbol="NIFTY23500CE",
        contract_type=ContractType.CALL,
        strike=23500.0,
        expiry=date(2026, 4, 24),
        underlying_security_id="13",
        underlying_symbol="NIFTY",
        exchange_segment="NSE_FNO",
    )
    assert meta.lot_size == 1
    assert meta.risk_free_rate == 0.065
    assert meta.cross_listed is False
    assert meta.exchanges == []
    assert meta.peer_security_id is None
    assert meta.tier is None

def test_contract_meta_future():
    meta = ContractMeta(
        security_id="42534",
        symbol="NIFTYFUT",
        contract_type=ContractType.FUTURE,
        strike=None,
        expiry=date(2026, 4, 24),
        underlying_security_id="13",
        underlying_symbol="NIFTY",
        exchange_segment="NSE_FNO",
    )
    assert meta.strike is None

def test_tick_defaults():
    tick = Tick(security_id="13", ltp=23500.0)
    assert tick.oi is None
    assert tick.volume is None
    assert tick.timestamp > 0

def test_fair_result_signal_fair():
    r = FairResult(
        security_id="42528", symbol="NIFTY23500CE",
        contract_type=ContractType.CALL, strike=23500.0,
        expiry="2026-04-24", market_price=100.0, fair_value=100.5,
        mispricing=-0.5, mispricing_pct=-0.497,
        underlying_price=23500.0, time_to_expiry=0.044,
    )
    assert r.signal == "FAIR"
    assert r.signal_strength < 1.0

def test_fair_result_signal_overvalued():
    r = FairResult(
        security_id="42528", symbol="NIFTY23500CE",
        contract_type=ContractType.CALL, strike=23500.0,
        expiry="2026-04-24", market_price=150.0, fair_value=138.0,
        mispricing=12.0, mispricing_pct=8.7,
        underlying_price=23500.0, time_to_expiry=0.044,
    )
    assert r.signal == "OVERVALUED"
    assert r.signal_strength == 8.7

def test_fair_result_signal_undervalued():
    r = FairResult(
        security_id="42528", symbol="NIFTY23500CE",
        contract_type=ContractType.CALL, strike=23500.0,
        expiry="2026-04-24", market_price=120.0, fair_value=138.0,
        mispricing=-18.0, mispricing_pct=-13.04,
        underlying_price=23500.0, time_to_expiry=0.044,
    )
    assert r.signal == "UNDERVALUED"

def test_fair_result_has_enhanced_fields():
    r = FairResult(
        security_id="1", symbol="X", contract_type=ContractType.CALL,
        strike=100, expiry="2026-01-01", market_price=10, fair_value=10,
        mispricing=0, mispricing_pct=0, underlying_price=100, time_to_expiry=0.1,
        vanna=0.02, volga=0.03, charm=-0.001, speed=0.0001, color=-0.0003, zomma=0.0015,
        iv_rank=55.0, iv_percentile=48.0, moneyness=0.14,
        intrinsic_value=0.0, time_value=10.0,
        pc_parity_deviation=1.2, basis=None, skew=2.1,
        exchange_spread=0.35, stale=False, stale_since=None, tier=1,
    )
    assert r.vanna == 0.02
    assert r.iv_rank == 55.0
    assert r.tier == 1
