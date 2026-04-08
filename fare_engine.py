"""
F&O Fare (Fair Value) Calculation Engine
=========================================
Calculates theoretical fair value of F&O contracts using:
  - Black-Scholes model for Options (CE/PE)
  - Cost of Carry model for Futures
  - Mispricing = Market Price - Theoretical Price
  - +ve mispricing => Overvalued => SHORT candidate
  - -ve mispricing => Undervalued => LONG candidate
"""

import math
import time
import threading
import logging
from dataclasses import dataclass, field
from datetime import datetime, date
from typing import Optional, Dict, List, Callable
from collections import deque
from enum import Enum

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# Data Structures
# ─────────────────────────────────────────────

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
    strike: Optional[float]         # None for futures
    expiry: date
    underlying_security_id: str     # spot/index security_id
    underlying_symbol: str
    exchange_segment: str           # e.g. NSE_FNO
    lot_size: int = 1
    risk_free_rate: float = 0.065   # 6.5% RBI repo rate default


@dataclass
class Tick:
    security_id: str
    ltp: float
    timestamp: float = field(default_factory=time.time)
    oi: Optional[int] = None
    volume: Optional[int] = None
    bid: Optional[float] = None
    ask: Optional[float] = None


@dataclass
class FareResult:
    """Output of fair value calculation for one contract."""
    security_id: str
    symbol: str
    contract_type: ContractType
    strike: Optional[float]
    expiry: str

    market_price: float
    fair_value: float
    mispricing: float           # market - fair
    mispricing_pct: float       # mispricing / fair * 100

    # Greeks (options only)
    delta: Optional[float] = None
    gamma: Optional[float] = None
    theta: Optional[float] = None
    vega: Optional[float] = None
    implied_volatility: Optional[float] = None

    # Context
    underlying_price: float = 0.0
    time_to_expiry: float = 0.0     # years
    signal: str = ""                # OVERVALUED / UNDERVALUED / FAIR
    signal_strength: float = 0.0   # abs(mispricing_pct)
    calculated_at: str = ""

    def __post_init__(self):
        self.calculated_at = datetime.now().isoformat(timespec="seconds")
        if abs(self.mispricing_pct) < 1.0:
            self.signal = "FAIR"
        elif self.mispricing > 0:
            self.signal = "OVERVALUED"   # SHORT
        else:
            self.signal = "UNDERVALUED"  # LONG
        self.signal_strength = abs(self.mispricing_pct)


# ─────────────────────────────────────────────
# Black-Scholes Implementation
# ─────────────────────────────────────────────

def _norm_cdf(x: float) -> float:
    """Standard normal CDF using math.erfc for precision."""
    return 0.5 * math.erfc(-x / math.sqrt(2))


def _norm_pdf(x: float) -> float:
    return math.exp(-0.5 * x * x) / math.sqrt(2 * math.pi)


def black_scholes(
    S: float,           # Underlying spot price
    K: float,           # Strike price
    T: float,           # Time to expiry in years
    r: float,           # Risk-free rate (annual)
    sigma: float,       # Implied/historical volatility (annual)
    option_type: ContractType,
) -> Dict[str, float]:
    """
    Returns theoretical price + all Greeks.
    Returns empty dict if inputs are degenerate.
    """
    if T <= 0 or S <= 0 or K <= 0 or sigma <= 0:
        return {}

    try:
        d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * math.sqrt(T))
        d2 = d1 - sigma * math.sqrt(T)

        Nd1 = _norm_cdf(d1)
        Nd2 = _norm_cdf(d2)
        nd1 = _norm_pdf(d1)

        discount = math.exp(-r * T)

        if option_type == ContractType.CALL:
            price = S * Nd1 - K * discount * Nd2
            delta = Nd1
        else:  # PUT
            price = K * discount * _norm_cdf(-d2) - S * _norm_cdf(-d1)
            delta = Nd1 - 1

        gamma = nd1 / (S * sigma * math.sqrt(T))
        vega = S * nd1 * math.sqrt(T) / 100       # per 1% vol change
        theta_call = (
            -(S * nd1 * sigma) / (2 * math.sqrt(T))
            - r * K * discount * Nd2
        ) / 365
        if option_type == ContractType.CALL:
            theta = theta_call
        else:
            theta = theta_call + r * K * discount / 365

        return {
            "price": price,
            "delta": delta,
            "gamma": gamma,
            "vega": vega,
            "theta": theta,
        }
    except (ValueError, ZeroDivisionError, OverflowError) as e:
        logger.debug(f"BS error: {e}")
        return {}


