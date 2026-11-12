#!/usr/bin/env python3
"""Pet Hospital MCP Server - 把本地宠物医院 REST API 暴露为 MCP 工具。

Streamable HTTP，无状态：同时兼容 2025-03-26 / 2025-06-18 / 2025-11-25
（initialize 握手）和 2026-07-28（无握手、无 session）。仅使用 Python 标准库。
"""
from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

PET_URL = os.environ.get("PET_HOSPITAL_URL", "http://127.0.0.1:8080").rstrip("/")
HOST = os.environ.get("MCP_HOST", "127.0.0.1")
PORT = int(os.environ.get("MCP_PORT", "8090"))

SERVER_INFO = {"name": "pethospital-mcp", "version": "1.0.0"}
LEGACY_VERSIONS = ["2025-11-25", "2025-06-18", "2025-03-26"]
MODERN_VERSIONS = ["2026-07-28"]
SUPPORTED_VERSIONS = MODERN_VERSIONS + LEGACY_VERSIONS
LATEST_LEGACY = LEGACY_VERSIONS[0]
MAX_PAGE_SIZE = 100

SUMMARY_FIELDS = (
    "id", "name", "species", "breed", "gender", "ageMonths", "ownerName",
    "ownerPhone", "doctor", "disease", "status", "totalCost", "visitCount",
)


def _obj(props: dict, required: list[str] | None = None) -> dict:
    schema = {"type": "object", "properties": props, "additionalProperties": False}
    if required:
        schema["required"] = required
    return schema


def _s(value: str) -> dict:
    return {"type": "string", "description": value}


def _i(value: str) -> dict:
    return {"type": "integer", "description": value}


def _n(value: str) -> dict:
    return {"type": "number", "description": value}


TOOLS = [
    {
        "name": "pet_list",
        "description": "分页查询宠物档案，支持关键词与多字段过滤。返回精简列表字段。",
        "inputSchema": _obj({
            "q": _s("全文关键词"), "name": _s("宠物名"), "ownerName": _s("主人姓名"),
            "ownerPhone": _s("主人电话"), "species": _s("种类，如 犬/猫"),
            "gender": _s("性别：公/母"), "doctor": _s("主治医生"), "disease": _s("疾病"),
            "status": _s("状态：待就诊/就诊中/住院中/已康复/慢性病随访"),
            "min": _n("最低总花费"), "max": _n("最高总花费"),
            "sortBy": _s("排序字段，如 totalCost"), "order": _s("asc 或 desc"),
            "page": _i("页码，从 1 开始"), "pageSize": _i("每页条数，最大 100"),
        }),
    },
    {
        "name": "pet_get",
        "description": "按 ID 查询单只宠物完整档案（含历史病历与消费明细）。",
        "inputSchema": _obj({"id": _s("档案 ID，如 PET-000001")}, ["id"]),
    },
    {
        "name": "pet_search",
        "description": "全文检索宠物档案（跨字段，空格分词 AND，含病历全文）。",
        "inputSchema": _obj({"q": _s("检索关键词")}, ["q"]),
    },
    {
        "name": "pet_create",
        "description": "新增宠物档案，ID 自动生成。",
        "inputSchema": _obj({
            "name": _s("宠物姓名"), "species": _s("种类"), "ownerName": _s("主人姓名"),
            "ownerPhone": _s("主人电话"), "breed": _s("品种"), "gender": _s("性别"),
            "ageMonths": _i("月龄"), "color": _s("毛色"), "chipNo": _s("芯片号"),
            "ownerAddr": _s("主人住址"), "doctor": _s("主治医生"), "disease": _s("疾病"),
            "status": _s("就诊状态"), "allergy": _s("过敏史"), "note": _s("备注"),
        }, ["name", "species", "ownerName", "ownerPhone"]),
    },
    {
        "name": "pet_update",
        "description": "局部更新宠物档案，只修改 fields 中传入的字段。",
        "inputSchema": _obj({
            "id": _s("档案 ID"),
            "fields": {"type": "object", "description": "要更新的字段键值对", "additionalProperties": True},
        }, ["id", "fields"]),
    },
    {
        "name": "pet_delete",
        "description": "删除宠物档案。",
        "inputSchema": _obj({"id": _s("档案 ID")}, ["id"]),
    },
    {
        "name": "pet_stats",
        "description": "医院经营统计：档案数、收入、种类/状态/医生分布与消费排行。",
        "inputSchema": _obj({"top": _i("消费排行条数，默认 5，最大 20")}),
    },
    {
        "name": "pet_add_record",
        "description": "为宠物追加一条历史病历。",
        "inputSchema": _obj({
            "id": _s("档案 ID"), "doctor": _s("医生"), "diagnosis": _s("诊断"),
            "symptoms": _s("症状"), "treatment": _s("治疗"), "visitDate": _s("就诊日期 YYYY-MM-DD"),
            "prescription": {"type": "array", "items": {"type": "string"}, "description": "处方列表"},
            "weightKg": _n("体重 kg"), "temperature": _n("体温"),
            "followUp": _s("复诊建议"), "charge": _n("本次费用"),
        }, ["id"]),
    },
    {
        "name": "pet_add_charge",
        "description": "为宠物追加一笔收费，总花费自动累计。",
        "inputSchema": _obj({
            "id": _s("档案 ID"), "item": _s("收费项目"), "category": _s("分类，如 检查/药品/住院"),
            "amount": _n("金额"), "doctor": _s("医生"), "date": _s("日期 YYYY-MM-DD"),
        }, ["id", "item", "category", "amount"]),
    },
    {
        "name": "pet_summary",
        "description": "查询单只宠物的费用与就诊汇总。",
        "inputSchema": _obj({"id": _s("档案 ID")}, ["id"]),
    },
]

