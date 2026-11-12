"""Agent Skills 动态加载。

项目根目录 = 进程启动时的工作目录；Skill 位于 <root>/.agents/skills/。
初始化只解析 SKILL.md 的 YAML frontmatter，完整正文仅在 loadSkill 时读取。
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

SKILLS_DIR = Path(".agents") / "skills"
SKILL_FILE = "SKILL.md"


@dataclass
class Skill:
    name: str
    description: str
    directory: Path


def _parse_frontmatter(path: Path) -> dict[str, str]:
    """只读取 SKILL.md 开头的 YAML frontmatter，不加载正文。"""
    values: dict[str, str] = {}
    block_key = ""
    block_marker = ""
    block: list[str] = []

    def flush() -> None:
        nonlocal block_key
        if block_key:
            separator = "\n" if block_marker == "|" else " "
            values[block_key] = separator.join(block).strip()
            block_key = ""

    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            if fh.readline().strip() != "---":
                return {}
            for line in fh:
                stripped = line.strip()
                if stripped == "---":
                    flush()
                    break
                if block_key:
                    if line[:1] in (" ", "\t"):
                        block.append(stripped)
                        continue
                    flush()
                if not stripped or stripped.startswith("#") or ":" not in line:
                    continue
                key, _, value = line.partition(":")
                key = key.strip()
                value = value.strip()
                if value in ("|", ">"):
                    block_key, block_marker, block = key, value, []
                elif len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
                    values[key] = value[1:-1]
                else:
                    values[key] = value
            else:
                flush()
    except OSError:
        return {}
    return values


class SkillRegistry:
    def __init__(self, project_root=None) -> None:
        self.project_root = Path(project_root or Path.cwd()).resolve()
        self.root = self.project_root / SKILLS_DIR
        self.skills: dict[str, Skill] = {}
        self._discover()

    def _discover(self) -> None:
        try:
            folders = sorted(self.root.iterdir(), key=lambda p: p.name.lower())
        except OSError:
            return
        for folder in folders:
            skill_file = folder / SKILL_FILE
            if not folder.is_dir() or not skill_file.is_file():
                continue
            meta = _parse_frontmatter(skill_file)
            name = meta.get("name", "").strip()
            description = meta.get("description", "").strip()
            if not name or not description or name in self.skills:
                continue
            self.skills[name] = Skill(name, description, folder.resolve())

    def build_system_prompt(self, base: str = "") -> str:
        parts = [base.strip()] if base and base.strip() else []
        if self.skills:
            parts.append("You have access to the following skills:")
            parts.extend(
                f"- `{skill.name}`: {' '.join(skill.description.split())}"
                for skill in sorted(self.skills.values(), key=lambda s: s.name.lower())
            )
            parts.append(
                "Use the `loadSkill` tool to load the full instructions of a skill "
                "when needed. You can also load additional files referenced by a skill."
            )
        return "\n".join(parts)

    def load(self, name: str, filename: str | None = None) -> str:
        skill = self.skills.get(name)
        if skill is None:
            available = "、".join(sorted(self.skills)) or "无"
            return f"未找到 Skill：{name}（可用：{available}）"

        if not filename or not str(filename).strip():
            return self._read_within(skill, skill.directory / SKILL_FILE)

        raw = str(filename).strip()
        path = Path(raw)
        target = path if path.is_absolute() else None

        if target is None:
            for base in (skill.directory, self.project_root):
                candidate = base / path
                if candidate.exists():
                    target = candidate
                    break
        if target is None:
            target = skill.directory / path

        if target.exists():
            return self._read_within(skill, target)

        if len(path.parts) == 1:
            matches = sorted(
                item
                for item in skill.directory.rglob("*")
                if item.is_file() and item.name == raw
            )
            if len(matches) == 1:
                return self._read_within(skill, matches[0])
            if len(matches) > 1:
                candidates = "\n".join(
                    f"- {item.relative_to(skill.directory).as_posix()}"
                    for item in matches
                )
                return f"找到多个同名文件，请通过 filename 指定：\n{candidates}"

        return f"未找到文件：{raw}"

    def _read_within(self, skill: Skill, path: Path) -> str:
        try:
            resolved = path.resolve()
            root = skill.directory.resolve()
        except OSError as exc:
            return f"读取文件失败：{exc}"
        if not resolved.is_relative_to(root):
            return f"拒绝读取：文件必须位于 Skill 目录内（{root}）。"
        if not resolved.is_file():
            return f"不是文件：{resolved}"
        try:
            return resolved.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            return f"读取文件失败：{exc}"


_registry = SkillRegistry()


def init_skills(project_root=None) -> SkillRegistry:
    """按指定项目根目录重新初始化；默认使用启动时工作目录。"""
    global _registry
    _registry = SkillRegistry(project_root)
    return _registry


def get_registry() -> SkillRegistry:
    return _registry


def build_system_prompt(base: str = "") -> str:
    return _registry.build_system_prompt(base)