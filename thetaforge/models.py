"""Domain objects: market snapshots, option legs, positions, the book."""
from __future__ import annotations

import math
from dataclasses import dataclass, field, asdict
from datetime import date, datetime
from typing import Any, Literal

from .config import UNIVERSE, Instrument
from . import pricing

LegKind = Literal["call", "put", "share", "future"]
Side = Literal["long", "short"]


# --------------------------------------------------------------------------
# Market data
# --------------------------------------------------------------------------

@dataclass
class UnderlyingSnapshot:
    """Everything we know about one underlying at snapshot time."""
    symbol: str
    spot: float
    iv: float                      # ATM implied vol, annualised (0.15 = 15%)
    hv: float = 0.0                # 30d historical vol, annualised
    iv_pct_52w: float = 0.0        # IV percentile over 52 weeks, 0-1
    iv_pct_13w: float = 0.0
    iv_pct_26w: float = 0.0
    prior_close: float = 0.0
    volume: float = 0.0
    source: str = "unknown"
    as_of: str = ""

    @property
    def iv_rank(self) -> float:
        """
        IV Rank on the 0-100 scale traders quote.

        Preference order: broker-supplied 52w IV percentile, else the
        IV/HV relationship as a fallback proxy.
        """
        if self.iv_pct_52w > 0:
            return round(self.iv_pct_52w * 100, 0)
        if self.hv > 0:
            return round(min(max((self.iv / self.hv - 0.6) / 0.9, 0.0), 1.0) * 100, 0)
        return 0.0

    @property
    def iv_premium(self) -> float:
        """IV minus HV: positive means options are pricing more than realised."""
        return self.iv - self.hv

    @property
    def instrument(self) -> Instrument:
        return UNIVERSE[self.symbol]

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["iv_rank"] = self.iv_rank
        return d


@dataclass
class OptionQuote:
    """A single listed contract."""
    symbol: str
    expiry: str                    # YYYY-MM-DD
    strike: float
    kind: LegKind
    bid: float = 0.0
    ask: float = 0.0
    last: float = 0.0
    iv: float = 0.0
    open_interest: int = 0
    volume: int = 0
    delta: float = 0.0
    source: str = "model"          # "quote" when it came off a real book

    @property
    def mid(self) -> float:
        if self.bid > 0 and self.ask > 0:
            return (self.bid + self.ask) / 2.0
        return self.last or self.bid or self.ask

    @property
    def spread_pct(self) -> float:
        m = self.mid
        if m <= 0 or self.ask <= 0:
            return 1.0
        return (self.ask - self.bid) / m


# --------------------------------------------------------------------------
# Positions
# --------------------------------------------------------------------------

@dataclass
class Leg:
    kind: LegKind
    side: Side
    strike: float
    qty: int                        # always positive; `side` carries direction
    expiry: str = ""
    dte: int = 0                    # per-leg; calendars/diagonals differ by leg
    price: float = 0.0              # per-share/point premium
    iv: float = 0.0
    delta: float = 0.0              # per contract, signed by side
    gamma: float = 0.0
    theta: float = 0.0
    vega: float = 0.0
    source: str = "model"

    @property
    def sign(self) -> int:
        return 1 if self.side == "long" else -1

    def label(self) -> str:
        if self.kind in ("share", "future"):
            return f"{self.side} {self.qty}"
        k = "C" if self.kind == "call" else "P"
        return f"{'+' if self.side == 'long' else '-'}{self.qty}x {self.strike:g}{k}"


@dataclass
class Position:
    symbol: str
    strategy: str                   # human label, e.g. "Short Strangle"
    strategy_key: str               # machine key, e.g. "short_strangle"
    sleeve: str                     # options | futures | stocks | cash
    legs: list[Leg] = field(default_factory=list)
    contracts: int = 1               # the "(3X)" multiplier in the blueprint table
    dte: int = 45
    expiry: str = ""
    bpr: float = 0.0                 # buying power reduction, dollars
    credit: float = 0.0              # net credit received, dollars
    max_loss: float = 0.0            # dollars; math.inf for undefined risk
    pop: float = 0.0                 # probability of profit, 0-1
    correlation: float = 0.0         # avg |rho| to the rest of the book
    notes: str = ""
    defined_risk: bool = True
    data_quality: str = "model"

    # populated by the risk engine
    delta: float = 0.0               # raw position delta (underlying shares equiv)
    beta_delta: float = 0.0          # SPY beta-weighted delta
    gamma: float = 0.0
    theta: float = 0.0               # dollars per day
    vega: float = 0.0                # dollars per vol point
    notional: float = 0.0
    _spot: float = 0.0               # underlying price at snapshot time
    _unit_bpr: float = 0.0           # BPR for a single contract, sizing scratch
    _cap: float = 0.0                # per-trade BPR cap, sizing scratch

    @property
    def instrument(self) -> Instrument:
        return UNIVERSE[self.symbol]

    @property
    def multiplier(self) -> float:
        return self.instrument.multiplier

    def leg_summary(self) -> str:
        return " / ".join(leg.label() for leg in self.legs)

    def strikes(self) -> str:
        opt = [l for l in self.legs if l.kind in ("call", "put")]
        if not opt:
            return "—"
        return " / ".join(
            f"{l.strike:g}{'C' if l.kind == 'call' else 'P'}"
            for l in sorted(opt, key=lambda x: x.strike)
        )

    def roc(self) -> float:
        """Return on capital if the credit is fully retained."""
        return self.credit / self.bpr if self.bpr else 0.0

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        d["legs"] = [asdict(l) for l in self.legs]
        d["strikes"] = self.strikes()
        d["roc"] = self.roc()
        return d


