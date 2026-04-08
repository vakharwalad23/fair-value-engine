from datetime import date
from src.core.fair_engine import FairEngine
from src.core.models import ContractMeta, ContractType, Tick

def _make_engine_with_nifty():
    engine = FairEngine()
    expiry = date(2026, 5, 1)
    ce = ContractMeta("42528", "NIFTY23500CE", ContractType.CALL, 23500.0, expiry, "13", "NIFTY", "NSE_FNO")
    pe = ContractMeta("42529", "NIFTY23500PE", ContractType.PUT, 23500.0, expiry, "13", "NIFTY", "NSE_FNO")
    fut = ContractMeta("42534", "NIFTYFUT", ContractType.FUTURE, None, expiry, "13", "NIFTY", "NSE_FNO")
    engine.register_contract(ce)
    engine.register_contract(pe)
    engine.register_contract(fut)
    return engine

def test_register_and_deregister():
    engine = _make_engine_with_nifty()
    assert "42528" in engine._contracts
    engine.deregister_contract("42528")
    assert "42528" not in engine._contracts

def test_on_tick_produces_result():
    engine = _make_engine_with_nifty()
    engine.on_tick(Tick("13", 23500.0))
    engine.on_tick(Tick("42528", 150.0))
    result = engine.get_result("42528")
    assert result is not None
    assert result.market_price == 150.0
    assert result.fair_value > 0
    assert result.delta is not None
    assert result.vanna is not None

def test_future_result():
    engine = _make_engine_with_nifty()
    engine.on_tick(Tick("13", 23500.0))
    engine.on_tick(Tick("42534", 23520.0))
    result = engine.get_result("42534")
    assert result is not None
    assert result.fair_value > 23500
    assert result.basis is not None

def test_moneyness_itm_call():
    engine = _make_engine_with_nifty()
    engine.on_tick(Tick("13", 23600.0))
    engine.on_tick(Tick("42528", 200.0))
    result = engine.get_result("42528")
    assert result is not None
    assert result.moneyness is not None
    assert result.intrinsic_value > 0
    assert result.time_value >= 0

def test_put_call_parity_deviation():
    engine = _make_engine_with_nifty()
    engine.on_tick(Tick("13", 23500.0))
    engine.on_tick(Tick("42528", 150.0))
    engine.on_tick(Tick("42529", 140.0))
    ce_result = engine.get_result("42528")
    pe_result = engine.get_result("42529")
    assert ce_result is not None
    assert ce_result.pc_parity_deviation is not None or pe_result.pc_parity_deviation is not None

def test_iv_history_tracking():
    engine = _make_engine_with_nifty()
    engine.on_tick(Tick("13", 23500.0))
    engine.on_tick(Tick("42528", 150.0))
    assert len(engine._iv_history.get("42528", [])) >= 1

def test_snapshot_callback():
    engine = _make_engine_with_nifty()
    snapshots = []
    engine.on_fair_update(lambda r: snapshots.append(r))
    engine.on_tick(Tick("13", 23500.0))
    engine.on_tick(Tick("42528", 150.0))
    assert len(snapshots) >= 1
