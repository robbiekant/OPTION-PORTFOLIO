"""
IBKR Client Portal Web API provider.

This is the primary source: it is the only one that carries BOTH listed ETF
option chains and futures option chains (/GC, /CL, /NG, /6J, /ZS) with
greeks, implied vol and open interest.

Setup on the machine that runs ThetaForge:
    1. Download the IBKR Client Portal Gateway
       https://www.interactivebrokers.com/en/trading/ib-api.php#client-portal-api
    2. ./bin/run.sh root/conf.yaml
    3. Browse to https://localhost:5000 and log in.
    4. Leave it running. ThetaForge talks to https://localhost:5000/v1/api.

Falls back cleanly (available() -> False) when the gateway is not up.
"""
from __future__ import annotations

import datetime as dt
import time
import urllib3

import requests

from ..config import UNIVERSE
from ..models import OptionQuote, UnderlyingSnapshot

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

BASE = "https://localhost:5000/v1/api"

# Client Portal market data field codes
F_LAST, F_BID, F_ASK = "31", "84", "86"
F_VOLUME, F_IV_UNDERLYING, F_HV = "87", "7283", "7084"
F_OPT_IV, F_DELTA, F_GAMMA, F_THETA, F_VEGA = "7633", "7308", "7309", "7310", "7311"
F_OI = "7697"


class IBKRProvider:
    name = "ibkr"

    def __init__(self, base: str = BASE, timeout: float = 12.0):
        self.base = base
        self.timeout = timeout
        self._session = requests.Session()
        self._session.verify = False
        self._conid_cache: dict[str, int] = {}

    # ---- plumbing -------------------------------------------------------
    def _get(self, path: str, **params):
        r = self._session.get(f"{self.base}{path}", params=params,
                              timeout=self.timeout)
        r.raise_for_status()
        return r.json()

    def available(self) -> bool:
        try:
            status = self._session.post(f"{self.base}/iserver/auth/status",
                                        timeout=4.0).json()
            return bool(status.get("authenticated"))
        except Exception:
            return False

    # ---- contract resolution -------------------------------------------
    def conid(self, symbol: str) -> int | None:
        inst = UNIVERSE.get(symbol)
        if inst and inst.ib_conid:
            return inst.ib_conid
        if symbol in self._conid_cache:
            return self._conid_cache[symbol]
        try:
            rows = self._get("/iserver/secdef/search", symbol=symbol, name=False)
        except Exception:
            return None
        for row in rows or []:
            if row.get("symbol") == symbol:
                cid = int(row["conid"])
                self._conid_cache[symbol] = cid
                return cid
        return None

    def _snapshot_fields(self, conids: list[int], fields: list[str]) -> dict:
        ids = ",".join(str(c) for c in conids)
        flds = ",".join(fields)
        # Client Portal needs the request primed before it returns values.
        self._get("/iserver/marketdata/snapshot", conids=ids, fields=flds)
        time.sleep(1.2)
        rows = self._get("/iserver/marketdata/snapshot", conids=ids, fields=flds)
        return {int(r.get("conid", 0)): r for r in rows or []}

    # ---- interface ------------------------------------------------------
    def underlying(self, symbol: str) -> UnderlyingSnapshot | None:
        cid = self.conid(symbol)
        if not cid:
            return None
        try:
            data = self._snapshot_fields(
                [cid], [F_LAST, F_BID, F_ASK, F_VOLUME, F_IV_UNDERLYING, F_HV])
        except Exception:
            return None
        row = data.get(cid)
        if not row:
            return None

        def num(key, default=0.0):
            v = row.get(key)
            if v in (None, ""):
                return default
            try:
                return float(str(v).replace("%", "").replace(",", "").lstrip("C"))
            except ValueError:
                return default

        iv = num(F_IV_UNDERLYING) / 100.0
        hv = num(F_HV) / 100.0
        return UnderlyingSnapshot(
            symbol=symbol, spot=num(F_LAST), iv=iv, hv=hv,
            volume=num(F_VOLUME), source="ibkr",
            as_of=dt.datetime.now().isoformat(timespec="seconds"))

    def expirations(self, symbol: str) -> list[str]:
        cid = self.conid(symbol)
        if not cid:
            return []
        inst = UNIVERSE.get(symbol)
        sectype = "FOP" if inst and inst.kind == "future" else "OPT"
        try:
            info = self._get("/iserver/secdef/strikes", conid=cid,
                             sectype=sectype, month=_next_months(3)[0])
        except Exception:
            return []
        return sorted(info.get("expirations", []) or [])

    def chain(self, symbol: str, expiry: str, lo: float, hi: float) -> list[OptionQuote]:
        cid = self.conid(symbol)
        if not cid:
            return []
        inst = UNIVERSE.get(symbol)
        sectype = "FOP" if inst and inst.kind == "future" else "OPT"
        month = dt.date.fromisoformat(expiry).strftime("%b%y").upper()

        try:
            strikes_resp = self._get("/iserver/secdef/strikes", conid=cid,
                                     sectype=sectype, month=month)
        except Exception:
            return []

        out: list[OptionQuote] = []
        for kind, key in (("call", "call"), ("put", "put")):
            wanted = [s for s in (strikes_resp.get(key) or []) if lo <= s <= hi]
            conids: dict[int, float] = {}
            for strike in wanted:
                try:
                    info = self._get("/iserver/secdef/info", conid=cid,
                                     sectype=sectype, month=month,
                                     strike=strike, right=kind[0].upper())
                except Exception:
                    continue
                for row in info or []:
                    if row.get("maturityDate") == expiry.replace("-", ""):
                        conids[int(row["conid"])] = strike

            if not conids:
                continue
            try:
                data = self._snapshot_fields(
                    list(conids),
                    [F_LAST, F_BID, F_ASK, F_VOLUME, F_OPT_IV, F_DELTA, F_OI])
            except Exception:
                continue

            for ocid, strike in conids.items():
                row = data.get(ocid, {})

                def num(key, default=0.0):
                    v = row.get(key)
                    if v in (None, ""):
                        return default
                    try:
                        return float(str(v).replace("%", "").replace(",", ""))
                    except ValueError:
                        return default

                out.append(OptionQuote(
                    symbol=symbol, expiry=expiry, strike=strike, kind=kind,
                    bid=num(F_BID), ask=num(F_ASK), last=num(F_LAST),
                    iv=num(F_OPT_IV) / 100.0, delta=num(F_DELTA),
                    open_interest=int(num(F_OI)), volume=int(num(F_VOLUME)),
                    source="quote"))
        return out

    def daily_closes(self, symbol: str, days: int = 120) -> list[float]:
        cid = self.conid(symbol)
        if not cid:
            return []
        period = f"{max(days // 20, 1)}m"
        try:
            data = self._get("/iserver/marketdata/history", conid=cid,
                             period=period, bar="1d", outsideRth=False)
        except Exception:
            return []
        return [float(b["c"]) for b in data.get("data", []) if b.get("c")]


def _next_months(n: int) -> list[str]:
    today = dt.date.today()
    out = []
    for i in range(n):
        m = today.month + i
        y = today.year + (m - 1) // 12
        out.append(dt.date(y, ((m - 1) % 12) + 1, 1).strftime("%b%y").upper())
    return out
