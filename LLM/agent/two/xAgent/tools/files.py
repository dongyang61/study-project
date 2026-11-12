"""本地文件工具：实现、schema 与分发。

安全边界：
- 写/删/改名默认限制在会话工作目录内（Path.resolve() + is_relative_to）；
- 破坏性/覆盖操作必须显式 confirm=true，否则只返回目标摘要，不产生副作用；
- 如需放开工作目录限制，在 config.ini [agent] 设置 workspace_allow_outside=true
  （会允许修改工作目录之外的文件，风险自负）。
"""

from __future__ import annotations

import shutil
from pathlib import Path

from ..settings import agent_settings

TEXT_EXTENSIONS = {
    ".txt", ".md", ".py", ".json", ".csv", ".log", ".xml", ".yaml", ".yml",
    ".html", ".css", ".js", ".ts", ".java", ".c", ".cpp", ".h", ".ini",
    ".toml", ".sql", ".sh", ".bat", ".ps1", ".rst",
}

_WORKSPACE = Path.cwd().resolve()


class ToolError(RuntimeError):
    """工具执行错误。"""


def set_workspace(path=None) -> Path:
    """设置文件工具的工作目录（默认进程启动目录；会话恢复时跟随元信息）。"""
    global _WORKSPACE
    _WORKSPACE = Path(path or Path.cwd()).expanduser().resolve()
    return _WORKSPACE


def get_workspace() -> Path:
    return _WORKSPACE


def _allow_outside() -> bool:
    return bool(agent_settings().get("workspace_allow_outside", False))


def _path(value) -> Path:
    path = Path(str(value)).expanduser()
    return path if path.is_absolute() else _WORKSPACE / path


def _guard_write(path: Path, action: str) -> None:
    if _allow_outside():
        return
    try:
        resolved = path.resolve(strict=False)
    except OSError as exc:
        raise ToolError(f"无法解析路径：{path}（{exc}）") from exc
    workspace = _WORKSPACE.resolve()
    if not resolved.is_relative_to(workspace):
        raise ToolError(
            f"拒绝{action}：{resolved} 不在工作目录 {workspace} 内。"
            "如需放开，请在 config.ini [agent] 设置 workspace_allow_outside=true"
            "（会允许修改工作目录之外的文件）。"
        )


def _require_exists(path: Path) -> None:
    if not path.exists():
        raise ToolError(f"路径不存在：{path}")


def _is_text_file(path: Path) -> bool:
    if path.suffix.lower() in TEXT_EXTENSIONS:
        return True
    try:
        data = path.read_bytes()[:4096]
    except OSError:
        return False
    if b"\x00" in data:
        return False
    try:
        data.decode("utf-8")
        return True
    except UnicodeDecodeError:
        return False


def _summary(path: Path) -> str:
    try:
        if path.is_dir():
            count = sum(1 for _ in path.iterdir())
            return f"{path}（目录，{count} 个直接子项）"
        if path.is_file():
            return f"{path}（文件，{path.stat().st_size} 字节）"
    except OSError:
        pass
    return str(path)


def _need_confirm(action: str, target: Path, confirm, extra: str = "") -> str | None:
    if confirm is True:
        return None
    suffix = f"；{extra}" if extra else ""
    return (
        f"需要 confirm=true 才能{action}。目标摘要：{_summary(target)}{suffix}。"
        "请先向用户确认，再以 confirm=true 重新调用。"
    )


def get_cwd() -> str:
    return str(_WORKSPACE)


def list_dir(path: str) -> str:
    target = _path(path)
    _require_exists(target)
    if not target.is_dir():
        raise ToolError(f"不是目录：{target}")
    rows = []
    for item in sorted(target.iterdir(), key=lambda p: (not p.is_dir(), p.name.lower())):
        kind = "目录" if item.is_dir() else "文件"
        rows.append(f"[{kind}] {item.name}")
    return "\n".join(rows) if rows else "目录为空。"


def get_file_type(path: str) -> str:
    target = _path(path)
    _require_exists(target)
    if target.is_dir():
        return "类型：目录\n扩展名：无\n纯文本：否"
    return (
        f"类型：文件\n扩展名：{target.suffix or '无'}\n"
        f"纯文本：{'是' if _is_text_file(target) else '否'}"
    )


def read_text_file(path: str) -> str:
    target = _path(path)
    _require_exists(target)
    if not target.is_file():
        raise ToolError(f"不是文件：{target}")
    if not _is_text_file(target):
        raise ToolError(f"不是纯文本文件：{target}")
    try:
        return target.read_text(encoding="utf-8")
    except UnicodeDecodeError as exc:
        raise ToolError(f"文件不是 UTF-8 纯文本：{target}") from exc


def create_file(directory: str, filename: str, content: str = "") -> str:
    folder = _path(directory)
    _require_exists(folder)
    if not folder.is_dir():
        raise ToolError(f"不是目录：{folder}")
    target = folder / str(filename)
    _guard_write(target, "创建文件")
    if target.exists():
        raise ToolError(f"文件已存在：{target}")
    target.write_text(content, encoding="utf-8")
    return f"已创建文件：{target}"


