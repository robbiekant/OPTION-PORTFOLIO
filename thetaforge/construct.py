"""
Portfolio construction engine.

Turns a market snapshot into a fully-specified book that satisfies the
rulebook in config.py: sleeve split, VIX-scaled deployment, 45 DTE,
POP band, correlation ceiling, per-trade sizing caps and — last —
a beta-weighted delta driven to approximately zero.
"""
from __future__ import annotations

import datetime as dt
import math
from dataclasses import dataclass

from . import config, pricing, risk
from .models import Leg, OptionQuote, Portfolio, Position, UnderlyingSnapshot


# --------------------------------------------------------------------------
# Strategy selection
# --------------------------------------------------------------------------

@dataclass
class StrategySpec:
    key: str
    label: str
    defined_risk: bool
    sleeve: str
    bias: str            # bullish | bearish | neutral
    rationale: str


def choose_strategy(snap: UnderlyingSnapshot, bias: str,
                    prefer_defined: bool) -> StrategySpec:
    """
    Product-indifferent strategy selection driven by the volatility state,
    not by a view on the underlying.
    """
    ivr = snap.iv_rank
    inst = snap.instrument
    sleeve = "futures" if inst.kind == "future" else "options"

    # IV rank says premium is high against its own history. The IV/HV premium
    # says whether it is high against what the underlying is actually doing.
    # Both must agree before uncapped tail risk is on the table: a name can sit
    # at IVR 74 while implied still prices below realised, and selling naked
    # premium there is selling something that is cheap in the only sense that
    # settles the trade.
    rich = snap.iv_premium > 0.005

    if ivr >= 60 and rich and not prefer_defined:
        if bias == "neutral":
            return StrategySpec("short_strangle", "Short Strangle", False, sleeve,
                                bias, f"IVR {ivr:.0f} — premium is rich enough to "
                                "justify undefined risk on both sides")
        if bias == "bullish":
            return StrategySpec("short_put", "Short Put", False, sleeve, bias,
                                f"IVR {ivr:.0f} — sell the put skew outright")
        return StrategySpec("short_call", "Short Call", False, sleeve, bias,
                            f"IVR {ivr:.0f} — sell upside vol outright")

    if ivr >= 45:
        why = (f"IVR {ivr:.0f}" if rich else
               f"IVR {ivr:.0f} but IV {abs(snap.iv_premium):.1%} below realised — "
               "cap the tails")
        if bias == "neutral":
            return StrategySpec("iron_condor", "Short Iron Condor", True, sleeve,
                                bias, f"{why} — condor captures the range "
                                "with capped tails")
        if bias == "bullish":
            return StrategySpec("put_credit_spread", "Short Put Spread", True,
                                sleeve, bias, f"IVR {ivr:.0f} — defined-risk bullish")
        return StrategySpec("call_credit_spread", "Short Call Spread", True,
                            sleeve, bias, f"IVR {ivr:.0f} — defined-risk bearish")

    if ivr >= 25:
        if bias == "neutral":
            return StrategySpec("wide_iron_condor", "Short Wide Iron Condor", True,
                                sleeve, bias, f"IVR {ivr:.0f} — widen the wings, "
                                "premium is thinner")
        if bias == "bullish":
            return StrategySpec("put_credit_spread", "Short Put Spread", True,
                                sleeve, bias, f"IVR {ivr:.0f} — small defined-risk "
                                "bullish")
        return StrategySpec("call_credit_spread", "Short Call Spread", True,
                            sleeve, bias, f"IVR {ivr:.0f} — small defined-risk bearish")

    # Low IVR: buying vol is the cleaner expression.
    if bias == "bearish":
        return StrategySpec("calendar", "Long Put Calendar", True, sleeve, bias,
                            f"IVR {ivr:.0f} — vol is cheap; own it via a calendar "
                            "rather than sell it")
    return StrategySpec("put_credit_spread", "Short Put Spread", True, sleeve, bias,
                        f"IVR {ivr:.0f} — low vol, keep it defined and small")


# --------------------------------------------------------------------------
# Leg building
# --------------------------------------------------------------------------

