"""Core data models for the F&O Fair Value Engine."""
import math
import time
from dataclasses import dataclass, field
from datetime import date
from enum import Enum
from typing import Optional

from src.utils.time_utils import ist_now


INDEX_SYMBOLS = frozenset({"NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY", "SENSEX", "BANKEX"})


class ContractType(str, Enum):
    CALL = "CE"
    PUT = "PE"
    FUTURE = "FUT"


@dataclass
class ContractMeta:
    """Static metadata about an F&O contract."""
    security_id: str
    symbol: str
    contract_type: ContractType
    strike: Optional[float]
    expiry: date
    underlying_security_id: str
    underlying_symbol: str
    exchange_segment: str
    lot_size: int = 1
    risk_free_rate: float = 0.065
    cross_listed: bool = False
    exchanges: list[str] = field(default_factory=list)
    peer_security_id: Optional[str] = None
    tier: Optional[int] = None


@dataclass
class Tick:
    """A single price update from the feed."""
    security_id: str
    ltp: float
    timestamp: float = field(default_factory=time.time)
    oi: Optional[int] = None
    volume: Optional[int] = None
    bid: Optional[float] = None
    ask: Optional[float] = None
    buy_qty: Optional[int] = None
    sell_qty: Optional[int] = None


@dataclass
class FairResult:
    """Output of fair value calculation for one contract."""
    security_id: str
    symbol: str
    contract_type: ContractType
    strike: Optional[float]
    expiry: str
    market_price: float
    fair_value: float
    mispricing: float
    mispricing_pct: float
    underlying_price: float
    time_to_expiry: float

    # Standard Greeks
    delta: Optional[float] = None
    gamma: Optional[float] = None
    theta: Optional[float] = None
    vega: Optional[float] = None
    implied_volatility: Optional[float] = None

    # Enhanced Greeks
    vanna: Optional[float] = None
    volga: Optional[float] = None
    charm: Optional[float] = None
    speed: Optional[float] = None
    color: Optional[float] = None
    zomma: Optional[float] = None

    # Market structure metrics
    iv_rank: Optional[float] = None
    iv_percentile: Optional[float] = None
    moneyness: Optional[float] = None
    intrinsic_value: Optional[float] = None
    time_value: Optional[float] = None
    pc_parity_deviation: Optional[float] = None
    basis: Optional[float] = None
    skew: Optional[float] = None
    exchange_spread: Optional[float] = None

    # Liquidity metrics
    volume: Optional[int] = None
    oi: Optional[int] = None
    bid: Optional[float] = None
    ask: Optional[float] = None
    spread: Optional[float] = None
    spread_pct: Optional[float] = None
    buy_qty: Optional[int] = None
    sell_qty: Optional[int] = None
    liquidity_score: Optional[float] = None
    low_liquidity: bool = False

    # 20-level depth (only for top 50 contracts)
    depth_bids: Optional[list] = None
    depth_asks: Optional[list] = None
    total_bid_depth: Optional[int] = None
    total_ask_depth: Optional[int] = None
    bid_ask_imbalance: Optional[float] = None

    # Cross-validation (from Dhan option chain API)
    dhan_iv: Optional[float] = None
    dhan_delta: Optional[float] = None
    dhan_theta: Optional[float] = None
    dhan_gamma: Optional[float] = None
    dhan_vega: Optional[float] = None
    iv_deviation: Optional[float] = None

    # Context
    cross_listed: bool = False
    exchanges: list[str] = field(default_factory=list)
    tier: Optional[int] = None
    stale: bool = False
    stale_since: Optional[str] = None

    signal: str = ""
    signal_strength: float = 0.0
    calculated_at: str = ""

    def __post_init__(self):
        if not self.calculated_at:
            self.calculated_at = ist_now().isoformat(timespec="seconds")
        if not self.signal:
            if abs(self.mispricing_pct) < 1.0:
                self.signal = "FAIR"
            elif self.mispricing > 0:
                self.signal = "OVERVALUED"
            else:
                self.signal = "UNDERVALUED"
        if self.signal_strength == 0.0 and self.mispricing_pct != 0.0:
            self.signal_strength = abs(self.mispricing_pct)


@dataclass
class DepthLevel:
    price: float
    quantity: int
    orders: int


@dataclass
class DepthData:
    security_id: str
    bids: list  # list of DepthLevel
    asks: list  # list of DepthLevel
    total_bid_depth: int
    total_ask_depth: int
    bid_ask_imbalance: float  # (bid - ask) / (bid + ask), range -1 to +1


def compute_liquidity_score(volume: Optional[int], oi: Optional[int], spread_pct: Optional[float], ltp: Optional[float]) -> float:
    if ltp is None or ltp <= 0:
        return 0.0
    vol_score = min(30, math.log1p(volume or 0) * 3)
    oi_score = min(30, math.log1p(oi or 0) * 2.5)
    spread_score = max(0, 40 - (spread_pct or 100) * 10)
    return round(vol_score + oi_score + spread_score, 1)
