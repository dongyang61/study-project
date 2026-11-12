"""createSkill：把技能原子落盘到 <workspace>/.agents/skills/<name>/SKILL.md。

约束：
- name 仅允许 `^[a-z0-9][a-z0-9-_]{0,63}$`；
- 同名目录已存在时拒绝覆盖，并返回可用技能列表；
- 附件只允许技能目录内的相对路径，禁止绝对路径与 `..`；
- 先写临时目录，再 `os.replace` 重命名，失败不留半成品。
"""

from __future__ import annotations

import os
import re
import secrets
from pathlib import Path, PurePosixPath

from ..skills import SKILLS_DIR, SKILL_FILE, SkillRegistry, init_skills

__all__ = ["TOOL_NAME", "CREATE_SKILL_TOOL", "SkillCreateError", "create_skill"]

TOOL_NAME = "createSkill"
SKILL_NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-_]{0,63}$")


class SkillCreateError(RuntimeError):
    """技能创建参数或落盘错误。"""


CREATE_SKILL_TOOL = {
    "type": "function",
    "function": {
        "name": TOOL_NAME,
        "description": (
            "创建一个新技能：在 <工作目录>/.agents/skills/<name>/ 下写入带 YAML frontmatter"
            "（name/description）的 SKILL.md，可附加多个说明文件。若同名技能已存在会拒绝覆盖"
            "并返回现有技能列表。创建后立即刷新技能索引，后续启动也会自动发现。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "pattern": "^[a-z0-9][a-z0-9-_]{0,63}$",
                    "description": "技能名，仅小写字母/数字/连字符/下划线，例如 pdf-report。",
                },
                "description": {
                    "type": "string",
                    "description": "一句话说明技能用途，会写入 frontmatter 并注入系统提示。",
                },
                "content": {
                    "type": "string",
                    "description": "SKILL.md 正文（frontmatter 之后的 Markdown 说明）。",
                },
                "files": {
                    "type": "array",
                    "description": "可选附件列表；path 必须是技能目录内的相对路径。",
                    "items": {
                        "type": "object",
                        "properties": {
                            "path": {
                                "type": "string",
                                "description": "相对路径，例如 examples/demo.md。",
                            },
                            "content": {"type": "string", "description": "文件内容。"},
                        },
                        "required": ["path"],
                        "additionalProperties": False,
                    },
                },
            },
            "required": ["name", "description", "content"],
            "additionalProperties": False,
        },
    },
}


def _yaml_value(value: str) -> str:
    text = " ".join(str(value).split())
    if not text:
        return '""'
    if text[0] in "|>\"'":
        return '"' + text.replace('"', '\\"') + '"'
    return text


def _strip_frontmatter(text: str) -> str:
    lines = text.splitlines()
    if lines and lines[0].strip() == "---":
        for index in range(1, len(lines)):
            if lines[index].strip() == "---":
                return "\n".join(lines[index + 1 :]).lstrip("\n")
    return text


def _render_skill_md(name: str, description: str, content: str) -> str:
    body = _strip_frontmatter(content or "").strip()
    header = (
        "---\n"
        f"name: {_yaml_value(name)}\n"
        f"description: {_yaml_value(description)}\n"
        "---\n"
    )
    return header + ("\n" + body + "\n" if body else "")


def _safe_attachment_path(raw) -> PurePosixPath:
    if not isinstance(raw, str) or not raw.strip():
        raise SkillCreateError("附件 path 不能为空。")
    normalized = raw.strip().replace("\\", "/")
    if normalized.startswith("/") or re.match(r"^[A-Za-z]:", normalized):
        raise SkillCreateError(f"附件路径不能是绝对路径：{raw}")
    path = PurePosixPath(normalized)
    if not path.parts or any(part in {"..", ""} for part in path.parts):
        raise SkillCreateError(f"附件路径不能包含 '..'：{raw}")
    if normalized.lower() == SKILL_FILE.lower():
        raise SkillCreateError("附件不能覆盖 SKILL.md。")
    return path


def _write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="\n") as fh:
        fh.write(content)
        fh.flush()
        os.fsync(fh.fileno())


def _existing_names(root: Path) -> list[str]:
    return sorted(SkillRegistry(root).skills)


def create_skill(
    name: str,
    description: str,
    content: str,
    files: list[dict] | None = None,
    project_root=None,
) -> str:
    """创建技能；错误以字符串返回，避免中断 Agent 循环。"""
    try:
        if not isinstance(name, str) or not SKILL_NAME_RE.fullmatch(name.strip()):
            return (
                "createSkill 执行失败：name 必须匹配 "
                "^[a-z0-9][a-z0-9-_]{0,63}$（仅小写字母/数字/-/_，且以字母或数字开头）。"
            )
        name = name.strip()
        if not isinstance(description, str) or not description.strip():
            return "createSkill 执行失败：description 不能为空。"
        if content is None:
            content = ""
        if not isinstance(content, str):
            return "createSkill 执行失败：content 必须是字符串。"
        if files is not None and not isinstance(files, list):
            return "createSkill 执行失败：files 必须是数组。"

        root = Path(project_root or Path.cwd()).resolve()
        skills_root = root / SKILLS_DIR
        target = skills_root / name
        if target.exists():
            available = "、".join(_existing_names(root)) or "无"
            return (
                f"拒绝覆盖：Skill「{name}」已存在（{target}）。"
                f"如确需修改，请使用其他名称或先手动删除。现有技能：{available}"
            )

        validated: list[tuple[PurePosixPath, str]] = []
        for item in files or []:
            if not isinstance(item, dict):
                return "createSkill 执行失败：files 的每一项必须是对象。"
            relative = _safe_attachment_path(item.get("path"))
            item_content = item.get("content", "")
            if not isinstance(item_content, str):
                return f"createSkill 执行失败：附件 {relative} 的 content 必须是字符串。"
            validated.append((relative, item_content))

        skills_root.mkdir(parents=True, exist_ok=True)
        staging = skills_root / f".tmp-{name}-{secrets.token_hex(4)}"
        try:
            staging.mkdir()
            _write_text(
                staging / SKILL_FILE,
                _render_skill_md(name, description.strip(), content),
            )
            staging_resolved = staging.resolve()
            for relative, item_content in validated:
                destination = staging.joinpath(*relative.parts)
                if not destination.resolve().is_relative_to(staging_resolved):
                    raise SkillCreateError(f"附件路径越界：{relative}")
                _write_text(destination, item_content)
            try:
                os.replace(staging, target)
            except FileExistsError:
                available = "、".join(_existing_names(root)) or "无"
                return (
                    f"拒绝覆盖：Skill「{name}」在写入期间已被创建。现有技能：{available}"
                )
        except Exception:
            _cleanup(staging)
            raise

        init_skills(root)
        available = "、".join(_existing_names(root)) or "无"
        attachment_note = f"，附件 {len(validated)} 个" if validated else ""
        return (
            f"已创建 Skill「{name}」：{target / SKILL_FILE}{attachment_note}。"
            f"技能索引已刷新，当前可用：{available}"
        )
    except SkillCreateError as exc:
        return f"createSkill 执行失败：{exc}"
    except Exception as exc:  # 兜底，避免工具异常中断 Agent 循环
        return f"createSkill 执行失败：{exc}"


def _cleanup(path: Path) -> None:
    try:
        if not path.exists():
            return
        for item in sorted(path.rglob("*"), reverse=True):
            if item.is_file() or item.is_symlink():
                item.unlink()
            elif item.is_dir():
                item.rmdir()
        path.rmdir()
    except OSError:
        pass
