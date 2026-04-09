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
    if req.tier1_underlyings is not None:
        tier_config.tier1_underlyings = req.tier1_underlyings
    if req.tier2_stocks is not None:
        tier_config.tier2_stocks = req.tier2_stocks
    if req.tier2_atm_range is not None:
        tier_config.tier2_atm_range = req.tier2_atm_range
    if req.tier2_expiry_count is not None:
        tier_config.tier2_expiry_count = req.tier2_expiry_count
    tier_config.save()
    return {"status": "updated", "config": tier_config.to_dict()}
