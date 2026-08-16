"""Risk engine: margin models, greeks aggregation, beta-weighting, correlation."""
from __future__ import annotations

import math
from typing import Iterable

import numpy as np

from . import config, pricing
from .models import Leg, Position, Portfolio, UnderlyingSnapshot


# --------------------------------------------------------------------------
# Buying power reduction
# --------------------------------------------------------------------------

def naked_option_margin(spot: float, strike: float, premium: float,
                        kind: str, multiplier: float = 100.0) -> float:
    """
    Reg-T naked option requirement:
        max(20% of underlying - OTM amount + premium,
            10% of strike + premium)
    """
    otm = max(0.0, spot - strike) if kind == "put" else max(0.0, strike - spot)
    a = config.NAKED_MARGIN_PCT_OTM * spot - otm + premium
    b = config.NAKED_MARGIN_FLOOR_PCT * strike + premium
    return max(a, b, 0.0) * multiplier


def vertical_spread_margin(width: float, credit_per_unit: float,
                           multiplier: float = 100.0) -> float:
    return max(0.0, (width - credit_per_unit)) * multiplier


def position_bpr(pos: Position, snap: UnderlyingSnapshot) -> float:
    """Estimate buying power reduction for a whole structure."""
    inst = pos.instrument
    mult = inst.multiplier
    spot = snap.spot
    n = pos.contracts

    puts = sorted([l for l in pos.legs if l.kind == "put"], key=lambda l: l.strike)
    calls = sorted([l for l in pos.legs if l.kind == "call"], key=lambda l: l.strike)
    shares = [l for l in pos.legs if l.kind in ("share", "future")]

    if shares and not (puts or calls):
        if inst.kind == "future":
            return inst.margin_per_contract * sum(l.qty for l in shares) * n
        # ETF shares: assume 50% Reg-T initial
        return sum(l.qty * spot * 0.5 for l in shares) * n

    # Calendars / diagonals: same-strike or near-strike long-dated long against
    # a short-dated short. The requirement is the net debit paid.
    if pos.strategy_key in ("calendar", "diagonal"):
        debit = sum(l.sign * l.price for l in pos.legs)
        return max(debit, 0.0) * mult * n

    def side_req(legs: list[Leg], kind: str) -> float:
        shorts = [l for l in legs if l.side == "short"]
        longs = [l for l in legs if l.side == "long"]
        if not shorts:
            return 0.0
        short = shorts[0]
        if longs:
            # defined risk: widest width among matched pairs
            width = max(abs(short.strike - l.strike) for l in longs)
            credit = sum(s.price for s in shorts) - sum(l.price for l in longs)
            return vertical_spread_margin(width, max(credit, 0.0), mult)
        return naked_option_margin(spot, short.strike, short.price, kind, mult)

    put_req = side_req(puts, "put")
    call_req = side_req(calls, "call")

    # Strangles/condors: brokers charge the greater side, not both.
    req = max(put_req, call_req)

    if inst.kind == "future":
        req = max(req, inst.margin_per_contract * config.FUTURES_OPTION_SPAN_FACTOR)

    return req * n


def position_max_loss(pos: Position, snap: UnderlyingSnapshot) -> float:
    mult = pos.multiplier
    n = pos.contracts
    if pos.strategy_key in ("calendar", "diagonal"):
        debit = sum(l.sign * l.price for l in pos.legs)
        return max(debit, 0.0) * mult * n
    if pos.strategy_key == "long_shares":
        return sum(l.qty for l in pos.legs if l.kind == "share") * snap.spot
    puts = sorted([l for l in pos.legs if l.kind == "put"], key=lambda l: l.strike)
    calls = sorted([l for l in pos.legs if l.kind == "call"], key=lambda l: l.strike)

    def side_loss(legs: list[Leg]) -> float:
        shorts = [l for l in legs if l.side == "short"]
        longs = [l for l in legs if l.side == "long"]
        if not shorts:
            return 0.0
        if not longs:
            return math.inf
        short = shorts[0]
        return max(abs(short.strike - l.strike) for l in longs) * mult

    pl, cl = side_loss(puts), side_loss(calls)
    if math.isinf(pl) or math.isinf(cl):
        return math.inf
    worst = max(pl, cl)
    return max(0.0, worst - pos.credit / n) * n if worst else 0.0


