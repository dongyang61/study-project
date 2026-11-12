#!/usr/bin/env python3
"""AnythingLLM MCP Server - 工作区、文档上传/向量化与检索问答。

Streamable HTTP，无状态：同时兼容 2025-03-26 / 2025-06-18 / 2025-11-25
（initialize 握手）和 2026-07-28（无握手、无 session）。
仅使用 Python 标准库。
"""
from __future__ import annotations

import json
import logging
import mimetypes
import os
import secrets
import socket
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

ANYTHINGLLM_URL = os.environ.get("ANYTHINGLLM_URL", "http://localhost:3001").rstrip("/")
ANYTHINGLLM_API_KEY = os.environ.get("ANYTHINGLLM_API_KEY", "").strip()
HOST = os.environ.get("MCP_HOST", "127.0.0.1")
PORT = int(os.environ.get("MCP_PORT", "8765"))
REQUEST_TIMEOUT = 60
MAX_UPLOAD_BYTES = 50 * 1024 * 1024

logger = logging.getLogger("anythingllm-mcp")
if not logger.handlers:
    _handler = logging.StreamHandler(sys.stderr)
    _handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s [%(name)s] %(message)s")
    )
    logger.addHandler(_handler)
    logger.setLevel(logging.INFO)

MISSING_KEY_MESSAGE = (
    "未配置 ANYTHINGLLM_API_KEY：请先设置环境变量后再启动本 MCP Server，"
    "且不会向上游 AnythingLLM 发起请求。"
)

SERVER_INFO = {"name": "anythingllm-mcp", "version": "1.1.0"}
LEGACY_VERSIONS = ["2025-11-25", "2025-06-18", "2025-03-26"]
MODERN_VERSIONS = ["2026-07-28"]
SUPPORTED_VERSIONS = MODERN_VERSIONS + LEGACY_VERSIONS
LATEST_LEGACY = LEGACY_VERSIONS[0]
WORKSPACE_PROP = {
    "type": "string",
    "description": "工作区 slug；省略时自动使用第一个工作区。",
}

TOOLS = [
    {
        "name": "first_workspace_files",
        "description": (
            "读取本机 AnythingLLM 中第一个工作区的文件信息，"
            "返回标题、来源路径、作者、发布时间、词数、token 数、置顶状态等。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
        "outputSchema": {
            "type": "object",
            "properties": {
                "workspace": {"type": "object"},
                "fileCount": {"type": "integer"},
                "files": {"type": "array", "items": {"type": "object"}},
            },
            "required": ["workspace", "fileCount", "files"],
        },
    },
    {
        "name": "list_workspaces",
        "description": "列出 AnythingLLM 中全部工作区（id、name、slug）。",
        "inputSchema": {
            "type": "object",
            "properties": {},
            "additionalProperties": False,
        },
    },
    {
        "name": "workspace_files",
        "description": "读取指定工作区（或第一个工作区）的文件列表与元信息。",
        "inputSchema": {
            "type": "object",
            "properties": {"workspace_slug": WORKSPACE_PROP},
            "additionalProperties": False,
        },
    },
    {
        "name": "upload_document",
        "description": (
            "上传本机文件到 AnythingLLM 文档库，并加入指定工作区完成向量化。"
            "file_path 必须是本机可读文件的绝对路径或相对路径。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "file_path": {
                    "type": "string",
                    "description": "本机文件路径，最大 50 MiB。",
                },
                "workspace_slug": WORKSPACE_PROP,
                "embed": {
                    "type": "boolean",
                    "description": "是否加入工作区并触发向量化，默认 true。",
                    "default": True,
                },
            },
            "required": ["file_path"],
            "additionalProperties": False,
        },
    },
    {
        "name": "ask_workspace",
        "description": (
            "向指定工作区提问。mode=query 使用文档检索增强，mode=chat 使用会话模式；"
            "返回回答与引用来源。"
        ),
        "inputSchema": {
            "type": "object",
            "properties": {
                "message": {"type": "string", "description": "要提问的内容。"},
                "workspace_slug": WORKSPACE_PROP,
                "mode": {
                    "type": "string",
                    "enum": ["query", "chat"],
                    "default": "query",
                    "description": "检索增强（query）或普通会话（chat）。",
                },
            },
            "required": ["message"],
            "additionalProperties": False,
        },
    },
]
TOOL_NAMES = {tool["name"] for tool in TOOLS}


class AnythingLLMError(RuntimeError):
    """带错误码的上游/校验错误。"""

    def __init__(self, code: str, message: str, detail: str = "") -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.detail = detail

    def to_dict(self) -> dict:
        return {"code": self.code, "message": self.message, "detail": self.detail}


