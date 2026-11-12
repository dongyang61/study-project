"""createMCP：把 MCP Server 配置写入项目根目录的 .mcp.json。"""

from __future__ import annotations

import json
from pathlib import Path

from ..mcp_client import CONFIG_FILE, reset_mcp_manager

__all__ = ["TOOL_NAME", "CREATE_MCP_TOOL", "create_mcp"]

TOOL_NAME = "createMCP"

CREATE_MCP_TOOL = {
    "type": "function",
    "function": {
        "name": TOOL_NAME,
        "description": (
            "将 MCP Server 配置写入当前项目目录的 .mcp.json，已存在的同名 Server 会被更新。"
            "支持 stdio（command/args）和 streamable_http（url/headers）。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "MCP Server 名称，例如 Bazi-MCP。",
                },
                "type": {
                    "type": "string",
                    "enum": ["stdio", "streamable_http"],
                    "description": "连接类型；省略时根据 command/url 自动推断。",
                },
                "url": {
                    "type": "string",
                    "description": "streamable_http 的服务地址。",
                },
                "command": {
                    "type": "string",
                    "description": "stdio 的可执行程序，例如 npx、uvx、python。",
                },
                "args": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "stdio 程序参数列表。",
                },
                "env": {
                    "type": "object",
                    "additionalProperties": {"type": "string"},
                    "description": "stdio 进程的额外环境变量。",
                },
                "headers": {
                    "type": "object",
                    "additionalProperties": {"type": "string"},
                    "description": "streamable_http 的请求头，例如 Authorization。",
                },
                "cwd": {
                    "type": "string",
                    "description": "stdio 进程的工作目录，可选。",
                },
            },
            "required": ["name"],
            "additionalProperties": False,
        },
    },
}


def _http_type(value: str) -> str:
    value = value.strip().lower()
    return "streamable_http" if value in {"http", "streamable-http", "streamablehttp"} else value


def create_mcp(
    name: str,
    type: str | None = None,
    url: str | None = None,
    command: str | None = None,
    args: list[str] | None = None,
    env: dict | None = None,
    headers: dict | None = None,
    cwd: str | None = None,
    project_root=None,
) -> str:
    """写入/更新 .mcp.json；错误以字符串返回，避免中断 Agent 循环。"""
    try:
        if not isinstance(name, str) or not name.strip():
            return "createMCP 执行失败：name 不能为空。"
        name = name.strip()

        kind = _http_type(type or "")
        if not kind:
            kind = "stdio" if command else "streamable_http" if url else ""

        if kind == "stdio":
            if not isinstance(command, str) or not command.strip():
                return "createMCP 执行失败：stdio 配置需要 command。"
            if args is not None and (
                not isinstance(args, list) or not all(isinstance(a, str) for a in args)
            ):
                return "createMCP 执行失败：args 必须是字符串列表。"
            if env is not None and not isinstance(env, dict):
                return "createMCP 执行失败：env 必须是对象。"
            conf = {"type": "stdio", "command": command.strip()}
            if args:
                conf["args"] = args
            if env:
                conf["env"] = {str(k): str(v) for k, v in env.items()}
            if cwd:
                conf["cwd"] = str(cwd)
        elif kind == "streamable_http":
            if not isinstance(url, str) or not url.strip():
                return "createMCP 执行失败：streamable_http 配置需要 url。"
            if headers is not None and not isinstance(headers, dict):
                return "createMCP 执行失败：headers 必须是对象。"
            conf = {"type": "streamable_http", "url": url.strip()}
            if headers:
                conf["headers"] = {str(k): str(v) for k, v in headers.items()}
        else:
            return f"createMCP 执行失败：不支持的 type：{kind or '未指定'}"

        path = Path(project_root or Path.cwd()) / CONFIG_FILE
        data: dict = {}
        if path.is_file():
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except (OSError, json.JSONDecodeError) as exc:
                return f"createMCP 执行失败：现有 {path} 无法解析：{exc}"
            if not isinstance(data, dict):
                return f"createMCP 执行失败：现有 {path} 不是 JSON 对象。"

        servers = data.setdefault("mcpServers", {})
        if not isinstance(servers, dict):
            return f"createMCP 执行失败：{path} 中的 mcpServers 不是对象。"
        servers[name] = conf

        try:
            path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        except OSError as exc:
            return f"createMCP 执行失败：写入 {path} 失败：{exc}"

        reset_mcp_manager()
        return f"已保存 MCP Server「{name}」到 {path}（{kind}）。"
    except Exception as exc:  # 兜底，避免工具异常中断 Agent 循环
        return f"createMCP 执行失败：{exc}"