from fastapi import APIRouter

router = APIRouter(prefix="/api/scrip", tags=["scrip"])
scrip_master = None


@router.get("/expiries")
def get_expiries(symbol: str):
    expiries = scrip_master.get_expiries(symbol.upper())
    return {"symbol": symbol.upper(), "expiries": [e.isoformat() for e in expiries]}


@router.get("/strikes")
def get_strikes(symbol: str, expiry: str):
    from datetime import date
    exp = date.fromisoformat(expiry)
    strikes = scrip_master.get_strikes(symbol.upper(), exp)
    return {"symbol": symbol.upper(), "expiry": expiry, "strikes": strikes}
