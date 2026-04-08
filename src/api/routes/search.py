from fastapi import APIRouter

router = APIRouter(prefix="/api", tags=["search"])
fuzzy_index = None
slot_tracker = None


@router.get("/search")
def search(q: str, limit: int = 20):
    results = fuzzy_index.search(q, limit=limit)
    for r in results:
        r["subscribed"] = slot_tracker._slots.get(r["security_id"]) is not None
        r["slot_cost"] = 0 if r["subscribed"] else 1
    return results
