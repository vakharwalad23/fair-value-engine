"""Option chain API routes — proxies to Dhan + cross-validation."""
import time
import logging
from typing import Any
from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api/optionchain", tags=["optionchain"])
logger = logging.getLogger(__name__)

dhan_client: Any = None  # dhanhq.dhanhq instance, set at startup
engine: Any = None
scrip_master: Any = None

# Simple TTL cache: key -> (timestamp, data)
_cache: dict[str, tuple[float, dict]] = {}
CACHE_TTL = 5  # seconds


def _require_dhan():
    if dhan_client is None:
        raise HTTPException(503, "Dhan API client not configured")


def _cached_chain(under_sid: int, segment: str, expiry: str) -> dict:
    key = f"{under_sid}:{segment}:{expiry}"
    now = time.time()
    if key in _cache and now - _cache[key][0] < CACHE_TTL:
        return _cache[key][1]
    resp = dhan_client.option_chain(under_sid, segment, expiry)
    data = resp.get("data", resp) if isinstance(resp, dict) else resp
    _cache[key] = (now, data)
    return data


@router.get("")
def get_option_chain(symbol: str, expiry: str):
    """Get Dhan option chain with engine values side-by-side."""
    _require_dhan()
    # Resolve underlying security_id
    under_sid = scrip_master.get_underlying_security_id(symbol.upper()) if scrip_master else None
    if not under_sid:
        raise HTTPException(404, f"Unknown underlying: {symbol}")

    try:
        chain = _cached_chain(int(under_sid), "NSE_FNO", expiry)
    except Exception as e:
        raise HTTPException(502, f"Dhan API error: {e}")

    # Annotate with engine values if available
    if engine and chain and isinstance(chain, dict):
        oc = chain.get("oc", {})
        for strike_key, strike_data in oc.items():
            for side in ("ce", "pe"):
                option = strike_data.get(side, {})
                sec_id = str(option.get("security_id", ""))
                if sec_id and engine:
                    result = engine.get_result(sec_id)
                    if result:
                        option["engine_fair_value"] = result.fair_value
                        option["engine_iv"] = result.implied_volatility
                        option["engine_delta"] = result.delta
                        option["engine_mispricing_pct"] = result.mispricing_pct
                        option["engine_signal"] = result.signal
                        option["source"] = "LIVE_FEED"
                    else:
                        option["source"] = "API_DATA"

    return chain


@router.get("/expiries")
def get_expiries(symbol: str):
    """Get available expiry dates from Dhan."""
    _require_dhan()
    under_sid = scrip_master.get_underlying_security_id(symbol.upper()) if scrip_master else None
    if not under_sid:
        raise HTTPException(404, f"Unknown underlying: {symbol}")

    try:
        resp = dhan_client.expiry_list(int(under_sid), "NSE_FNO")
        return resp.get("data", resp) if isinstance(resp, dict) else resp
    except Exception as e:
        raise HTTPException(502, f"Dhan API error: {e}")


@router.get("/validate")
def validate_chain(symbol: str, expiry: str):
    """Cross-validate engine Greeks/IV against Dhan for all strikes."""
    _require_dhan()
    from src.core.cross_validator import CrossValidator

    under_sid = scrip_master.get_underlying_security_id(symbol.upper()) if scrip_master else None
    if not under_sid:
        raise HTTPException(404, f"Unknown underlying: {symbol}")

    try:
        chain = _cached_chain(int(under_sid), "NSE_FNO", expiry)
    except Exception as e:
        raise HTTPException(502, f"Dhan API error: {e}")

    reports = []
    oc = chain.get("oc", {}) if isinstance(chain, dict) else {}
    for strike_key, strike_data in oc.items():
        for side in ("ce", "pe"):
            option = strike_data.get(side, {})
            sec_id = str(option.get("security_id", ""))
            if not sec_id or not engine:
                continue
            result = engine.get_result(sec_id)
            if not result:
                continue
            report = CrossValidator.validate(result, option)
            reports.append(report.to_dict())

    return {
        "symbol": symbol.upper(),
        "expiry": expiry,
        "validations": reports,
        "total": len(reports),
        "alerts": sum(1 for r in reports if any(v.get("status") == "ALERT" for v in [r["iv"], r["delta"], r["theta"], r["gamma"], r["vega"]])),
    }
