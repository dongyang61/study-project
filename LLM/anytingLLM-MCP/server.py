#!/usr/bin/env python3
"""AnythingLLM MCP Server - 单工具：读取第一个工作区的文件信息。

Streamable HTTP，无状态：同时兼容 2025-03-26 / 2025-06-18 / 2025-11-25
（initialize 握手）和 2026-07-28（无握手、无 session）。
仅使用 Python 标准库。
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

ANYTHINGLLM_URL = os.environ.get("ANYTHINGLLM_URL", "http://localhost:3001").rstrip("/")
ANYTHINGLLM_API_KEY = os.environ.get(
    "ANYTHINGLLM_API_KEY", "EPHZ30T-CTXM3T9-KFZ3P1J-XV28DM4"
)
HOST = os.environ.get("MCP_HOST", "127.0.0.1")
PORT = int(os.environ.get("MCP_PORT", "8765"))

SERVER_INFO = {"name": "anythingllm-mcp", "version": "1.0.0"}
LEGACY_VERSIONS = ["2025-11-25", "2025-06-18", "2025-03-26"]
MODERN_VERSIONS = ["2026-07-28"]
SUPPORTED_VERSIONS = MODERN_VERSIONS + LEGACY_VERSIONS
LATEST_LEGACY = LEGACY_VERSIONS[0]

TOOL = {
    "name": "first_workspace_files",
    "description": (
        "读取本机 AnythingLLM 中第一个工作区的文件信息，"
        "返回标题、来源路径、作者、发布时间、词数、token 数、置顶状态等。"
    ),
    "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
    "outputSchema": {
        "type": "object",
        "properties": {
            "workspace": {"type": "object"},
            "fileCount": {"type": "integer"},
            "files": {"type": "array", "items": {"type": "object"}},
        },
        "required": ["workspace", "fileCount", "files"],
    },
}


def anythingllm_get(path: str) -> dict:
    req = urllib.request.Request(
        ANYTHINGLLM_URL + path,
        headers={
            "Authorization": "Bearer " + ANYTHINGLLM_API_KEY,
            "Accept": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as res:
        return json.load(res)


def first_workspace_files() -> dict:
    workspaces = anythingllm_get("/api/v1/workspaces").get("workspaces") or []
    if not workspaces:
        raise RuntimeError("AnythingLLM 中没有任何工作区")
    ws = workspaces[0]
    slug = urllib.parse.quote(str(ws.get("slug", "")), safe="")
    payload = anythingllm_get("/api/v1/workspace/" + slug).get("workspace")
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
        "workspace": {
            "id": ws.get("id"),
            "name": ws.get("name"),
            "slug": ws.get("slug"),
        },
        "fileCount": len(files),
        "files": files,
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
                "instructions": "调用 first_workspace_files 读取第一个工作区的文件信息。",
            },
        }, 200

    if method == "server/discover":
        result = {
            "supportedVersions": SUPPORTED_VERSIONS,
            "capabilities": {"tools": {"listChanged": False}},
            "instructions": "调用 first_workspace_files 读取第一个工作区的文件信息。",
            "ttlMs": 3600000,
            "cacheScope": "public",
        }
        result = with_meta(result) if modern else result
        return {"jsonrpc": "2.0", "id": req_id, "result": result}, 200

    if method == "ping":
        return {"jsonrpc": "2.0", "id": req_id, "result": {}}, 200

    if method == "tools/list":
        result = {"tools": [TOOL]}
        if modern:
            result.update({"ttlMs": 3600000, "cacheScope": "public"})
            with_meta(result)
        return {"jsonrpc": "2.0", "id": req_id, "result": result}, 200

    if method == "tools/call":
        name = params.get("name")
        if name != TOOL["name"]:
            return error(req_id, -32602, f"Unknown tool: {name}"), 200
        try:
            data = first_workspace_files()
            result = {
                "content": [
                    {"type": "text", "text": json.dumps(data, ensure_ascii=False, indent=2)}
                ],
                "structuredContent": data,
                "isError": False,
            }
        except urllib.error.HTTPError as exc:
            result = {
                "content": [
                    {
                        "type": "text",
                        "text": f"AnythingLLM API 错误: HTTP {exc.code} {exc.reason}",
                    }
                ],
                "isError": True,
            }
        except Exception as exc:  # noqa: BLE001 - 工具错误需回传给客户端
            result = {
                "content": [{"type": "text", "text": f"读取失败: {exc}"}],
                "isError": True,
            }
        if modern:
            with_meta(result)
        return {"jsonrpc": "2.0", "id": req_id, "result": result}, 200

    # 未实现的方法：新协议要求 404
    return error(req_id, -32601, f"Method not found: {method}"), (404 if modern else 200)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "anythingllm-mcp/1.0.0"

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
    print(f"AnythingLLM MCP server: http://{HOST}:{PORT}/mcp", file=sys.stderr)
    print(f"AnythingLLM API: {ANYTHINGLLM_URL}", file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
