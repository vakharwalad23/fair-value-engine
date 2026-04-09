from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api", tags=["search"])
fuzzy_index = None
slot_tracker = None


@router.get("/search")
def search(q: str, limit: int = 20):
    if fuzzy_index is None:
        raise HTTPException(503, "Server not ready — search index not initialized")
    results = fuzzy_index.search(q, limit=limit)
    for r in results:
        r["subscribed"] = slot_tracker.contains(r["security_id"])
        r["slot_cost"] = 0 if r["subscribed"] else 1
    return results
