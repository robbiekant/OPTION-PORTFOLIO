"""Generates the rules, philosophy and trade-management HTML rulebook."""
from __future__ import annotations

import datetime as dt
from pathlib import Path

from . import config
from .theme import page

SOURCES = [
    ("6 Steps To Build An Options Portfolio From Scratch", "tastylive",
     "Chandler / Butler / McGaragle / Batista / Mulmat / Sosnoff"),
    ("The Blueprint to Tom Sosnoff's Ideal Portfolio in 2025", "tastylive",
     "Tom Sosnoff"),
    ("Best and Worst $100k+ Portfolio Strategies", "tastylive", "model portfolio"),
    ("Stop Chasing Options Strategies. Build This Instead", "Theta Profits", "Roman"),
]

PHILOSOPHY = [
    ("The edge is portfolio construction, not strategy selection",
     "There is no secret structure. Iron condors on FXI, XOP and SPY all test out "
     "to roughly the same 74-80% success rate. What separates a book that compounds "
     "from one that blows up is how the positions sit together: total beta-weighted "
     "delta near zero, assets that do not move together, and capital small enough "
     "that no single outcome matters.",
     "Product indifference tested across underlyings"),
    ("Be product indifferent",
     "You are not a gold trader or a bond trader. You are a seller of overpriced "
     "optionality wherever it appears. If the volatility is in soybeans this month, "
     "trade soybeans. If a full-size contract is too large, step down to the micro. "
     "The underlying matters far less than whether its premium is rich and its "
     "market is liquid.",
     "McGaragle, step 3"),
    ("Sell time, hedge direction",
     "Theta is the return stream. Delta is the risk you neutralise so that the "
     "theta can actually be collected. A book that is long 113 beta-weighted deltas "
     "is not a theta book — it is a leveraged equity position wearing a costume.",
     "Roman: manage total beta-weighted delta, harvest theta"),
    ("Volatility is mean reverting; price is not",
     "Sell premium when implied volatility is high relative to its own history and "
     "to what the underlying actually realises. That edge is statistical and repeats. "
     "A directional view is neither.",
     "Batista, step 4"),
    ("Non-correlation is the only free lunch",
     "Mixing indices, commodities, currencies and international equities takes book "
     "correlation down toward 0.3. At that level portfolio volatility drops roughly "
     "35% and single-event outlier risk is largely designed out — without giving up "
     "any premium.",
     "Sosnoff @18:39"),
    ("Occurrences, not conviction",
     "A 70%-probability trade means nothing over five occurrences and almost "
     "everything over five hundred. Trading small is what buys you enough "
     "occurrences for the probabilities to actually show up.",
     "Butler, step 2 / Sosnoff @53:33"),
    ("Over-allocation is the one fatal error",
     "Sosnoff names it directly: allocating too much capital is the number one "
     "reason traders blow up. Every other rule here is recoverable. This one is not.",
     "Sosnoff @44:42"),
]

MECHANICS = [
    ("Entry window: 45 DTE",
     f"Enter around {config.TARGET_DTE} days to expiration — acceptable range "
     f"{config.DTE_WINDOW[0]}-{config.DTE_WINDOW[1]} DTE. Roughly 75% of the money "
     "made in time decay happens between here and the management point.",
     "Sosnoff @26:10"),
    ("Management point: 21 DTE",
     f"At {config.MANAGE_DTE} DTE you close, roll or defend. No exceptions. Gamma "
     "risk past this point rises faster than the remaining theta compensates for.",
     "Batista / Sosnoff"),
    ("Profit target: 50% of credit",
     f"Close winners at {config.PROFIT_TARGET_UNDEFINED:.0%} of the credit received. "
     "Do not let winners run — closing early captures the fastest rate of return, "
     "clears the risk and frees the capital to be redeployed.",
     "Batista: manage winners"),
    ("Loss discipline",
     f"Defined risk: stop at {config.LOSS_MULTIPLE_DEFINED:.0f}x the credit received. "
     f"Undefined risk: {config.LOSS_MULTIPLE_UNDEFINED:.1f}x. A short strike reaching "
     f"{config.TESTED_DELTA_TRIGGER:.0%} delta forces a decision — roll out, roll "
     "down, add the opposite side, or close.",
     "Control your knowns before entry"),
    ("Strike selection is expected move, not opinion",
     "Delta is interchangeable with expected move. Knowing the 45-day expected move "
     "gives you a mechanical framework for where the short strikes belong — no view "
     "required.",
     "Sosnoff @28:47"),
    ("Redeploy roughly 8 times a year",
     "Capital that comes back at 21 DTE goes straight back to work. Eight turns a "
     "year at this credit level is what converts a 2%-a-month gross into a 22-31% "
     "annual target — the multiple over the risk-free rate that justifies the "
     "effort at all.",
     "Sosnoff: target ROI"),
]

