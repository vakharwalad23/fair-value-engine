from src.api.schemas import ContractAddRequest, FairResultResponse, SlotUsageResponse

def test_contract_add_request():
    req = ContractAddRequest(symbol="NIFTY", expiry="2026-04-24", strike=23500.0, contract_type="CE")
    assert req.symbol == "NIFTY"

def test_contract_add_request_future():
    req = ContractAddRequest(symbol="NIFTY", expiry="2026-04-24", strike=None, contract_type="FUT")
    assert req.strike is None

def test_fair_result_response():
    r = FairResultResponse(
        security_id="42528", symbol="NIFTY23500CE", contract_type="CE",
        strike=23500.0, expiry="2026-04-24", market_price=150.0,
        fair_value=138.0, mispricing=12.0, mispricing_pct=8.7,
        signal="OVERVALUED", signal_strength=8.7,
        underlying_price=23500.0, time_to_expiry=0.044,
    )
    assert r.signal == "OVERVALUED"

def test_slot_usage_response():
    r = SlotUsageResponse(used=5000, total=15000, available=10000, per_tier={1: 3000, 2: 1500, 3: 500})
    assert r.available == 10000
