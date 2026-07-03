"""
Methodology playbooks for GammaRips MCP (V3).

Server-versioned markdown documents that teach a bring-your-own-agent HOW to
compose the data tools — the daily workflow, the run-your-own-tournament
selection pattern, the exit lab, and the data contract / leakage rules.

Serving methodology through the server (instead of only as installable skill
files) means every connected agent gets the CURRENT playbooks: when research
updates the methodology, the next `get_playbook` call reflects it — no
client-side reinstall.

Content lives in `content/playbooks/*.md` in this repo. Names are strictly
`[a-z0-9-]+` and resolved against that directory only.
"""

from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import Any

from utils.safety import safe_error

logger = logging.getLogger(__name__)

_PLAYBOOK_DIR = Path(__file__).resolve().parents[2] / "content" / "playbooks"
_NAME_RE = re.compile(r"^[a-z0-9-]{1,64}$")


def _title_and_summary(text: str) -> tuple[str | None, str | None]:
    """First markdown H1 as title; first non-empty, non-heading line as summary."""
    title, summary = None, None
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        if stripped.startswith("# ") and title is None:
            title = stripped[2:].strip()
            continue
        if not stripped.startswith("#") and not stripped.startswith(">"):
            summary = stripped
            break
    return title, summary


def list_playbooks() -> list[dict[str, Any]]:
    """
    List the methodology playbooks this server publishes.

    Playbooks are versioned server-side documentation of HOW to use the data
    tools: the daily workflow, the run-your-own-tournament selection pattern,
    the exit lab, and the data contract / leakage rules. Fetch one with
    `get_playbook(name)`.

    Returns:
        List of {name, title, summary}.
    """
    try:
        if not _PLAYBOOK_DIR.is_dir():
            return [{"error": "playbook directory not found"}]
        results = []
        for path in sorted(_PLAYBOOK_DIR.glob("*.md")):
            title, summary = _title_and_summary(path.read_text(encoding="utf-8"))
            results.append({"name": path.stem, "title": title, "summary": summary})
        return results
    except Exception as e:
        return [{"error": safe_error(e, "list_playbooks")}]


def get_playbook(name: str) -> dict[str, Any]:
    """
    Fetch one methodology playbook (markdown) by name.

    Start with `start-here`. Use `list_playbooks` to see everything published.
    Playbooks are living documents — re-fetch rather than caching long-term;
    the `changelog` playbook records dated methodology/data changes.

    Args:
        name: Playbook name as returned by `list_playbooks` (e.g. "start-here",
            "daily-workflow", "run-your-own-tournament", "exit-lab",
            "leakage-and-data-contract", "changelog").

    Returns:
        {name, title, content} — content is markdown.
    """
    try:
        key = (name or "").strip().lower()
        if not _NAME_RE.match(key):
            return {"error": "invalid playbook name"}
        path = _PLAYBOOK_DIR / f"{key}.md"
        if not path.is_file():
            available = [p.stem for p in sorted(_PLAYBOOK_DIR.glob("*.md"))]
            return {"error": f"unknown playbook '{key}'", "available": available}
        content = path.read_text(encoding="utf-8")
        title, _ = _title_and_summary(content)
        return {"name": key, "title": title, "content": content}
    except Exception as e:
        return {"error": safe_error(e, "get_playbook")}
