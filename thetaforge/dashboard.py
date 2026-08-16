"""Generates the portfolio dashboard HTML."""
from __future__ import annotations

import datetime as dt
import math
from pathlib import Path

from . import config, risk
from .models import Portfolio, UnderlyingSnapshot
from .theme import diverging, page

SLEEVE_ORDER = ["options", "futures", "stocks"]
SLEEVE_LABEL = {"options": "Listed ETF &amp; index options",
                "futures": "Futures &amp; futures options",
                "stocks": "Outright ETF holdings &amp; delta trim"}


def _money(v: float, dp: int = 0) -> str:
    if v is None or (isinstance(v, float) and math.isinf(v)):
        return "undef"
    return f"{v:,.{dp}f}"


def _signed(v: float, dp: int = 1) -> str:
    """Green/red — reserved for quantities where the sign really is good or bad."""
    cls = "pos" if v > 0 else ("neg" if v < 0 else "muted")
    return f'<span class="{cls}">{v:+,.{dp}f}</span>'


def _directional(v: float, dp: int = 1) -> str:
    """
    Blue/orange for quantities where the sign means direction, not quality.
    A negative delta is not a bad delta — using green/red here would imply a
    judgement the number does not carry. Matches the correlation heatmap:
    blue is negative, warm is positive.
    """
    if abs(v) < 0.05:
        return f'<span class="muted">{v:+,.{dp}f}</span>'
    colour = "var(--series-2)" if v > 0 else "var(--series-1)"
    return f'<span style="color:{colour}">{v:+,.{dp}f}</span>'


def _position_rows(pf: Portfolio, snaps: dict[str, UnderlyingSnapshot]) -> str:
    out = ""
    for sleeve in SLEEVE_ORDER:
        rows = [p for p in pf.positions if p.sleeve == sleeve]
        if not rows:
            continue
        sub_bpr = sum(p.bpr for p in rows)
        out += (f'<tr class="sleeve-row"><td colspan="13">{SLEEVE_LABEL[sleeve]}'
                f' — ${_money(sub_bpr)} BPR, '
                f'{sub_bpr / (pf.total_bpr or 1):.0%} of deployed</td></tr>')
        for p in sorted(rows, key=lambda x: -x.bpr):
            snap = snaps.get(p.symbol)
            ivr = f"{snap.iv_rank:.0f}" if snap else "—"
            iv = f"{snap.iv:.0%}" if snap else "—"
            ml = ("undef" if math.isinf(p.max_loss) else f"${_money(p.max_loss)}")
            mult = "" if p.contracts == 1 else f" <span class='muted'>({p.contracts}X)</span>"
            out += f"""<tr>
<td class="l sym">{p.symbol}</td>
<td>{ivr}</td>
<td class="l">{p.strategy}{mult}</td>
<td class="l muted">{p.strikes()}</td>
<td>${_money(p.bpr)}</td>
<td>{p.pop:.0%}</td>
<td>${_money(p.credit)}</td>
<td>{_directional(p.beta_delta)}</td>
<td>{p.correlation:.2f}</td>
<td>{p.dte if p.dte else '—'}</td>
<td>{iv}</td>
<td>{_signed(p.theta, 0)}</td>
<td>{ml}</td></tr>"""
    return out


def _totals_row(pf: Portfolio) -> str:
    return f"""<tr class="total">
<td class="l">TOTAL</td><td></td><td class="l">{len(pf.positions)} positions</td>
<td></td><td>${_money(pf.total_bpr)}</td><td>{pf.portfolio_pop:.0%}</td>
<td>${_money(pf.total_credit)}</td><td>{_directional(pf.total_beta_delta)}</td>
<td>{pf.avg_correlation:.2f}</td><td></td><td></td>
<td>{_signed(pf.total_theta, 0)}</td><td></td></tr>"""


def _hbars(items: list[tuple[str, float]], fmt, diverge: bool = False,
           palette: tuple[str, str] = ("var(--pos)", "var(--neg)")) -> str:
    if not items:
        return ""
    vmax = max(abs(v) for _, v in items) or 1.0
    out = ""
    for name, v in items:
        if diverge:
            w = abs(v) / vmax * 50
            left = 50 if v >= 0 else 50 - w
            colour = (palette[0] if v >= 0 else palette[1])
            bar = (f'<div class="fill" style="left:{left}%;width:{w}%;'
                   f'background:{colour}"></div><div class="axis0" '
                   f'style="left:50%"></div>')
        else:
            w = abs(v) / vmax * 100
            bar = (f'<div class="fill" style="left:0;width:{w}%;'
                   f'background:var(--series-1)"></div>')
        out += (f'<div class="hbar"><div class="name">{name}</div>'
                f'<div class="track">{bar}</div>'
                f'<div class="num">{fmt(v)}</div></div>')
    return out


