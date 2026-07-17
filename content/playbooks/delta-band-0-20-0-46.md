Status: active
Type: finding
Tag: proven-on-cohort
Exit-context: 3-day hold realized labels (1,375-trade study, option PnL)
Source: GammaRips 1,375-trade realized-label study (edge-rank levers)
Date: 2026-07-06

# Mid-delta band |delta| 0.20–0.46

Across the 1,375-trade realized-label study, **mid |delta| 0.20–0.46 was the only contract
feature that separated won from lost trades**. Deep OTM lottery strikes and near-ITM both
underperformed the band. It is the confirmed lever behind the engine's edge-rank pre-sort
(alongside RR<1.4 and ATR-move as soft tilts).

Application: prefer candidates inside the band; treat outside-band candidates as needing an
explicit reason. Interaction note: the band is also the conditioning variable that makes
[[mom-60-conditional-lever]] work at all — the levers are call-delta-defined and do not
transfer to puts.