def _price_leg(snap: UnderlyingSnapshot, strike: float, kind: str, dte: int,
               r: float, chain: list[OptionQuote] | None) -> tuple[float, float, str]:
    """Return (premium, iv, source). Prefers a real quote, models otherwise."""
    if chain:
        match = min((q for q in chain if q.kind == kind),
                    key=lambda q: abs(q.strike - strike), default=None)
        if match and abs(match.strike - strike) < 1e-6 and match.mid > 0:
            return match.mid, (match.iv or snap.iv), "quote"

    T = dte / 365.0
    inst = snap.instrument
    q = r if inst.kind == "future" else 0.0
    atm = pricing.term_adjust(snap.iv, dte)
    iv = pricing.skew_iv(atm, snap.spot, strike, T, inst.asset_class)
    px = pricing.bs_price(snap.spot, strike, T, r, iv, kind, q)
    return px, iv, "model"


def build_legs(spec: StrategySpec, snap: UnderlyingSnapshot, dte: int,
               r: float, chain: list[OptionQuote] | None = None,
               delta_tilt: float = 0.0) -> tuple[list[Leg], float]:
    """
    Construct the legs for a strategy. `delta_tilt` shifts short-strike
    deltas to steer the position's directional exposure: positive tilt
    pushes deltas long (fatter short puts), negative pushes them short.
    Returns (legs, net_credit_per_contract_in_points).
    """
    S, T = snap.spot, dte / 365.0
    inst = snap.instrument
    q = r if inst.kind == "future" else 0.0
    atm = pricing.term_adjust(snap.iv, dte)
    inc = pricing.strike_increment(S)
    base = config.DEFAULT_SHORT_DELTA.get(spec.key, 0.20)

    def K(target_delta: float, kind: str) -> float:
        d = min(max(target_delta, 0.02), 0.60)
        raw = pricing.strike_for_delta(S, T, r, atm, d, kind, q)
        return pricing.round_to_increment(raw, inc)

    def leg(kind: str, side: str, strike: float, qty: int = 1,
            leg_dte: int | None = None) -> Leg:
        d = leg_dte or dte
        px, iv, src = _price_leg(snap, strike, kind, d, r, chain)
        return Leg(kind=kind, side=side, strike=strike, qty=qty,
                   expiry="", dte=d, price=px, iv=iv, source=src)

    legs: list[Leg] = []
    put_d = base + delta_tilt
    call_d = base - delta_tilt

    if spec.key == "short_put":
        legs = [leg("put", "short", K(put_d, "put"))]
    elif spec.key == "short_call":
        legs = [leg("call", "short", K(call_d, "call"))]
    elif spec.key == "short_strangle":
        legs = [leg("put", "short", K(put_d, "put")),
                leg("call", "short", K(call_d, "call"))]
    elif spec.key == "put_credit_spread":
        short_k = K(put_d, "put")
        legs = [leg("put", "short", short_k),
                leg("put", "long", short_k - _wing(S, inc))]
    elif spec.key == "call_credit_spread":
        short_k = K(call_d, "call")
        legs = [leg("call", "short", short_k),
                leg("call", "long", short_k + _wing(S, inc))]
    elif spec.key in ("iron_condor", "wide_iron_condor", "skewed_iron_condor"):
        w = _wing(S, inc) * (1.5 if spec.key == "wide_iron_condor" else 1.0)
        sp, sc = K(put_d, "put"), K(call_d, "call")
        legs = [leg("put", "short", sp), leg("put", "long", sp - w),
                leg("call", "short", sc), leg("call", "long", sc + w)]
    elif spec.key == "calendar":
        # Sell the near cycle, own the far cycle at the same strike. The
        # position is long vega and long theta only because the two legs
        # sit on different clocks.
        k = pricing.round_to_increment(S, inc)
        legs = [leg("put", "short", k),
                leg("put", "long", k, leg_dte=dte + 30)]
    else:
        legs = [leg("put", "short", K(put_d, "put"))]

    credit = sum(-l.sign * l.price for l in legs)
    return legs, credit


def _wing(S: float, inc: float) -> float:
    """Spread width: roughly 3-5% of spot, snapped to the strike grid."""
    return max(inc * 2, pricing.round_to_increment(S * 0.045, inc))


# --------------------------------------------------------------------------
# Directional assumptions
# --------------------------------------------------------------------------

