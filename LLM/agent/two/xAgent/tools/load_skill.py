"""loadSkill：按需加载 Skill 的 SKILL.md 或附件文件。"""

from __future__ import annotations

from ..skills import get_registry

__all__ = ["TOOL_NAME", "LOAD_SKILL_TOOL", "load_skill"]

TOOL_NAME = "loadSkill"

LOAD_SKILL_TOOL = {
    "type": "function",
    "function": {
        "name": TOOL_NAME,
        "description": (
            "加载指定 Skill 的完整说明或附件文件。仅提供 name 时返回 SKILL.md 全文；"
            "提供 filename 时只读取 Skill 目录内的相对路径（禁止绝对路径与 .. 越界）；"
            "单次返回内容超过 50000 字符会截断并提示。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Skill 的名称，即 SKILL.md frontmatter 中的 name。",
                },
                "filename": {
                    "type": "string",
                    "description": (
                        "可选附件路径或文件名。只给文件名时会递归搜索该 Skill 目录；"
                        "存在多个同名文件时返回候选路径。"
                    ),
                },
            },
            "required": ["name"],
            "additionalProperties": False,
        },
    },
}


def load_skill(name: str, filename: str | None = None) -> str:
    """读取 Skill 内容；错误以字符串返回，避免中断 Agent 循环。"""
    try:
        if not isinstance(name, str) or not name.strip():
            return "loadSkill 执行失败：name 不能为空。"
        if filename is not None and not isinstance(filename, str):
            return "loadSkill 执行失败：filename 必须是字符串。"
        return get_registry().load(name.strip(), filename)
    except Exception as exc:  # 兜底，避免工具异常中断 Agent 循环
        return f"loadSkill 执行失败：{exc}"