# Leakage & the Data Contract

Every column this server exposes is classified, and the classification is machine-readable (`get_enriched_signal_schema`). If you do research on this data, this page is the contract. Leakage-safety here is physics, not policy — the engine's own research burned weeks on subtle lookahead before these rules were hardened.

## The vocabulary
Every column carries one of five classifications, each with an **as-of boundary** — when the value became knowable:

| Classification | As-of boundary | May be used as a model input? |
|---|---|---|
| `identity` | ≤ scan_date | join keys, not signals |
| `feature` | ≤ scan_date (the selection point) | **YES — the only class that may** |
| `label` | realized post-entry | no — outcomes to predict |
| `opportunity` | realized post-entry | no — excursion structure (`opp_*`) |
| `regime_telemetry` | realized post-entry (entry-day close, `oc_*`) | no |

The rule in one line: **a feature is something knowable at ≤ scan_date.** Anything realized after entry — labels, excursions, entry-day-close regime values — describes the future relative to selection. Conditioning selection on it is lookahead, full stop.

## How the server enforces this physically
- `get_pool(view="features")` serves an **allowlist view**: only identity + feature + cohort-meta columns exist in it. New columns are excluded until deliberately classified — the failure mode is a missing column, never a leaked one.
- `query_outcomes` joins labels onto that same view (labels arrive *labeled as labels*, never mixed into the feature vector).
- Live-pool tools serve a view that physically strips the forward-outcome columns the outcome tracker writes back upstream.
- Realized data is only served for **closed** windows.

## Two label horizons — never pool them
- `realized_return_pct` — same-day GIGO bracket (+40/−30, flat 15:45 ET). The live policy label.
- `realized_return_pct_3d` — 3-trading-day companion bracket (+80/−60). A different game; comparing or averaging across horizons produces nonsense.

## Known data honesty items (read before concluding anything)
- **Session-frozen fields:** `recommended_oi` and `recommended_volume` are scan-time snapshots (prior-session OI; frozen volume). Derived `volume_oi_ratio` and `moneyness_pct` inherit this. They are *features* (knowable at scan) but they are NOT live liquidity.
- **`recommended_spread_pct` is permanently NULL** on the current data plan (no options NBBO). Historical pre-2026-06 values were unreliable and should be ignored.
- **The illiquid tail:** ~28% of pool rows have NULL labels (no tradeable bars at the entry anchor). Non-random exclusion — always report it (every relevant response's `meta` carries the counts).
- **Underlying vs option outcomes:** `get_signal_performance` / `get_win_rate_summary` track the UNDERLYING stock's directional move, not option PnL. Direction being right (~54%) does not mean the option made money (~41%) — theta, IV and the bracket eat the difference. Never conflate the two universes.
- **Fractions everywhere:** all return/excursion values are fractions (0.40 = +40%).

## If you remember one thing
Before using any column in selection logic, check its classification. If it isn't `feature`, using it means your backtest is fiction.
