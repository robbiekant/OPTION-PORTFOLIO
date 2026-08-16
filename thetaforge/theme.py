"""
Shared visual system for the HTML outputs.

Dark-first terminal aesthetic. Colours are the validated default data-viz
palette stepped for a dark surface; the four categorical slots used here
pass the lightness band, chroma floor, adjacent CVD separation (worst 8.4
protan), normal-vision floor (19.8) and 3:1 contrast checks.
"""
from __future__ import annotations

CSS = """
:root{
  --surface-0:#0e0e0d; --surface-1:#1a1a19; --surface-2:#232322; --surface-3:#2d2d2b;
  --line:#383835; --line-soft:#2a2a28;
  --text-primary:#ffffff; --text-secondary:#c3c2b7; --text-muted:#8a8980;
  --series-1:#3987e5; --series-2:#d95926; --series-3:#199e70; --series-4:#c98500;
  --good:#0ca30c; --warning:#fab219; --serious:#ec835a; --critical:#d03b3b;
  --pos:#199e70; --neg:#d95926; --mid:#383835;
  --mono:'IBM Plex Mono',ui-monospace,SFMono-Regular,Menlo,monospace;
  --sans:'Inter',-apple-system,BlinkMacSystemFont,'Segoe UI',sans-serif;
}
*{box-sizing:border-box}
body{margin:0;background:var(--surface-0);color:var(--text-primary);
  font-family:var(--sans);font-size:14px;line-height:1.6;
  -webkit-font-smoothing:antialiased}
.wrap{max-width:1500px;margin:0 auto;padding:32px 28px 80px}
h1,h2,h3,h4{font-weight:600;letter-spacing:-.01em;margin:0}
h1{font-size:27px;letter-spacing:-.02em}
h2{font-size:19px;margin:44px 0 14px;padding-bottom:9px;
  border-bottom:1px solid var(--line)}
h3{font-size:15px;margin:26px 0 9px;color:var(--text-primary)}
h4{font-size:13px;margin:18px 0 6px;color:var(--text-secondary);
  text-transform:uppercase;letter-spacing:.06em}
p{margin:0 0 12px;color:var(--text-secondary)}
a{color:var(--series-1)}
code,.mono{font-family:var(--mono);font-size:12.5px}
.muted{color:var(--text-muted)}
.small{font-size:12.5px}

header.masthead{border-bottom:1px solid var(--line);padding-bottom:20px;
  margin-bottom:8px;display:flex;justify-content:space-between;
  align-items:flex-end;gap:24px;flex-wrap:wrap}
.brand{font-family:var(--mono);font-size:11px;letter-spacing:.22em;
  text-transform:uppercase;color:var(--series-1);margin-bottom:9px}
.stamp{font-family:var(--mono);font-size:11.5px;color:var(--text-muted);
  text-align:right;line-height:1.8}

.grid{display:grid;gap:12px}
.g2{grid-template-columns:repeat(2,1fr)}
.g3{grid-template-columns:repeat(3,1fr)}
.g4{grid-template-columns:repeat(4,1fr)}
.g5{grid-template-columns:repeat(5,1fr)}
@media(max-width:1100px){.g4,.g5{grid-template-columns:repeat(2,1fr)}
  .g3{grid-template-columns:1fr}}
@media(max-width:680px){.g2,.g4,.g5{grid-template-columns:1fr}}

.tile{background:var(--surface-1);border:1px solid var(--line-soft);
  border-radius:9px;padding:15px 17px}
.tile .lab{font-size:10.5px;text-transform:uppercase;letter-spacing:.08em;
  color:var(--text-muted);margin-bottom:7px;font-family:var(--mono)}
.tile .val{font-family:var(--mono);font-size:25px;font-weight:600;
  letter-spacing:-.02em;line-height:1.15}
.tile .sub{font-size:11.5px;color:var(--text-muted);margin-top:5px}
.tile.accent{border-color:var(--series-1)}

.card{background:var(--surface-1);border:1px solid var(--line-soft);
  border-radius:9px;padding:19px 21px;margin-bottom:12px}
.card h3{margin-top:0}

table{width:100%;border-collapse:collapse;font-family:var(--mono);font-size:12px}
thead th{text-align:right;padding:9px 8px;border-bottom:1px solid var(--line);
  color:var(--text-muted);font-weight:600;font-size:10.5px;
  text-transform:uppercase;letter-spacing:.06em;white-space:nowrap}
thead th:first-child,thead th.l{text-align:left}
tbody td{padding:8px;border-bottom:1px solid var(--line-soft);text-align:right;
  white-space:nowrap;color:var(--text-secondary)}
tbody td:first-child,tbody td.l{text-align:left}
tbody tr:hover{background:var(--surface-2)}
tbody tr.total td{border-top:1px solid var(--line);border-bottom:none;
  font-weight:600;color:var(--text-primary);padding-top:11px}
.sym{color:var(--text-primary);font-weight:600}
.pos{color:var(--pos)}.neg{color:var(--neg)}
.sleeve-row td{background:var(--surface-2);color:var(--text-muted);
  font-size:10.5px;text-transform:uppercase;letter-spacing:.08em;
  padding:7px 8px;font-weight:600}

.pill{display:inline-block;padding:2px 8px;border-radius:11px;font-size:10.5px;
  font-family:var(--mono);border:1px solid var(--line);color:var(--text-secondary)}
.pill.good{color:var(--good);border-color:var(--good)}
.pill.warn{color:var(--warning);border-color:var(--warning)}
.pill.crit{color:var(--critical);border-color:var(--critical)}
.pill.q{color:var(--text-muted)}

.bar-track{height:7px;background:var(--surface-3);border-radius:4px;
  overflow:hidden;position:relative}
.bar-fill{height:100%;border-radius:4px}

.hbar{display:flex;align-items:center;gap:10px;margin-bottom:7px}
.hbar .name{font-family:var(--mono);font-size:11.5px;width:74px;flex:none;
  color:var(--text-secondary)}
.hbar .track{flex:1;height:15px;background:var(--surface-2);border-radius:4px;
  position:relative;overflow:hidden}
.hbar .fill{position:absolute;top:0;bottom:0;border-radius:4px}
.hbar .num{font-family:var(--mono);font-size:11.5px;width:74px;flex:none;
  text-align:right;color:var(--text-secondary)}
.axis0{position:absolute;top:0;bottom:0;width:1px;background:var(--line)}

.heat{border-collapse:separate;border-spacing:2px;font-size:10.5px}
.heat td,.heat th{padding:5px 3px;text-align:center;border:none;
  border-radius:3px;min-width:40px}
.heat th{color:var(--text-muted);font-size:10px;background:none}
.heat td{color:var(--text-primary);font-family:var(--mono)}

.rule{display:flex;gap:13px;padding:12px 0;border-bottom:1px solid var(--line-soft)}
.rule:last-child{border-bottom:none}
.rule .n{font-family:var(--mono);font-size:11px;color:var(--series-1);
  flex:none;width:30px;padding-top:2px}
.rule .b{flex:1}
.rule .b .t{font-weight:600;font-size:13.5px;margin-bottom:3px}
.rule .b .d{font-size:13px;color:var(--text-secondary)}
.rule .b .src{font-size:11px;color:var(--text-muted);font-family:var(--mono);
  margin-top:5px}

.check{display:flex;gap:11px;align-items:flex-start;padding:10px 0;
  border-bottom:1px solid var(--line-soft);font-size:13px}
.check:last-child{border-bottom:none}
.check .ic{flex:none;width:15px;height:15px;border-radius:50%;margin-top:4px;
  display:flex;align-items:center;justify-content:center;font-size:9px;
  font-weight:700;color:var(--surface-0)}
.check .ic.p{background:var(--good)}
.check .ic.w{background:var(--warning)}
.check .nm{font-weight:600;width:190px;flex:none}
.check .dt{color:var(--text-secondary);flex:1}
.check .rl{color:var(--text-muted);font-size:11.5px;font-family:var(--mono);
  width:250px;flex:none;text-align:right}
@media(max-width:900px){.check{flex-wrap:wrap}
  .check .nm,.check .rl{width:auto;text-align:left}}

.note{background:var(--surface-2);border-left:2px solid var(--series-4);
  padding:11px 15px;border-radius:0 6px 6px 0;font-size:12.5px;
  color:var(--text-secondary);margin:12px 0}
.note.crit{border-left-color:var(--critical)}
.note.info{border-left-color:var(--series-1)}

.legend{display:flex;gap:16px;flex-wrap:wrap;margin:10px 0 14px;
  font-size:11.5px;color:var(--text-secondary);font-family:var(--mono)}
.legend span{display:flex;align-items:center;gap:6px}
.swatch{width:11px;height:11px;border-radius:3px;flex:none}

.tip{position:relative;cursor:help;border-bottom:1px dotted var(--text-muted)}
.tip:hover::after{content:attr(data-tip);position:absolute;bottom:135%;left:0;
  background:var(--surface-3);border:1px solid var(--line);border-radius:6px;
  padding:8px 11px;font-size:11.5px;font-family:var(--sans);width:270px;
  z-index:20;color:var(--text-primary);white-space:normal;line-height:1.5;
  box-shadow:0 8px 24px rgba(0,0,0,.5)}

footer{margin-top:52px;padding-top:20px;border-top:1px solid var(--line);
  font-size:11.5px;color:var(--text-muted);font-family:var(--mono);line-height:1.9}
"""

FONTS = ('<link rel="preconnect" href="https://fonts.googleapis.com">'
         '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>'
         '<link href="https://fonts.googleapis.com/css2?'
         'family=IBM+Plex+Mono:wght@400;500;600&'
         'family=Inter:wght@400;500;600&display=swap" rel="stylesheet">')


def page(title: str, body: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{title}</title>{FONTS}<style>{CSS}</style></head>
<body><div class="wrap">{body}</div></body></html>"""


def diverging(value: float, vmax: float) -> str:
    """Blue (negative) <-> gray (zero) <-> red (positive), for correlations."""
    if vmax <= 0:
        return "var(--mid)"
    t = max(-1.0, min(1.0, value / vmax))
    if abs(t) < 0.04:
        return "#383835"
    if t > 0:
        stops = ["#3f3a38", "#6b4340", "#964a46", "#b8524d", "#d03b3b"]
    else:
        stops = ["#38393f", "#3a4a63", "#3a5c8a", "#3771b8", "#3987e5"]
    return stops[min(int(abs(t) * len(stops)), len(stops) - 1)]
