"""ThetaForge command line.

    thetaforge fetch                 pull live data, save a snapshot
    thetaforge build                 construct the portfolio from a snapshot
    thetaforge report                write the rules & philosophy HTML
    thetaforge dashboard             write the portfolio dashboard HTML
    thetaforge run                   fetch + build + both HTML outputs
    thetaforge snapshots             list saved snapshots
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from . import config, fetch, risk, store
from .construct import build_portfolio
from .corr_prior import matrix_for

OUTPUT = Path(__file__).resolve().parent.parent / "output"


def _load(stamp: str | None):
    sp = store.SnapshotProvider(stamp)
    if not sp.available():
        sys.exit(f"No snapshot found ({sp.stamp}). Run `thetaforge fetch` first.")
    snaps = sp.all_underlyings()
    closes = {s: sp.daily_closes(s, config.CORRELATION_LOOKBACK_DAYS) for s in snaps}
    closes = {k: v for k, v in closes.items() if v}
    realised = risk.correlation_matrix(fetch.returns_from_closes(closes)) if closes else {}
    corr, corr_src = matrix_for(list(snaps), realised)
    chains = {}
    for sym, snap in snaps.items():
        lo, hi = fetch.strike_window(snap)
        for exp in sp.expirations(sym):
            q = sp.chain(sym, exp, lo, hi)
            if q:
                chains[sym] = q
                break
    return sp, snaps, corr, corr_src, chains


def cmd_fetch(args):
    res = fetch.fetch_all(prefer=args.prefer, want_chains=not args.no_chains)
    print(json.dumps(res, indent=2))


def cmd_build(args):
    sp, snaps, corr, corr_src, chains = _load(args.stamp)
    pf = build_portfolio(snaps, corr, nlv=args.nlv, stance=args.stance,
                         chains=chains, as_of=sp.stamp)
    payload = {
        "as_of": pf.as_of, "nlv": pf.nlv, "stance": pf.stance,
        "vix_proxy": pf.vix_proxy, "correlation_source": corr_src,
        "total_bpr": pf.total_bpr, "bpr_pct": pf.bpr_pct,
        "total_credit": pf.total_credit, "total_theta": pf.total_theta,
        "theta_pct": pf.theta_pct, "total_vega": pf.total_vega,
        "beta_delta": pf.total_beta_delta, "portfolio_pop": pf.portfolio_pop,
        "avg_correlation": pf.avg_correlation,
        "positions": [p.to_dict() for p in pf.positions],
        "cash": pf.cash_positions, "warnings": pf.warnings,
        "audit": risk.audit(pf),
    }
    store.save_portfolio(payload, sp.stamp)
    _print_book(pf)
    return pf, corr_src


def cmd_report(args):
    from .report import write_report
    p = write_report(OUTPUT / "thetaforge_rulebook.html")
    print(f"wrote {p}")


def cmd_dashboard(args):
    from .dashboard import write_dashboard
    sp, snaps, corr, corr_src, chains = _load(args.stamp)
    pf = build_portfolio(snaps, corr, nlv=args.nlv, stance=args.stance,
                         chains=chains, as_of=sp.stamp)
    p = write_dashboard(pf, snaps, corr, corr_src,
                        OUTPUT / "thetaforge_dashboard.html")
    print(f"wrote {p}")


def cmd_run(args):
    if not args.offline:
        fetch.fetch_all(prefer=args.prefer)
    cmd_build(args)
    cmd_report(args)
    cmd_dashboard(args)


def cmd_snapshots(args):
    for s in store.list_snapshots():
        print(s)


def _print_book(pf):
    print(f"\n{'=' * 108}")
    print(f"  ThetaForge book — {pf.as_of} — NLV ${pf.nlv:,.0f} — "
          f"{pf.stance} stance — vol proxy {pf.vix_proxy}")
    print("=" * 108)
    hdr = (f"{'Asset':<7}{'IVR':>5}  {'Strategy':<26}{'BPR':>9}{'POP':>7}"
           f"{'Credit':>9}{'SPYΔ':>8}{'Corr':>7}{'DTE':>5}{'IV':>7}{'Θ/day':>8}")
    print(hdr)
    print("-" * 108)
    for p in sorted(pf.positions, key=lambda x: (x.sleeve, -x.bpr)):
        print(f"{p.symbol:<7}{'':>5}  {p.strategy[:25]:<26}{p.bpr:>9,.0f}"
              f"{p.pop:>7.0%}{p.credit:>9,.0f}{p.beta_delta:>8.1f}"
              f"{p.correlation:>7.2f}{p.dte:>5}{'':>7}{p.theta:>8,.0f}")
    print("-" * 108)
    print(f"{'TOTAL':<7}{'':>5}  {'':<26}{pf.total_bpr:>9,.0f}"
          f"{pf.portfolio_pop:>7.0%}{pf.total_credit:>9,.0f}"
          f"{pf.total_beta_delta:>8.1f}{pf.avg_correlation:>7.2f}"
          f"{'':>5}{'':>7}{pf.total_theta:>8,.0f}")
    print(f"\n  Deployment {pf.bpr_pct:.1%} of NLV | theta {pf.theta_pct:.3%}/day | "
          f"vega ${pf.total_vega:,.0f}/vol pt | "
          f"SPY notional ${pf.spy_notional_equiv:,.0f}")
    print("\n  Rulebook audit:")
    for row in risk.audit(pf):
        mark = "OK  " if row["status"] == "pass" else "WARN"
        print(f"   [{mark}] {row['check']:<24} {row['detail']}")
    for w in pf.warnings:
        print(f"   [NOTE] {w}")
    print()


def main(argv=None):
    ap = argparse.ArgumentParser(prog="thetaforge",
                                 description="Delta-neutral theta-harvesting "
                                             "portfolio builder (ETFs & futures only)")
    ap.add_argument("--nlv", type=float, default=config.PORTFOLIO_NLV)
    ap.add_argument("--stance", default="moderate",
                    choices=["conservative", "moderate", "aggressive"])
    ap.add_argument("--stamp", default=None, help="snapshot date to replay")
    ap.add_argument("--prefer", default="ibkr", help="preferred provider")
    sub = ap.add_subparsers(dest="cmd", required=True)

    f = sub.add_parser("fetch"); f.add_argument("--no-chains", action="store_true")
    f.set_defaults(func=cmd_fetch)
    sub.add_parser("build").set_defaults(func=cmd_build)
    sub.add_parser("report").set_defaults(func=cmd_report)
    sub.add_parser("dashboard").set_defaults(func=cmd_dashboard)
    r = sub.add_parser("run"); r.add_argument("--offline", action="store_true")
    r.set_defaults(func=cmd_run)
    sub.add_parser("snapshots").set_defaults(func=cmd_snapshots)

    args = ap.parse_args(argv)
    OUTPUT.mkdir(exist_ok=True)
    args.func(args)


if __name__ == "__main__":
    main()