def _heatmap(corr: dict, symbols: list[str]) -> str:
    syms = [s for s in symbols if s in corr]
    if len(syms) < 2:
        return "<p class='muted small'>Not enough series for a correlation matrix.</p>"
    head = "<tr><th></th>" + "".join(f"<th>{s}</th>" for s in syms) + "</tr>"
    body = ""
    for a in syms:
        cells = ""
        for b in syms:
            v = corr[a].get(b, 0.0)
            bg = "#4a4a46" if a == b else diverging(v, 1.0)
            cells += f'<td style="background:{bg}" title="{a} vs {b}: {v:+.2f}">{v:+.2f}</td>'
        body += f'<tr><th>{a}</th>{cells}</tr>'
    return f'<table class="heat">{head}{body}</table>'


def _audit_rows(pf: Portfolio) -> str:
    out = ""
    for row in risk.audit(pf):
        ok = row["status"] == "pass"
        out += (f'<div class="check"><div class="ic {"p" if ok else "w"}">'
                f'{"✓" if ok else "!"}</div>'
                f'<div class="nm">{row["check"]}</div>'
                f'<div class="dt">{row["detail"]}</div>'
                f'<div class="rl">{row["rule"]}</div></div>')
    return out


def _underlying_rows(snaps: dict[str, UnderlyingSnapshot],
                     pf: Portfolio) -> str:
    traded = {p.symbol for p in pf.positions}
    out = ""
    for sym, s in sorted(snaps.items(), key=lambda kv: -kv[1].iv_rank):
        prem = s.iv_premium
        verdict = ("sell premium" if s.iv_rank >= 45 and prem > 0
                   else "own premium" if s.iv_rank < 25
                   else "selective")
        chg = ((s.spot / s.prior_close - 1) if s.prior_close else 0.0)
        out += f"""<tr>
<td class="l sym">{sym}</td>
<td class="l muted">{s.instrument.asset_class.replace('_', ' ')}</td>
<td>{s.spot:,.2f}</td>
<td>{_directional(chg * 100, 2)}%</td>
<td>{s.iv:.1%}</td><td>{s.hv:.1%}</td>
<td>{_directional(prem * 100, 1)}</td>
<td>{s.iv_rank:.0f}</td>
<td class="l">{verdict}</td>
<td>{'yes' if sym in traded else '<span class="muted">—</span>'}</td></tr>"""
    return out


