#!/usr/bin/env python3
"""
Seed a snapshot from the IBKR data pulled on 2026-08-15 (2026-08-14 close).

This exists so the very first portfolio build is reproducible without a
gateway running. Once IB Gateway is up on your machine,
`thetaforge fetch` overwrites this with a live pull.

Every number below came off the IBKR connector:
  - last price          (last / price history for futures)
  - implied_vol_underlying  -> annual_iv
  - historical_vol          -> annual_pct
  - implied_volatility_percentile -> high_13w / high_26w / high_52w
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from thetaforge import store
from thetaforge.models import UnderlyingSnapshot

STAMP = "2026-08-15"
AS_OF = "2026-08-15T18:39:00"

RAW = [
    # symbol, spot,     iv,      hv,      p13w,   p26w,   p52w,   prior_close
    ("SPY",   776.01,   0.115851, 0.118205, 0.0000, 0.0000, 0.0637, 777.88),
    ("QQQ",   730.85,   0.181152, 0.222340, 0.0000, 0.0000, 0.2988, 732.07),
    ("IWM",   304.90,   0.156231, 0.148916, 0.0000, 0.0000, 0.0000, 0.0),
    ("SMH",   587.30,   0.429551, 0.524997, 0.0794, 0.4841, 0.7410, 589.12),
    ("FXI",    34.92,   0.190642, 0.197830, 0.1111, 0.0556, 0.0956, 34.86),
    ("TLT",    82.04,   0.105003, 0.075307, 0.7778, 0.6270, 0.4861, 82.59),
    ("GLD",   401.81,   0.248471, 0.224324, 0.9365, 0.6032, 0.7171, 398.96),
    ("SLV",    58.60,   0.385913, 0.408234, 0.0000, 0.0000, 0.2470, 58.16),
    # Futures: spot from daily bars (GCZ6 / CLX6 close 2026-08-14),
    # IV from implied_vol_underlying. IBKR returned no percentile series
    # for these, so IV rank falls back to the IV/HV proxy.
    ("/GC",  4437.30,   0.216682, 0.190000, 0.0000, 0.0000, 0.0000, 4420.40),
    ("/CL",    80.10,   0.449960, 0.420000, 0.0000, 0.0000, 0.0000, 79.07),
]


def main() -> None:
    unders = {}
    for sym, spot, iv, hv, p13, p26, p52, prior in RAW:
        unders[sym] = UnderlyingSnapshot(
            symbol=sym, spot=spot, iv=iv, hv=hv,
            iv_pct_13w=p13, iv_pct_26w=p26, iv_pct_52w=p52,
            prior_close=prior, source="ibkr", as_of=AS_OF)

    store.save_underlyings(unders, STAMP)
    store.save_meta({
        "stamp": STAMP,
        "fetched_at": AS_OF,
        "providers_online": ["ibkr (via connector)"],
        "symbols": list(unders),
        "chains": {},
        "note": "Seed snapshot. Underlying spot/IV/HV/IV-percentile are live "
                "IBKR values as of the 2026-08-14 close. Option leg premiums "
                "are model-priced from these inputs until a gateway pull "
                "supplies live chains.",
    }, STAMP)
    print(f"Seeded {len(unders)} underlyings into snapshot {STAMP}")
    for s, u in unders.items():
        print(f"  {s:6s} spot={u.spot:>9.2f}  iv={u.iv:>6.2%}  "
              f"hv={u.hv:>6.2%}  ivr={u.iv_rank:>3.0f}")


if __name__ == "__main__":
    main()