def _auth_headers(extra: dict | None = None) -> dict:
    if not ANYTHINGLLM_API_KEY:
        raise RuntimeError(MISSING_KEY_MESSAGE)
    return {
        "Authorization": "Bearer " + ANYTHINGLLM_API_KEY,
        "Accept": "application/json",
        **(extra or {}),
    }


def anythingllm_request(
    method: str,
    path: str,
    *,
    json_body: dict | None = None,
    data: bytes | None = None,
    content_type: str | None = None,
    timeout: int = REQUEST_TIMEOUT,
):
    """调用 AnythingLLM API，并把网络/HTTP/JSON 错误统一成可读异常。"""
    headers = _auth_headers()
    if json_body is not None:
        data = json.dumps(json_body, ensure_ascii=False).encode("utf-8")
        content_type = "application/json"
    if content_type:
        headers["Content-Type"] = content_type
    req = urllib.request.Request(
        ANYTHINGLLM_URL + path, data=data, method=method, headers=headers
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as res:
            raw = res.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:400]
        raise AnythingLLMError(
            "ANYTHINGLLM_HTTP",
            f"AnythingLLM API 返回 HTTP {exc.code}",
            detail,
        ) from exc
    except (socket.timeout, TimeoutError) as exc:
        raise AnythingLLMError(
            "ANYTHINGLLM_TIMEOUT",
            f"请求 AnythingLLM 超时（{timeout} 秒）",
            str(exc),
        ) from exc
    except urllib.error.URLError as exc:
        reason = exc.reason
        if isinstance(reason, (socket.timeout, TimeoutError)):
            raise AnythingLLMError(
                "ANYTHINGLLM_TIMEOUT",
                f"请求 AnythingLLM 超时（{timeout} 秒）",
                str(reason),
            ) from exc
        raise AnythingLLMError(
            "ANYTHINGLLM_UNAVAILABLE",
            f"无法连接 AnythingLLM {ANYTHINGLLM_URL}",
            str(reason),
        ) from exc
    except OSError as exc:
        raise AnythingLLMError(
            "ANYTHINGLLM_UNAVAILABLE", "请求 AnythingLLM 失败", str(exc)
        ) from exc

    if not raw:
        return {}
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AnythingLLMError(
            "ANYTHINGLLM_UPSTREAM",
            "AnythingLLM 返回了无法解析的 JSON",
            str(exc),
        ) from exc
    if isinstance(payload, dict) and payload.get("success") is False:
        raise AnythingLLMError(
            "ANYTHINGLLM_UPSTREAM",
            "AnythingLLM 返回失败",
            str(payload.get("error") or payload.get("message") or ""),
        )
    return payload


def anythingllm_get(path: str) -> dict:
    return anythingllm_request("GET", path)


def _workspace_list() -> list[dict]:
    payload = anythingllm_get("/api/v1/workspaces")
    workspaces = payload.get("workspaces") if isinstance(payload, dict) else None
    return [ws for ws in (workspaces or []) if isinstance(ws, dict)]


def _resolve_workspace(slug=None) -> tuple[str, str]:
    """返回 (slug, name)；未指定时选第一个工作区。"""
    workspaces = _workspace_list()
    if not workspaces:
        raise AnythingLLMError(
            "ANYTHINGLLM_VALIDATION", "AnythingLLM 中没有任何工作区"
        )
    requested = str(slug or "").strip()
    if requested:
        for ws in workspaces:
            if str(ws.get("slug")) == requested:
                return requested, str(ws.get("name") or requested)
        available = "、".join(str(ws.get("slug")) for ws in workspaces)
        raise AnythingLLMError(
            "ANYTHINGLLM_VALIDATION",
            f"工作区不存在：{requested}",
            f"可用 slug：{available}",
        )
    first = workspaces[0]
    return str(first.get("slug") or ""), str(first.get("name") or "")


def list_workspaces() -> dict:
    workspaces = [
        {"id": ws.get("id"), "name": ws.get("name"), "slug": ws.get("slug")}
        for ws in _workspace_list()
    ]
    return {"count": len(workspaces), "workspaces": workspaces}


