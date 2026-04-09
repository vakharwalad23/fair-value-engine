import math
from src.core.fair_engine import black_scholes, future_fair_value, implied_volatility_newton
from src.core.models import ContractType

def test_bs_call_price():
    result = black_scholes(23500, 23500, 30/365, 0.065, 0.15, ContractType.CALL)
    assert result is not None
    assert 400 < result["price"] < 600
    assert 0.45 < result["delta"] < 0.60

def test_bs_put_price():
    result = black_scholes(23500, 23500, 30/365, 0.065, 0.15, ContractType.PUT)
    assert result is not None
    assert result["delta"] < 0
    assert result["price"] > 0

def test_bs_greeks_present():
    result = black_scholes(23500, 23500, 30/365, 0.065, 0.15, ContractType.CALL)
    for key in ("price", "delta", "gamma", "vega", "theta", "vanna", "volga", "charm", "speed", "color", "zomma"):
        assert key in result, f"Missing greek: {key}"

def test_bs_degenerate_inputs():
    assert black_scholes(0, 23500, 0.1, 0.065, 0.15, ContractType.CALL) is None
    assert black_scholes(23500, 0, 0.1, 0.065, 0.15, ContractType.CALL) is None
    assert black_scholes(23500, -100, 0.1, 0.065, 0.15, ContractType.CALL) is None
    assert black_scholes(23500, 23500, 0, 0.065, 0.15, ContractType.CALL) is None
    assert black_scholes(23500, 23500, 0.1, 0.065, 0, ContractType.CALL) is None

def test_future_fair_value():
    fv = future_fair_value(23500, 30/365, 0.065)
    expected = 23500 * math.exp(0.065 * 30/365)
    assert abs(fv - expected) < 0.01

def test_iv_solver_round_trip():
    sigma = 0.20
    result = black_scholes(23500, 23500, 30/365, 0.065, sigma, ContractType.CALL)
    iv = implied_volatility_newton(result["price"], 23500, 23500, 30/365, 0.065, ContractType.CALL)
    assert iv is not None
    assert abs(iv - sigma) < 0.001

def test_iv_solver_returns_none_for_bad_input():
    assert implied_volatility_newton(0, 23500, 23500, 0.1, 0.065, ContractType.CALL) is None
    assert implied_volatility_newton(100, 23500, 23500, 0, 0.065, ContractType.CALL) is None

def test_vanna_sign():
    # ATM option with d2 > 0: vanna = -n(d1)*d2/sigma < 0
    result = black_scholes(23500, 23500, 30/365, 0.065, 0.15, ContractType.CALL)
    assert result["vanna"] < 0

def test_volga_positive():
    result = black_scholes(23500, 23500, 30/365, 0.065, 0.15, ContractType.CALL)
    assert result["volga"] > 0
