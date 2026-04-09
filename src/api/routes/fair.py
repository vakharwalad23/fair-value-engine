"""Fair value data routes."""
from dataclasses import asdict
from typing import Optional
from fastapi import APIRouter, HTTPException
from src.core.fair_engine import FairEngine
from src.core.models import FairResult

router = APIRouter(prefix="/api", tags=["fair"])
engine: Optional[FairEngine] = None


def _get_engine() -> FairEngine:
    if engine is None:
        raise HTTPException(503, "Server not ready — engine not initialized")
    return engine


def _to_response(r: FairResult) -> dict:
    d = asdict(r)
    # Convert ContractType enum to its string value
    ct = d.get("contract_type")
    if hasattr(ct, "value"):
        d["contract_type"] = ct.value
    return d


@router.get("/fair")
def get_all_fair():
    eng = _get_engine()
    results = eng.get_all_results()
    return [_to_response(r) for r in sorted(results, key=lambda r: -r.signal_strength)]


@router.get("/fair/signals")
def get_signals(min_pct: float = 1.0):
    eng = _get_engine()
    results = eng.get_all_results()
    filtered = [r for r in results if abs(r.mispricing_pct) >= min_pct]
    return [_to_response(r) for r in sorted(filtered, key=lambda r: -r.signal_strength)]


@router.get("/fair/{security_id}")
def get_fair(security_id: str):
    eng = _get_engine()
    result = eng.get_result(security_id)
    if not result:
        raise HTTPException(404, "No fair data for this security_id")
    return _to_response(result)


@router.get("/history/{security_id}")
def get_history(security_id: str, limit: int = 100):
    eng = _get_engine()
    history = eng.get_history(security_id)
    return [_to_response(r) for r in history[-limit:]]
