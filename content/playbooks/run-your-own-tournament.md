# Run Your Own Tournament — the Selection Pattern

The engine's own daily selection uses a **randomized bracket tournament**: no scoring rubric, no weights, no memory — just repeated small-batch head-to-head comparisons by an LLM judge, with randomization and consensus to wash out ordering artifacts. This playbook is that pattern, written so YOUR agent can run it with its own model and its own priorities.

Why a tournament instead of "score every candidate 1-10"? Absolute scores from an LLM are poorly calibrated and drift with context; *relative* judgments inside a small batch are far more stable. The bracket structure turns ~50 candidates into a sequence of small, answerable questions.

## The pattern

**Inputs:** today's pool (`get_enriched_signals`), any context you want the judge to see (e.g. `get_daily_report()`, `get_regime_context()`), and your objective statement.

**One bracket:**
1. Shuffle the pool randomly.
2. Split into batches of ≤10 candidates.
3. For each batch, ask your model ONE simple question with the per-candidate JSON attached — the engine's own prompt is deliberately plain, of the form: *"You're trying to make money buying a single option contract and selling it for profit within N days. Here are the candidates. Pick the top 2."*
4. Advance each batch's top 2. Re-batch the winners. Repeat until one remains.

**Consensus (the part that matters):**
Run **3 independent brackets** with different shuffles. The final selection is the *consensus* winner:
- 3/3 brackets agree → high confidence
- 2/3 agree → medium confidence
- all disagree → low confidence — treat as a no-trade signal or dig deeper manually.

**Fail closed.** If a bracket errors, don't silently fall back to "highest score." No selection is a valid output.

## Make it yours
The engine's judge optimizes *its* objective (single option, profit within its window, its risk posture). Your agent should replace the objective sentence with its own: your horizon, your risk tolerance, your position-size constraints, your existing portfolio exposures. Two subscribers running this same pattern with different objectives will — correctly — land on different contracts. That diffusion is by design.

## Grounding tips
- Give the judge only **point-in-time-safe** fields (see `get_playbook("leakage-and-data-contract")`). Never show it outcome or excursion columns for the candidates it's judging.
- Stale-liquidity warning: scan-time OI/volume are frozen snapshots. If liquidity matters to your sizing, re-fetch live data before entry.
- Keep the prompt dumb. The engine's biggest prompt-engineering lesson: added rubrics, weights, and memory made selection *worse*. Simple question + rich per-candidate data + consensus beats clever prompting.
