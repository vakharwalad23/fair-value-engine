from fastapi import APIRouter, HTTPException
from src.api.schemas import TierConfigRequest

router = APIRouter(prefix="/api", tags=["tiers"])
tier_config = None


def _require_tier_config():
    if tier_config is None:
        raise HTTPException(503, "Server not ready — tier config not initialized")


@router.get("/tiers")
def get_tiers():
    _require_tier_config()
    return tier_config.to_dict()


@router.post("/tiers")
def update_tiers(req: TierConfigRequest):
    _require_tier_config()
    tier_config.update(
        tier1_underlyings=req.tier1_underlyings,
        tier2_stocks=req.tier2_stocks,
        tier2_atm_range=req.tier2_atm_range,
        tier2_expiry_count=req.tier2_expiry_count,
    )
    return {"status": "updated", "config": tier_config.to_dict()}
