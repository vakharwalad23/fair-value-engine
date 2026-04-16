from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api", tags=["health"])
engine = None
slot_tracker = None
connection_pool = None


@router.get("/health")
def health():
    if engine is None:
        return {"status": "starting", "contracts_loaded": 0, "fair_results": 0,
                "ws_clients": 0, "slots_used": 0, "slots_total": 0}
    return {
        "status": "ok",
        "contracts_loaded": engine.contract_count(),
        "fair_results": engine.result_count(),
        "slots_used": slot_tracker.used,
        "slots_total": slot_tracker.total,
    }


@router.get("/slots")
def get_slots():
    if connection_pool is None:
        raise HTTPException(503, "Feed not configured — set DHAN_CLIENT_ID and DHAN_ACCESS_TOKEN")
    return {**slot_tracker.to_dict(), "per_connection": connection_pool.per_connection_usage()}


@router.get("/market-status")
def get_market_status():
    from src.utils.market_hours import market_status, seconds_until_market_open, is_market_open
    status = market_status()
    result = {"status": status}
    if not is_market_open():
        secs = seconds_until_market_open()
        result["next_open_in_seconds"] = int(secs)
        result["next_open_in_hours"] = round(secs / 3600, 1)
    return result
