# ThetaForge

A delta-neutral, theta-harvesting options portfolio builder for **ETFs and
futures only** — no single-name equity risk.

It encodes the portfolio-construction methodology from the tastylive /
Tom Sosnoff blueprint and the Theta Profits delta-neutral framework as
executable rules, pulls live option-chain data, and produces two artefacts:

| Output | What it is |
|---|---|
| `output/thetaforge_rulebook.html` | The philosophy, restrictions and trade-management protocol |
| `output/thetaforge_dashboard.html` | The constructed portfolio, with full greeks and a rulebook audit |

---

## Install

```bash
cd theta-forge
pip install -r requirements.txt
```

## Run

```bash
python -m thetaforge.cli run              # fetch + build + both HTML outputs
python -m thetaforge.cli fetch            # pull live data, save a snapshot
python -m thetaforge.cli build            # construct the book from a snapshot
python -m thetaforge.cli dashboard        # regenerate the dashboard only
python -m thetaforge.cli report           # regenerate the rulebook only
python -m thetaforge.cli snapshots        # list saved snapshots
```

Useful flags:

```bash
--nlv 300000                # portfolio size
--stance moderate           # conservative | moderate | aggressive
--stamp 2026-08-15          # replay a past snapshot, fully offline
python -m thetaforge.cli run --offline    # rebuild without touching the network
```

---

## Data sources

Providers are tried in order and the first one that answers wins, per symbol.

**1 · IBKR Client Portal Web API — primary.**
The only source that carries both listed ETF option chains and *futures*
option chains (/GC, /CL, /NG, /6J, /ZS) with greeks, IV and open interest.

Setup:

1. Download the [Client Portal Gateway](https://www.interactivebrokers.com/en/trading/ib-api.php#client-portal-api)
2. `./bin/run.sh root/conf.yaml`
3. Open `https://localhost:5000`, log in, leave it running
4. ThetaForge auto-detects it at `https://localhost:5000/v1/api`

**2 · CBOE delayed quotes — free fallback.** No key, no account. Listed
ETF/index options only.

**3 · Yahoo (yfinance) — fallback.** Chains and daily closes for correlations.

**4 · Snapshot replay — always available.** Every fetch is written to
`data/snapshots/<date>/`, so any build is reproducible offline, and you can
re-run a past date to see what the engine would have done.

When no futures-options source is online, futures exposure is proxied through
ETFs (GLD for /GC, USO for /CL, UNG for /NG) and the dashboard flags the
substitution rather than hiding it.

---

## What the engine actually does

1. **Fetch** spot, IV, HV, IV percentile, chains and daily closes for the universe.
2. **Score** each underlying: IV rank, IV−HV premium, liquidity, correlation to the book.
3. **Choose a structure** from the volatility state, not from a price view.
   Undefined risk requires *both* a high IV rank **and** implied above realised.
4. **Select strikes** by delta, inverted from the live IV surface and snapped to
   the real listed strike increments.
5. **Size** to the sleeve budget under the per-trade caps, stepping down to micro
   contracts (/MGC, /MCL) rather than dropping an asset class when a full-size
   contract would breach the cap.
6. **Neutralise delta** — solve a global strike tilt by bisection, then a /MES
   hedge, then a SPY share trim for the last few deltas.
7. **Audit** the finished book against every rule and report pass/warn.

## The rules, in code

Everything lives in `thetaforge/config.py` — change it there, not in the
generators.

| Rule | Value |
|---|---|
| Deployment | VIX-scaled: 25–50% (low vol) up to 50–80% (VIX 40+) |
| Sleeve split | 50% options / 20% futures / 20% stocks / 10% cash |
| Entry / management | 45 DTE in, 21 DTE out |
| Profit target | 50% of credit |
| Stop | 2× credit (defined), 2.5× (undefined) |
| Per-trade cap | 5% BPR defined, 15% undefined, 2% debit structures |
| Book POP | 65–72%, BPR-weighted |
| Daily theta | 0.1–0.3% of net liq |
| Correlation | book average below 0.50, no pair above 0.80 |

## Layout

```
thetaforge/
  config.py        the rulebook as constants + the universe
  pricing.py       Black-Scholes / Black-76, greeks, IV solve, skew & term structure
  models.py        UnderlyingSnapshot, OptionQuote, Leg, Position, Portfolio
  risk.py          margin models, greeks aggregation, beta-weighting, POP, audit
  construct.py     strategy selection, sizing, delta neutralisation
  corr_prior.py    realised correlations, with a documented prior as fallback
  fetch.py         provider orchestration
  store.py         snapshot persistence and replay
  providers/       ibkr.py, free.py (CBOE + Yahoo)
  report.py        rulebook HTML
  dashboard.py     portfolio dashboard HTML
  theme.py         shared visual system
data/snapshots/    every fetch, kept for reruns
output/            generated HTML
```

---

## Notes on the numbers

- **Delta** is carried in underlying unit equivalents (shares for ETFs, ounces
  or barrels for futures), so `delta × spot` is always a dollar notional and
  beta-weighting is one consistent formula.
- **Beta-weighted delta** = `delta × spot × beta / SPY_price`. This is the number
  the whole strategy is organised around.
- **1σ daily P/L** is a full portfolio-variance calculation across position
  deltas and the correlation matrix — *not* `beta_delta × SPY move`, which
  collapses to near zero on a delta-neutral book and would badly understate risk.
- **BPR** models Reg-T requirements (naked: `max(20% spot − OTM, 10% strike) +
  premium`; verticals: `width − credit`; futures options: a SPAN approximation).
  Your broker's actual numbers will differ, particularly under portfolio margin.
- Legs marked **model** are priced with Black-Scholes off the live underlying IV
  with term-structure and skew adjustment. Legs marked **quote** came off a real
  book. The dashboard reports the split.

## Disclaimer

Educational tooling, not investment advice. Options carry risk of substantial
loss; undefined-risk positions can lose more than the capital committed to them.
Model-priced premiums are estimates — verify every strike and price against a
live chain before sending an order.