def _workspace_files(slug=None) -> dict:
    resolved, name = _resolve_workspace(slug)
    encoded = urllib.parse.quote(resolved, safe="")
    payload = anythingllm_get("/api/v1/workspace/" + encoded).get("workspace")
    detail = payload[0] if isinstance(payload, list) and payload else (payload or {})

    files = []
    for doc in detail.get("documents") or []:
        meta = doc.get("metadata") or {}
        if isinstance(meta, str):
            try:
                meta = json.loads(meta)
            except ValueError:
                meta = {}
        files.append(
            {
                "title": meta.get("title") or doc.get("filename"),
                "filename": doc.get("filename"),
                "source": meta.get("url"),
                "originPath": meta.get("chunkSource") or None,
                "author": meta.get("docAuthor"),
                "published": meta.get("published"),
                "wordCount": meta.get("wordCount"),
                "tokenCount": meta.get("token_count_estimate"),
                "pinned": doc.get("pinned"),
                "watched": doc.get("watched"),
                "docId": doc.get("docId"),
                "docpath": doc.get("docpath"),
                "createdAt": doc.get("createdAt"),
            }
        )

    return {
        "workspace": {"id": detail.get("id"), "name": name, "slug": resolved},
        "fileCount": len(files),
        "files": files,
    }


def first_workspace_files() -> dict:
    return _workspace_files()


def workspace_files(workspace_slug=None) -> dict:
    return _workspace_files(workspace_slug)


def _multipart_file(field: str, path: Path) -> tuple[bytes, str]:
    boundary = "----AnythingLLM" + secrets.token_hex(16)
    filename = path.name.replace('"', "_").replace("\r", "_").replace("\n", "_")
    mime = mimetypes.guess_type(filename)[0] or "application/octet-stream"
    head = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="{field}"; filename="{filename}"\r\n'
        f"Content-Type: {mime}\r\n\r\n"
    ).encode("utf-8")
    tail = f"\r\n--{boundary}--\r\n".encode("utf-8")
    return head + path.read_bytes() + tail, f"multipart/form-data; boundary={boundary}"


def upload_document(file_path, workspace_slug=None, embed=True) -> dict:
    if not isinstance(file_path, str) or not file_path.strip():
        raise AnythingLLMError("ANYTHINGLLM_VALIDATION", "file_path 不能为空")
    path = Path(file_path).expanduser()
    if not path.is_file():
        raise AnythingLLMError(
            "ANYTHINGLLM_VALIDATION", f"文件不存在：{path}", str(path.resolve())
        )
    size = path.stat().st_size
    if size > MAX_UPLOAD_BYTES:
        raise AnythingLLMError(
            "ANYTHINGLLM_VALIDATION",
            "文件超过上传上限",
            f"{size} 字节 > {MAX_UPLOAD_BYTES} 字节",
        )
    if embed is not None and not isinstance(embed, bool):
        raise AnythingLLMError("ANYTHINGLLM_VALIDATION", "embed 必须是布尔值")

    slug, name = _resolve_workspace(workspace_slug)
    body, content_type = _multipart_file("file", path)
    uploaded = anythingllm_request(
        "POST",
        "/api/v1/document/upload",
        data=body,
        content_type=content_type,
        timeout=120,
    )
    documents = uploaded.get("documents") if isinstance(uploaded, dict) else None
    document = documents[0] if isinstance(documents, list) and documents else {}
    location = ""
    if isinstance(document, dict):
        location = str(document.get("location") or document.get("docpath") or "")

    embedded = False
    embed_error = ""
    if embed is not False and location:
        try:
            anythingllm_request(
                "POST",
                f"/api/v1/workspace/{urllib.parse.quote(slug, safe='')}/update-embeddings",
                json_body={"adds": [location], "deletes": []},
                timeout=120,
            )
            embedded = True
        except AnythingLLMError as exc:
            embed_error = exc.message

    return {
        "workspace": {"name": name, "slug": slug},
        "fileName": path.name,
        "size": size,
        "location": location,
        "embedded": embedded,
        "embedError": embed_error,
        "document": document,
    }


def ask_workspace(message, workspace_slug=None, mode="query") -> dict:
    if not isinstance(message, str) or not message.strip():
        raise AnythingLLMError("ANYTHINGLLM_VALIDATION", "message 不能为空")
    mode = str(mode or "query").strip().lower()
    if mode not in {"query", "chat"}:
        raise AnythingLLMError(
            "ANYTHINGLLM_VALIDATION", "mode 只能是 query 或 chat", repr(mode)
        )
    slug, name = _resolve_workspace(workspace_slug)
    payload = anythingllm_request(
        "POST",
        f"/api/v1/workspace/{urllib.parse.quote(slug, safe='')}/chat",
        json_body={"message": message.strip(), "mode": mode},
        timeout=180,
    )
    if not isinstance(payload, dict):
        raise AnythingLLMError(
            "ANYTHINGLLM_UPSTREAM", "AnythingLLM 返回了非对象响应", type(payload).__name__
        )
    if payload.get("error"):
        raise AnythingLLMError(
            "ANYTHINGLLM_UPSTREAM", "AnythingLLM 问答失败", str(payload.get("error"))
        )
    return {
        "workspace": {"name": name, "slug": slug},
        "id": payload.get("id"),
        "type": payload.get("type"),
        "textResponse": payload.get("textResponse") or payload.get("response") or "",
        "sources": payload.get("sources") or [],
    }


