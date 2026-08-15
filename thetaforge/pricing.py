"""Black-Scholes pricing, greeks, implied vol solving, and a skew model.

Used both to price legs when a live quote is unavailable and to compute
greeks consistently across ETF options and futures options (Black-76).
"""
from __future__ import annotations

import math
from dataclasses import dataclass

from scipy.optimize import brentq
from scipy.stats import norm

SQRT_252 = math.sqrt(252.0)


# --------------------------------------------------------------------------
# Core Black-Scholes / Black-76
# --------------------------------------------------------------------------

def _d1_d2(S: float, K: float, T: float, r: float, sigma: float, q: float = 0.0):
    if T <= 0 or sigma <= 0:
        return float("inf") if S > K else float("-inf"), float("inf") if S > K else float("-inf")
    vol_t = sigma * math.sqrt(T)
    d1 = (math.log(S / K) + (r - q + 0.5 * sigma ** 2) * T) / vol_t
    return d1, d1 - vol_t


def bs_price(S: float, K: float, T: float, r: float, sigma: float,
             kind: str = "call", q: float = 0.0) -> float:
    """European option price. For futures options pass q=r (Black-76)."""
    if T <= 0:
        return max(0.0, S - K) if kind == "call" else max(0.0, K - S)
    d1, d2 = _d1_d2(S, K, T, r, sigma, q)
    df, dq = math.exp(-r * T), math.exp(-q * T)
    if kind == "call":
        return S * dq * norm.cdf(d1) - K * df * norm.cdf(d2)
    return K * df * norm.cdf(-d2) - S * dq * norm.cdf(-d1)


@dataclass
class Greeks:
    price: float
    delta: float
    gamma: float
    theta: float          # per calendar day
    vega: float           # per 1 vol point (1%)
    rho: float

    def scaled(self, qty: float, multiplier: float) -> "Greeks":
        f = qty * multiplier
        return Greeks(self.price * f, self.delta * f, self.gamma * f,
                      self.theta * f, self.vega * f, self.rho * f)


def greeks(S: float, K: float, T: float, r: float, sigma: float,
           kind: str = "call", q: float = 0.0) -> Greeks:
    if T <= 0 or sigma <= 0:
        intrinsic = max(0.0, S - K) if kind == "call" else max(0.0, K - S)
        d = (1.0 if S > K else 0.0) if kind == "call" else (-1.0 if S < K else 0.0)
        return Greeks(intrinsic, d, 0.0, 0.0, 0.0, 0.0)

    d1, d2 = _d1_d2(S, K, T, r, sigma, q)
    df, dq = math.exp(-r * T), math.exp(-q * T)
    pdf = norm.pdf(d1)
    sqrt_t = math.sqrt(T)

    price = bs_price(S, K, T, r, sigma, kind, q)
    gamma = dq * pdf / (S * sigma * sqrt_t)
    vega = S * dq * pdf * sqrt_t / 100.0

    if kind == "call":
        delta = dq * norm.cdf(d1)
        theta = (-S * dq * pdf * sigma / (2 * sqrt_t)
                 - r * K * df * norm.cdf(d2)
                 + q * S * dq * norm.cdf(d1)) / 365.0
        rho = K * T * df * norm.cdf(d2) / 100.0
    else:
        delta = -dq * norm.cdf(-d1)
        theta = (-S * dq * pdf * sigma / (2 * sqrt_t)
                 + r * K * df * norm.cdf(-d2)
                 - q * S * dq * norm.cdf(-d1)) / 365.0
        rho = -K * T * df * norm.cdf(-d2) / 100.0

    return Greeks(price, delta, gamma, theta, vega, rho)


def implied_vol(price: float, S: float, K: float, T: float, r: float,
                kind: str = "call", q: float = 0.0) -> float | None:
    if T <= 0 or price <= 0:
        return None
    try:
        return brentq(lambda s: bs_price(S, K, T, r, s, kind, q) - price,
                      1e-4, 5.0, maxiter=100, xtol=1e-6)
    except (ValueError, RuntimeError):
        return None


