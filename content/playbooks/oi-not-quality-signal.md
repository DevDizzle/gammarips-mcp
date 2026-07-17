Status: active
Type: finding
Tag: falsified-on-cohort
Exit-context: 3-day hold era labels (option PnL); quintile study
Source: GammaRips recommended_oi quintile study (2026-06-04 gate removal)
Date: 2026-07-06

# Open interest is not a quality signal — and it's stale anyway

Two independent problems:
1. **Falsified as selection quality:** `recommended_oi` quintiles were the *monotonic
   loser* — higher OI, worse realized option PnL. OI-based quality gates choked real
   winners and were removed from the engine (2026-06-04).
2. **The data is session-frozen:** pool OI/volume are scan-time snapshots; the overnight
   sweep only becomes OI the next morning. What you read in the pool is not what's true
   at entry.

Application: OI/volume matter for **fills** (can I get in and out?), never for **which
contract is good**. Keep the concerns separate in every thesis: selection cites edges;
liquidity is a fill-risk note with its own doctrine rule.
