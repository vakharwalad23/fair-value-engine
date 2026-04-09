from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api/scrip", tags=["scrip"])
scrip_master = None


def _require_scrip_master():
    if scrip_master is None:
        raise HTTPException(503, "Server not ready — scrip master not initialized")


@router.get("/expiries")
def get_expiries(symbol: str):
    _require_scrip_master()
    expiries = scrip_master.get_expiries(symbol.upper())
    return {"symbol": symbol.upper(), "expiries": [e.isoformat() for e in expiries]}


@router.get("/strikes")
def get_strikes(symbol: str, expiry: str):
    _require_scrip_master()
    from datetime import date
    exp = date.fromisoformat(expiry)
    strikes = scrip_master.get_strikes(symbol.upper(), exp)
    return {"symbol": symbol.upper(), "expiry": expiry, "strikes": strikes}