def with_meta(result: dict) -> dict:
    result["resultType"] = "complete"
    result.setdefault("_meta", {})["io.modelcontextprotocol/serverInfo"] = SERVER_INFO
    return result


def error(req_id, code: int, message: str, data=None) -> dict:
    err = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": req_id, "error": err}


def _call_tool(name: str, arguments) -> dict:
    if name not in TOOL_NAMES:
        raise AnythingLLMError(
            "ANYTHINGLLM_VALIDATION",
            f"Unknown tool: {name}",
            f"可用工具：{', '.join(sorted(TOOL_NAMES))}",
        )
    if arguments is None:
        arguments = {}
    if not isinstance(arguments, dict):
        raise AnythingLLMError(
            "ANYTHINGLLM_VALIDATION", "arguments 必须是对象", type(arguments).__name__
        )
    if name == "first_workspace_files":
        return first_workspace_files()
    if name == "list_workspaces":
        return list_workspaces()
    if name == "workspace_files":
        return workspace_files(arguments.get("workspace_slug"))
    if name == "upload_document":
        return upload_document(
            arguments.get("file_path"),
            arguments.get("workspace_slug"),
            arguments.get("embed", True),
        )
    return ask_workspace(
        arguments.get("message"),
        arguments.get("workspace_slug"),
        arguments.get("mode", "query"),
    )