# --------------------------------------------------------------------------
# Greeks aggregation
# --------------------------------------------------------------------------

def compute_position_greeks(pos: Position, snap: UnderlyingSnapshot,
                            r: float = config.RISK_FREE_RATE) -> Position:
    inst = pos.instrument
    mult = inst.multiplier
    q = r if inst.kind == "future" else 0.0   # Black-76 for futures options

    # Delta is carried in *underlying unit equivalents* (shares for ETFs,
    # ounces/barrels for futures) so that delta * spot is always a dollar
    # notional and beta-weighting is a single consistent formula.
    d = g = th = v = 0.0
    for leg in pos.legs:
        sgn = leg.sign * leg.qty
        if leg.kind == "share":
            leg.delta = leg.sign
            d += sgn
            continue
        if leg.kind == "future":
            leg.delta = leg.sign
            d += sgn * mult
            continue

        # Each leg decays on its own clock — this is what makes a calendar a
        # calendar rather than a zero-width strangle.
        T = max(leg.dte or pos.dte, 0) / 365.0
        gk = pricing.greeks(snap.spot, leg.strike, T, r, leg.iv or snap.iv,
                            leg.kind, q)
        leg.delta = gk.delta * leg.sign
        leg.gamma = gk.gamma * leg.sign
        leg.theta = gk.theta * leg.sign * mult
        leg.vega = gk.vega * leg.sign * mult
        d += sgn * gk.delta * mult
        g += sgn * gk.gamma * mult
        th += sgn * gk.theta * mult
        v += sgn * gk.vega * mult

    n = pos.contracts
    pos.delta = d * n
    pos.gamma = g * n
    pos.theta = th * n
    pos.vega = v * n
    pos.notional = abs(pos.delta) * snap.spot
    pos._spot = snap.spot
    pos.beta_delta = beta_weight(pos.delta, snap.spot, inst.beta_to_spy)
    return pos


def beta_weight(delta_units: float, spot: float, beta: float,
                spy_spot: float = 1.0) -> float:
    """
    Convert raw delta into SPY-equivalent deltas:
        beta_delta = delta * spot * beta / spy_price
    """
    if spy_spot <= 0:
        return 0.0
    return delta_units * spot * beta / spy_spot


def rebase_beta_deltas(portfolio: Portfolio, spy_spot: float) -> None:
    """Re-express every position's delta in SPY-share equivalents."""
    from .config import UNIVERSE
    portfolio._spy_spot = spy_spot
    for p in portfolio.positions:
        inst = UNIVERSE[p.symbol]
        p.beta_delta = beta_weight(p.delta, p._spot or 0.0,
                                   inst.beta_to_spy, spy_spot)


# --------------------------------------------------------------------------
# Probability of profit
# --------------------------------------------------------------------------

def position_pop(pos: Position, snap: UnderlyingSnapshot,
                 r: float = config.RISK_FREE_RATE) -> float:
    """
    POP for a credit structure: probability price finishes between the
    breakevens. Computed from the risk-neutral lognormal distribution.
    """
    if pos.strategy_key in ("long_shares", "futures_hedge", "share_hedge"):
        return 0.50            # a directional holding is a coin flip by construction
    if pos.strategy_key in ("calendar", "diagonal"):
        return _calendar_pop(pos, snap, r)
    T = max(pos.dte, 1) / 365.0
    sigma = snap.iv
    S = snap.spot
    mult = pos.multiplier
    credit_per_unit = (pos.credit / pos.contracts) / mult if pos.contracts else 0.0

    puts = sorted([l for l in pos.legs if l.kind == "put"], key=lambda l: l.strike)
    calls = sorted([l for l in pos.legs if l.kind == "call"], key=lambda l: l.strike)
    short_put = next((l for l in puts if l.side == "short"), None)
    short_call = next((l for l in calls if l.side == "short"), None)

    lower = (short_put.strike - credit_per_unit) if short_put else 0.0
    upper = (short_call.strike + credit_per_unit) if short_call else math.inf

    def cdf_below(K: float) -> float:
        if K <= 0:
            return 0.0
        if math.isinf(K):
            return 1.0
        return 1.0 - pricing.prob_otm(S, K, T, sigma, "put", r)

    p = cdf_below(upper) - cdf_below(lower)
    return round(min(max(p, 0.0), 1.0), 4)


