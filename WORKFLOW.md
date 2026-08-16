# Working with this repo through Claude

This file is the contract between Ravi and Claude. It tells any future Claude
session exactly how to pick this repo up, run it, change it, and put it back.

**Repo:** `https://github.com/robbiekant/OPTION-PORTFOLIO`
**Working directory in the sandbox:** `~/OPTION-PORTFOLIO`

---

## What Ravi says → what Claude does

| Ravi says | Claude does |
|---|---|
| "clone my option portfolio" / "pull the repo" | Clone → install deps → build → deliver both HTML files |
| "refresh my dashboard" | Clone → `run --offline` (or live if IB Gateway is up) → deliver |
| "change X and rerun" | Clone → edit → rebuild → deliver → commit + push |
| "just commit what you changed" | Push the working tree with a descriptive message |
| "what changed since last time?" | `git log --oneline` and diff the config |

Claude should **always deliver the regenerated HTML** after any change, not just
report that the code was edited.

---

## The loop, step by step

### 1 · Clone

The repo is public, so this needs no credentials:

```bash
cd ~ && rm -rf OPTION-PORTFOLIO
git clone https://github.com/robbiekant/OPTION-PORTFOLIO.git
cd OPTION-PORTFOLIO
pip install -r requirements.txt --break-system-packages -q
```

### 2 · Run

```bash
python -m thetaforge.cli run --offline     # rebuild from the committed snapshot
python -m thetaforge.cli run               # live pull (needs IB Gateway running)
```

If IB Gateway is not reachable — which is the normal case when Claude runs this
in a cloud sandbox — the tool falls back to the committed snapshot in
`data/snapshots/`. That is why snapshots are version controlled: every build is
reproducible without a broker connection.

To refresh market data from the IBKR **connector** (available to Claude in chat
even when the gateway is not), pull spot/IV/HV per symbol and rewrite
`seed_snapshot.py`, then re-run. See "Refreshing market data" below.

Outputs land in `output/`:
- `thetaforge_dashboard.html`
- `thetaforge_rulebook.html`

### 3 · Change

All trading rules live in **`thetaforge/config.py`**. Nothing else should need
editing for a strategy change:

| To change… | Edit |
|---|---|
| Portfolio size | `PORTFOLIO_NLV` |
| How aggressive | `VIX_BANDS` / pass `--stance` |
| Sleeve split | `SLEEVE_TARGETS` |
| Entry/exit timing | `TARGET_DTE`, `MANAGE_DTE`, `DTE_WINDOW` |
| Profit target / stops | `PROFIT_TARGET_*`, `LOSS_MULTIPLE_*` |
| Strike selection | `DEFAULT_SHORT_DELTA` |
| Position size caps | `MAX_BPR_*` |
| Which products to trade | `UNIVERSE` |
| Correlation limits | `MAX_PORTFOLIO_CORRELATION`, `MAX_PAIR_CORRELATION` |
| POP / theta targets | `PORTFOLIO_POP_TARGET`, `THETA_TARGET_PCT` |

Strategy *selection* logic (which structure for which vol state) is in
`thetaforge/construct.py::choose_strategy`.

**After any config change, re-run the audit and read it.** If a change pushes a
rule into WARN, say so plainly rather than quietly retuning something else to
make the audit green.

### 4 · Commit back

Claude pushes with the Composio GitHub connector using
`GITHUB_COMMIT_MULTIPLE_FILES` (atomic, all files in one commit).

Note: plain `git push` does **not** work from the Claude sandbox — the git proxy
refuses to pass credentials for repos outside its authorised set, so a personal
access token will not help. The connector is the write path.

Commit message style:

```
<area>: <what changed and why>

e.g.  config: widen short deltas to 0.30, targeting 62% book POP
      construct: require IV>HV before allowing undefined risk
      universe: add /NG and /6J futures options
```

Push only source, config, snapshots and docs. Never push `output/*.html` —
they are regenerated on every run and would create noisy diffs.

---

## Refreshing market data without IB Gateway

When Claude has the IBKR connector in chat but no gateway:

1. `search_contracts` → resolve conids (already cached in `config.UNIVERSE`)
2. `get_price_snapshot` per symbol with fields
   `last, implied_vol_underlying, historical_vol, implied_volatility_percentile, prior_close`
3. For futures: `search_futures` → front month → `get_price_history` (1 day bars)
   for the settle, plus `get_price_snapshot` for IV
4. Rewrite the `RAW` table in `seed_snapshot.py` with the new values and a new
   `STAMP`, then `python seed_snapshot.py && python -m thetaforge.cli run --offline`

The conids for the current universe are already stored in `config.UNIVERSE`, so
step 1 is usually unnecessary.

---

## Guardrails

- **Never commit credentials.** No IBKR passwords, API keys, account numbers or
  net-liquidation values from the live account. `.gitignore` covers the common
  cases; check anything new before pushing.
- **This repo is public.** Anything committed is world-readable. The trading
  rules and market snapshots are fine; account specifics are not.
- **Model-priced legs are estimates.** Any leg marked `model` in the dashboard
  was priced with Black-Scholes off the live underlying IV, not off a real
  quote. Verify against a live chain before sending orders.
- **Don't silently retune to pass the audit.** The audit exists to surface
  tension between the rules and the market. A WARN with an explanation is more
  useful than a green light that was engineered.