def assign_biases(snaps: dict[str, UnderlyingSnapshot],
                  corr: dict[str, dict[str, float]]) -> dict[str, str]:
    """
    Spread directional assumptions across the book so the deltas partially
    cancel before any explicit hedging. Highly-correlated equity names get
    opposing biases; genuinely uncorrelated sleeves stay neutral.
    """
    biases: dict[str, str] = {}
    equity = [s for s in snaps if snaps[s].instrument.asset_class in
              ("us_large_cap", "us_tech", "us_small_cap", "semiconductors",
               "china_equity")]
    equity.sort(key=lambda s: snaps[s].iv_rank, reverse=True)

    for i, sym in enumerate(equity):
        snap = snaps[sym]
        if snap.iv_rank >= 60:
            biases[sym] = "neutral"
        else:
            biases[sym] = "bearish" if i % 2 == 0 else "bullish"

    for sym, snap in snaps.items():
        if sym in biases:
            continue
        ac = snap.instrument.asset_class
        if ac == "long_duration_rates":
            biases[sym] = "bullish" if snap.iv_rank < 50 else "neutral"
        elif ac in ("precious_metals", "energy"):
            biases[sym] = "neutral"
        else:
            biases[sym] = "neutral"
    return biases


# --------------------------------------------------------------------------
# The builder
# --------------------------------------------------------------------------

