"""
Free fallback providers: CBOE delayed chains and Yahoo Finance.

These cover listed ETF/index options only — there are no futures option
chains here. When ThetaForge runs on these, futures exposure is proxied
through ETFs (GLD for /GC, USO for /CL, UNG for /NG) and the dashboard
flags the substitution.
"""
from __future__ import annotations

import datetime as dt
import math

import requests

from ..models import OptionQuote, UnderlyingSnapshot
from .. import pricing

CBOE_URL = "https://cdn.cboe.com/api/global/delayed_quotes/options/{sym}.json"


class CboeProvider:
    """CBOE's public delayed-quote endpoint. No key, no account."""
    name = "cboe"

    def __init__(self, timeout: float = 20.0):
        self.timeout = timeout
        self._cache: dict[str, dict] = {}

    def available(self) -> bool:
        try:
            r = requests.get(CBOE_URL.format(sym="SPY"), timeout=6)
            return r.status_code == 200
        except Exception:
            return False

    def _payload(self, symbol: str) -> dict:
        sym = symbol.lstrip("/").upper()
        if sym in self._cache:
            return self._cache[sym]
        r = requests.get(CBOE_URL.format(sym=sym), timeout=self.timeout)
        r.raise_for_status()
        data = r.json().get("data", {})
        self._cache[sym] = data
        return data

    def underlying(self, symbol: str) -> UnderlyingSnapshot | None:
        try:
            d = self._payload(symbol)
        except Exception:
            return None
        spot = float(d.get("current_price") or 0)
        if not spot:
            return None
        # Derive ATM IV from the chain itself.
        opts = d.get("options", [])
        atm = sorted(opts, key=lambda o: abs(_strike(o["option"]) - spot))[:8]
        ivs = [float(o.get("iv") or 0) for o in atm if o.get("iv")]
        iv = sum(ivs) / len(ivs) if ivs else 0.0
        return UnderlyingSnapshot(
            symbol=symbol, spot=spot, iv=iv, hv=float(d.get("iv30") or 0) / 100.0,
            prior_close=float(d.get("prev_day_close") or 0),
            volume=float(d.get("volume") or 0), source="cboe",
            as_of=dt.datetime.now().isoformat(timespec="seconds"))

    def expirations(self, symbol: str) -> list[str]:
        try:
            d = self._payload(symbol)
        except Exception:
            return []
        return sorted({_expiry(o["option"]) for o in d.get("options", [])})

    def chain(self, symbol: str, expiry: str, lo: float, hi: float) -> list[OptionQuote]:
        try:
            d = self._payload(symbol)
        except Exception:
            return []
        out = []
        for o in d.get("options", []):
            code = o["option"]
            if _expiry(code) != expiry:
                continue
            k = _strike(code)
            if not (lo <= k <= hi):
                continue
            out.append(OptionQuote(
                symbol=symbol, expiry=expiry, strike=k,
                kind="call" if code[-9] == "C" else "put",
                bid=float(o.get("bid") or 0), ask=float(o.get("ask") or 0),
                last=float(o.get("last_trade_price") or 0),
                iv=float(o.get("iv") or 0), delta=float(o.get("delta") or 0),
                open_interest=int(o.get("open_interest") or 0),
                volume=int(o.get("volume") or 0), source="quote"))
        return out

    def daily_closes(self, symbol: str, days: int = 120) -> list[float]:
        return []


class YahooProvider:
    """yfinance fallback. Best used for daily closes / correlations."""
    name = "yahoo"

    def available(self) -> bool:
        try:
            import yfinance  # noqa: F401
            import yfinance as yf
            return bool(yf.Ticker("SPY").fast_info.get("lastPrice"))
        except Exception:
            return False

    def underlying(self, symbol: str) -> UnderlyingSnapshot | None:
        try:
            import yfinance as yf
        except ImportError:
            return None
        try:
            t = yf.Ticker(symbol.lstrip("/"))
            spot = float(t.fast_info["lastPrice"])
            hist = t.history(period="3mo")["Close"].pct_change().dropna()
            hv = float(hist.std() * math.sqrt(252))
            return UnderlyingSnapshot(symbol=symbol, spot=spot, iv=hv * 1.08, hv=hv,
                                      source="yahoo",
                                      as_of=dt.datetime.now().isoformat(timespec="seconds"))
        except Exception:
            return None

    def expirations(self, symbol: str) -> list[str]:
        try:
            import yfinance as yf
            return list(yf.Ticker(symbol.lstrip("/")).options)
        except Exception:
            return []

    def chain(self, symbol: str, expiry: str, lo: float, hi: float) -> list[OptionQuote]:
        try:
            import yfinance as yf
            ch = yf.Ticker(symbol.lstrip("/")).option_chain(expiry)
        except Exception:
            return []
        out = []
        for df, kind in ((ch.calls, "call"), (ch.puts, "put")):
            for _, r in df.iterrows():
                k = float(r["strike"])
                if not (lo <= k <= hi):
                    continue
                out.append(OptionQuote(
                    symbol=symbol, expiry=expiry, strike=k, kind=kind,
                    bid=float(r.get("bid") or 0), ask=float(r.get("ask") or 0),
                    last=float(r.get("lastPrice") or 0),
                    iv=float(r.get("impliedVolatility") or 0),
                    open_interest=int(r.get("openInterest") or 0),
                    volume=int(r.get("volume") or 0), source="quote"))
        return out

    def daily_closes(self, symbol: str, days: int = 120) -> list[float]:
        try:
            import yfinance as yf
            h = yf.Ticker(symbol.lstrip("/")).history(period=f"{days}d")
            return [float(x) for x in h["Close"].tolist()]
        except Exception:
            return []


def _strike(code: str) -> float:
    """CBOE option code: ROOTyymmddC00450000 -> 450.0"""
    return int(code[-8:]) / 1000.0


def _expiry(code: str) -> str:
    body = code[-15:-9]
    return f"20{body[0:2]}-{body[2:4]}-{body[4:6]}"