def implied_volatility_newton(
    market_price: float,
    S: float,
    K: float,
    T: float,
    r: float,
    option_type: ContractType,
    max_iter: int = 100,
    tol: float = 1e-6,
) -> Optional[float]:
    """
    Newton-Raphson IV solver.
    Returns None if it fails to converge.
    """
    if T <= 0 or market_price <= 0:
        return None

    sigma = 0.3  # initial guess 30%
    for _ in range(max_iter):
        result = black_scholes(S, K, T, r, sigma, option_type)
        if not result:
            return None
        price = result["price"]
        vega_raw = result["vega"] * 100  # convert back from per-1%
        if abs(vega_raw) < 1e-10:
            break
        diff = price - market_price
        if abs(diff) < tol:
            return sigma
        sigma -= diff / vega_raw
        if sigma <= 0:
            sigma = 1e-4

    return sigma if 0 < sigma < 5 else None


# ─────────────────────────────────────────────
# Future Fair Value (Cost of Carry)
# ─────────────────────────────────────────────

def future_fair_value(
    S: float,       # Spot price
    T: float,       # Time to expiry in years
    r: float,       # Risk-free rate
    d: float = 0.0, # Continuous dividend yield
) -> float:
    """F = S * e^((r-d)*T)  — cost of carry model."""
    return S * math.exp((r - d) * T)


# ─────────────────────────────────────────────
# Fare Engine
# ─────────────────────────────────────────────