def build_portfolio(snaps: dict[str, UnderlyingSnapshot],
                    corr: dict[str, dict[str, float]],
                    nlv: float = config.PORTFOLIO_NLV,
                    stance: str = "moderate",
                    r: float = config.RISK_FREE_RATE,
                    chains: dict[str, list[OptionQuote]] | None = None,
                    as_of: str | None = None) -> Portfolio:
    chains = chains or {}
    as_of = as_of or dt.date.today().isoformat()

    spy = snaps.get(config.BENCHMARK)
    spy_spot = spy.spot if spy else 1.0
    vix_proxy = round((spy.iv if spy else 0.15) * 100, 1)

    target_pct = config.deployment_target(vix_proxy, stance)
    budget = nlv * target_pct

    portfolio = Portfolio(nlv=nlv, as_of=as_of, vix_proxy=vix_proxy,
                          stance=stance, correlation_matrix=corr)
    portfolio._spy_spot = spy_spot

    biases = assign_biases(snaps, corr)
    tradables = [s for s, v in snaps.items()
                 if v.instrument.asset_class != "cash" and v.spot > 0
                 and s != "/MES"]

    # ---- sleeve budgets -------------------------------------------------
    sleeve_budget = {k: budget * v for k, v in config.SLEEVE_TARGETS.items()}

    # ---- 1. build one candidate position per underlying ------------------
    candidates: list[Position] = []
    for sym in tradables:
        snap = snaps[sym]
        inst = snap.instrument
        if inst.liquidity < config.MIN_LIQUIDITY_SCORE:
            portfolio.warnings.append(f"{sym} skipped: liquidity below threshold")
            continue

        others = [s for s in tradables if s != sym]
        c = risk.avg_correlation_to_book(sym, others, corr)

        # Undefined risk is only allowed where premium is genuinely rich and
        # the product is deep enough to defend.
        prefer_defined = not (snap.iv_rank >= 55 and inst.liquidity >= 4)
        spec = choose_strategy(snap, biases.get(sym, "neutral"), prefer_defined)

        dte = _pick_dte(sym, inst.kind)
        expiry = (dt.date.fromisoformat(as_of) + dt.timedelta(days=dte)).isoformat()
        legs, credit_pts = build_legs(spec, snap, dte, r, chains.get(sym))

        pos = Position(
            symbol=sym, strategy=spec.label, strategy_key=spec.key,
            sleeve=spec.sleeve, legs=legs, contracts=1, dte=dte, expiry=expiry,
            defined_risk=spec.defined_risk, correlation=c, notes=spec.rationale,
            data_quality="quote" if any(l.source == "quote" for l in legs) else "model",
        )
        for l in pos.legs:
            l.expiry = expiry
        pos.credit = credit_pts * inst.multiplier
        candidates.append(pos)

    # ---- 2. size to the sleeve budgets ----------------------------------
    kept: list[Position] = []
    for sleeve in ("options", "futures"):
        group = [p for p in candidates if p.sleeve == sleeve]
        if not group:
            continue
        per_trade = sleeve_budget[sleeve] / len(group)
        for pos in group:
            snap = snaps[pos.symbol]
            cap = _cap_for(pos) * budget

            unit_bpr = risk.position_bpr(pos, snap)

            # One full-size contract too big for the sizing cap? Step down to
            # the micro contract rather than dropping the asset class.
            if unit_bpr > cap and pos.symbol in config.MICRO_SUBSTITUTE:
                micro = config.MICRO_SUBSTITUTE[pos.symbol]
                snaps.setdefault(micro, _clone_snap(snap, micro))
                portfolio.warnings.append(
                    f"{pos.symbol} full-size contract needs ${unit_bpr:,.0f} "
                    f"(> {cap / budget:.0%} cap) — stepped down to {micro}.")
                pos.symbol = micro
                snap = snaps[micro]
                unit_bpr = risk.position_bpr(pos, snap)

            if unit_bpr <= 0:
                pos.contracts = 1
            elif unit_bpr > cap:
                portfolio.warnings.append(
                    f"{pos.symbol} dropped: one contract costs ${unit_bpr:,.0f}, "
                    f"above the ${cap:,.0f} per-trade cap.")
                continue
            else:
                n = max(1, int(per_trade // unit_bpr))
                pos.contracts = min(n, max(1, int(cap // unit_bpr)))

            _finalise(pos, snap, r)
            pos._unit_bpr = unit_bpr
            pos._cap = cap
            kept.append(pos)

    portfolio.positions = kept

    # ---- 2b. redistribute unused sleeve budget --------------------------
    # Equal-splitting leaves capital on the table whenever a position's unit
    # BPR does not divide evenly into its share. Walk the positions from
    # cheapest to most expensive and add contracts while budget and the
    # per-trade cap both allow it.
    for sleeve in ("options", "futures"):
        group = [p for p in portfolio.positions if p.sleeve == sleeve]
        if not group:
            continue
        used = sum(p.bpr for p in group)
        spare = sleeve_budget[sleeve] - used
        for pos in sorted(group, key=lambda p: p._unit_bpr):
            if spare <= 0:
                break
            unit, cap = pos._unit_bpr, pos._cap
            if unit <= 0:
                continue
            room = min(int(spare // unit), int((cap - pos.bpr) // unit))
            if room <= 0:
                continue
            pos.contracts += room
            snap = snaps[pos.symbol]
            before = pos.bpr
            _finalise(pos, snap, r)
            spare -= (pos.bpr - before)

    # ---- 3. stock sleeve: ETF shares used purely to shape delta ---------
    _add_stock_sleeve(portfolio, snaps, sleeve_budget["stocks"], r)

    # ---- 4. cash sleeve --------------------------------------------------
    deployed = portfolio.total_bpr
    portfolio.cash_positions = _cash_sleeve(nlv, deployed)

    # ---- 5. neutralise beta-weighted delta ------------------------------
    risk.rebase_beta_deltas(portfolio, spy_spot)
    _neutralise_delta(portfolio, snaps, r, spy_spot)
    risk.rebase_beta_deltas(portfolio, spy_spot)

    # ---- 6. final metrics ------------------------------------------------
    for pos in portfolio.positions:
        snap = snaps.get(pos.symbol)
        if snap is None:
            continue          # synthetic hedges (/MES) carry their own metrics
        pos.pop = risk.position_pop(pos, snap, r)
        pos.max_loss = risk.position_max_loss(pos, snap)

    if portfolio.bpr_pct > target_pct * 1.15:
        portfolio.warnings.append(
            f"Deployment {portfolio.bpr_pct:.1%} exceeds the {target_pct:.0%} "
            f"target for a {config.vix_regime(vix_proxy)}-vol regime.")

    return portfolio


def _cap_for(pos: Position) -> float:
    """Per-trade BPR cap as a fraction of the deployment budget."""
    if pos.strategy_key in ("calendar", "diagonal"):
        return config.MAX_BPR_DEBIT_STRUCTURE
    if not pos.defined_risk:
        return config.MAX_BPR_UNDEFINED_RISK
    return config.MAX_BPR_DEFINED_RISK


def _pick_dte(symbol: str, kind: str) -> int:
    """
    Stagger expirations so the book is not all rolling on the same day —
    the source material explicitly calls for diversifying expiration cycles.
    """
    base = config.TARGET_DTE
    offset = (hash(symbol) % 5 - 2) * 6      # -12 .. +12
    dte = base + offset
    if kind == "future":
        dte += 6
    return max(config.DTE_WINDOW[0], min(dte, config.DTE_WINDOW[1]))


def _finalise(pos: Position, snap: UnderlyingSnapshot, r: float) -> None:
    inst = snap.instrument
    credit_pts = sum(-l.sign * l.price for l in pos.legs)
    pos.credit = credit_pts * inst.multiplier * pos.contracts
    pos.bpr = risk.position_bpr(pos, snap)
    risk.compute_position_greeks(pos, snap, r)
    pos.pop = risk.position_pop(pos, snap, r)
    pos.max_loss = risk.position_max_loss(pos, snap)


def _add_stock_sleeve(portfolio: Portfolio, snaps: dict[str, UnderlyingSnapshot],
                      budget: float, r: float) -> None:
    """
    Outright ETF holdings in genuinely non-correlated sleeves. These carry
    the 20% stock allocation and give the book something to hedge against
    rather than pure short-premium exposure.
    """
    picks = [s for s in ("TLT", "FXI", "GLD") if s in snaps]
    if not picks:
        return
    each = budget / len(picks)
    for sym in picks:
        snap = snaps[sym]
        shares = int(each / (snap.spot * 0.5))     # 50% Reg-T initial
        if shares <= 0:
            continue
        pos = Position(
            symbol=sym, strategy="Long Shares", strategy_key="long_shares",
            sleeve="stocks", legs=[Leg("share", "long", 0.0, shares)],
            contracts=1, dte=0, expiry="—", defined_risk=True,
            notes="Outright holding in a non-correlated sleeve; also the "
                  "collateral against which short calls can be written.",
            data_quality="quote",
        )
        pos.bpr = shares * snap.spot * 0.5
        pos.credit = 0.0
        pos.pop = 0.5
        pos.max_loss = shares * snap.spot
        risk.compute_position_greeks(pos, snap, r)
        portfolio.positions.append(pos)


def _cash_sleeve(nlv: float, deployed: float) -> list[dict]:
    idle = max(0.0, nlv - deployed)
    return [
        {"symbol": "SGOV", "name": "iShares 0-3 Month Treasury", "amount": idle * 0.45,
         "role": "Yield on idle capital, T+1 liquid"},
        {"symbol": "BIL", "name": "SPDR 1-3 Month T-Bill", "amount": idle * 0.35,
         "role": "Yield on idle capital, second venue"},
        {"symbol": "CASH", "name": "Unswept cash", "amount": idle * 0.20,
         "role": "Same-day dry powder for adjustments and vol spikes"},
    ]


def _neutralise_delta(portfolio: Portfolio, snaps: dict[str, UnderlyingSnapshot],
                      r: float, spy_spot: float) -> None:
    """
    Drive total beta-weighted delta toward zero. Preference order:
      1. Solve for a single global strike tilt across the neutral
         premium-selling positions (bisection on total beta-delta).
      2. Add a micro E-mini S&P hedge for whatever residual remains.

    Tilting strikes is preferred over hedging because it keeps the theta
    while moving the delta; a futures hedge adds margin and no decay.
    """
    tiltable = [p for p in portfolio.positions
                if p.strategy_key in ("short_strangle", "iron_condor",
                                      "wide_iron_condor", "skewed_iron_condor")]
    tolerance = max(0.010 * portfolio.nlv / spy_spot, 8.0)

    if tiltable:
        def net_at(tilt: float) -> float:
            for pos in tiltable:
                snap = snaps[pos.symbol]
                spec = StrategySpec(pos.strategy_key, pos.strategy,
                                    pos.defined_risk, pos.sleeve, "neutral",
                                    pos.notes)
                legs, _ = build_legs(spec, snap, pos.dte, r, None,
                                     delta_tilt=tilt)
                for l in legs:
                    l.expiry = pos.expiry
                pos.legs = legs
                _finalise(pos, snap, r)
            risk.rebase_beta_deltas(portfolio, spy_spot)
            return portfolio.total_beta_delta

        lo, hi = -0.12, 0.12
        f_lo, f_hi = net_at(lo), net_at(hi)
        if f_lo * f_hi < 0:                     # a root exists in the bracket
            for _ in range(24):
                mid = (lo + hi) / 2.0
                f_mid = net_at(mid)
                if abs(f_mid) <= tolerance:
                    break
                if f_lo * f_mid < 0:
                    hi, f_hi = mid, f_mid
                else:
                    lo, f_lo = mid, f_mid
        else:                                   # clamp to the better endpoint
            net_at(lo if abs(f_lo) < abs(f_hi) else hi)

    # residual hedge with /MES — only if it genuinely reduces the exposure
    net = portfolio.total_beta_delta
    mes_delta_per_contract = 5.0 * _es_price(snaps, spy_spot) / spy_spot
    if abs(net) > tolerance and mes_delta_per_contract > 0:
        n = round(net / mes_delta_per_contract)
        if n != 0 and abs(net - n * mes_delta_per_contract) < abs(net):
            side = "short" if n > 0 else "long"
            qty = abs(int(n))
            pos = Position(
                symbol="/MES", strategy=f"{side.title()} {qty}x Micro E-mini S&P",
                strategy_key="futures_hedge", sleeve="futures",
                legs=[Leg("future", side, 0.0, qty)], contracts=1, dte=0,
                expiry="continuous", defined_risk=False, pop=0.5,
                notes="Delta ballast. Neutralises residual beta-weighted delta "
                      "without disturbing any premium-selling position.",
                data_quality="model",
            )
            pos.bpr = config.UNIVERSE["/MES"].margin_per_contract * qty
            pos.max_loss = math.inf
            snap = UnderlyingSnapshot("/MES", _es_price(snaps, spy_spot),
                                      snaps[config.BENCHMARK].iv if config.BENCHMARK in snaps else 0.15)
            risk.compute_position_greeks(pos, snap, r)
            portfolio.positions.append(pos)
            risk.rebase_beta_deltas(portfolio, spy_spot)

    # Fine trim with SPY shares. A micro E-mini moves delta in ~50-share
    # steps, which is too coarse to finish the job on a $300k book; shares
    # are 1 delta each and close the last gap exactly.
    net = portfolio.total_beta_delta
    if abs(net) >= 5 and config.BENCHMARK in snaps:
        qty = int(round(abs(net)))
        side = "short" if net > 0 else "long"
        spy_snap = snaps[config.BENCHMARK]
        pos = Position(
            symbol=config.BENCHMARK,
            strategy=f"{side.title()} {qty} SPY shares (delta trim)",
            strategy_key="share_hedge", sleeve="stocks",
            legs=[Leg("share", side, 0.0, qty)], contracts=1, dte=0,
            expiry="—", defined_risk=True, pop=0.5,
            notes="Residual delta trim. Shares move delta one unit at a time, "
                  "so they finish what the strike tilt and the /MES hedge "
                  "cannot resolve exactly.",
            data_quality="quote",
        )
        pos.bpr = qty * spy_snap.spot * 0.5
        pos.max_loss = qty * spy_snap.spot if side == "long" else math.inf
        risk.compute_position_greeks(pos, spy_snap, r)
        portfolio.positions.append(pos)


def _es_price(snaps: dict[str, UnderlyingSnapshot], spy_spot: float) -> float:
    """S&P index level implied by SPY (SPY tracks ~1/10 of the index)."""
    return spy_spot * 10.0


def _clone_snap(snap: UnderlyingSnapshot, symbol: str) -> UnderlyingSnapshot:
    """
    Micro contracts track the same underlying at the same price — only the
    contract multiplier differs — so the market snapshot carries over intact.
    """
    return UnderlyingSnapshot(
        symbol=symbol, spot=snap.spot, iv=snap.iv, hv=snap.hv,
        iv_pct_13w=snap.iv_pct_13w, iv_pct_26w=snap.iv_pct_26w,
        iv_pct_52w=snap.iv_pct_52w, prior_close=snap.prior_close,
        volume=snap.volume, source=f"{snap.source} (via {snap.symbol})",
        as_of=snap.as_of)
