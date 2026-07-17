"""
V4 registry verification — asserts the server registers EXACTLY the frozen
9-tool map with the correct free/pro tiers, and that web_search is gone.

The 9 names are contract-frozen (downstream repos rename against them), so this
guards against an accidental rename/add/drop. Runnable directly:

    PYTHONPATH=src python tests/verify_tools.py

or via pytest (it exposes `test_v4_registry`).
"""

from __future__ import annotations

import os
import sys

sys.path.insert(0, "src")
os.environ.setdefault("REQUIRE_API_KEY", "false")

# The frozen V4 surface (2026-07-17 simplification replan).
EXPECTED_FREE = {
    "get_pool",
    "get_regime_context",
    "get_market_calendar_status",
    "get_playbook",
    "get_daily_report",
}
EXPECTED_PRO = {
    "get_signal",
    "get_liquidity",
    "query_outcomes",
    "replay_contract",
}
EXPECTED_TOOLS = EXPECTED_FREE | EXPECTED_PRO
KILLED = {"web_search"}


def _surface() -> tuple[set[str], dict[str, str]]:
    import server

    tools = server.get_tools_list()
    names = {t["name"] for t in tools}
    tiers = {t["name"]: t["tier"] for t in tools}
    return names, tiers


def run_all() -> list[tuple[str, bool, str]]:
    names, tiers = _surface()
    from utils.auth import anon_tools

    anon = set(anon_tools())
    checks: list[tuple[str, bool, str]] = []

    checks.append(("exactly_9_tools", len(names) == 9, f"got {len(names)}: {sorted(names)}"))
    checks.append(
        ("names_match_frozen_map", names == EXPECTED_TOOLS, f"diff: {names ^ EXPECTED_TOOLS}")
    )
    checks.append(("web_search_killed", not (names & KILLED), f"present: {names & KILLED}"))
    checks.append(
        ("free_tier_correct", {n for n in names if tiers[n] == "anon"} == EXPECTED_FREE, "")
    )
    checks.append(("pro_tier_correct", {n for n in names if tiers[n] == "pro"} == EXPECTED_PRO, ""))
    checks.append(("anon_set_matches_free", anon == EXPECTED_FREE, f"anon={sorted(anon)}"))

    # every registered tool must carry a non-empty agent-facing description
    import server

    descs = {t["name"]: (t.get("description") or "").strip() for t in server.get_tools_list()}
    missing = [n for n, d in descs.items() if len(d) < 40]
    checks.append(("all_tools_documented", not missing, f"thin/empty docstrings: {missing}"))

    return checks


def test_v4_registry():
    failures = [f"{name}: {note}" for name, ok, note in run_all() if not ok]
    assert not failures, "\n".join(failures)


if __name__ == "__main__":
    results = run_all()
    width = max(len(n) for n, _, _ in results)
    fails = 0
    for name, ok, note in results:
        status = "PASS" if ok else f"FAIL {note}"
        print(f"{name:<{width}}  {status}")
        fails += not ok
    print(f"\n{len(results) - fails}/{len(results)} passed")
    sys.exit(1 if fails else 0)
