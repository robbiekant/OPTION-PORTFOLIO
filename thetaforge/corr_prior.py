"""
Correlation priors.

When daily closes are available the engine computes realised correlations
from them. When they are not (offline rerun, provider without history),
it falls back to this prior — long-run daily-return correlations between
these asset classes, rounded to two decimals.

The prior is deliberately conservative: where a relationship is unstable
(gold vs equities, crude vs equities) it uses the higher end of the
historical range so the correlation gate errs toward rejecting a trade.
"""
from __future__ import annotations

PRIOR: dict[str, dict[str, float]] = {
    #        SPY    QQQ    IWM    SMH    FXI    TLT    GLD    SLV    /GC    /CL
    "SPY":  {"SPY": 1.00, "QQQ": 0.94, "IWM": 0.85, "SMH": 0.82, "FXI": 0.42,
             "TLT": -0.18, "GLD": 0.08, "SLV": 0.22, "/GC": 0.08, "/CL": 0.28},
    "QQQ":  {"SPY": 0.94, "QQQ": 1.00, "IWM": 0.78, "SMH": 0.89, "FXI": 0.41,
             "TLT": -0.12, "GLD": 0.10, "SLV": 0.24, "/GC": 0.10, "/CL": 0.22},
    "IWM":  {"SPY": 0.85, "QQQ": 0.78, "IWM": 1.00, "SMH": 0.70, "FXI": 0.38,
             "TLT": -0.22, "GLD": 0.05, "SLV": 0.21, "/GC": 0.05, "/CL": 0.30},
    "SMH":  {"SPY": 0.82, "QQQ": 0.89, "IWM": 0.70, "SMH": 1.00, "FXI": 0.44,
             "TLT": -0.10, "GLD": 0.09, "SLV": 0.25, "/GC": 0.09, "/CL": 0.20},
    "FXI":  {"SPY": 0.42, "QQQ": 0.41, "IWM": 0.38, "SMH": 0.44, "FXI": 1.00,
             "TLT": -0.05, "GLD": 0.14, "SLV": 0.20, "/GC": 0.14, "/CL": 0.24},
    "TLT":  {"SPY": -0.18, "QQQ": -0.12, "IWM": -0.22, "SMH": -0.10, "FXI": -0.05,
             "TLT": 1.00, "GLD": 0.30, "SLV": 0.16, "/GC": 0.30, "/CL": -0.14},
    "GLD":  {"SPY": 0.08, "QQQ": 0.10, "IWM": 0.05, "SMH": 0.09, "FXI": 0.14,
             "TLT": 0.30, "GLD": 1.00, "SLV": 0.80, "/GC": 0.98, "/CL": 0.16},
    "SLV":  {"SPY": 0.22, "QQQ": 0.24, "IWM": 0.21, "SMH": 0.25, "FXI": 0.20,
             "TLT": 0.16, "GLD": 0.80, "SLV": 1.00, "/GC": 0.79, "/CL": 0.22},
    "/GC":  {"SPY": 0.08, "QQQ": 0.10, "IWM": 0.05, "SMH": 0.09, "FXI": 0.14,
             "TLT": 0.30, "GLD": 0.98, "SLV": 0.79, "/GC": 1.00, "/CL": 0.16},
    "/CL":  {"SPY": 0.28, "QQQ": 0.22, "IWM": 0.30, "SMH": 0.20, "FXI": 0.24,
             "TLT": -0.14, "GLD": 0.16, "SLV": 0.22, "/CL": 1.00, "/GC": 0.16},
}


def matrix_for(symbols: list[str],
               realised: dict[str, dict[str, float]] | None = None
               ) -> tuple[dict[str, dict[str, float]], str]:
    """
    Return (matrix, source). Uses realised correlations where both legs are
    present, prior values otherwise.
    """
    realised = realised or {}
    used_realised = False
    out: dict[str, dict[str, float]] = {}
    for a in symbols:
        row: dict[str, float] = {}
        for b in symbols:
            if a == b:
                row[b] = 1.0
                continue
            r = realised.get(a, {}).get(b)
            if r is not None:
                row[b] = round(float(r), 3)
                used_realised = True
            else:
                row[b] = PRIOR.get(a, {}).get(b, 0.35)
        out[a] = row
    src = "realised" if used_realised else "prior"
    if used_realised and any(
            PRIOR.get(a, {}).get(b) is not None and
            realised.get(a, {}).get(b) is None
            for a in symbols for b in symbols if a != b):
        src = "mixed (realised where available, prior elsewhere)"
    return out, src