@dataclass
class Portfolio:
    nlv: float
    as_of: str
    positions: list[Position] = field(default_factory=list)
    cash_positions: list[dict[str, Any]] = field(default_factory=list)
    vix_proxy: float = 0.0
    stance: str = "moderate"
    correlation_matrix: dict[str, dict[str, float]] = field(default_factory=dict)
    warnings: list[str] = field(default_factory=list)

    # ---- aggregates ------------------------------------------------------
    @property
    def total_bpr(self) -> float:
        return sum(p.bpr for p in self.positions)

    @property
    def bpr_pct(self) -> float:
        return self.total_bpr / self.nlv if self.nlv else 0.0

    @property
    def total_credit(self) -> float:
        return sum(p.credit for p in self.positions)

    @property
    def total_theta(self) -> float:
        return sum(p.theta for p in self.positions)

    @property
    def theta_pct(self) -> float:
        return self.total_theta / self.nlv if self.nlv else 0.0

    @property
    def total_vega(self) -> float:
        return sum(p.vega for p in self.positions)

    @property
    def total_beta_delta(self) -> float:
        return sum(p.beta_delta for p in self.positions)

    @property
    def spy_notional_equiv(self) -> float:
        """What the book is effectively long/short in SPY dollar terms."""
        return self.total_beta_delta * self._spy_spot

    _spy_spot: float = 0.0

    @property
    def portfolio_pop(self) -> float:
        """BPR-weighted probability of profit."""
        tb = self.total_bpr
        if not tb:
            return 0.0
        return sum(p.pop * p.bpr for p in self.positions) / tb

    @property
    def avg_correlation(self) -> float:
        m = self.correlation_matrix
        vals = [abs(v) for k, row in m.items() for k2, v in row.items() if k != k2]
        return sum(vals) / len(vals) if vals else 0.0

    @property
    def defined_risk_max_loss(self) -> float:
        return sum(p.max_loss for p in self.positions if math.isfinite(p.max_loss))

    def sleeve_bpr(self) -> dict[str, float]:
        out: dict[str, float] = {}
        for p in self.positions:
            out[p.sleeve] = out.get(p.sleeve, 0.0) + p.bpr
        return out

    def daily_pl_sigma(self, snaps: dict[str, Any] | None = None) -> float:
        """
        One standard deviation of daily P/L.

        A near-zero beta-weighted delta does NOT mean near-zero risk: it means
        the *market-directional* component nets out. Each position still carries
        its own idiosyncratic move. So this is a genuine portfolio-variance
        calculation over position deltas, using each underlying's own daily
        volatility and the correlation matrix:

            sigma = sqrt( SUM_i SUM_j  x_i x_j rho_ij )
            where x_i = delta_i * spot_i * daily_vol_i

        Reporting only |beta_delta x SPY move| would understate this badly.
        """
        snaps = snaps or {}
        expo: dict[str, float] = {}
        for p in self.positions:
            snap = snaps.get(p.symbol)
            daily_vol = (snap.iv / math.sqrt(252)) if snap and snap.iv else 0.01
            x = p.delta * (p._spot or 0.0) * daily_vol
            expo[p.symbol] = expo.get(p.symbol, 0.0) + x

        var = 0.0
        for a, xa in expo.items():
            for b, xb in expo.items():
                rho = 1.0 if a == b else self.correlation_matrix.get(a, {}).get(b, 0.3)
                var += xa * xb * rho
        return math.sqrt(max(var, 0.0))

    def daily_pl_swing(self, underlying_move_pct: float = 0.01) -> float:
        """Directional P/L from a market-wide move of the given size."""
        return abs(self.total_beta_delta * self._spy_spot * underlying_move_pct)

    def vega_pl_per_vol_point(self) -> float:
        return self.total_vega