MANAGEMENT = [
    ("Daily", "Re-check total beta-weighted delta. If it has drifted outside "
     "the neutral band, re-centre it — roll the tested side, or add/remove a "
     "micro futures hedge. Do not let a directional position accumulate by accident."),
    ("On a tested short strike (delta > 30)",
     "First choice: roll the untested side closer to collect more credit and "
     "re-centre delta. Second: roll the tested strike out in time for a credit. "
     "Third: close. Never add size to defend a loser."),
    ("On a 50% winner", "Close it. Redeploy into whatever now has the highest "
     "IV rank, subject to the correlation gate."),
    ("At 21 DTE", "Close or roll regardless of P/L. This is a calendar rule, "
     "not a discretionary one."),
    ("On a volatility spike (VIX up 50%+)",
     "This is the opportunity, not the emergency — provided sizing was right. "
     "The deployment table scales UP in high vol. Use the cash sleeve to sell "
     "the richer premium; do not panic-close the existing book."),
    ("On a correlation regime shift",
     "When everything starts moving together, the diversification benefit is gone. "
     "Cut gross exposure rather than trusting a correlation number computed in "
     "calmer conditions."),
]


def _phil_rows(items):
    return "".join(
        f'<div class="rule"><div class="n">{i:02d}</div><div class="b">'
        f'<div class="t">{t}</div><div class="d">{d}</div>'
        f'<div class="src">{s}</div></div></div>'
        for i, (t, d, s) in enumerate(items, 1))


def _vix_table() -> str:
    rows = ""
    for b in config.VIX_BANDS:
        hi = "40+" if b.vix_high > 90 else f"{b.vix_high:.0f}"
        rows += (f"<tr><td class='l sym'>{b.vix_low:.0f}–{hi}</td>"
                 f"<td class='l'>{b.name}</td>"
                 f"<td>{b.conservative:.0%}</td><td>{b.moderate:.0%}</td>"
                 f"<td>{b.aggressive:.0%}</td>"
                 f"<td>${config.PORTFOLIO_NLV * b.moderate:,.0f}</td></tr>")
    return f"""<table><thead><tr><th class="l">VIX</th><th class="l">Regime</th>
<th>Conservative</th><th>Moderate</th><th>Aggressive</th>
<th>Moderate on $300k</th></tr></thead><tbody>{rows}</tbody></table>"""


def _sizing_table() -> str:
    r = [("Single defined-risk trade", f"1% – {config.MAX_BPR_DEFINED_RISK:.0%} of buying power",
          "Spreads, condors, calendars"),
         ("Single undefined-risk trade", f"1% – {config.MAX_BPR_UNDEFINED_RISK:.0%} of buying power",
          "Naked puts/calls, strangles"),
         ("Max loss per trade", f"{config.MAX_LOSS_PER_TRADE_PCT:.0%} of net liq",
          "Hard ceiling on any single outcome"),
         ("Default trade size", "1 contract", "Take risk by widening, not by adding size"),
         ("Positions per underlying", str(config.MAX_POSITIONS_PER_UNDERLYING),
          "One expression per asset at a time"),
         ("Book correlation", f"below {config.MAX_PORTFOLIO_CORRELATION}",
          "Average pairwise absolute correlation"),
         ("Any single pair", f"below {config.MAX_PAIR_CORRELATION}",
          "Refuse the second leg above this"),
         ("Liquidity", f"{config.MIN_LIQUIDITY_SCORE}+ of 4 stars",
          f"Bid/ask under {config.MAX_BID_ASK_PCT:.0%} of mid, real open interest")]
    rows = "".join(f"<tr><td class='l sym'>{a}</td><td class='l'>{b}</td>"
                   f"<td class='l muted'>{c}</td></tr>" for a, b, c in r)
    return (f"<table><thead><tr><th class='l'>Constraint</th><th class='l'>Limit</th>"
            f"<th class='l'>Why</th></tr></thead><tbody>{rows}</tbody></table>")


