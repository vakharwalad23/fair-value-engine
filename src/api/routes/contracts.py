from datetime import date
from fastapi import APIRouter, HTTPException
from src.api.schemas import ContractAddRequest, ContractAddResponse
from src.core.models import INDEX_SYMBOLS

router = APIRouter(prefix="/api", tags=["contracts"])
engine = None
scrip_master = None
connection_pool = None
slot_tracker = None
tier_config = None


def _require_engine():
    if engine is None:
        raise HTTPException(503, "Server not ready — engine not initialized")


def _require_pool():
    if connection_pool is None:
        raise HTTPException(503, "Feed not configured — set DHAN_CLIENT_ID and DHAN_ACCESS_TOKEN")


@router.get("/contracts")
def list_contracts():
    _require_engine()
    return [
        {"security_id": m.security_id, "symbol": m.symbol,
         "type": m.contract_type.value, "strike": m.strike,
         "expiry": m.expiry.isoformat(), "underlying": m.underlying_symbol,
         "exchange_segment": m.exchange_segment, "lot_size": m.lot_size,
         "tier": m.tier, "cross_listed": m.cross_listed}
        for m in engine.get_all_contracts()
    ]


@router.post("/contracts/add", status_code=201)
def add_contract(req: ContractAddRequest):
    _require_engine()
    _require_pool()
    from src.scrip.scrip_master import ContractNotFoundError
    try:
        expiry = date.fromisoformat(req.expiry)
        meta = scrip_master.resolve(req.symbol, expiry, req.strike, req.contract_type.upper())
    except ContractNotFoundError as e:
        raise HTTPException(404, str(e))
    except ValueError as e:
        raise HTTPException(400, str(e))

    slot_cost = 1
    underlying_already = slot_tracker.contains(meta.underlying_security_id)
    if not underlying_already:
        slot_cost += 1
    forecast = slot_tracker.forecast(slot_cost)
    if not forecast["fits"]:
        raise HTTPException(409, f"Not enough slots: need {slot_cost}, have {slot_tracker.available}")

    meta.tier = 3
    engine.register_contract(meta)

    if not connection_pool.subscribe(meta.security_id, meta.exchange_segment):
        engine.deregister_contract(meta.security_id)
        raise HTTPException(409, "Failed to subscribe — no connection capacity")

    slot_tracker.add(meta.security_id, tier=3)

    if not underlying_already:
        underlying_seg = "IDX_I" if meta.underlying_symbol in INDEX_SYMBOLS else "NSE_EQ"
        connection_pool.subscribe(meta.underlying_security_id, underlying_seg)
        slot_tracker.add(meta.underlying_security_id, tier=3)

    tier_config.add_tier3(meta.security_id, meta.exchange_segment)
    tier_config.save()

    return ContractAddResponse(
        status="registered", security_id=meta.security_id,
        symbol=meta.symbol, slot_cost=slot_cost, slots_remaining=slot_tracker.available,
    )


@router.post("/contracts/subscribe/{security_id}")
def resubscribe(security_id: str):
    _require_engine()
    _require_pool()
    meta = engine.get_contract(security_id)
    if not meta:
        raise HTTPException(404, "Contract not registered")
    connection_pool.subscribe(meta.security_id, meta.exchange_segment)
    return {"status": "subscribed", "security_id": security_id}


@router.delete("/contracts/unsubscribe/{security_id}")
def unsubscribe(security_id: str):
    _require_engine()
    _require_pool()
    meta = engine.get_contract(security_id)
    if not meta:
        raise HTTPException(404, "Contract not registered")
    connection_pool.unsubscribe(meta.security_id, meta.exchange_segment)
    slot_tracker.remove(security_id)
    tier_config.remove_tier3(security_id)
    tier_config.save()
    return {"status": "unsubscribed", "security_id": security_id}


@router.delete("/contracts/{security_id}")
def remove_contract(security_id: str):
    _require_engine()
    _require_pool()
    meta = engine.get_contract(security_id)
    if not meta:
        raise HTTPException(404, "Contract not found")
    connection_pool.unsubscribe(meta.security_id, meta.exchange_segment)
    engine.deregister_contract(security_id)
    slot_tracker.remove(security_id)
    tier_config.remove_tier3(security_id)
    tier_config.save()
    return {"status": "removed", "security_id": security_id}
