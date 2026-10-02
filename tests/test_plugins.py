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


if __name__ == "__main__":
    test_plugins_pass_check_mode()
    test_commerce_patterns_catch_prices_and_trials_only()
    print("PASS")
