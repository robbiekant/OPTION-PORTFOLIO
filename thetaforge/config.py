"""
ThetaForge configuration: the rulebook, expressed as code.

Every constant here traces to a specific rule from the source material
(tastylive "6 Steps To Build An Options Portfolio From Scratch",
Sosnoff "Blueprint to Tom Sosnoff's Ideal Portfolio in 2025",
tastylive "Best and Worst $100k+ Portfolio Strategies",
Theta Profits "Stop Chasing Options Strategies").
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

# --------------------------------------------------------------------------
# Portfolio level
# --------------------------------------------------------------------------

PORTFOLIO_NLV = 300_000.0
RISK_FREE_RATE = 0.041          # 3m T-bill, override at runtime
BENCHMARK = "SPY"               # everything beta-weights to this

# Sleeve split of *buying power reduction* (Sosnoff blueprint).
SLEEVE_TARGETS = {
    "options": 0.50,            # ETF / index options, defined + undefined risk
    "futures": 0.20,            # futures & futures options
    "stocks": 0.20,             # outright ETF shares, for delta shaping & hedges
    "cash": 0.10,               # dry powder held back inside the deployed budget
}

# --------------------------------------------------------------------------
# Capital deployment, scaled by the volatility regime (Sosnoff @45:30)
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class VixBand:
    name: str
    vix_low: float
    vix_high: float
    conservative: float
    moderate: float
    aggressive: float

VIX_BANDS: tuple[VixBand, ...] = (
    VixBand("low",      0.0,  15.0, 0.25, 0.38, 0.50),
    VixBand("moderate", 15.0, 30.0, 0.32, 0.46, 0.60),
    VixBand("elevated", 30.0, 40.0, 0.40, 0.55, 0.70),
    VixBand("high",     40.0, 99.0, 0.50, 0.65, 0.80),
)

DeploymentStance = Literal["conservative", "moderate", "aggressive"]


def deployment_target(vix: float, stance: DeploymentStance = "moderate") -> float:
    """Fraction of net liq to commit as buying power reduction."""
    for band in VIX_BANDS:
        if band.vix_low <= vix < band.vix_high:
            return getattr(band, stance)
    return VIX_BANDS[-1].aggressive


def vix_regime(vix: float) -> str:
    for band in VIX_BANDS:
        if band.vix_low <= vix < band.vix_high:
            return band.name
    return VIX_BANDS[-1].name


# --------------------------------------------------------------------------
# Trade mechanics
# --------------------------------------------------------------------------

TARGET_DTE = 45                 # the decay-curve sweet spot
DTE_WINDOW = (30, 60)           # acceptable entry range
MANAGE_DTE = 21                 # roll or close here, no exceptions
PROFIT_TARGET_UNDEFINED = 0.50  # close naked/strangle at 50% of credit
PROFIT_TARGET_DEFINED = 0.50    # close spreads/condors at 50%
LOSS_MULTIPLE_DEFINED = 2.0     # stop at 2x credit received on defined risk
LOSS_MULTIPLE_UNDEFINED = 2.5   # stop at 2.5x credit on undefined risk
TESTED_DELTA_TRIGGER = 0.30     # short strike delta that forces a decision

# Probability of profit envelope for the *whole book* (Sosnoff @42:20)
PORTFOLIO_POP_TARGET = (0.65, 0.72)

# Daily theta as a fraction of net liq (Sosnoff @1:00:33)
THETA_TARGET_PCT = (0.001, 0.003)

# Short-strike delta defaults by structure. Calibrated so the BPR-weighted
# book POP lands inside PORTFOLIO_POP_TARGET rather than drifting high —
# an 85%-POP book is under-collecting premium for the capital it ties up.
DEFAULT_SHORT_DELTA = {
    "short_put": 0.25,
    "short_call": 0.25,
    "short_strangle": 0.20,
    "short_straddle": 0.50,
    "put_credit_spread": 0.26,
    "call_credit_spread": 0.24,
    "iron_condor": 0.19,
    "wide_iron_condor": 0.14,
    "skewed_iron_condor": 0.25,
    "ratio_spread": 0.30,
    "jade_lizard": 0.25,
    "calendar": 0.50,
}

# Micro substitutes: when one full-size contract would breach the per-trade
# sizing cap, the engine steps down to the micro rather than skipping the
# asset class entirely (Katie McGaragle, "scaling exposure").
MICRO_SUBSTITUTE = {"/GC": "/MGC", "/CL": "/MCL"}

# --------------------------------------------------------------------------
# Sizing restrictions (Sosnoff @47:38 / @47:51, Butler "risk <=5%")
# --------------------------------------------------------------------------

MAX_BPR_DEFINED_RISK = 0.05     # 1-5% of buying power on one defined-risk trade
MAX_BPR_UNDEFINED_RISK = 0.15   # 1-15% on one undefined-risk trade
# Debit structures (calendars, diagonals) pay out on a volatility view rather
# than on decay, and their capital is at risk from the first day rather than
# collateralised against a credit. They get a tighter leash.
MAX_BPR_DEBIT_STRUCTURE = 0.02
MAX_LOSS_PER_TRADE_PCT = 0.02   # hard cap: 2% of NLV expected max loss
MAX_POSITIONS_PER_UNDERLYING = 1
MIN_OCCURRENCES_PER_YEAR = 500  # law of large numbers floor

# --------------------------------------------------------------------------
# Correlation & liquidity gates (Chandler step 1)
# --------------------------------------------------------------------------

MAX_PORTFOLIO_CORRELATION = 0.50   # book-level average pairwise |rho|
MAX_PAIR_CORRELATION = 0.80        # refuse to add a second leg above this
CORRELATION_LOOKBACK_DAYS = 120
MIN_LIQUIDITY_SCORE = 3            # 1-4 stars; 3+ only
MAX_BID_ASK_PCT = 0.05             # spread as fraction of mid

# --------------------------------------------------------------------------
# Universe: ETFs and futures only. No single-name equity risk.
# --------------------------------------------------------------------------

@dataclass(frozen=True)
class Instrument:
    symbol: str
    name: str
    kind: Literal["etf", "future"]
    asset_class: str
    ib_conid: int | None = None
    ib_exchange: str = "SMART"
    multiplier: float = 100.0
    beta_to_spy: float = 1.0
    # futures only
    ib_underlying_conid: int | None = None
    front_conid: int | None = None
    front_symbol: str = ""
    tick_value: float = 0.0
    margin_per_contract: float = 0.0
    liquidity: int = 4


UNIVERSE: dict[str, Instrument] = {
    # ---- Equity index / sector ETFs -------------------------------------
    "SPY": Instrument("SPY", "SPDR S&P 500 ETF", "etf", "us_large_cap",
                      ib_conid=756733, ib_exchange="ARCA", beta_to_spy=1.00, liquidity=4),
    "QQQ": Instrument("QQQ", "Invesco QQQ Trust", "etf", "us_tech",
                      ib_conid=320227571, ib_exchange="NASDAQ", beta_to_spy=1.12, liquidity=4),
    "IWM": Instrument("IWM", "iShares Russell 2000 ETF", "etf", "us_small_cap",
                      ib_conid=9579970, ib_exchange="ARCA", beta_to_spy=1.08, liquidity=4),
    "SMH": Instrument("SMH", "VanEck Semiconductor ETF", "etf", "semiconductors",
                      ib_conid=229725622, ib_exchange="NASDAQ", beta_to_spy=1.55, liquidity=4),
    "FXI": Instrument("FXI", "iShares China Large-Cap ETF", "etf", "china_equity",
                      ib_conid=31421120, ib_exchange="ARCA", beta_to_spy=0.55, liquidity=4),
    # ---- Rates ----------------------------------------------------------
    "TLT": Instrument("TLT", "iShares 20+ Year Treasury Bond ETF", "etf", "long_duration_rates",
                      ib_conid=15547841, ib_exchange="NASDAQ", beta_to_spy=-0.10, liquidity=4),
    # ---- Metals ---------------------------------------------------------
    "GLD": Instrument("GLD", "SPDR Gold Shares", "etf", "precious_metals",
                      ib_conid=51529211, ib_exchange="ARCA", beta_to_spy=0.12, liquidity=4),
    "SLV": Instrument("SLV", "iShares Silver Trust", "etf", "precious_metals",
                      ib_conid=39039301, ib_exchange="ARCA", beta_to_spy=0.28, liquidity=4),
    # ---- Futures --------------------------------------------------------
    "/GC": Instrument("/GC", "COMEX Gold Futures (100 oz)", "future", "precious_metals",
                      ib_underlying_conid=17340718, ib_exchange="COMEX", multiplier=100.0,
                      beta_to_spy=0.10, front_conid=462941472, front_symbol="GCZ6",
                      tick_value=10.0, margin_per_contract=23_000.0, liquidity=4),
    "/MGC": Instrument("/MGC", "COMEX Micro Gold Futures (10 oz)", "future",
                       "precious_metals", ib_exchange="COMEX", multiplier=10.0,
                       beta_to_spy=0.10, front_symbol="MGCZ6",
                       tick_value=1.0, margin_per_contract=2_300.0, liquidity=4),
    "/CL": Instrument("/CL", "NYMEX Light Sweet Crude Oil Futures (1,000 bbl)", "future",
                      "energy", ib_underlying_conid=17340715, ib_exchange="NYMEX",
                      multiplier=1000.0, beta_to_spy=0.22, front_conid=304037511,
                      front_symbol="CLX6", tick_value=10.0,
                      margin_per_contract=7_800.0, liquidity=4),
    "/MCL": Instrument("/MCL", "NYMEX Micro Crude Oil Futures (100 bbl)", "future",
                       "energy", ib_exchange="NYMEX", multiplier=100.0,
                       beta_to_spy=0.22, front_symbol="MCLX6", tick_value=1.0,
                       margin_per_contract=780.0, liquidity=3),
    "/MES": Instrument("/MES", "Micro E-mini S&P 500", "future", "us_large_cap",
                       ib_exchange="CME", multiplier=5.0, beta_to_spy=1.00,
                       tick_value=1.25, margin_per_contract=2_600.0, liquidity=4),
    # ---- Cash equivalents ----------------------------------------------
    "SGOV": Instrument("SGOV", "iShares 0-3 Month Treasury Bond ETF", "etf", "cash",
                       beta_to_spy=0.0, liquidity=4),
    "BIL": Instrument("BIL", "SPDR 1-3 Month T-Bill ETF", "etf", "cash",
                      beta_to_spy=0.0, liquidity=4),
}

# Asset classes we want represented, for the non-correlation mandate.
DIVERSIFICATION_TARGETS = (
    "us_large_cap", "us_tech", "us_small_cap", "semiconductors",
    "china_equity", "long_duration_rates", "precious_metals", "energy",
)

# Margin approximation constants (Reg-T / portfolio margin blend)
NAKED_MARGIN_PCT_OTM = 0.20     # 20% of underlying less OTM amount
NAKED_MARGIN_FLOOR_PCT = 0.10   # floor: 10% of strike
FUTURES_OPTION_SPAN_FACTOR = 0.55  # SPAN margin ~55% of outright futures margin
