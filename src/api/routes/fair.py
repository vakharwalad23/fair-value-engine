"""Fair value data routes."""
from fastapi import APIRouter, HTTPException
from src.core.models import FairResult

router = APIRouter(prefix="/api", tags=["fair"])
engine = None


def _to_response(r: FairResult) -> dict:
    return {
        "security_id": r.security_id, "symbol": r.symbol,
        "contract_type": r.contract_type.value if hasattr(r.contract_type, 'value') else r.contract_type,
        "strike": r.strike, "expiry": r.expiry,
        "market_price": r.market_price, "fair_value": r.fair_value,
        "mispricing": r.mispricing, "mispricing_pct": r.mispricing_pct,
        "signal": r.signal, "signal_strength": r.signal_strength,
        "underlying_price": r.underlying_price, "time_to_expiry": r.time_to_expiry,
        "calculated_at": r.calculated_at,
        "delta": r.delta, "gamma": r.gamma, "theta": r.theta, "vega": r.vega,
        "implied_volatility": r.implied_volatility,
        "vanna": r.vanna, "volga": r.volga, "charm": r.charm,
        "speed": r.speed, "color": r.color, "zomma": r.zomma,
        "iv_rank": r.iv_rank, "iv_percentile": r.iv_percentile,
        "moneyness": r.moneyness, "intrinsic_value": r.intrinsic_value,
        "time_value": r.time_value, "pc_parity_deviation": r.pc_parity_deviation,
        "basis": r.basis, "skew": r.skew, "exchange_spread": r.exchange_spread,
        "cross_listed": r.cross_listed, "exchanges": r.exchanges,
        "tier": r.tier, "stale": r.stale, "stale_since": r.stale_since,
    }


@router.get("/fair")
def get_all_fair():
    results = engine.get_all_results()
    return [_to_response(r) for r in sorted(results, key=lambda r: -r.signal_strength)]


@router.get("/fair/signals")
def get_signals(min_pct: float = 1.0):
    results = engine.get_all_results()
    filtered = [r for r in results if abs(r.mispricing_pct) >= min_pct]
    return [_to_response(r) for r in sorted(filtered, key=lambda r: -r.signal_strength)]


@router.get("/fair/{security_id}")
def get_fair(security_id: str):
    result = engine.get_result(security_id)
    if not result:
        raise HTTPException(404, "No fair data for this security_id")
    return _to_response(result)


@router.get("/history/{security_id}")
def get_history(security_id: str, limit: int = 100):
    history = engine.get_history(security_id)
    return [_to_response(r) for r in history[-limit:]]
