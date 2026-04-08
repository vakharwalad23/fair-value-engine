from fastapi import APIRouter

router = APIRouter(prefix="/api", tags=["health"])
engine = None
slot_tracker = None
connection_pool = None
ws_clients = None


@router.get("/health")
def health():
    return {
        "status": "ok",
        "contracts_loaded": len(engine._contracts),
        "fair_results": len(engine._results),
        "ws_clients": len(ws_clients) if ws_clients else 0,
        "slots_used": slot_tracker.used,
        "slots_total": slot_tracker.total,
    }


@router.get("/slots")
def get_slots():
    return {**slot_tracker.to_dict(), "per_connection": connection_pool.per_connection_usage()}
