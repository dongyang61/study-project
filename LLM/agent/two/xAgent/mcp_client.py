"""MCP Client：读取项目 .mcp.json，发现并调用 MCP Server 工具。

每个 Server 在后台事件循环上维护一个持久 ClientSession，跨调用复用；
会话断开或超时后整体关闭，下次调用自动重建。
"""

from __future__ import annotations

import asyncio
import atexit
import concurrent.futures
import json
import os
import re
import threading
from collections import Counter
from contextlib import AsyncExitStack
from dataclasses import dataclass
from pathlib import Path

import httpx2
from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client
from mcp.client.streamable_http import streamable_http_client

from .logger import get_logger

CONFIG_FILE = ".mcp.json"
DEFAULT_TIMEOUT = 60
LOCAL_TOOL_NAMES = {
    "get_cwd", "list_dir", "get_file_type", "read_text_file", "create_file",
    "edit_text_file", "create_dir", "delete_dir", "delete_file", "rename_path",
    "getCurrentTime", "isLeapYear", "RunCli", "fetchWeb", "searchWeb",
    "loadSkill", "createSkill", "createMCP",
}

logger = get_logger("xAgent.mcp")

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
        description = self.description or self.name
        return {
            "type": "function",
            "function": {
                "name": self.exposed_name,
                "description": f"[MCP:{self.server}] {description}",
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


class _BackgroundLoop:
    """单后台线程事件循环，所有持久会话都提交到它上面执行。"""

    def __init__(self) -> None:
        self._loop: asyncio.AbstractEventLoop | None = None
        self._thread: threading.Thread | None = None
        self._ready = threading.Event()
        self._start_lock = threading.Lock()

    def start(self) -> asyncio.AbstractEventLoop:
        with self._start_lock:
            if self._thread is not None and self._thread.is_alive():
                return self._loop  # type: ignore[return-value]
            self._ready.clear()
            self._thread = threading.Thread(
                target=self._run, name="mcp-client-loop", daemon=True
            )
            self._thread.start()
            self._ready.wait()
            return self._loop  # type: ignore[return-value]

    def _run(self) -> None:
        loop = asyncio.new_event_loop()
        asyncio.set_event_loop(loop)
        self._loop = loop
        self._ready.set()
        loop.run_forever()

    def submit(self, coro, timeout: float):
        loop = self.start()
        future = asyncio.run_coroutine_threadsafe(coro, loop)
        try:
            return future.result(timeout)
        except concurrent.futures.TimeoutError:
            future.cancel()
            raise TimeoutError(f"操作超时（{timeout:g} 秒）") from None


_LOOP = _BackgroundLoop()


class _PersistentSession:
    """单个 MCP Server 的持久连接；按需建立，失败后关闭，下次调用重建。"""

    def __init__(self, server: str, conf: dict) -> None:
        self.server = server
        self.conf = conf
        self.lock = threading.Lock()
        self._stack: AsyncExitStack | None = None
        self._session: ClientSession | None = None
        self._closed = False

    def list_tools(self):
        return self._run(self._list_tools)

    def call_tool(self, name: str, arguments: dict):
        return self._run(lambda: self._call_tool(name, arguments))

    def close(self) -> None:
        with self.lock:
            if self._closed:
                return
            self._closed = True
            self._close_locked()

    def _run(self, factory):
        """在锁内确保连接可用后执行一次操作；失败则关闭会话。"""
        with self.lock:
            if self._closed:
                raise MCPError(f"MCP Server {self.server} 已关闭。")
            try:
                _LOOP.submit(self._ensure_open(), self.conf["timeout"])
                return _LOOP.submit(factory(), self.conf["timeout"])
            except Exception:
                self._close_locked()
                raise

    def _close_locked(self) -> None:
        stack, self._stack, self._session = self._stack, None, None
        if stack is None:
            return
        try:
            _LOOP.submit(stack.aclose(), 5)
        except Exception:
            pass

    async def _ensure_open(self) -> None:
        if self._session is not None:
            return

        stack = AsyncExitStack()
        try:
            if self.conf["type"] == "stdio":
                params = StdioServerParameters(
                    command=self.conf["command"],
                    args=self.conf["args"],
                    env=self.conf["env"],
                    cwd=self.conf.get("cwd"),
                )
                read, write = await stack.enter_async_context(stdio_client(params))
            else:
                client = httpx2.AsyncClient(
                    headers=self.conf.get("headers") or None,
                    timeout=self.conf["timeout"],
                )
                await stack.enter_async_context(client)
                read, write = await stack.enter_async_context(
                    streamable_http_client(self.conf["url"], http_client=client)
                )

            session = await stack.enter_async_context(ClientSession(read, write))
            await session.initialize()
        except BaseException:
            await stack.aclose()
            raise

        self._stack = stack
        self._session = session

    async def _list_tools(self):
        result = await self._session.list_tools()
        return result.tools

    async def _call_tool(self, name: str, arguments: dict):
        return await self._session.call_tool(name, arguments)


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
        self._sessions: dict[str, _PersistentSession] = {}
        self._closed = False
        self.discover()
        atexit.register(self.close)

    def discover(self) -> None:
        try:
            configs = load_mcp_config(self.project_root)
        except MCPError as exc:
            self.errors.append(str(exc))
            return

        found = []
        for server_name, raw in configs.items():
            session = None
            try:
                conf = _normalize(server_name, raw)
                old = self._sessions.pop(server_name, None)
                if old is not None:
                    old.close()
                session = _PersistentSession(server_name, conf)
                self._sessions[server_name] = session
                tools = session.list_tools()
            except Exception as exc:
                if session is not None:
                    session.close()
                self._sessions.pop(server_name, None)
                message = _error_text(exc)
                if "Server returned an error response" in message:
                    message += "；请检查 URL 是否有效、type 是否为 streamable_http、是否需要 headers 鉴权"
                self.errors.append(f"MCP Server {server_name} 不可用：{message}")
                logger.warning("MCP Server %s 不可用：%s", server_name, message)
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
            # 始终带来源前缀，避免与本地工具/其他 Server 同名冲突。
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
            if counts[name] > 1:
                logger.info(
                    "MCP 工具重名：%s/%s 暴露为 %s", server_name, name, exposed
                )

    def call(self, exposed_name: str, arguments: dict) -> str:
        tool = self.tools.get(exposed_name)
        if tool is None:
            return f"未知 MCP 工具：{exposed_name}"
        session = self._sessions.get(tool.server)
        if session is None:
            return f"MCP Server 未连接：{tool.server}"
        try:
            logger.info("调用 MCP 工具 %s/%s", tool.server, tool.name)
            result = session.call_tool(tool.name, arguments)
        except Exception as exc:
            logger.error("MCP 工具调用失败 %s/%s：%s", tool.server, tool.name, exc)
            return f"MCP 工具调用失败（{tool.server}/{tool.name}）：{_error_text(exc)}"
        return _format_result(result)

    def close(self) -> None:
        """关闭全部持久连接（幂等），确保 stdio 子进程退出。"""
        if self._closed:
            return
        self._closed = True
        for session in list(self._sessions.values()):
            try:
                session.close()
            except Exception:
                pass
        self._sessions.clear()


_manager: MCPManager | None = None


def get_mcp_manager() -> MCPManager:
    global _manager
    if _manager is None:
        _manager = MCPManager()
    return _manager


def reset_mcp_manager() -> None:
    global _manager
    manager, _manager = _manager, None
    if manager is not None:
        manager.close()


def mcp_tool_schemas() -> list[dict]:
    return [tool.schema() for tool in get_mcp_manager().tools.values()]


def is_mcp_tool(name: str) -> bool:
    return name in get_mcp_manager().tools


def call_mcp_tool(name: str, arguments: dict) -> str:
    return get_mcp_manager().call(name, arguments)