def _calendar_pop(pos: Position, snap: UnderlyingSnapshot, r: float) -> float:
    """
    A calendar has no closed-form breakeven. Value the structure at the
    near-term expiry across a grid of underlying prices — the far leg still
    has life left — find where P/L crosses zero, and integrate the
    risk-neutral density between those crossings.
    """
    near = min(pos.legs, key=lambda l: l.dte)
    far = max(pos.legs, key=lambda l: l.dte)
    if near.dte == far.dte:
        return 0.5

    S, sigma = snap.spot, snap.iv
    T1 = max(near.dte, 1) / 365.0
    residual = max(far.dte - near.dte, 1) / 365.0
    debit = sum(l.sign * l.price for l in pos.legs)
    if debit <= 0:
        return 0.5

    def pl(px: float) -> float:
        far_val = pricing.bs_price(px, far.strike, residual, r,
                                   far.iv or sigma, far.kind)
        near_val = (max(0.0, px - near.strike) if near.kind == "call"
                    else max(0.0, near.strike - px))
        return (far.sign * far_val + near.sign * near_val) - debit

    grid = [S * (0.55 + 0.9 * i / 400) for i in range(401)]
    profitable = [px for px in grid if pl(px) > 0]
    if not profitable:
        return 0.05
    lo, hi = min(profitable), max(profitable)

    def cdf_below(K: float) -> float:
        return 1.0 - pricing.prob_otm(S, K, T1, sigma, "put", r)

    return round(min(max(cdf_below(hi) - cdf_below(lo), 0.0), 1.0), 4)


# --------------------------------------------------------------------------
# Correlation
# --------------------------------------------------------------------------

def correlation_matrix(returns: dict[str, list[float]]) -> dict[str, dict[str, float]]:
    syms = [s for s, v in returns.items() if len(v) > 5]
    if len(syms) < 2:
        return {}
    n = min(len(returns[s]) for s in syms)
    mat = np.array([returns[s][-n:] for s in syms])
    with np.errstate(invalid="ignore"):
        c = np.corrcoef(mat)
    c = np.nan_to_num(c)
    return {a: {b: round(float(c[i][j]), 3) for j, b in enumerate(syms)}
            for i, a in enumerate(syms)}


def avg_correlation_to_book(symbol: str, others: Iterable[str],
                            matrix: dict[str, dict[str, float]]) -> float:
    row = matrix.get(symbol, {})
    vals = [abs(row[o]) for o in others if o != symbol and o in row]
    return round(sum(vals) / len(vals), 3) if vals else 0.0


# --------------------------------------------------------------------------
# Rule checks
# --------------------------------------------------------------------------

