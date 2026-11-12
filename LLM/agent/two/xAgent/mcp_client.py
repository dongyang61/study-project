"""MCP Client：读取项目 .mcp.json，发现并调用 MCP Server 工具。

同步 Agent 循环通过 asyncio.run 为每次操作建立独立会话，避免共享事件循环。
"""

from __future__ import annotations

import asyncio
import json
import os
import re
from collections import Counter
from contextlib import asynccontextmanager
from dataclasses import dataclass
from pathlib import Path

import httpx2
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client

CONFIG_FILE = ".mcp.json"
DEFAULT_TIMEOUT = 60
LOCAL_TOOL_NAMES = {"RunCli", "fetchWeb", "searchWeb", "loadSkill", "createMCP"}

_HTTP_TYPES = {"streamable_http", "streamable-http", "streamablehttp", "http"}
_NAME_RE = re.compile(r"[^A-Za-z0-9_-]")


class MCPError(RuntimeError):
    """MCP 配置或调用错误。"""


@dataclass
class MCPTool:
    server: str
    name: str
    exposed_name: str
    description: str
    input_schema: dict

    def schema(self) -> dict:
        return {
            "type": "function",
            "function": {
                "name": self.exposed_name,
                "description": self.description or self.name,
                "parameters": self.input_schema or {"type": "object", "properties": {}},
            },
        }


def _error_text(exc: BaseException) -> str:
    if isinstance(exc, BaseExceptionGroup):
        return "；".join(_error_text(item) for item in exc.exceptions)
    message = str(exc).strip()
    return f"{type(exc).__name__}: {message}" if message else type(exc).__name__


def _safe(value: str) -> str:
    return _NAME_RE.sub("_", value) or "mcp"


def load_mcp_config(project_root=None) -> dict[str, dict]:
    """读取 <project_root>/.mcp.json 的 mcpServers。"""
    path = Path(project_root or Path.cwd()) / CONFIG_FILE
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MCPError(f"读取 {path} 失败：{exc}") from exc
    servers = data.get("mcpServers") if isinstance(data, dict) else None
    if not isinstance(servers, dict):
        raise MCPError(f"{path} 缺少 mcpServers 对象。")
    return servers


def _normalize(name: str, conf: dict) -> dict:
    if not isinstance(conf, dict):
        raise MCPError("Server 配置必须是对象。")

    kind = str(conf.get("type") or "").strip().lower()
    if not kind:
        kind = "stdio" if conf.get("command") else "streamable_http" if conf.get("url") else ""
    if kind in _HTTP_TYPES:
        kind = "streamable_http"

    timeout = conf.get("timeout", DEFAULT_TIMEOUT)
    try:
        timeout = float(timeout)
    except (TypeError, ValueError):
        timeout = DEFAULT_TIMEOUT
    if timeout <= 0:
        timeout = DEFAULT_TIMEOUT

    if kind == "stdio":
        command = conf.get("command")
        if not isinstance(command, str) or not command.strip():
            raise MCPError("stdio 配置缺少 command。")
        args = conf.get("args") or []
        if not isinstance(args, list) or not all(isinstance(a, str) for a in args):
            raise MCPError("stdio 的 args 必须是字符串列表。")
        env = conf.get("env")
        if env is not None and not isinstance(env, dict):
            raise MCPError("stdio 的 env 必须是对象。")
        return {
            "type": kind,
            "command": command.strip(),
            "args": args,
            "env": {**os.environ, **{str(k): str(v) for k, v in (env or {}).items()}},
            "cwd": conf.get("cwd"),
            "timeout": timeout,
        }

    if kind == "streamable_http":
        url = conf.get("url")
        if not isinstance(url, str) or not url.strip():
            raise MCPError("streamable_http 配置缺少 url。")
        headers = conf.get("headers")
        if headers is not None and not isinstance(headers, dict):
            raise MCPError("streamable_http 的 headers 必须是对象。")
        return {
            "type": kind,
            "url": url.strip(),
            "headers": {str(k): str(v) for k, v in (headers or {}).items()},
            "timeout": timeout,
        }

    raise MCPError(f"不支持的 MCP 传输类型：{kind or '未指定'}")


@asynccontextmanager
async def _session(conf: dict):
    if conf["type"] == "stdio":
        params = StdioServerParameters(
            command=conf["command"],
            args=conf["args"],
            env=conf["env"],
            cwd=conf.get("cwd"),
        )
        async with stdio_client(params) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                yield session
        return

    client = httpx2.AsyncClient(headers=conf.get("headers") or None, timeout=conf["timeout"])
    async with client:
        async with streamable_http_client(conf["url"], http_client=client) as (read, write):
            async with ClientSession(read, write) as session:
                await session.initialize()
                yield session


