"""Black-Scholes pricing and Greeks for F&O fair value calculation."""
import math
from typing import Optional

from src.core.models import ContractType


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
    if S <= 0 or T <= 0 or sigma <= 0:
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
    vanna = nd1 * d2 / sigma
    volga = vega_raw * d1 * d2 / sigma
    speed = -(gamma / S) * (1 + d1 / (sigma * sqrt_T))
    color = (
        -nd1 / (2 * S * T * sigma * sqrt_T)
        * (2 * r * T + 1 + d1 * (2 * r * T - d2 * sigma * sqrt_T) / (sigma * sqrt_T))
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