def audit(portfolio: Portfolio) -> list[dict[str, str]]:
    """Run the book against the rulebook. Returns a list of check results."""
    out: list[dict[str, str]] = []

    def check(name: str, ok: bool, detail: str, rule: str):
        out.append({"check": name, "status": "pass" if ok else "warn",
                    "detail": detail, "rule": rule})

    target = config.deployment_target(portfolio.vix_proxy, portfolio.stance)
    band = config.vix_regime(portfolio.vix_proxy)
    # The cash sleeve is deliberately left undeployed, so the reachable
    # ceiling is the target less that reserve.
    reachable = target * (1.0 - config.SLEEVE_TARGETS["cash"])
    ok = 0.80 * reachable <= portfolio.bpr_pct <= target * 1.10
    check("Capital deployment", ok,
          f"{portfolio.bpr_pct:.1%} of net liq deployed; {target:.0%} target "
          f"less a {config.SLEEVE_TARGETS['cash']:.0%} cash reserve gives a "
          f"{reachable:.1%} working ceiling ({band}-vol regime, "
          f"{portfolio.stance} stance)",
          f"Sosnoff: scale deployment to VIX; {band} regime -> {target:.0%}")

    lo, hi = config.PORTFOLIO_POP_TARGET
    pop = portfolio.portfolio_pop
    check("Portfolio POP", lo <= pop <= hi + 0.08,
          f"{pop:.1%} BPR-weighted probability of profit",
          f"Target band {lo:.0%}-{hi:.0%}")

    tlo, thi = config.THETA_TARGET_PCT
    tp = portfolio.theta_pct
    regime_note = ""
    if tp < tlo and band == "low":
        regime_note = (" — expected in a low-vol regime; reaching the floor "
                       "here would require over-deploying into cheap premium")
    check("Daily theta", tlo <= tp <= thi * 1.25,
          f"${portfolio.total_theta:,.0f}/day = {tp:.3%} of net liq{regime_note}",
          f"Target {tlo:.1%}-{thi:.1%} of net liq per day")

    ac = portfolio.avg_correlation
    check("Book correlation", ac <= config.MAX_PORTFOLIO_CORRELATION,
          f"average pairwise |rho| = {ac:.2f}",
          f"Must stay below {config.MAX_PORTFOLIO_CORRELATION}")

    bd = portfolio.total_beta_delta
    neutral_band = 0.02 * portfolio.nlv / max(portfolio._spy_spot, 1)
    check("Beta-weighted delta", abs(bd) <= max(neutral_band, 25),
          f"{bd:+.1f} SPY deltas = ${portfolio.spy_notional_equiv:,.0f} "
          f"notional ({portfolio.spy_notional_equiv / portfolio.nlv:+.1%} of NLV)",
          "Directional exposure must be near zero")

    sleeves = portfolio.sleeve_bpr()
    total = portfolio.total_bpr or 1.0
    for name, want in config.SLEEVE_TARGETS.items():
        if name == "cash":
            continue
        got = sleeves.get(name, 0.0) / total
        check(f"Sleeve: {name}", abs(got - want) <= 0.15,
              f"{got:.0%} of deployed BPR vs {want:.0%} target",
              f"Blueprint target {want:.0%}")

    # Per-trade sizing caps apply to derivatives positions. Outright ETF
    # holdings are the stock sleeve, governed by the sleeve target above,
    # and the /MES hedge is ballast rather than a risk-taking trade.
    exempt = {"long_shares", "futures_hedge", "share_hedge"}
    denom = portfolio.nlv * config.deployment_target(
        portfolio.vix_proxy, portfolio.stance) or total

    def _cap(p) -> float:
        if p.strategy_key in ("calendar", "diagonal"):
            return config.MAX_BPR_DEBIT_STRUCTURE
        return (config.MAX_BPR_UNDEFINED_RISK if not p.defined_risk
                else config.MAX_BPR_DEFINED_RISK)

    breaches = [(p, p.bpr / denom, _cap(p))
                for p in portfolio.positions if p.strategy_key not in exempt]
    over = [(p, s, c) for p, s, c in breaches if s > c + 1e-3]
    if over:
        worst = max(over, key=lambda x: x[1] - x[2])
        check("Per-trade sizing", False,
              f"{len(over)} position(s) above cap; largest is "
              f"{worst[0].symbol} at {worst[1]:.1%} (cap {worst[2]:.0%})",
              "Defined risk <=5% of BPR, undefined risk <=15%")
    else:
        check("Per-trade sizing", True,
              f"largest derivatives position is "
              f"{max((s for _, s, _ in breaches), default=0):.1%} of BPR",
              "Defined risk <=5% of BPR, undefined risk <=15%")

    # Stock sleeve concentration
    stock = [p for p in portfolio.positions if p.strategy_key == "long_shares"]
    if stock:
        worst = max(p.bpr / total for p in stock)
        check("Stock sleeve concentration", worst <= 0.12,
              f"largest outright ETF holding is {worst:.1%} of deployed BPR",
              "No single ETF holding above 12% of deployed capital")

    return out