def build_html(pf: Portfolio, snaps: dict[str, UnderlyingSnapshot],
               corr: dict, corr_src: str) -> str:
    target = config.deployment_target(pf.vix_proxy, pf.stance)
    regime = config.vix_regime(pf.vix_proxy)
    idle = pf.nlv - pf.total_bpr
    mo_credit = pf.total_theta * 30
    retain = pf.total_credit * 0.25

    quality = {}
    for p in pf.positions:
        quality[p.data_quality] = quality.get(p.data_quality, 0) + 1
    qual_note = ", ".join(f"{v} {k}-priced" for k, v in quality.items())

    sleeves = pf.sleeve_bpr()
    sleeve_items = [(k, sleeves.get(k, 0.0)) for k in SLEEVE_ORDER]
    delta_items = [(p.symbol, p.beta_delta) for p in
                   sorted(pf.positions, key=lambda x: -abs(x.beta_delta))[:10]]
    theta_items = [(p.symbol, p.theta) for p in
                   sorted(pf.positions, key=lambda x: -abs(x.theta))[:10]
                   if abs(p.theta) > 0.5]

    cash_rows = "".join(
        f"<tr><td class='l sym'>{c['symbol']}</td><td class='l'>{c['name']}</td>"
        f"<td>${_money(c['amount'])}</td><td class='l muted'>{c['role']}</td></tr>"
        for c in pf.cash_positions)

    warn_html = ""
    if pf.warnings:
        warn_html = "".join(f'<div class="note">{w}</div>' for w in pf.warnings)

    sigma = pf.daily_pl_sigma(snaps)
    swing = pf.daily_pl_swing(0.01)

    body = f"""
<header class="masthead">
  <div><div class="brand">ThetaForge — Portfolio</div>
  <h1>Delta-Neutral Theta Book</h1>
  <p class="small muted" style="margin-top:6px">ETFs &amp; futures only ·
  {pf.stance} stance · {regime}-volatility regime</p></div>
  <div class="stamp">Snapshot {pf.as_of}<br>
  Net liq ${_money(pf.nlv)}<br>
  Vol proxy {pf.vix_proxy} (SPY 30d IV)</div>
</header>

<div class="grid g5" style="margin-top:22px">
  <div class="tile accent"><div class="lab">Buying power used</div>
    <div class="val">{pf.bpr_pct:.1%}</div>
    <div class="sub">${_money(pf.total_bpr)} of ${_money(pf.nlv)} · target {target:.0%}</div></div>
  <div class="tile"><div class="lab">Beta-weighted delta</div>
    <div class="val">{pf.total_beta_delta:+.1f}</div>
    <div class="sub">${_money(pf.spy_notional_equiv)} SPY-equivalent</div></div>
  <div class="tile"><div class="lab">Theta per day</div>
    <div class="val">${_money(pf.total_theta)}</div>
    <div class="sub">{pf.theta_pct:.3%} of net liq</div></div>
  <div class="tile"><div class="lab">Portfolio POP</div>
    <div class="val">{pf.portfolio_pop:.0%}</div>
    <div class="sub">BPR-weighted · target {config.PORTFOLIO_POP_TARGET[0]:.0%}–{config.PORTFOLIO_POP_TARGET[1]:.0%}</div></div>
  <div class="tile"><div class="lab">Book correlation</div>
    <div class="val">{pf.avg_correlation:.2f}</div>
    <div class="sub">avg pairwise · ceiling {config.MAX_PORTFOLIO_CORRELATION}</div></div>
</div>

<div class="grid g5" style="margin-top:12px">
  <div class="tile"><div class="lab">Credit collected</div>
    <div class="val" style="font-size:20px">${_money(pf.total_credit)}</div>
    <div class="sub">{pf.total_credit / pf.nlv:.2%} of net liq at entry</div></div>
  <div class="tile"><div class="lab">Vega</div>
    <div class="val" style="font-size:20px">${_money(pf.total_vega)}</div>
    <div class="sub">P/L per 1 point of IV</div></div>
  <div class="tile"><div class="lab">Theta over 30 days</div>
    <div class="val" style="font-size:20px">${_money(mo_credit)}</div>
    <div class="sub">{mo_credit / pf.nlv:.2%} if held flat</div></div>
  <div class="tile"><div class="lab">Expected retention</div>
    <div class="val" style="font-size:20px">${_money(retain)}</div>
    <div class="sub">25% of credit · {retain / pf.nlv:.2%} monthly</div></div>
  <div class="tile"><div class="lab">1σ daily P/L</div>
    <div class="val" style="font-size:20px">±${_money(sigma)}</div>
    <div class="sub">{sigma / pf.nlv:.2%} of net liq · full portfolio variance</div></div>
</div>

{warn_html}

<h2>Positions</h2>
<p class="small muted">Strikes are the actual listed increments for each product.
Credit and greeks are per position including the contract multiplier.
Data quality: {qual_note}.</p>
<div class="card" style="overflow-x:auto">
<table>
<thead><tr>
<th class="l">Asset</th>
<th><span class="tip" data-tip="IV Rank: where current implied volatility sits within its own 52-week range. Above 45 favours selling premium.">IVR</span></th>
<th class="l">Strategy</th><th class="l">Strikes</th>
<th><span class="tip" data-tip="Buying power reduction — the capital the broker holds against the position. Not the same as risk.">BPR</span></th>
<th><span class="tip" data-tip="Probability of profit at expiration, measured to the breakevens rather than the strikes.">POP</span></th>
<th>Credit</th>
<th><span class="tip" data-tip="Position delta converted into SPY-share equivalents using the underlying's beta. This is the number that must sum to about zero.">SPY Δ</span></th>
<th><span class="tip" data-tip="Average absolute correlation of this underlying to the rest of the book.">Corr</span></th>
<th>DTE</th><th>IV</th>
<th><span class="tip" data-tip="Dollars of time decay this position earns per calendar day.">Θ/day</span></th>
<th>Max loss</th>
</tr></thead>
<tbody>{_position_rows(pf, snaps)}{_totals_row(pf)}</tbody></table></div>

<h2>Cash sleeve</h2>
<div class="card">
<p class="small">${_money(idle)} is not committed to buying power reduction. It is
not idle by accident — it is the reserve that lets the book scale <em>into</em> a
volatility spike rather than being forced out of one.</p>
<table><thead><tr><th class="l">Symbol</th><th class="l">Instrument</th>
<th>Amount</th><th class="l">Role</th></tr></thead>
<tbody>{cash_rows}</tbody></table></div>

<h2>Risk decomposition</h2>
<div class="grid g3">
  <div class="card"><h3>Capital by sleeve</h3>
  <p class="small muted">Target 50 / 20 / 20 with 10% held in cash.</p>
  {_hbars(sleeve_items, lambda v: f"${_money(v)}")}</div>

  <div class="card"><h3>Beta-weighted delta by position</h3>
  <p class="small muted">Longs and shorts offset to roughly zero — this is the
  mechanism, not a coincidence.</p>
  {_hbars(delta_items, lambda v: f"{v:+.1f}", diverge=True, palette=("var(--series-2)", "var(--series-1)"))}</div>

  <div class="card"><h3>Theta contribution</h3>
  <p class="small muted">Dollars of decay per day, per position.</p>
  {_hbars(theta_items, lambda v: f"${v:+,.0f}", diverge=True)}</div>
</div>

<h2>Correlation matrix</h2>
<div class="card">
<p class="small">Source: {corr_src}. Red is positive co-movement, blue is negative,
grey is independence. The book's average pairwise absolute correlation is
<strong>{pf.avg_correlation:.2f}</strong> against a ceiling of
{config.MAX_PORTFOLIO_CORRELATION} — low enough that portfolio volatility is
materially below the sum of its parts.</p>
<div class="legend">
  <span><span class="swatch" style="background:#3987e5"></span>−1.0 inverse</span>
  <span><span class="swatch" style="background:#383835"></span>0.0 independent</span>
  <span><span class="swatch" style="background:#d03b3b"></span>+1.0 identical</span>
</div>
<div style="overflow-x:auto">{_heatmap(corr, list(snaps))}</div></div>

<h2>Universe — volatility state</h2>
<div class="card" style="overflow-x:auto">
<p class="small muted">IV premium is implied minus historical volatility. Positive
means options are pricing more movement than the underlying has actually been
delivering — that gap is the edge being harvested.</p>
<table><thead><tr>
<th class="l">Symbol</th><th class="l">Asset class</th><th>Spot</th><th>Chg</th>
<th>IV</th><th>HV</th><th>IV−HV</th><th>IVR</th>
<th class="l">Read</th><th>Traded</th></tr></thead>
<tbody>{_underlying_rows(snaps, pf)}</tbody></table></div>

<h2>Rulebook audit</h2>
<div class="card">{_audit_rows(pf)}</div>

<h2>Management calendar</h2>
<div class="card">
<div class="grid g3">
  <div><h4>Now</h4><p class="small">Enter at the strikes above. Work mid-price;
  do not pay the spread on entry.</p></div>
  <div><h4>Daily</h4><p class="small">Re-check beta-weighted delta. Re-centre if it
  drifts beyond ±{max(0.010 * pf.nlv / max(pf._spy_spot, 1), 8):.0f} SPY deltas.</p></div>
  <div><h4>At 50% of credit</h4><p class="small">Close the winner. Redeploy into the
  highest IVR name that passes the correlation gate.</p></div>
</div>
<div class="grid g3" style="margin-top:14px">
  <div><h4>On a 30-delta test</h4><p class="small">Roll the untested side first.
  Then roll out for credit. Then close. Never add size.</p></div>
  <div><h4>At {config.MANAGE_DTE} DTE</h4><p class="small">Close or roll regardless
  of P/L. Calendar rule, not a judgement call.</p></div>
  <div><h4>On a vol spike</h4><p class="small">Deploy the cash sleeve into the richer
  premium. The deployment table scales up, not down.</p></div>
</div></div>

<footer>
ThetaForge dashboard · snapshot {pf.as_of} · generated
{dt.datetime.now().isoformat(timespec='seconds')}<br>
Underlying prices, implied volatility, historical volatility and IV percentiles
sourced from Interactive Brokers. Option premiums marked "model" are priced with
Black-Scholes (Black-76 for futures options) off the live underlying IV with a
term-structure and skew adjustment; they refresh to live quotes on the next
gateway pull.<br>
Educational material, not investment advice. Undefined-risk positions marked
"undef" can lose more than the capital committed to them.
</footer>"""
    return page("ThetaForge — Portfolio Dashboard", body)


def write_dashboard(pf: Portfolio, snaps, corr, corr_src, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(build_html(pf, snaps, corr, corr_src), encoding="utf-8")
    return path