def _sleeve_table() -> str:
    desc = {"options": "ETF and index options — defined and undefined risk. "
                       "The engine room of the book.",
            "futures": "Futures and futures options. Capital-efficient access to "
                       "genuinely uncorrelated markets; also the delta hedge.",
            "stocks": "Outright ETF holdings. Delta shaping, hedges, and collateral "
                      "where the derivative is illiquid.",
            "cash": "Held back deliberately. Dry powder for adjustments and for the "
                    "volatility spikes that are the whole point of the strategy."}
    rows = ""
    for k, v in config.SLEEVE_TARGETS.items():
        rows += (f"<tr><td class='l sym'>{k.title()}</td><td>{v:.0%}</td>"
                 f"<td class='l muted'>{desc[k]}</td></tr>")
    return (f"<table><thead><tr><th class='l'>Sleeve</th><th>Target</th>"
            f"<th class='l'>Role</th></tr></thead><tbody>{rows}</tbody></table>")


def _strategy_table() -> str:
    rows = [
        ("IVR 60+", "Short strangle / naked put / naked call", "Undefined",
         "Premium is rich enough to justify uncapped tails"),
        ("IVR 45–60", "Iron condor / credit spread", "Defined",
         "Still worth selling, but cap the tail"),
        ("IVR 25–45", "Wide iron condor / small credit spread", "Defined",
         "Widen wings — premium is thinner, so is the cushion"),
        ("IVR under 25", "Calendar / diagonal, or stand aside", "Defined",
         "Vol is cheap; owning it beats selling it"),
    ]
    body = "".join(
        f"<tr><td class='l sym'>{a}</td><td class='l'>{b}</td>"
        f"<td><span class='pill'>{c}</span></td><td class='l muted'>{d}</td></tr>"
        for a, b, c, d in rows)
    dl = "".join(f"<tr><td class='l'>{k.replace('_',' ').title()}</td>"
                 f"<td>{v:.2f}</td></tr>"
                 for k, v in sorted(config.DEFAULT_SHORT_DELTA.items()))
    return f"""<div class="grid g2">
<div class="card"><h3>Structure by volatility state</h3>
<table><thead><tr><th class="l">IV Rank</th><th class="l">Structure</th>
<th>Risk</th><th class="l">Rationale</th></tr></thead><tbody>{body}</tbody></table></div>
<div class="card"><h3>Default short-strike deltas</h3>
<p class="small">Calibrated so the book's BPR-weighted probability of profit lands
inside the {config.PORTFOLIO_POP_TARGET[0]:.0%}–{config.PORTFOLIO_POP_TARGET[1]:.0%}
band. A book running at 85% POP is under-collecting for the capital it ties up.</p>
<table><thead><tr><th class="l">Structure</th><th>Short Δ</th></tr></thead>
<tbody>{dl}</tbody></table></div></div>"""