def handle_message(msg: dict, headers) -> tuple[dict | None, int]:
    """处理单条 JSON-RPC 消息，返回 (响应体或 None, HTTP 状态码)。"""
    if not isinstance(msg, dict):
        return error(None, -32600, "Invalid Request"), 400

    method = msg.get("method")
    req_id = msg.get("id")
    params = msg.get("params") or {}
    meta = params.get("_meta") or {} if isinstance(params, dict) else {}
    body_version = meta.get("io.modelcontextprotocol/protocolVersion")
    header_version = headers.get("MCP-Protocol-Version")
    modern = (body_version or header_version) in MODERN_VERSIONS

    # 新协议：每个请求自带版本，并做头部校验
    if modern:
        if not header_version:
            return error(req_id, -32020, "Missing MCP-Protocol-Version header"), 400
        if body_version and body_version != header_version:
            return error(
                req_id,
                -32020,
                "Header mismatch: MCP-Protocol-Version header value "
                f"'{header_version}' does not match body value '{body_version}'",
            ), 400
        header_method = headers.get("Mcp-Method")
        if header_method and method and header_method != method:
            return error(
                req_id,
                -32020,
                f"Header mismatch: Mcp-Method header value '{header_method}' "
                f"does not match body value '{method}'",
            ), 400
        header_name = headers.get("Mcp-Name")
        if header_name and method == "tools/call" and header_name != params.get("name"):
            return error(
                req_id,
                -32020,
                f"Header mismatch: Mcp-Name header value '{header_name}' "
                f"does not match body value '{params.get('name')}'",
            ), 400

    requested_version = body_version or header_version
    if requested_version and requested_version not in SUPPORTED_VERSIONS:
        return error(
            req_id,
            -32022,
            "Unsupported protocol version",
            {"supported": SUPPORTED_VERSIONS, "requested": requested_version},
        ), 400

    # 通知（含 notifications/initialized）无需响应
    if "id" not in msg:
        return None, 202
    if method is None:
        return None, 202

    if method == "initialize":
        requested = params.get("protocolVersion")
        version = requested if requested in LEGACY_VERSIONS else LATEST_LEGACY
        return {
            "jsonrpc": "2.0",
            "id": req_id,
            "result": {
                "protocolVersion": version,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": SERVER_INFO,
                "instructions": (
                    "可列出工作区、读取工作区文件、上传并向量化文档，"
                    "或对工作区文档进行检索问答。"
                ),
            },
        }, 200

    if method == "server/discover":
        result = {
            "supportedVersions": SUPPORTED_VERSIONS,
            "capabilities": {"tools": {"listChanged": False}},
            "instructions": (
                "可列出工作区、读取工作区文件、上传并向量化文档，"
                "或对工作区文档进行检索问答。"
            ),
            "ttlMs": 3600000,
            "cacheScope": "public",
        }
        result = with_meta(result) if modern else result
        return {"jsonrpc": "2.0", "id": req_id, "result": result}, 200

    if method == "ping":
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}, 200

    if method == "tools/list":
        result = {"tools": TOOLS}
        if modern:
            result.update({"ttlMs": 3600000, "cacheScope": "public"})
            with_meta(result)
        return {"jsonrpc": "2.0", "id": req_id, "result": result}, 200

    if method == "tools/call":
        name = params.get("name")
        if name not in TOOL_NAMES:
            return error(req_id, -32602, f"Unknown tool: {name}"), 200
        if not ANYTHINGLLM_API_KEY:
            logger.warning("拒绝 tools/call：%s", MISSING_KEY_MESSAGE)
            result = {
                "content": [{"type": "text", "text": MISSING_KEY_MESSAGE}],
                "isError": True,
            }
            if modern:
                with_meta(result)
            return {"jsonrpc": "2.0", "id": req_id, "result": result}, 200
        started = time.monotonic()
        try:
            logger.info("调用工具 %s", name)
            data = _call_tool(name, params.get("arguments") or {})
            result = {
                "content": [
                    {"type": "text", "text": json.dumps(data, ensure_ascii=False, indent=2)}
                ],
                "structuredContent": data,
                "isError": False,
            }
            logger.info(
                "tools/call %s 成功（%.3fs）", name, time.monotonic() - started
            )
        except Exception as exc:  # noqa: BLE001 - 工具错误需回传给客户端
            payload = (
                exc.to_dict()
                if isinstance(exc, AnythingLLMError)
                else {
                    "code": "ANYTHINGLLM_UPSTREAM",
                    "message": "工具执行失败",
                    "detail": f"{type(exc).__name__}: {exc}",
                }
            )
            logger.error(
                "tools/call %s 失败 code=%s detail=%s（%.3fs）",
                name,
                payload["code"],
                payload["detail"],
                time.monotonic() - started,
            )
            result = {
                "content": [
                    {"type": "text", "text": json.dumps(payload, ensure_ascii=False)}
                ],
                "structuredContent": payload,
                "isError": True,
            }
        if modern:
            with_meta(result)
        return {"jsonrpc": "2.0", "id": req_id, "result": result}, 200

    # 未实现的方法：新协议要求 404
    return error(req_id, -32601, f"Method not found: {method}"), (404 if modern else 200)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "anythingllm-mcp/1.1.0"

    def log_message(self, fmt, *args):
        sys.stderr.write("%s - %s\n" % (self.address_string(), fmt % args))

    def _send(self, status: int, body: dict | list | None = None):
        raw = b"" if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        if body is not None:
            self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.end_headers()
        if raw:
            self.wfile.write(raw)

    def _origin_allowed(self) -> bool:
        origin = self.headers.get("Origin")
        if not origin:
            return True
        return origin.startswith(
            ("http://localhost", "http://127.0.0.1", "http://[::1]")
        )

    def do_GET(self):
        self._send(405, error(None, -32600, "仅支持 POST /mcp"))

    do_DELETE = do_GET
    do_PUT = do_GET

    def do_OPTIONS(self):
        self._send(204)

    def do_POST(self):
        if self.path.rstrip("/") != "/mcp":
            self._send(404, error(None, -32601, "Not found"))
            return
        if not self._origin_allowed():
            self._send(403, error(None, -32600, "Forbidden origin"))
            return
        try:
            length = int(self.headers.get("Content-Length") or 0)
            payload = json.loads(self.rfile.read(length) or b"null")
        except (ValueError, TypeError):
            self._send(400, error(None, -32700, "Parse error: invalid JSON"))
            return

        if isinstance(payload, list):
            responses = []
            for item in payload:
                resp, _ = handle_message(item, self.headers)
                if resp is not None:
                    responses.append(resp)
            self._send(202 if not responses else 200, responses or None)
            return

        resp, status = handle_message(payload, self.headers)
        self._send(status, resp)


def main():
    server = ThreadingHTTPServer((HOST, PORT), Handler)
    server.daemon_threads = True
    logger.info("AnythingLLM MCP server: http://%s:%s/mcp", HOST, PORT)
    if ANYTHINGLLM_API_KEY:
        logger.info("AnythingLLM API: %s", ANYTHINGLLM_URL)
    else:
        logger.warning("%s（服务仍会启动，但 tools/call 直接返回 isError=true）", MISSING_KEY_MESSAGE)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
