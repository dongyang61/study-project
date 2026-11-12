"""文件工具：实现、schema 与分发。"""

from __future__ import annotations

import shutil
from pathlib import Path

TEXT_EXTENSIONS = {
    ".txt", ".md", ".py", ".json", ".csv", ".log", ".xml", ".yaml", ".yml",
    ".html", ".css", ".js", ".ts", ".java", ".c", ".cpp", ".h", ".ini",
    ".toml", ".sql", ".sh", ".bat", ".ps1", ".rst",
}


class ToolError(RuntimeError):
    """工具执行错误。"""


def _path(value: str) -> Path:
    return Path(value).expanduser()


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


def get_cwd() -> str:
    return str(Path.cwd())


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
        return f"类型：目录\n扩展名：无\n纯文本：否"
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
    target = folder / filename
    if target.exists():
        raise ToolError(f"文件已存在：{target}")
    target.write_text(content, encoding="utf-8")
    return f"已创建文件：{target}"


def edit_text_file(path: str, content: str) -> str:
    target = _path(path)
    _require_exists(target)
    if not target.is_file():
        raise ToolError(f"不是文件：{target}")
    if not _is_text_file(target):
        raise ToolError(f"不是纯文本文件：{target}")
    target.write_text(content, encoding="utf-8")
    return f"已写入文件：{target}"


def create_dir(path: str) -> str:
    target = _path(path)
    if target.exists():
        if target.is_dir():
            return f"目录已存在：{target}"
        raise ToolError(f"同名文件已存在：{target}")
    target.mkdir(parents=True, exist_ok=True)
    return f"已创建目录：{target}"


def delete_dir(path: str) -> str:
    target = _path(path)
    _require_exists(target)
    if not target.is_dir():
        raise ToolError(f"不是目录：{target}")
    shutil.rmtree(target)
    return f"已删除目录：{target}"


def delete_file(path: str) -> str:
    target = _path(path)
    _require_exists(target)
    if not target.is_file():
        raise ToolError(f"不是文件：{target}")
    target.unlink()
    return f"已删除文件：{target}"


def rename_path(path: str, new_name: str) -> str:
    source = _path(path)
    _require_exists(source)
    target = source.parent / new_name
    if target.exists():
        raise ToolError(f"目标已存在：{target}")
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


_PATH_PROP = {"type": "string", "description": "路径，可使用绝对路径或相对路径。"}

TOOLS = [
    _schema("get_cwd", "获取当前工作目录。", {}, []),
    _schema("list_dir", "列出指定目录下的文件和子目录。", {"path": _PATH_PROP}, ["path"]),
    _schema("get_file_type", "获取路径类型、扩展名及是否为纯文本。", {"path": _PATH_PROP}, ["path"]),
    _schema("read_text_file", "读取指定 UTF-8 纯文本文件的内容。", {"path": _PATH_PROP}, ["path"]),
    _schema(
        "create_file",
        "在指定目录下创建新文件，可写入初始内容。",
        {
            "directory": _PATH_PROP,
            "filename": {"type": "string", "description": "新文件名。"},
            "content": {"type": "string", "description": "初始内容，默认为空。"},
        },
        ["directory", "filename"],
    ),
    _schema(
        "edit_text_file",
        "用给定内容覆盖写入指定纯文本文件。",
        {
            "path": _PATH_PROP,
            "content": {"type": "string", "description": "新的完整文件内容。"},
        },
        ["path", "content"],
    ),
    _schema("create_dir", "创建目录，支持多级目录。", {"path": _PATH_PROP}, ["path"]),
    _schema("delete_dir", "递归删除目录及其全部内容。", {"path": _PATH_PROP}, ["path"]),
    _schema("delete_file", "删除指定文件。", {"path": _PATH_PROP}, ["path"]),
    _schema(
        "rename_path",
        "重命名文件或目录。",
        {
            "path": _PATH_PROP,
            "new_name": {"type": "string", "description": "新名称，不包含路径。"},
        },
        ["path", "new_name"],
    ),
]

FUNCTIONS = {
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


def dispatch(name: str, arguments: dict) -> str:
    func = FUNCTIONS.get(name)
    if not func:
        return f"未知工具：{name}"
    try:
        return func(**arguments)
    except TypeError as exc:
        return f"参数错误：{exc}"
    except Exception as exc:
        return f"执行失败：{exc}"