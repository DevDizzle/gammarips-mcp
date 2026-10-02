"""
Build and check the three GammaRips plugins from ONE skill source.

Root `skills/` is the only copy you edit. It serves:
  * Cursor  — `.cursor-plugin/plugin.json` at the repo root lists `skills/...`
              (cursor.directory imports the repo).
  * Claude  — `plugins/claude/` is the Claude directory plugin folder. The
              directory scans only that folder, so the skills are COPIED into
              `plugins/claude/skills/` (committed; symlinks are rejected).
  * ChatGPT / Codex — `plugins/chatgpt/` holds the OpenAI manifest. The ZIP
              `dist/gammarips-chatgpt-plugin-<version>.zip` takes the skills
              from root `skills/`.

The skills ship to ChatGPT, whose plugin rules forbid prices, trial offers and
subscribe steps, so the shared skills must stay plan-neutral: they tell the
agent to pass on the server's own `subscription_required` message, and the
server picks the text per client (utils.clients).

    .venv/bin/python scripts/build_plugins.py           # sync + check + ZIP
    .venv/bin/python scripts/build_plugins.py --check   # check only (no writes)

Limits: developers.openai.com/plugins/deploy/submission and
claude.com/docs/plugins/pre-submission-checklist.
"""

from __future__ import annotations

import filecmp
import json
import re
import shutil
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILLS = ROOT / "skills"
CHATGPT = ROOT / "plugins" / "chatgpt"
CLAUDE = ROOT / "plugins" / "claude"
CURSOR_MANIFEST = ROOT / ".cursor-plugin" / "plugin.json"
DIST = ROOT / "dist"