def _format_result(result) -> str:
    parts = []
    if getattr(result, "is_error", False):
        parts.append("MCP 工具返回错误（isError=true）。")

    texts = []
    others = []
    for item in getattr(result, "content", None) or []:
        text = getattr(item, "text", None)
        if text is not None:
            texts.append(text)
            continue
        try:
            others.append(item.model_dump_json(exclude_none=True))
        except Exception:
            others.append(str(item))

    if texts:
        parts.extend(["文本内容：", "\n".join(texts)])
    if others:
        parts.extend(["其他内容：", "\n".join(others)])

    structured = getattr(result, "structured_content", None) or getattr(
        result, "structuredContent", None
    )
    if structured:
        try:
            value = json.dumps(structured, ensure_ascii=False, indent=2, default=str)
        except Exception:
            value = str(structured)
        parts.extend(["结构化数据：", value])

    return "\n".join(parts) or "（工具未返回内容）"


class MCPManager:
    def __init__(self, project_root=None, reserved=None) -> None:
        self.project_root = Path(project_root or Path.cwd()).resolve()
        self.reserved = set(reserved or LOCAL_TOOL_NAMES)
        self.servers: dict[str, dict] = {}
        self.tools: dict[str, MCPTool] = {}
        self.errors: list[str] = []
        self.discover()

    def discover(self) -> None:
        try:
            configs = load_mcp_config(self.project_root)
        except MCPError as exc:
            self.errors.append(str(exc))
            return

        found = []
        for server_name, raw in configs.items():
            try:
                conf = _normalize(server_name, raw)
                tools = asyncio.run(
                    asyncio.wait_for(self._list_tools(conf), timeout=conf["timeout"])
                )
            except Exception as exc:
                message = _error_text(exc)
                if "Server returned an error response" in message:
                    message += "；请检查 URL 是否有效、type 是否为 streamable_http、是否需要 headers 鉴权"
                self.errors.append(f"MCP Server {server_name} 不可用：{message}")
                continue
            self.servers[server_name] = conf
            for tool in tools:
                found.append(
                    (
                        server_name,
                        tool.name,
                        tool.description or "",
                        getattr(tool, "input_schema", None)
                        or getattr(tool, "inputSchema", None)
                        or {},
                    )
                )

        counts = Counter(name for _, name, _, _ in found)
        used: set[str] = set()
        for server_name, name, description, schema in found:
            exposed = name
            if (
                counts[name] > 1
                or name in self.reserved
                or _NAME_RE.search(name)
            ):
                exposed = f"{_safe(server_name)}__{_safe(name)}"
            base = exposed
            index = 2
            while exposed in used:
                exposed = f"{base}_{index}"
                index += 1
            used.add(exposed)
            self.tools[exposed] = MCPTool(
                server_name, name, exposed, description, schema
            )

    async def _list_tools(self, conf: dict):
        async with _session(conf) as session:
            result = await session.list_tools()
            return result.tools

    def call(self, exposed_name: str, arguments: dict) -> str:
        tool = self.tools.get(exposed_name)
        if tool is None:
            return f"未知 MCP 工具：{exposed_name}"
        conf = self.servers[tool.server]
        try:
            result = asyncio.run(
                asyncio.wait_for(
                    self._call_tool(conf, tool.name, arguments), timeout=conf["timeout"]
                )
            )
        except Exception as exc:
            return f"MCP 工具调用失败（{tool.server}/{tool.name}）：{_error_text(exc)}"
        return _format_result(result)

    async def _call_tool(self, conf: dict, name: str, arguments: dict):
        async with _session(conf) as session:
            return await session.call_tool(name, arguments)


_manager: MCPManager | None = None


def get_mcp_manager() -> MCPManager:
    global _manager
    if _manager is None:
        _manager = MCPManager()
    return _manager


def reset_mcp_manager() -> None:
    global _manager
    _manager = None


def mcp_tool_schemas() -> list[dict]:
    return [tool.schema() for tool in get_mcp_manager().tools.values()]


def is_mcp_tool(name: str) -> bool:
    return name in get_mcp_manager().tools


def call_mcp_tool(name: str, arguments: dict) -> str:
    return get_mcp_manager().call(name, arguments)