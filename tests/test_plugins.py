"""
The three plugins (Cursor, Claude, ChatGPT/Codex) share one skill set in root
`skills/`. CI fails when a plugin copy drifts from it, when a skill or the
ChatGPT manifest carries commerce text (OpenAI forbids it), or when a manifest
breaks a directory limit. Runnable directly:

    .venv/bin/python tests/test_plugins.py

or via pytest.
"""

from __future__ import annotations

import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import build_plugins  # noqa: E402


def test_plugins_pass_check_mode():
    r = subprocess.run(
        [sys.executable, "scripts/build_plugins.py", "--check"],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )
    assert r.returncode == 0, r.stdout + r.stderr


def test_commerce_patterns_catch_prices_and_trials_only():
    def hits(text: str) -> bool:
        return any(re.search(p, text, re.IGNORECASE) for p in build_plugins.COMMERCE)

    assert hits("Pro is $29/month")
    assert hits("start the 30-day free trial")
    assert hits("see https://gammarips.com/pricing")
    assert hits("subscribe now")
    assert not hits("If a tool returns `subscription_required`, pass on its message.")
    assert not hits("The full pool needs GammaRips Pro.")


def test_trade_plan_ships_to_claude_and_cursor_not_chatgpt():
    names = {d.name for d in build_plugins.skill_dirs()}
    assert "gammarips-trade-plan" in names
    assert (ROOT / "plugins/claude/skills/gammarips-trade-plan/SKILL.md").is_file()
    chatgpt = {d.name for d in build_plugins.chatgpt_skill_dirs()}
    assert "gammarips-trade-plan" not in chatgpt
    assert chatgpt == names - build_plugins.CHATGPT_EXCLUDED_SKILLS


def test_retired_cohort_label_rides_first():
    sys.path.insert(0, str(ROOT / "src"))
    from tools import v4

    labeled = v4._label_retired_cohort({"total_trades": 17})
    assert list(labeled)[0] == "cohort_status"
    assert labeled["cohort_status"].startswith("RETIRED 2026-09-28")
    assert labeled["total_trades"] == 17
    assert v4._label_retired_cohort([1, 2]) == [1, 2]


if __name__ == "__main__":
    test_plugins_pass_check_mode()
    test_commerce_patterns_catch_prices_and_trials_only()
    test_trade_plan_ships_to_claude_and_cursor_not_chatgpt()
    test_retired_cohort_label_rides_first()
    print("PASS")
