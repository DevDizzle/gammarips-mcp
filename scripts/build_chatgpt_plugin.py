"""
Build the OpenAI plugin-directory ZIP (ChatGPT + Codex) from plugins/chatgpt/.

Checks the package against the field limits in
developers.openai.com/plugins/deploy/submission, then writes
dist/gammarips-chatgpt-plugin-<version>.zip with plugin.json at the ZIP root.
Also fails when any package text carries a price, a trial offer, or a key: the
directory forbids commerce text, and credentials never go in the ZIP.

    .venv/bin/python scripts/build_chatgpt_plugin.py
"""

from __future__ import annotations

import json
import re
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PKG = ROOT / "plugins" / "chatgpt"
DIST = ROOT / "dist"

# (field, max chars, required) under extensions.com.openai.interface
LIMITS = [
    ("displayName", 30, True),
    ("shortDescription", 30, True),
    ("longDescription", 4000, True),
    ("developerName", 80, True),
    ("category", None, True),
    ("websiteURL", 1024, True),
    ("supportURL", 1024, True),
    ("privacyPolicyURL", 1024, True),
    ("termsOfServiceURL", 1024, True),
]
FORBIDDEN = [r"\$\d", r"\btrial\b", r"/pricing", r"/account", r"gr_live_[A-Za-z0-9]", r"subscribe"]


def check(errors: list[str]) -> dict:
    manifest = json.loads((PKG / "plugin.json").read_text())
    mcp = json.loads((PKG / "mcp.json").read_text())

    if not re.fullmatch(r"[a-z0-9-]{1,64}", manifest.get("name", "")):
        errors.append("name must be 1-64 chars of lowercase letters, digits, hyphens")
    openai = manifest["extensions"]["com.openai"]
    ui = openai["interface"]
    for field, limit, required in LIMITS:
        value = ui.get(field)
        if required and not value:
            errors.append(f"interface.{field} is required")
        elif value and limit and len(value) > limit:
            errors.append(f"interface.{field} is {len(value)} chars (max {limit})")
        if value and field.endswith("URL") and not value.startswith("https://"):
            errors.append(f"interface.{field} must be HTTPS")
    prompts = ui.get("defaultPrompt", [])
    if len(prompts) > 3 or any(len(p) > 128 for p in prompts):
        errors.append("defaultPrompt: at most 3 prompts of 128 chars")
    caps = ui.get("capabilities", [])
    if len(caps) > 20 or any(len(c) > 120 for c in caps):
        errors.append("capabilities: at most 20 items of 120 chars")
    for field in ("composerIcon", "logo"):
        path = ui.get(field, "")
        if not path.startswith("./") or not (PKG / path).is_file():
            errors.append(f"interface.{field} must be a ./ path to a file in the package")

    cases = openai.get("review", {}).get("test_cases", {})
    positive, negative = cases.get("positive", []), cases.get("negative", [])
    if len(positive) < 5 or len(negative) < 3:
        errors.append(
            f"need 5 positive + 3 negative test cases, have {len(positive)} + {len(negative)}"
        )
    for c in positive:
        for key in ("description", "prompt", "tools_triggered", "expected_behavior"):
            if not c.get(key):
                errors.append(f"positive case missing {key}: {c.get('prompt', '?')[:40]}")
    for c in negative:
        for key in ("description", "prompt"):
            if not c.get(key):
                errors.append(f"negative case missing {key}")

    servers = mcp.get("mcpServers", {})
    if len(servers) != 1:
        errors.append("exactly one MCP server per plugin")
    for name, server in servers.items():
        if not server.get("url", "").startswith("https://"):
            errors.append(f"mcp server {name} must use an HTTPS url")

    if not list((PKG / "skills").glob("*/SKILL.md")):
        errors.append("no skills/*/SKILL.md")
    for path in PKG.rglob("*"):
        if path.suffix in (".json", ".md"):
            text = path.read_text()
            if path.name == "plugin.json":
                # The commerce declaration may name what the plugin does NOT do.
                text = text.replace(openai.get("review", {}).get("commerce_description", ""), "")
            for pattern in FORBIDDEN:
                if re.search(pattern, text, re.IGNORECASE):
                    errors.append(f"{path.relative_to(PKG)} matches forbidden /{pattern}/")
    return manifest


def main() -> int:
    errors: list[str] = []
    manifest = check(errors)
    if errors:
        for e in errors:
            print(f"FAIL {e}")
        return 1
    DIST.mkdir(exist_ok=True)
    out = DIST / f"gammarips-chatgpt-plugin-{manifest['version']}.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(PKG.rglob("*")):
            if path.is_file():
                zf.write(path, path.relative_to(PKG).as_posix())
    print(f"OK {out.relative_to(ROOT)}")
    for name in zipfile.ZipFile(out).namelist():
        print(f"   {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