def build_html() -> str:
    src = "".join(
        f"<tr><td class='l sym'>{t}</td><td class='l'>{ch}</td>"
        f"<td class='l muted'>{who}</td></tr>" for t, ch, who in SOURCES)

    mgmt = "".join(
        f'<div class="rule"><div class="n">▸</div><div class="b">'
        f'<div class="t">{w}</div><div class="d">{d}</div></div></div>'
        for w, d in MANAGEMENT)

    lo, hi = config.PORTFOLIO_POP_TARGET
    tlo, thi = config.THETA_TARGET_PCT

    body = f"""
<header class="masthead">
  <div><div class="brand">ThetaForge — Rulebook</div>
  <h1>Delta-Neutral Theta Harvesting</h1>
  <p class="small muted" style="margin-top:6px">Philosophy, restrictions and
  trade management for an ETF &amp; futures options portfolio</p></div>
  <div class="stamp">Generated {dt.date.today().isoformat()}<br>
  Portfolio ${config.PORTFOLIO_NLV:,.0f}<br>ETFs &amp; futures only</div>
</header>

<div class="grid g4" style="margin-top:22px">
  <div class="tile accent"><div class="lab">Objective</div>
    <div class="val">~2%<span style="font-size:14px">/mo</span></div>
    <div class="sub">at the lowest drawdown the structure allows</div></div>
  <div class="tile"><div class="lab">Book POP target</div>
    <div class="val">{lo:.0%}–{hi:.0%}</div>
    <div class="sub">BPR-weighted, not per trade</div></div>
  <div class="tile"><div class="lab">Daily theta target</div>
    <div class="val">{tlo:.1%}–{thi:.1%}</div>
    <div class="sub">of net liquidating value</div></div>
  <div class="tile"><div class="lab">Beta-weighted delta</div>
    <div class="val">≈ 0</div>
    <div class="sub">the number that defines the strategy</div></div>
</div>

<h2>1 · Philosophy</h2>
<div class="card">{_phil_rows(PHILOSOPHY)}</div>

<h2>2 · Capital allocation</h2>
<p>Two independent decisions: <strong>how much</strong> of the account is at work,
and <strong>how it is split</strong> across product types. The first is a function
of the volatility regime; the second is fixed.</p>
<div class="grid g2">
  <div class="card"><h3>How much — scaled to the VIX</h3>
  <p class="small">Deployment means buying power reduction, which is not the same
  as risk. In low volatility there is simply less premium to collect, so committing
  more capital buys more exposure without buying more edge.</p>
  {_vix_table()}</div>
  <div class="card"><h3>How it is split — the sleeves</h3>
  <p class="small">Percentages are of deployed buying power, not of net liq.</p>
  {_sleeve_table()}</div>
</div>

<h2>3 · Restrictions</h2>
<div class="grid g2">
  <div class="card"><h3>Sizing and gates</h3>{_sizing_table()}</div>
  <div class="card"><h3>Universe restrictions</h3>
  <p>Liquid ETFs, index products and futures only. <strong>No single-name equity
  risk.</strong> A single stock carries idiosyncratic event risk — earnings,
  guidance, litigation, a CEO — that no amount of portfolio-level delta management
  can hedge, and that is not compensated in the premium.</p>
  <h4>Required diversification</h4>
  <p class="small">The book must span these asset classes so that correlation stays
  structurally low rather than accidentally low:</p>
  <div class="legend">{''.join(f'<span><span class="swatch" style="background:var(--series-{(i % 4) + 1})"></span>{c.replace("_", " ")}</span>' for i, c in enumerate(config.DIVERSIFICATION_TARGETS))}</div>
  <div class="note">A position is rejected outright when its average absolute
  correlation to the existing book exceeds {config.MAX_PAIR_CORRELATION}, however
  attractive the premium. Correlated premium is the same trade twice.</div></div>
</div>

<h2>4 · Trade mechanics</h2>
<div class="card">{_phil_rows(MECHANICS)}</div>
{_strategy_table()}

<h2>5 · Trade management protocol</h2>
<div class="card">{mgmt}</div>
<div class="note crit"><strong>The one rule that is not negotiable:</strong>
size. Every other rule here has a recovery path. Over-allocation does not —
it is the single most common cause of a blown account, and it is entirely
self-inflicted.</div>

<h2>6 · What "2% a month" actually requires</h2>
<div class="card">
<p>The arithmetic behind the objective, so the target is not mistaken for a promise:</p>
<div class="grid g3" style="margin:16px 0">
  <div class="tile"><div class="lab">Gross credit collected</div>
    <div class="val" style="font-size:20px">100%</div>
    <div class="sub">premium sold across the book at entry</div></div>
  <div class="tile"><div class="lab">Retained after management</div>
    <div class="val" style="font-size:20px">~25%</div>
    <div class="sub">the conservative retention assumption</div></div>
  <div class="tile"><div class="lab">Turns per year</div>
    <div class="val" style="font-size:20px">~8</div>
    <div class="sub">45 DTE in, 21 DTE out, redeploy</div></div>
</div>
<p>Retaining about a quarter of the premium sold yields a baseline near 1.75% a
month with prices and volatility flat. Eight redeployments a year compound that
toward the 22–31% annual band. The gap between 1.75% and 2% is closed by
<em>management</em> — taking winners at 50%, rolling tested sides for credit,
and selling into volatility expansions — not by selling more premium.</p>
<div class="note">Drawdown control comes from three places and none of them is
prediction: correlation near 0.3 (cuts portfolio volatility ~35%), beta-weighted
delta near zero (removes the market's direction from the P/L), and sizing small
enough that the worst single position cannot matter.</div>
</div>

<h2>7 · Sources</h2>
<div class="card"><table><thead><tr><th class="l">Video</th><th class="l">Channel</th>
<th class="l">Presenter</th></tr></thead><tbody>{src}</tbody></table></div>

<footer>
ThetaForge rulebook · generated {dt.datetime.now().isoformat(timespec='seconds')}<br>
This document encodes a trading methodology drawn from the sources above. It is
educational material, not investment advice. Options carry risk of substantial
loss; undefined-risk positions can lose more than the capital committed to them.
</footer>"""
    return page("ThetaForge — Rulebook", body)


def write_report(path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(build_html(), encoding="utf-8")
    return path
