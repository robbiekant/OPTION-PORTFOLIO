"""Fetch orchestration: try providers in order, persist everything."""
from __future__ import annotations

import datetime as dt
import math

from . import config, pricing, store
from .models import OptionQuote, UnderlyingSnapshot
from .providers.free import CboeProvider, YahooProvider
from .providers.ibkr import IBKRProvider


def build_provider_chain(prefer: str = "ibkr") -> list:
    chain = []
    if prefer == "ibkr":
        chain.append(IBKRProvider())
    chain += [CboeProvider(), YahooProvider()]
    if prefer != "ibkr":
        chain.append(IBKRProvider())
    return chain


def fetch_all(symbols: list[str] | None = None, prefer: str = "ibkr",
              stamp: str | None = None, want_chains: bool = True,
              verbose: bool = True) -> dict:
    """
    Pull underlyings, chains and daily closes for the universe and write a
    reproducible snapshot to disk. Returns a summary dict.
    """
    symbols = symbols or [s for s, i in config.UNIVERSE.items()
                          if i.asset_class != "cash"]
    stamp = stamp or store.today_stamp()
    providers = build_provider_chain(prefer)
    live = [p for p in providers if _safe_available(p)]

    if verbose:
        names = ", ".join(p.name for p in live) or "none"
        print(f"[fetch] providers online: {names}")

    unders: dict[str, UnderlyingSnapshot] = {}
    closes: dict[str, list[float]] = {}
    chain_counts: dict[str, int] = {}

    for sym in symbols:
        snap = None
        for p in live:
            snap = _safe(p.underlying, sym)
            if snap and snap.spot > 0:
                break
        if not snap:
            if verbose:
                print(f"[fetch] {sym}: no data from any provider")
            continue
        unders[sym] = snap
        if verbose:
            print(f"[fetch] {sym:6s} spot={snap.spot:>10.2f}  iv={snap.iv:>6.2%}  "
                  f"ivr={snap.iv_rank:>3.0f}  src={snap.source}")

        for p in live:
            c = _safe(p.daily_closes, sym, config.CORRELATION_LOOKBACK_DAYS)
            if c:
                closes[sym] = c
                break

        if want_chains:
            expiry = target_expiry(sym)
            lo, hi = strike_window(snap)
            for p in live:
                quotes = _safe(p.chain, sym, expiry, lo, hi) or []
                if quotes:
                    store.save_chain(sym, expiry, quotes, stamp)
                    chain_counts[sym] = len(quotes)
                    break

    store.save_underlyings(unders, stamp)
    if closes:
        store.save_closes(closes, stamp)
    store.save_meta({
        "stamp": stamp,
        "fetched_at": dt.datetime.now().isoformat(timespec="seconds"),
        "providers_online": [p.name for p in live],
        "symbols": list(unders),
        "chains": chain_counts,
    }, stamp)

    return {"stamp": stamp, "underlyings": len(unders),
            "chains": sum(chain_counts.values()),
            "providers": [p.name for p in live]}


def target_expiry(symbol: str, today: dt.date | None = None) -> str:
    today = today or dt.date.today()
    inst = config.UNIVERSE.get(symbol)
    dte = config.TARGET_DTE + (6 if inst and inst.kind == "future" else 0)
    return (today + dt.timedelta(days=dte)).isoformat()


def strike_window(snap: UnderlyingSnapshot, sigmas: float = 2.5) -> tuple[float, float]:
    em = pricing.expected_move(snap.spot, snap.iv, config.TARGET_DTE)
    return max(0.0, snap.spot - sigmas * em), snap.spot + sigmas * em


def returns_from_closes(closes: dict[str, list[float]]) -> dict[str, list[float]]:
    out = {}
    for sym, series in closes.items():
        rets = [(series[i] / series[i - 1] - 1.0)
                for i in range(1, len(series)) if series[i - 1]]
        if rets:
            out[sym] = rets
    return out


def _safe_available(p) -> bool:
    try:
        return bool(p.available())
    except Exception:
        return False


def _safe(fn, *args):
    try:
        return fn(*args)
    except Exception:
        return None