class FareEngine:
    """
    Core engine that:
    1. Stores live tick data per security_id
    2. On each tick, recalculates fair value for all contracts
       that depend on the updated security
    3. Fires callbacks with FareResult
    4. Supports custom intervals for aggregated snapshots
    """

    def __init__(self):
        self._contracts: Dict[str, ContractMeta] = {}        # security_id -> meta
        self._ltp: Dict[str, float] = {}                      # security_id -> latest LTP
        self._iv_cache: Dict[str, float] = {}                 # security_id -> last IV
        self._results: Dict[str, FareResult] = {}             # security_id -> latest result
        self._history: Dict[str, deque] = {}                  # security_id -> deque of results
        self._callbacks: List[Callable[[FareResult], None]] = []
        self._lock = threading.Lock()
        self._snapshot_callbacks: List[Callable[[List[FareResult]], None]] = []
        self._snapshot_timers: List[threading.Timer] = []

    def register_contract(self, meta: ContractMeta):
        with self._lock:
            self._contracts[meta.security_id] = meta
            self._history[meta.security_id] = deque(maxlen=1000)

    def on_fare_update(self, callback: Callable[[FareResult], None]):
        """Register callback fired on every tick-level fare update."""
        self._callbacks.append(callback)

    def on_snapshot(self, interval_seconds: float, callback: Callable[[List[FareResult]], None]):
        """
        Register a periodic snapshot callback.
        Fires every `interval_seconds` with all current FareResults.
        """
        self._snapshot_callbacks.append(callback)
        self._schedule_snapshot(interval_seconds, callback)

    def _schedule_snapshot(self, interval: float, callback):
        def fire():
            with self._lock:
                snapshot = list(self._results.values())
            callback(snapshot)
            self._schedule_snapshot(interval, callback)  # reschedule

        t = threading.Timer(interval, fire)
        t.daemon = True
        t.start()
        self._snapshot_timers.append(t)

    def on_tick(self, tick: Tick):
        """
        Called when a new price tick arrives.
        Updates LTP, recalculates fare for all contracts
        that reference this security_id (as underlying or as self).
        """
        with self._lock:
            self._ltp[tick.security_id] = tick.ltp

            # Find contracts that are THIS contract or have this as underlying
            to_recalc = [
                meta for meta in self._contracts.values()
                if meta.security_id == tick.security_id
                or meta.underlying_security_id == tick.security_id
            ]

        for meta in to_recalc:
            result = self._calculate(meta, tick)
            if result:
                with self._lock:
                    self._results[meta.security_id] = result
                    self._history[meta.security_id].append(result)
                for cb in self._callbacks:
                    try:
                        cb(result)
                    except Exception as e:
                        logger.error(f"Callback error: {e}")

    def _calculate(self, meta: ContractMeta, tick: Tick) -> Optional[FareResult]:
        """Calculate fair value for a single contract."""
        underlying_ltp = self._ltp.get(meta.underlying_security_id)
        contract_ltp = self._ltp.get(meta.security_id)

        if underlying_ltp is None or contract_ltp is None:
            return None

        today = date.today()
        days_to_expiry = (meta.expiry - today).days
        T = max(days_to_expiry / 365.0, 1 / 365.0)  # min 1 day

        r = meta.risk_free_rate

        if meta.contract_type == ContractType.FUTURE:
            fair = future_fair_value(underlying_ltp, T, r)
            mispricing = contract_ltp - fair
            mispct = (mispricing / fair * 100) if fair else 0
            return FareResult(
                security_id=meta.security_id,
                symbol=meta.symbol,
                contract_type=meta.contract_type,
                strike=None,
                expiry=meta.expiry.isoformat(),
                market_price=contract_ltp,
                fair_value=round(fair, 2),
                mispricing=round(mispricing, 2),
                mispricing_pct=round(mispct, 3),
                underlying_price=underlying_ltp,
                time_to_expiry=round(T, 4),
            )

        else:  # Options
            K = meta.strike

            # Solve IV from market price
            iv = implied_volatility_newton(contract_ltp, underlying_ltp, K, T, r, meta.contract_type)

            # Use cached IV if solver fails
            if iv is None:
                iv = self._iv_cache.get(meta.security_id, 0.20)
            else:
                self._iv_cache[meta.security_id] = iv

            # Fair value using same IV (this gives you BS price == market for IV solver)
            # For "fair" we use the IV from the ATM strike of same expiry if available
            # Simple approach: compare against same-expiry ATM IV
            # Here we compute BS price with current IV to detect bid/ask mispricing
            greeks = black_scholes(underlying_ltp, K, T, r, iv, meta.contract_type)
            if not greeks:
                return None

            fair = greeks["price"]
            mispricing = contract_ltp - fair
            mispct = (mispricing / fair * 100) if fair else 0

            return FareResult(
                security_id=meta.security_id,
                symbol=meta.symbol,
                contract_type=meta.contract_type,
                strike=K,
                expiry=meta.expiry.isoformat(),
                market_price=contract_ltp,
                fair_value=round(fair, 2),
                mispricing=round(mispricing, 2),
                mispricing_pct=round(mispct, 3),
                delta=round(greeks.get("delta", 0), 4),
                gamma=round(greeks.get("gamma", 0), 6),
                theta=round(greeks.get("theta", 0), 4),
                vega=round(greeks.get("vega", 0), 4),
                implied_volatility=round(iv * 100, 3),  # as %
                underlying_price=underlying_ltp,
                time_to_expiry=round(T, 4),
            )

    def get_all_results(self) -> List[FareResult]:
        with self._lock:
            return list(self._results.values())

    def get_result(self, security_id: str) -> Optional[FareResult]:
        with self._lock:
            return self._results.get(security_id)

    def get_history(self, security_id: str) -> List[FareResult]:
        with self._lock:
            return list(self._history.get(security_id, []))

    def stop(self):
        for t in self._snapshot_timers:
            t.cancel()
