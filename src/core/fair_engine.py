"""Black-Scholes pricing and Greeks for F&O fair value calculation."""
import math
import time
import threading
import logging
from collections import deque
from datetime import date
from typing import Optional, Callable

from src.core.models import ContractType, ContractMeta, Tick, FairResult
from src.utils.time_utils import time_to_expiry_years, ist_now

logger = logging.getLogger(__name__)


def _norm_cdf(x: float) -> float:
    """Standard normal CDF using math.erfc."""
    return 0.5 * math.erfc(-x / math.sqrt(2))


def _norm_pdf(x: float) -> float:
    """Standard normal PDF."""
    return math.exp(-0.5 * x * x) / math.sqrt(2 * math.pi)


def black_scholes(
    S: float,
    K: float,
    T: float,
    r: float,
    sigma: float,
    option_type: ContractType,
) -> Optional[dict]:
    """Compute Black-Scholes price and Greeks.

    Returns a dict with price, delta, gamma, vega, theta, vanna, volga,
    charm, speed, color, zomma — or None for degenerate inputs.
    """
    if S <= 0 or K <= 0 or T <= 0 or sigma <= 0:
        return None

    sqrt_T = math.sqrt(T)
    d1 = (math.log(S / K) + (r + 0.5 * sigma ** 2) * T) / (sigma * sqrt_T)
    d2 = d1 - sigma * sqrt_T

    nd1 = _norm_pdf(d1)
    nd2 = _norm_pdf(d2)

    Nd1 = _norm_cdf(d1)
    Nd2 = _norm_cdf(d2)
    Nd1_neg = _norm_cdf(-d1)
    Nd2_neg = _norm_cdf(-d2)

    discount = math.exp(-r * T)

    if option_type == ContractType.CALL:
        price = S * Nd1 - K * discount * Nd2
        delta = Nd1
        # Charm for call
        charm = -nd1 * (2 * r * T - d2 * sigma * sqrt_T) / (2 * T * sigma * sqrt_T) / 365
    else:
        price = K * discount * Nd2_neg - S * Nd1_neg
        delta = Nd1 - 1
        # Charm for put
        charm = -nd1 * (2 * r * T - d2 * sigma * sqrt_T) / (2 * T * sigma * sqrt_T) / 365

    # Gamma (same for call and put)
    gamma = nd1 / (S * sigma * sqrt_T)

    # Vega raw (per unit sigma, not per 1%)
    vega_raw = S * nd1 * sqrt_T
    vega = vega_raw / 100  # per 1% move in vol

    # Theta (per calendar day)
    if option_type == ContractType.CALL:
        theta = (-(S * nd1 * sigma) / (2 * sqrt_T) - r * K * discount * Nd2) / 365
    else:
        theta = (-(S * nd1 * sigma) / (2 * sqrt_T) + r * K * discount * Nd2_neg) / 365

    # Enhanced Greeks
    vanna = -nd1 * d2 / sigma
    volga = vega_raw * d1 * d2 / sigma
    speed = -(gamma / S) * (1 + d1 / (sigma * sqrt_T))
    color = (
        -nd1 / (2 * S * T * sigma * sqrt_T)
        * (1 + d1 * (2 * r * T - d2 * sigma * sqrt_T) / (sigma * sqrt_T))
        / 365
    )
    zomma = gamma * (d1 * d2 - 1) / sigma

    return {
        "price": price,
        "delta": delta,
        "gamma": gamma,
        "vega": vega,
        "theta": theta,
        "vanna": vanna,
        "volga": volga,
        "charm": charm,
        "speed": speed,
        "color": color,
        "zomma": zomma,
    }


def implied_volatility_newton(
    market_price: float,
    S: float,
    K: float,
    T: float,
    r: float,
    option_type: ContractType,
    max_iterations: int = 100,
    tolerance: float = 1e-6,
) -> Optional[float]:
    """Newton-Raphson IV solver.

    Returns implied volatility or None if inputs are degenerate or
    convergence fails.
    """
    if market_price <= 0 or T <= 0:
        return None

    sigma = 0.20  # initial guess
    sqrt_T = math.sqrt(T)

    for _ in range(max_iterations):
        result = black_scholes(S, K, T, r, sigma, option_type)
        if result is None:
            return None

        price = result["price"]
        # vega_raw = S * nd1 * sqrt_T (vega before /100 scaling)
        vega_raw = result["vega"] * 100

        diff = price - market_price
        if abs(diff) < tolerance:
            return sigma

        if vega_raw < 1e-10:
            return None

        sigma -= diff / vega_raw
        if sigma <= 0:
            return None

    return None


def future_fair_value(S: float, T: float, r: float, d: float = 0.0) -> float:
    """Cost of Carry model: F = S * e^((r-d)*T)."""
    return S * math.exp((r - d) * T)