# (field, max chars, required) under extensions.com.openai.interface
OPENAI_LIMITS = [
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
COMMERCE = [r"\$\d", r"\btrial\b", r"/pricing", r"/account", r"subscribe\b", r"upgrade"]
SECRET = re.compile(r"gr_live_[A-Za-z0-9]{8,}")
NAME_RE = re.compile(r"[a-z0-9](?:[a-z0-9-]{0,62}[a-z0-9])?")
# Skills held out of the ChatGPT ZIP. v1 goes to OpenAI review without the
# trade-plan skill (specific trade plans carry more review risk there); the
# server's start-here playbook still carries the plan steps for every client.
CHATGPT_EXCLUDED_SKILLS = {"gammarips-trade-plan"}


def skill_dirs() -> list[Path]:
    return sorted(p.parent for p in SKILLS.glob("*/SKILL.md"))


def chatgpt_skill_dirs() -> list[Path]:
    return [d for d in skill_dirs() if d.name not in CHATGPT_EXCLUDED_SKILLS]


def sync_claude_skills(errors: list[str], write: bool) -> None:
    """Make plugins/claude/skills an exact copy of root skills/."""
    dest = CLAUDE / "skills"
    if write:
        if dest.exists():
            shutil.rmtree(dest)
        for src in skill_dirs():
            shutil.copytree(src, dest / src.name)
        return
    cmp = filecmp.dircmp(SKILLS, dest) if dest.exists() else None
    if cmp is None or _differs(cmp):
        errors.append("plugins/claude/skills is out of sync with skills/ (run without --check)")


def _differs(cmp: filecmp.dircmp) -> bool:
    if cmp.left_only or cmp.right_only or cmp.diff_files or cmp.funny_files:
        return True
    return any(_differs(sub) for sub in cmp.subdirs.values())


def check_skills(errors: list[str]) -> None:
    dirs = skill_dirs()
    if not dirs:
        errors.append("no skills/*/SKILL.md")
    for d in dirs:
        text = (d / "SKILL.md").read_text()
        front = re.match(r"---\n(.*?)\n---\n", text, re.S)
        if not front:
            errors.append(f"skills/{d.name}: no YAML front matter")
            continue
        meta = dict(line.split(":", 1) for line in front.group(1).splitlines() if ":" in line)
        if meta.get("name", "").strip() != d.name:
            errors.append(f"skills/{d.name}: front-matter name must equal the folder name")
        if not meta.get("description", "").strip():
            errors.append(f"skills/{d.name}: description is required")
        # Shared with ChatGPT: plan-neutral only.
        for pattern in COMMERCE:
            if re.search(pattern, text, re.IGNORECASE):
                errors.append(f"skills/{d.name}: commerce text /{pattern}/ (ChatGPT forbids it)")


def check_cursor(errors: list[str]) -> None:
    listed = set(json.loads(CURSOR_MANIFEST.read_text()).get("skills", []))
    for d in skill_dirs():
        if f"skills/{d.name}" not in listed:
            errors.append(f".cursor-plugin/plugin.json does not list skills/{d.name}")


def check_claude(errors: list[str]) -> None:
    manifest = json.loads((CLAUDE / ".claude-plugin" / "plugin.json").read_text())
    if not NAME_RE.fullmatch(manifest.get("name", "")):
        errors.append("claude: name must be lowercase letters, digits, hyphens (max 64)")
    for key in ("description", "author", "version", "license"):
        if not manifest.get(key):
            errors.append(f"claude: plugin.json needs {key}")
    for name, server in manifest.get("mcpServers", {}).items():
        if server.get("type") not in ("http", "sse", "ws"):
            errors.append(f"claude: mcp server {name} needs type http, sse or ws")
        if not server.get("url", "").startswith("https://"):
            errors.append(f"claude: mcp server {name} needs an https url")
        if "headers" in server:
            errors.append(f"claude: mcp server {name} must not carry headers (OAuth only)")
    readme = re.sub(r"```.*?```", "", (CLAUDE / "README.md").read_text(), flags=re.S)
    if len(readme.split()) < 40:
        errors.append("claude: README.md needs at least 40 words outside code blocks")
    if not (CLAUDE / "LICENSE").is_file():
        errors.append("claude: LICENSE missing")
    for path in CLAUDE.rglob("*"):
        if path.name in (".DS_Store", "Thumbs.db", "desktop.ini") or path.is_symlink():
            errors.append(f"claude: remove {path.relative_to(CLAUDE)}")


def check_chatgpt(errors: list[str]) -> dict:
    manifest = json.loads((CHATGPT / "plugin.json").read_text())
    mcp = json.loads((CHATGPT / "mcp.json").read_text())

    if not NAME_RE.fullmatch(manifest.get("name", "")):
        errors.append("chatgpt: name must be lowercase letters, digits, hyphens (max 64)")
    openai = manifest["extensions"]["com.openai"]
    ui = openai["interface"]
    for field, limit, required in OPENAI_LIMITS:
        value = ui.get(field)
        if required and not value:
            errors.append(f"chatgpt: interface.{field} is required")
        elif value and limit and len(value) > limit:
            errors.append(f"chatgpt: interface.{field} is {len(value)} chars (max {limit})")
        if value and field.endswith("URL") and not value.startswith("https://"):
            errors.append(f"chatgpt: interface.{field} must be HTTPS")
    prompts = ui.get("defaultPrompt", [])
    if len(prompts) > 3 or any(len(p) > 128 for p in prompts):
        errors.append("chatgpt: defaultPrompt is at most 3 prompts of 128 chars")
    caps = ui.get("capabilities", [])
    if len(caps) > 20 or any(len(c) > 120 for c in caps):
        errors.append("chatgpt: capabilities is at most 20 items of 120 chars")
    for field in ("composerIcon", "logo"):
        path = ui.get(field, "")
        if not path.startswith("./") or not (CHATGPT / path).is_file():
            errors.append(f"chatgpt: interface.{field} must be a ./ path to a package file")

    cases = openai.get("review", {}).get("test_cases", {})
    positive, negative = cases.get("positive", []), cases.get("negative", [])
    if len(positive) < 5 or len(negative) < 3:
        errors.append(
            f"chatgpt: need 5 positive + 3 negative cases, have {len(positive)} + {len(negative)}"
        )
    for c in positive:
        # The OpenAI validator rejects a list here ("Input should be a valid string").
        for key in ("description", "prompt", "tools_triggered", "expected_behavior"):
            if key in c and not isinstance(c[key], str):
                errors.append(f"chatgpt: positive case {key} must be a string")
        for key in ("description", "prompt", "tools_triggered", "expected_behavior"):
            if not c.get(key):
                errors.append(f"chatgpt: positive case missing {key}: {c.get('prompt', '?')[:40]}")
    for c in negative:
        for key in ("description", "prompt"):
            if not c.get(key):
                errors.append(f"chatgpt: negative case missing {key}")

    servers = mcp.get("mcpServers", {})
    if len(servers) != 1:
        errors.append("chatgpt: exactly one MCP server per plugin")
    for name, server in servers.items():
        if not server.get("url", "").startswith("https://"):
            errors.append(f"chatgpt: mcp server {name} must use an HTTPS url")

    # The commerce declaration may name what the plugin does NOT do.
    text = json.dumps(manifest).replace(
        json.dumps(openai.get("review", {}).get("commerce_description", ""))[1:-1], ""
    )
    for pattern in COMMERCE:
        if re.search(pattern, text, re.IGNORECASE):
            errors.append(f"chatgpt: plugin.json has commerce text /{pattern}/")
    return manifest


def check_no_secrets(errors: list[str]) -> None:
    for base in (SKILLS, CHATGPT, CLAUDE):
        for path in base.rglob("*"):
            if (
                path.is_file()
                and path.suffix in (".json", ".md", "")
                and SECRET.search(path.read_text(errors="ignore"))
            ):
                errors.append(f"{path.relative_to(ROOT)} carries an API key")


def build_chatgpt_zip(manifest: dict) -> Path:
    DIST.mkdir(exist_ok=True)
    out = DIST / f"gammarips-chatgpt-plugin-{manifest['version']}.zip"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in sorted(CHATGPT.rglob("*")):
            if path.is_file():
                zf.write(path, path.relative_to(CHATGPT).as_posix())
        for d in chatgpt_skill_dirs():
            for path in sorted(d.rglob("*")):
                if path.is_file():
                    zf.write(path, (Path("skills") / path.relative_to(SKILLS)).as_posix())
    return out


def main() -> int:
    check_only = "--check" in sys.argv[1:]
    errors: list[str] = []
    check_skills(errors)
    sync_claude_skills(errors, write=not check_only and not errors)
    check_cursor(errors)
    check_claude(errors)
    manifest = check_chatgpt(errors)
    check_no_secrets(errors)
    if check_only:
        sync_claude_skills(errors, write=False)
    if errors:
        for e in errors:
            print(f"FAIL {e}")
        return 1
    if check_only:
        print("OK all three plugins pass and share one skill set")
        return 0
    out = build_chatgpt_zip(manifest)
    print(f"OK synced plugins/claude/skills; built {out.relative_to(ROOT)}")
    for name in zipfile.ZipFile(out).namelist():
        print(f"   {name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