def edit_text_file(path: str, content: str, confirm: bool = False) -> str:
    target = _path(path)
    _require_exists(target)
    if not target.is_file():
        raise ToolError(f"不是文件：{target}")
    if not _is_text_file(target):
        raise ToolError(f"不是纯文本文件：{target}")
    _guard_write(target, "覆盖写入文件")
    blocked = _need_confirm("覆盖写入文件", target, confirm)
    if blocked:
        return blocked
    target.write_text(content, encoding="utf-8")
    return f"已写入文件：{target}"


def create_dir(path: str) -> str:
    target = _path(path)
    _guard_write(target, "创建目录")
    if target.exists():
        if target.is_dir():
            return f"目录已存在：{target}"
        raise ToolError(f"同名文件已存在：{target}")
    target.mkdir(parents=True, exist_ok=True)
    return f"已创建目录：{target}"


def delete_dir(path: str, confirm: bool = False) -> str:
    target = _path(path)
    _require_exists(target)
    if not target.is_dir():
        raise ToolError(f"不是目录：{target}")
    _guard_write(target, "删除目录")
    blocked = _need_confirm("递归删除目录", target, confirm)
    if blocked:
        return blocked
    shutil.rmtree(target)
    return f"已删除目录：{target}"


def delete_file(path: str, confirm: bool = False) -> str:
    target = _path(path)
    _require_exists(target)
    if not target.is_file():
        raise ToolError(f"不是文件：{target}")
    _guard_write(target, "删除文件")
    blocked = _need_confirm("删除文件", target, confirm)
    if blocked:
        return blocked
    target.unlink()
    return f"已删除文件：{target}"


def rename_path(path: str, new_name: str, confirm: bool = False) -> str:
    source = _path(path)
    _require_exists(source)
    _guard_write(source, "重命名/移动路径")
    target = source.parent / str(new_name)
    _guard_write(target, "重命名/移动路径")
    if target.exists():
        raise ToolError(f"目标已存在：{target}")
    blocked = _need_confirm(
        "重命名/移动路径", source, confirm, extra=f"新路径：{target}"
    )
    if blocked:
        return blocked
    source.rename(target)
    return f"已重命名：{source} -> {target}"


def _schema(name: str, description: str, properties: dict, required: list[str]) -> dict:
    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description,
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required,
                "additionalProperties": False,
            },
        },
    }


_PATH_PROP = {
    "type": "string",
    "description": "路径；相对路径基于会话工作目录，默认禁止越出工作目录。",
}
_CONFIRM_PROP = {
    "type": "boolean",
    "description": (
        "破坏性/覆盖操作必须显式传 true。首次调用请传 false 获取目标摘要，"
        "向用户确认后再传 true 执行。"
    ),
}

FILE_TOOLS = [
    _schema("get_cwd", "获取当前会话工作目录（绝对路径）。", {}, []),
    _schema("list_dir", "列出指定目录下的文件和子目录。", {"path": _PATH_PROP}, ["path"]),
    _schema("get_file_type", "获取路径类型、扩展名及是否为纯文本。", {"path": _PATH_PROP}, ["path"]),
    _schema("read_text_file", "读取指定 UTF-8 纯文本文件的内容。", {"path": _PATH_PROP}, ["path"]),
    _schema(
        "create_file",
        "在指定目录下创建新文件；已存在时拒绝，不覆盖。",
        {
            "directory": _PATH_PROP,
            "filename": {"type": "string", "description": "新文件名。"},
            "content": {"type": "string", "description": "初始内容，默认为空。"},
        },
        ["directory", "filename"],
    ),
    _schema(
        "edit_text_file",
        "用给定内容覆盖写入指定纯文本文件。覆盖属于破坏性操作，需 confirm=true。",
        {
            "path": _PATH_PROP,
            "content": {"type": "string", "description": "新的完整文件内容。"},
            "confirm": _CONFIRM_PROP,
        },
        ["path", "content", "confirm"],
    ),
    _schema("create_dir", "创建目录，支持多级目录。", {"path": _PATH_PROP}, ["path"]),
    _schema(
        "delete_dir",
        "递归删除目录及其全部内容。需 confirm=true，否则只返回目标摘要。",
        {"path": _PATH_PROP, "confirm": _CONFIRM_PROP},
        ["path", "confirm"],
    ),
    _schema(
        "delete_file",
        "删除指定文件。需 confirm=true，否则只返回目标摘要。",
        {"path": _PATH_PROP, "confirm": _CONFIRM_PROP},
        ["path", "confirm"],
    ),
    _schema(
        "rename_path",
        "重命名文件或目录。需 confirm=true，否则只返回目标摘要。",
        {
            "path": _PATH_PROP,
            "new_name": {"type": "string", "description": "新名称或相对路径。"},
            "confirm": _CONFIRM_PROP,
        },
        ["path", "new_name", "confirm"],
    ),
]

FILE_FUNCTIONS = {
    "get_cwd": get_cwd,
    "list_dir": list_dir,
    "get_file_type": get_file_type,
    "read_text_file": read_text_file,
    "create_file": create_file,
    "edit_text_file": edit_text_file,
    "create_dir": create_dir,
    "delete_dir": delete_dir,
    "delete_file": delete_file,
    "rename_path": rename_path,
}