class FairEngine:
    """Thread-safe engine that maintains contract state and emits FairResult updates."""

    # Maximum entries retained in IV and result history per contract
    _MAX_HISTORY = 1000

    def __init__(self) -> None:
        self._lock = threading.Lock()

        # security_id -> ContractMeta
        self._contracts: dict[str, ContractMeta] = {}

        # underlying_security_id -> latest LTP
        self._underlying_ltp: dict[str, float] = {}

        # security_id -> latest LTP
        self._ltp: dict[str, float] = {}

        # security_id -> deque of FairResult
        self._history: dict[str, deque] = {}

        # security_id -> latest FairResult
        self._results: dict[str, FairResult] = {}

        # security_id -> list of (date_str, iv) — one entry per calendar day
        self._iv_history: dict[str, list] = {}

        # (underlying_symbol, expiry, strike) -> {"CE": sid, "PE": sid}
        self._pairs: dict[tuple, dict] = {}

        # underlying_security_id -> set of contract security_ids
        self._underlying_to_contracts: dict[str, set[str]] = {}

        # callbacks registered via on_fair_update
        self._update_callbacks: list[Callable] = []

        # (interval_s, callback) pairs registered via on_snapshot
        self._snapshot_callbacks: list[tuple[float, Callable, float]] = []

        self._stopped = False

    def register_contract(self, meta: ContractMeta) -> None:
        """Register a contract and update the pairs index."""
        with self._lock:
            self._contracts[meta.security_id] = meta
            self._history[meta.security_id] = deque(maxlen=self._MAX_HISTORY)
            self._underlying_to_contracts.setdefault(meta.underlying_security_id, set()).add(meta.security_id)
            if meta.contract_type in (ContractType.CALL, ContractType.PUT) and meta.strike is not None:
                key = (meta.underlying_symbol, meta.expiry, meta.strike)
                if key not in self._pairs:
                    self._pairs[key] = {}
                side = "CE" if meta.contract_type == ContractType.CALL else "PE"
                self._pairs[key][side] = meta.security_id

    def deregister_contract(self, security_id: str) -> None:
        """Remove a contract and clean up associated state."""
        with self._lock:
            meta = self._contracts.pop(security_id, None)
            self._history.pop(security_id, None)
            self._results.pop(security_id, None)
            self._ltp.pop(security_id, None)
            self._iv_history.pop(security_id, None)
            if meta:
                underlying_set = self._underlying_to_contracts.get(meta.underlying_security_id)
                if underlying_set is not None:
                    underlying_set.discard(security_id)
                    if not underlying_set:
                        del self._underlying_to_contracts[meta.underlying_security_id]
            if meta and meta.contract_type in (ContractType.CALL, ContractType.PUT) and meta.strike is not None:
                key = (meta.underlying_symbol, meta.expiry, meta.strike)
                pair = self._pairs.get(key, {})
                side = "CE" if meta.contract_type == ContractType.CALL else "PE"
                pair.pop(side, None)
                if not pair:
                    self._pairs.pop(key, None)

    def on_fair_update(self, callback: Callable) -> None:
        """Register a callback invoked with FairResult on every recalculation."""
        with self._lock:
            self._update_callbacks.append(callback)

    def on_snapshot(self, interval: float, callback: Callable) -> None:
        """Register a periodic snapshot callback (interval in seconds)."""
        with self._lock:
            self._snapshot_callbacks.append((interval, callback, time.time()))

    def on_tick(self, tick: Tick) -> None:
        """Process a price tick, recalculate all affected contracts."""
        if self._stopped:
            return

        with self._lock:
            is_underlying = tick.security_id in self._underlying_to_contracts

            if is_underlying:
                self._underlying_ltp[tick.security_id] = tick.ltp
                # Recalculate all contracts on this underlying that have a known LTP
                affected_sids = [
                    sid for sid in self._underlying_to_contracts[tick.security_id]
                    if sid in self._ltp
                ]
            else:
                # It is a contract tick
                if tick.security_id in self._contracts:
                    self._ltp[tick.security_id] = tick.ltp
                    affected_sids = [tick.security_id]
                else:
                    affected_sids = []

            results_to_emit = []
            for sid in affected_sids:
                meta = self._contracts.get(sid)
                if meta is None:
                    continue
                result = self._calculate(meta)
                if result is not None:
                    self._results[sid] = result
                    self._history[sid].append(result)
                    results_to_emit.append(result)

            callbacks = list(self._update_callbacks)

        # Emit callbacks outside the lock
        for result in results_to_emit:
            for cb in callbacks:
                try:
                    cb(result)
                except Exception:
                    logger.exception("on_fair_update callback raised")

    def _calculate(self, meta: ContractMeta) -> Optional[FairResult]:
        """Dispatch to future or option calculator."""
        S = self._underlying_ltp.get(meta.underlying_security_id)
        market_price = self._ltp.get(meta.security_id)
        if S is None or market_price is None:
            return None

        # Skip expired contracts
        if (meta.expiry - ist_now().date()).days < 0:
            return None

        T = time_to_expiry_years(meta.expiry)
        r = meta.risk_free_rate

        if meta.contract_type == ContractType.FUTURE:
            return self._calc_future(meta, S, market_price, T, r)
        return self._calc_option(meta, S, market_price, T, r)

    def _calc_future(
        self, meta: ContractMeta, S: float, market_price: float, T: float, r: float
    ) -> FairResult:
        """Calculate fair value for a futures contract."""
        fv = future_fair_value(S, T, r)
        mispricing = market_price - fv
        mispricing_pct = (mispricing / fv * 100) if fv > 0 else 0.0
        if fv < 1.0:
            mispricing_pct = 0.0
        elif abs(mispricing_pct) > 500:
            mispricing_pct = 500.0 if mispricing_pct > 0 else -500.0
        basis = market_price - S

        return FairResult(
            security_id=meta.security_id,
            symbol=meta.symbol,
            contract_type=meta.contract_type,
            strike=meta.strike,
            expiry=meta.expiry.isoformat(),
            market_price=market_price,
            fair_value=fv,
            mispricing=mispricing,
            mispricing_pct=mispricing_pct,
            underlying_price=S,
            time_to_expiry=T,
            basis=basis,
            cross_listed=meta.cross_listed,
            exchanges=list(meta.exchanges),
            tier=meta.tier,
        )

    def _calc_option(
        self, meta: ContractMeta, S: float, market_price: float, T: float, r: float
    ) -> Optional[FairResult]:
        """Calculate fair value and market structure metrics for an option."""
        K = meta.strike
        if K is None:
            return None

        iv = implied_volatility_newton(market_price, S, K, T, r, meta.contract_type)

        if iv is not None:
            self._update_iv_history(meta.security_id, iv)
            bs = black_scholes(S, K, T, r, iv, meta.contract_type)
        else:
            cached_iv = self._get_latest_iv(meta.security_id)
            if cached_iv is None:
                return None
            bs = black_scholes(S, K, T, r, cached_iv, meta.contract_type)

        if bs is None:
            return None

        fv = bs["price"]
        mispricing = market_price - fv
        mispricing_pct = (mispricing / fv * 100) if fv > 0 else 0.0
        if fv < 1.0:
            mispricing_pct = 0.0
        elif abs(mispricing_pct) > 500:
            mispricing_pct = 500.0 if mispricing_pct > 0 else -500.0

        iv_rank, iv_percentile = self._calc_iv_rank_percentile(meta.security_id, iv) if iv is not None else (None, None)
        moneyness = self._calc_moneyness(S, K, iv or 0.15, T)
        intrinsic = self._calc_intrinsic(S, K, meta.contract_type)
        time_val = max(market_price - intrinsic, 0.0)

        pcp_dev = self._calc_parity_deviation(meta, S, T, r)
        skew = self._calc_skew(meta)

        return FairResult(
            security_id=meta.security_id,
            symbol=meta.symbol,
            contract_type=meta.contract_type,
            strike=K,
            expiry=meta.expiry.isoformat(),
            market_price=market_price,
            fair_value=fv,
            mispricing=mispricing,
            mispricing_pct=mispricing_pct,
            underlying_price=S,
            time_to_expiry=T,
            delta=bs.get("delta"),
            gamma=bs.get("gamma"),
            theta=bs.get("theta"),
            vega=bs.get("vega"),
            implied_volatility=iv,
            vanna=bs.get("vanna"),
            volga=bs.get("volga"),
            charm=bs.get("charm"),
            speed=bs.get("speed"),
            color=bs.get("color"),
            zomma=bs.get("zomma"),
            iv_rank=iv_rank,
            iv_percentile=iv_percentile,
            moneyness=moneyness,
            intrinsic_value=intrinsic,
            time_value=time_val,
            pc_parity_deviation=pcp_dev,
            skew=skew,
            cross_listed=meta.cross_listed,
            exchanges=list(meta.exchanges),
            tier=meta.tier,
        )

    def _update_iv_history(self, security_id: str, iv: float) -> None:
        """Store one IV entry per calendar day (overwrites same-day entry)."""
        today_str = ist_now().date().isoformat()
        history = self._iv_history.setdefault(security_id, [])
        # Check last entry first (most recent) since we only ever update today or append
        if history and history[-1][0] == today_str:
            history[-1] = (today_str, iv)
            return
        history.append((today_str, iv))
        # Keep at most _MAX_HISTORY daily entries
        if len(history) > self._MAX_HISTORY:
            del history[0]

    def _calc_iv_rank_percentile(
        self, security_id: str, current_iv: Optional[float]
    ) -> tuple[Optional[float], Optional[float]]:
        """Compute IV rank and IV percentile from daily IV history."""
        if current_iv is None:
            return None, None
        history = self._iv_history.get(security_id, [])
        iv_values = [v for _, v in history]
        if len(iv_values) < 2:
            return None, None
        lo, hi = min(iv_values), max(iv_values)
        if hi == lo:
            return 0.0, 0.0
        iv_rank = (current_iv - lo) / (hi - lo) * 100
        iv_percentile = sum(1 for v in iv_values if v <= current_iv) / len(iv_values) * 100
        return iv_rank, iv_percentile

    def _calc_moneyness(self, S: float, K: float, sigma: float, T: float) -> Optional[float]:
        """Log-moneyness: ln(S/K) / (sigma * sqrt(T))."""
        if sigma <= 0 or T <= 0 or K <= 0:
            return None
        try:
            return math.log(S / K) / (sigma * math.sqrt(T))
        except (ValueError, ZeroDivisionError):
            return None

    def _calc_intrinsic(self, S: float, K: float, contract_type: ContractType) -> float:
        """Intrinsic value: max(S-K, 0) for calls, max(K-S, 0) for puts."""
        if contract_type == ContractType.CALL:
            return max(S - K, 0.0)
        return max(K - S, 0.0)

    def _calc_parity_deviation(
        self, meta: ContractMeta, S: float, T: float, r: float
    ) -> Optional[float]:
        """Put-call parity deviation: C - P - (S - K*e^(-rT)).

        Returns None if the counterpart price is not available.
        """
        if meta.strike is None:
            return None
        key = (meta.underlying_symbol, meta.expiry, meta.strike)
        pair = self._pairs.get(key, {})
        K = meta.strike
        discount = math.exp(-r * T)

        if meta.contract_type == ContractType.CALL:
            pe_sid = pair.get("PE")
            if pe_sid is None:
                return None
            pe_price = self._ltp.get(pe_sid)
            if pe_price is None:
                return None
            call_price = self._ltp.get(meta.security_id, 0.0)
            # C - P = S - K * e^(-rT) at parity
            return call_price - pe_price - (S - K * discount)
        else:
            ce_sid = pair.get("CE")
            if ce_sid is None:
                return None
            ce_price = self._ltp.get(ce_sid)
            if ce_price is None:
                return None
            put_price = self._ltp.get(meta.security_id, 0.0)
            return ce_price - put_price - (S - K * discount)

    def _calc_skew(self, meta: ContractMeta) -> Optional[float]:
        """IV skew: IV(PE) - IV(CE) at the same strike.

        Returns None if the counterpart IV is not available.
        """
        if meta.strike is None:
            return None
        key = (meta.underlying_symbol, meta.expiry, meta.strike)
        pair = self._pairs.get(key, {})

        ce_sid = pair.get("CE")
        pe_sid = pair.get("PE")
        if ce_sid is None or pe_sid is None:
            return None

        ce_iv = self._get_latest_iv(ce_sid)
        pe_iv = self._get_latest_iv(pe_sid)
        if ce_iv is None or pe_iv is None:
            return None
        return pe_iv - ce_iv

    def _get_latest_iv(self, security_id: str) -> Optional[float]:
        """Return the most recently recorded IV for a contract."""
        history = self._iv_history.get(security_id, [])
        if not history:
            return None
        return history[-1][1]

    def get_contract(self, security_id: str) -> Optional[ContractMeta]:
        """Return the ContractMeta for a contract, or None."""
        with self._lock:
            return self._contracts.get(security_id)

    def get_all_contracts(self) -> list[ContractMeta]:
        """Return all registered ContractMeta objects."""
        with self._lock:
            return list(self._contracts.values())

    def contract_count(self) -> int:
        """Return the number of registered contracts."""
        with self._lock:
            return len(self._contracts)

    def result_count(self) -> int:
        """Return the number of stored fair results."""
        with self._lock:
            return len(self._results)

    def get_result(self, security_id: str) -> Optional[FairResult]:
        """Return the latest FairResult for a contract, or None."""
        with self._lock:
            return self._results.get(security_id)

    def get_all_results(self) -> list[FairResult]:
        """Return all latest FairResults sorted by signal strength descending."""
        with self._lock:
            return sorted(self._results.values(), key=lambda r: r.signal_strength, reverse=True)

    def get_history(self, security_id: str, limit: int = 100) -> list[FairResult]:
        """Return up to `limit` recent FairResults for a contract."""
        with self._lock:
            h = self._history.get(security_id)
            if h is None:
                return []
            items = list(h)
            return items[-limit:]

    def stop(self) -> None:
        """Signal the engine to stop processing new ticks."""
        self._stopped = True