HANDLERS = {}
PAGE_KEYS = (
    "q", "name", "ownerName", "ownerPhone", "species", "gender", "doctor", "disease",
    "status", "min", "max", "sortBy", "order", "page", "pageSize",
)


def _request(method: str, path: str, params: dict | None = None, body=None):
    url = PET_URL + path
    if params:
        query = urllib.parse.urlencode({k: v for k, v in params.items() if v is not None})
        if query:
            url += "?" + query
    data = None if body is None else json.dumps(body, ensure_ascii=False).encode("utf-8")
    req = urllib.request.Request(
        url, data=data, method=method,
        headers={"Accept": "application/json", "Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=30) as res:
            payload = json.load(res)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", "replace")[:400]
        raise RuntimeError(f"HTTP {exc.code}: {detail}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"无法连接宠物医院 {PET_URL}：{exc.reason}（请先运行 pethospital.exe）") from exc
    if isinstance(payload, dict) and payload.get("code") not in (None, 200):
        raise RuntimeError(f"接口返回 {payload.get('code')}: {payload.get('message')}")
    if isinstance(payload, dict) and "data" in payload:
        return payload["data"]
    return payload


def _pid(value) -> str:
    if not isinstance(value, str) or not value.strip():
        raise ValueError("id 不能为空")
    return urllib.parse.quote(value.strip(), safe="")


def _summary(pet: dict) -> dict:
    return {k: pet.get(k) for k in SUMMARY_FIELDS if k in pet}


def _slim_page(data):
    if isinstance(data, dict) and isinstance(data.get("items"), list):
        data = dict(data)
        data["items"] = [_summary(item) for item in data["items"] if isinstance(item, dict)]
    return data


def pet_list(a: dict):
    params = {k: a.get(k) for k in PAGE_KEYS}
    if params.get("pageSize") is not None:
        params["pageSize"] = max(1, min(int(params["pageSize"]), MAX_PAGE_SIZE))
    return _slim_page(_request("GET", "/api/v1/pets", params=params))


def pet_get(a: dict):
    return _request("GET", f"/api/v1/pets/{_pid(a.get('id'))}")


def pet_search(a: dict):
    return _slim_page(_request("GET", "/api/v1/pets/search", params={"q": a.get("q")}))


def pet_create(a: dict):
    body = {k: v for k, v in a.items() if v is not None}
    return _request("POST", "/api/v1/pets", body=body)


def pet_update(a: dict):
    fields = a.get("fields")
    if not isinstance(fields, dict) or not fields:
        raise ValueError("fields 必须是非空对象")
    return _request("PATCH", f"/api/v1/pets/{_pid(a.get('id'))}", body=fields)


def pet_delete(a: dict):
    return _request("DELETE", f"/api/v1/pets/{_pid(a.get('id'))}")


def pet_stats(a: dict):
    top = int(a.get("top") or 5)
    top = max(1, min(top, 20))
    data = _request("GET", "/api/v1/stats", params={"top": top})
    if isinstance(data, dict) and isinstance(data.get("topSpenders"), list):
        data = dict(data)
        data["topSpenders"] = [_summary(p) for p in data["topSpenders"] if isinstance(p, dict)]
    return data


def pet_add_record(a: dict):
    body = {k: v for k, v in a.items() if k != "id" and v is not None}
    return _request("POST", f"/api/v1/pets/{_pid(a.get('id'))}/records", body=body)


def pet_add_charge(a: dict):
    body = {k: v for k, v in a.items() if k != "id" and v is not None}
    return _request("POST", f"/api/v1/pets/{_pid(a.get('id'))}/charges", body=body)


def pet_summary(a: dict):
    return _request("GET", f"/api/v1/pets/{_pid(a.get('id'))}/summary")


HANDLERS = {
    "pet_list": pet_list, "pet_get": pet_get, "pet_search": pet_search,
    "pet_create": pet_create, "pet_update": pet_update, "pet_delete": pet_delete,
    "pet_stats": pet_stats, "pet_add_record": pet_add_record,
    "pet_add_charge": pet_add_charge, "pet_summary": pet_summary,
}
TOOL_NAMES = {tool["name"] for tool in TOOLS}


def with_meta(result: dict) -> dict:
    result["resultType"] = "complete"
    result.setdefault("_meta", {})["io.modelcontextprotocol/serverInfo"] = SERVER_INFO
    return result


def error(req_id, code: int, message: str, data=None) -> dict:
    err = {"code": code, "message": message}
    if data is not None:
        err["data"] = data
    return {"jsonrpc": "2.0", "id": req_id, "error": err}


def _call_tool(name: str, arguments: dict) -> dict:
    if name not in TOOL_NAMES:
        raise ValueError(f"Unknown tool: {name}")
    if not isinstance(arguments, dict):
        raise ValueError("arguments 必须是对象")
    return HANDLERS[name](arguments)


def handle_message(msg: dict, headers) -> tuple[dict | None, int]:
    if not isinstance(msg, dict):
        return error(None, -32600, "Invalid Request"), 400

    method = msg.get("method")
    req_id = msg.get("id")
    params = msg.get("params") or {}
    meta = params.get("_meta") or {} if isinstance(params, dict) else {}
    body_version = meta.get("io.modelcontextprotocol/protocolVersion")
    header_version = headers.get("MCP-Protocol-Version")
    modern = (body_version or header_version) in MODERN_VERSIONS

    if modern:
        if not header_version:
            return error(req_id, -32020, "Missing MCP-Protocol-Version header"), 400
        if body_version and body_version != header_version:
            return error(req_id, -32020, "Header mismatch: MCP-Protocol-Version"), 400
        header_method = headers.get("Mcp-Method")
        if header_method and method and header_method != method:
            return error(req_id, -32020, "Header mismatch: Mcp-Method"), 400
        header_name = headers.get("Mcp-Name")
        if header_name and method == "tools/call" and header_name != params.get("name"):
            return error(req_id, -32020, "Header mismatch: Mcp-Name"), 400

    requested_version = body_version or header_version
    if requested_version and requested_version not in SUPPORTED_VERSIONS:
        return error(
            req_id, -32022, "Unsupported protocol version",
            {"supported": SUPPORTED_VERSIONS, "requested": requested_version},
        ), 400

    if "id" not in msg or method is None:
        return None, 202

    if method == "initialize":
        requested = params.get("protocolVersion")
        version = requested if requested in LEGACY_VERSIONS else LATEST_LEGACY
        return {
            "jsonrpc": "2.0", "id": req_id,
            "result": {
                "protocolVersion": version,
                "capabilities": {"tools": {"listChanged": False}},
                "serverInfo": SERVER_INFO,
                "instructions": "使用 pet_* 工具查询或维护本地宠物医院数据。",
            },
        }, 200

    if method == "server/discover":
        result = {
            "supportedVersions": SUPPORTED_VERSIONS,
            "capabilities": {"tools": {"listChanged": False}},
            "instructions": "使用 pet_* 工具查询或维护本地宠物医院数据。",
            "ttlMs": 3600000, "cacheScope": "public",
        }
        if modern:
            with_meta(result)
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
        arguments = params.get("arguments") or {}
        try:
            data = _call_tool(name, arguments)
            result = {
                "content": [{"type": "text", "text": json.dumps(data, ensure_ascii=False, indent=2)}],
                "structuredContent": data,
                "isError": False,
            }
        except Exception as exc:  # noqa: BLE001 - 工具错误需回传给客户端
            result = {
                "content": [{"type": "text", "text": f"调用失败: {exc}"}],
                "isError": True,
            }
        if modern:
            with_meta(result)
        return {"jsonrpc": "2.0", "id": req_id, "result": result}, 200

    return error(req_id, -32601, f"Method not found: {method}"), (404 if modern else 200)


class Handler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    server_version = "pethospital-mcp/1.0.0"

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
        return origin.startswith(("http://localhost", "http://127.0.0.1", "http://[::1]"))

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
    print(f"Pet Hospital MCP server: http://{HOST}:{PORT}/mcp", file=sys.stderr)
    print(f"Pet Hospital API: {PET_URL}", file=sys.stderr)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
