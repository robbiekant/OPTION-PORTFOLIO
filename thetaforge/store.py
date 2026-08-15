"""
Snapshot persistence.

Every fetch is written to data/snapshots/<YYYY-MM-DD>/ so that any
portfolio build can be reproduced exactly, offline, from a past date.
`SnapshotProvider` replays one of these directories through the same
provider interface the live sources use.
"""
from __future__ import annotations

import datetime as dt
import gzip
import json
from pathlib import Path
from typing import Any

from .models import OptionQuote, UnderlyingSnapshot

ROOT = Path(__file__).resolve().parent.parent / "data" / "snapshots"


def _dir(stamp: str) -> Path:
    p = ROOT / stamp
    p.mkdir(parents=True, exist_ok=True)
    return p


def today_stamp() -> str:
    return dt.date.today().isoformat()


def list_snapshots() -> list[str]:
    if not ROOT.exists():
        return []
    return sorted(p.name for p in ROOT.iterdir() if p.is_dir())


def latest_snapshot() -> str | None:
    snaps = list_snapshots()
    return snaps[-1] if snaps else None


# --------------------------------------------------------------------------
# Writing
# --------------------------------------------------------------------------

def save_underlyings(unders: dict[str, UnderlyingSnapshot],
                     stamp: str | None = None) -> Path:
    stamp = stamp or today_stamp()
    path = _dir(stamp) / "underlyings.json"
    path.write_text(json.dumps(
        {k: v.to_dict() for k, v in unders.items()}, indent=2))
    return path


def save_chain(symbol: str, expiry: str, quotes: list[OptionQuote],
               stamp: str | None = None) -> Path:
    stamp = stamp or today_stamp()
    d = _dir(stamp) / "chains"
    d.mkdir(exist_ok=True)
    safe = symbol.replace("/", "_")
    path = d / f"{safe}_{expiry}.json.gz"
    payload = [q.__dict__ for q in quotes]
    with gzip.open(path, "wt", encoding="utf-8") as fh:
        json.dump(payload, fh)
    return path


def save_closes(closes: dict[str, list[float]], stamp: str | None = None) -> Path:
    stamp = stamp or today_stamp()
    path = _dir(stamp) / "closes.json"
    path.write_text(json.dumps(closes))
    return path


def save_meta(meta: dict[str, Any], stamp: str | None = None) -> Path:
    stamp = stamp or today_stamp()
    path = _dir(stamp) / "meta.json"
    path.write_text(json.dumps(meta, indent=2, default=str))
    return path


def save_portfolio(payload: dict[str, Any], stamp: str | None = None) -> Path:
    stamp = stamp or today_stamp()
    path = _dir(stamp) / "portfolio.json"
    path.write_text(json.dumps(payload, indent=2, default=str))
    return path


# --------------------------------------------------------------------------
# Reading / replay
# --------------------------------------------------------------------------

class SnapshotProvider:
    """Replays a saved snapshot directory. Enables fully offline reruns."""
    name = "snapshot"

    def __init__(self, stamp: str | None = None):
        self.stamp = stamp or latest_snapshot() or today_stamp()
        self.dir = ROOT / self.stamp

    def available(self) -> bool:
        return (self.dir / "underlyings.json").exists()

    def _unders(self) -> dict[str, dict]:
        p = self.dir / "underlyings.json"
        return json.loads(p.read_text()) if p.exists() else {}

    def underlying(self, symbol: str) -> UnderlyingSnapshot | None:
        raw = self._unders().get(symbol)
        if not raw:
            return None
        raw = {k: v for k, v in raw.items() if k != "iv_rank"}
        return UnderlyingSnapshot(**raw)

    def all_underlyings(self) -> dict[str, UnderlyingSnapshot]:
        out = {}
        for sym, raw in self._unders().items():
            raw = {k: v for k, v in raw.items() if k != "iv_rank"}
            out[sym] = UnderlyingSnapshot(**raw)
        return out

    def expirations(self, symbol: str) -> list[str]:
        d = self.dir / "chains"
        if not d.exists():
            return []
        safe = symbol.replace("/", "_")
        return sorted(p.name[len(safe) + 1:-8] for p in d.glob(f"{safe}_*.json.gz"))

    def chain(self, symbol: str, expiry: str, lo: float, hi: float) -> list[OptionQuote]:
        safe = symbol.replace("/", "_")
        path = self.dir / "chains" / f"{safe}_{expiry}.json.gz"
        if not path.exists():
            return []
        with gzip.open(path, "rt", encoding="utf-8") as fh:
            rows = json.load(fh)
        return [OptionQuote(**r) for r in rows if lo <= r["strike"] <= hi]

    def daily_closes(self, symbol: str, days: int = 120) -> list[float]:
        p = self.dir / "closes.json"
        if not p.exists():
            return []
        return json.loads(p.read_text()).get(symbol, [])[-days:]
