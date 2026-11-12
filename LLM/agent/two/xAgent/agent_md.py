"""AGENT.md 长期规则加载。

- 默认读取工作目录下的 AGENT.md，文件不存在时兼容 AGENTS.md；
- 缺失不报错、不提示；
- 超过 [agent] agent_file_max_chars（默认 8000）时截断并追加“（已截断）”。
"""

from __future__ import annotations

from pathlib import Path

from .settings import FALLBACK_AGENT_FILE, agent_settings

TRUNCATED_SUFFIX = "\n\n（已截断）"


def resolve_agent_file(workspace: Path, configured: str) -> Path | None:
    for name in (configured, FALLBACK_AGENT_FILE):
        candidate = workspace / name
        if candidate.is_file():
            return candidate
    return None


def load_agent_rules(workspace, options: dict | None = None) -> tuple[str, dict | None]:
    """返回 (规则正文, 元信息)。未启用或文件不存在时返回 ("", None)。"""
    workspace = Path(workspace).resolve()
    options = options or agent_settings()
    if not options.get("agent_file_enabled", True):
        return "", None

    path = resolve_agent_file(workspace, options.get("agent_file", "AGENT.md"))
    if path is None:
        return "", None

    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "", None

    max_chars = int(options.get("agent_file_max_chars", 8000))
    original_chars = len(text)
    truncated = original_chars > max_chars
    if truncated:
        text = text[:max_chars] + TRUNCATED_SUFFIX

    meta = {
        "path": path,
        "name": path.name,
        "truncated": truncated,
        "original_chars": original_chars,
        "injected_chars": len(text),
        "max_chars": max_chars,
    }
    return text, meta


def build_prompt_section(rules: str, meta: dict | None) -> str:
    if not rules.strip():
        return ""
    name = (meta or {}).get("name", "AGENT.md")
    return f"# 工作目录长期规则（{name}）\n{rules.strip()}"
