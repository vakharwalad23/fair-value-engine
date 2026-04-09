"""Pydantic request/response models for the API."""
from pydantic import BaseModel
from typing import Optional


class ContractAddRequest(BaseModel):
    symbol: str
    expiry: str
    strike: Optional[float] = None
    contract_type: str


class ContractAddResponse(BaseModel):
    status: str
    security_id: str
    symbol: str
    slot_cost: int
    slots_remaining: int


class FairResultResponse(BaseModel):
    security_id: str
    symbol: str
    contract_type: str
    strike: Optional[float] = None
    expiry: str
    market_price: float
    fair_value: float
    mispricing: float
    mispricing_pct: float
    signal: str
    signal_strength: float
    underlying_price: float
    time_to_expiry: float
    calculated_at: str = ""
    delta: Optional[float] = None
    gamma: Optional[float] = None
    theta: Optional[float] = None
    vega: Optional[float] = None
    implied_volatility: Optional[float] = None
    vanna: Optional[float] = None
    volga: Optional[float] = None
    charm: Optional[float] = None
    speed: Optional[float] = None
    color: Optional[float] = None
    zomma: Optional[float] = None
    iv_rank: Optional[float] = None
    iv_percentile: Optional[float] = None
    moneyness: Optional[float] = None
    intrinsic_value: Optional[float] = None
    time_value: Optional[float] = None
    pc_parity_deviation: Optional[float] = None
    basis: Optional[float] = None
    skew: Optional[float] = None
    exchange_spread: Optional[float] = None
    cross_listed: bool = False
    exchanges: list[str] = []
    tier: Optional[int] = None
    stale: bool = False
    stale_since: Optional[str] = None


class SlotUsageResponse(BaseModel):
    used: int
    total: int
    available: int
    per_tier: dict[int, int]


class TierConfigRequest(BaseModel):
    tier1_underlyings: Optional[list[str]] = None
    tier1_expiry_count: Optional[int] = None
    tier2_stocks: Optional[list[str]] = None
    tier2_atm_range: Optional[int] = None
    tier2_expiry_count: Optional[int] = None


class SearchResult(BaseModel):
    security_id: str
    symbol: str
    trading_symbol: str
    display_name: str
    strike: Optional[float] = None
    option_type: Optional[str] = None
    expiry: Optional[str] = None
    exchange: Optional[str] = None
    lot_size: int = 1
    score: float = 0.0
    subscribed: bool = False
    slot_cost: int = 1


class HealthResponse(BaseModel):
    status: str
    contracts_loaded: int
    fair_results: int
    ws_clients: int
    slots_used: int
    slots_total: int