# --------------------------------------------------------------------------
# Strike selection
# --------------------------------------------------------------------------

def strike_for_delta(S: float, T: float, r: float, sigma: float,
                     target_delta: float, kind: str = "put",
                     q: float = 0.0) -> float:
    """Invert delta to a strike. target_delta given as a positive number."""
    target = abs(target_delta)
    if T <= 0 or sigma <= 0:
        return S
    dq = math.exp(-q * T)
    # N(d1) = target/dq for calls;  N(-d1) = target/dq for puts
    ratio = min(max(target / dq, 1e-6), 1 - 1e-6)
    if kind == "call":
        d1 = norm.ppf(ratio)
    else:
        d1 = -norm.ppf(ratio)
    vol_t = sigma * math.sqrt(T)
    return S * math.exp(-(d1 * vol_t) + (r - q + 0.5 * sigma ** 2) * T)


def round_to_increment(strike: float, increment: float) -> float:
    return round(strike / increment) * increment


def strike_increment(S: float) -> float:
    """Typical listed strike spacing by underlying price."""
    if S < 25:
        return 0.5
    if S < 100:
        return 1.0
    if S < 300:
        return 2.5
    if S < 1000:
        return 5.0
    return 25.0


# --------------------------------------------------------------------------
# Volatility surface: term structure + skew
# --------------------------------------------------------------------------

def term_adjust(atm_iv: float, dte: int, anchor_dte: int = 30) -> float:
    """Mild upward-sloping term structure in calm markets, inverted when IV is high."""
    if dte <= 0:
        return atm_iv
    slope = 0.06 if atm_iv < 0.30 else -0.05
    return atm_iv * (1.0 + slope * math.log(max(dte, 1) / anchor_dte))


def skew_iv(atm_iv: float, S: float, K: float, T: float,
            asset_class: str = "us_large_cap") -> float:
    """
    Sticky-delta style skew. Equity indices carry a pronounced put skew;
    commodities carry a call skew (upside vol); metals are closer to a smile.
    """
    if T <= 0 or S <= 0:
        return atm_iv
    moneyness = math.log(K / S) / (atm_iv * math.sqrt(T))

    put_skew_slope = {
        "us_large_cap": -0.085, "us_tech": -0.075, "us_small_cap": -0.070,
        "semiconductors": -0.055, "china_equity": -0.045,
        "long_duration_rates": -0.020, "precious_metals": 0.015,
        "energy": 0.035, "cash": 0.0,
    }.get(asset_class, -0.05)

    smile = 0.010 * moneyness ** 2
    iv = atm_iv * (1.0 + put_skew_slope * moneyness + smile)
    return max(iv, 0.02)


# --------------------------------------------------------------------------
# Probability
# --------------------------------------------------------------------------

def prob_otm(S: float, K: float, T: float, sigma: float, kind: str,
             r: float = 0.0) -> float:
    """Risk-neutral probability the option finishes out of the money."""
    if T <= 0 or sigma <= 0:
        return 1.0 if ((kind == "put" and S > K) or (kind == "call" and S < K)) else 0.0
    _, d2 = _d1_d2(S, K, T, sigma, sigma)
    _, d2 = _d1_d2(S, K, T, r, sigma)
    return norm.cdf(d2) if kind == "put" else norm.cdf(-d2)


def prob_touch(S: float, K: float, T: float, sigma: float) -> float:
    """Approximate probability of touching a barrier before expiry (~2x prob ITM)."""
    kind = "put" if K < S else "call"
    return min(1.0, 2.0 * (1.0 - prob_otm(S, K, T, sigma, kind)))


def expected_move(S: float, sigma: float, dte: int) -> float:
    """1 standard deviation move over the period."""
    return S * sigma * math.sqrt(max(dte, 0) / 365.0)
