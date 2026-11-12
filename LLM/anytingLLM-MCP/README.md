# AnythingLLM MCP Server

把本机 AnythingLLM 的工作区、文档与检索问答封装为 MCP 工具。纯 Python 标准库，Streamable HTTP、无状态。

## 1. 前置条件

- AnythingLLM 已启动，默认 `http://localhost:3001`；
- 已在 AnythingLLM 设置中生成 API Key；
- Python 3.13+（代码只用标准库）。

## 2. 启动

```powershell
# 在仓库根目录执行
$env:ANYTHINGLLM_API_KEY = "你的 AnythingLLM Key"
python LLM/anytingLLM-MCP/server.py
```

端点：`http://127.0.0.1:8765/mcp`（仅 POST，无状态）。

**未设置 `ANYTHINGLLM_API_KEY` 时**：

- 服务仍会启动，启动日志给出明确警告；
- `tools/list` 正常返回工具清单；
- 任意 `tools/call` 返回 `isError: true`，文本包含 `未配置 ANYTHINGLLM_API_KEY`；
- 不会向上游 AnythingLLM 发起任何请求。

## 3. 环境变量

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `ANYTHINGLLM_URL` | `http://localhost:3001` | AnythingLLM 地址，末尾 `/` 会自动去掉。 |
| `ANYTHINGLLM_API_KEY` | **无默认值，必须设置** | 仅从环境变量读取，不写入代码。 |
| `MCP_HOST` | `127.0.0.1` | 监听地址。 |
| `MCP_PORT` | `8765` | 监听端口。 |

## 4. 工具

| 工具 | 参数 | 真实行为 |
| --- | --- | --- |
| `first_workspace_files` | 无 | 读取第一个工作区的文件元信息（兼容旧客户端）。 |
| `list_workspaces` | 无 | `GET /api/v1/workspaces`，返回 id/name/slug。 |
| `workspace_files` | `workspace_slug?` | 读取指定工作区（省略则第一个）的文件列表。 |
| `upload_document` | `file_path`, `workspace_slug?`, `embed?` | 读取本机文件 → `POST /api/v1/document/upload` → 默认再 `POST /api/v1/workspace/{slug}/update-embeddings` 触发向量化。单文件上限 50 MiB。 |
| `ask_workspace` | `message`, `workspace_slug?`, `mode?` | `POST /api/v1/workspace/{slug}/chat`；`mode=query`（默认，检索增强）或 `chat`；返回 `textResponse` 与 `sources`。 |

### 4.1 参数约束

- `workspace_slug`：必须是已存在的工作区 slug；不存在时返回 `ANYTHINGLLM_VALIDATION` 并列出可用 slug。
- `file_path`：必填，必须指向本机存在的文件。
- `embed`：布尔值，默认 `true`。
- `mode`：enum `["query", "chat"]`，默认 `query`。
- 未知工具返回 JSON-RPC `-32602`。

### 4.2 上传流程

1. 校验文件存在、大小 ≤ 50 MiB；
2. 解析工作区（默认第一个）；
3. 构造 `multipart/form-data` 上传文件；
4. 取响应 `documents[0].location`（或 `docpath`）；
5. `embed=true` 时调用 `update-embeddings` 的 `adds`；
6. 返回 `location`、`embedded`、`embedError`（若向量化失败，上传仍成功但会说明原因）。

## 5. 协议支持

同一个端点同时兼容：

- 旧版：2025-03-26 / 2025-06-18 / 2025-11-25，支持 `initialize` 握手（不强制 session）；
- 新版：2026-07-28，无握手、无 session、无长连接；支持 `server/discover`，可带 `MCP-Protocol-Version`、`Mcp-Method`、`Mcp-Name` 头并做一致性校验。

响应统一为 JSON（非 SSE），每个 POST 独立处理。通知（无 `id`）返回 202。

## 6. 调用示例

### 6.1 列出工作区

请求：

```bash
curl -sS -X POST http://127.0.0.1:8765/mcp \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"tools/call","params":{"name":"list_workspaces","arguments":{}}}'
```

成功响应（示例；字段名与实际返回一致，`id`/`name`/`slug` 取决于你的 AnythingLLM 实例）：

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "content": [
      {
        "type": "text",
        "text": "{\n  \"count\": 1,\n  \"workspaces\": [\n    {\"id\": 1, \"name\": \"默认工作区\", \"slug\": \"default\"}\n  ]\n}"
      }
    ],
    "structuredContent": {
      "count": 1,
      "workspaces": [{"id": 1, "name": "默认工作区", "slug": "default"}]
    },
    "isError": false
  }
}
```

### 6.2 上传并向量化

```bash
curl -sS -X POST http://127.0.0.1:8765/mcp \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/call","params":{"name":"upload_document","arguments":{"file_path":"D:/docs/demo.md","embed":true}}}'
```

成功时 `structuredContent` 形如：

```json
{
  "workspace": {"name": "默认工作区", "slug": "default"},
  "fileName": "demo.md",
  "size": 1234,
  "location": "custom-documents/demo-<hash>.json",
  "embedded": true,
  "embedError": "",
  "document": {"location": "custom-documents/demo-<hash>.json"}
}
```

### 6.3 检索问答

```bash
curl -sS -X POST http://127.0.0.1:8765/mcp \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"ask_workspace","arguments":{"message":"这份文档讲了什么？","mode":"query"}}}'
```

成功时：

```json
{
  "workspace": {"name": "默认工作区", "slug": "default"},
  "id": "chat-id",
  "type": "textResponse",
  "textResponse": "文档主要讲了……",
  "sources": [{"title": "demo.md"}]
}
```

### 6.4 缺 Key 错误

```bash
curl -sS -X POST http://127.0.0.1:8765/mcp \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"list_workspaces","arguments":{}}}'
```

```json
{
  "jsonrpc": "2.0",
  "id": 4,
  "result": {
    "content": [
      {
        "type": "text",
        "text": "未配置 ANYTHINGLLM_API_KEY：请先设置环境变量后再启动本 MCP Server，且不会向上游 AnythingLLM 发起请求。"
      }
    ],
    "isError": true
  }
}
```

### 6.5 上游错误

工具执行失败时 `isError: true`，`structuredContent` 为：

```json
{
  "code": "ANYTHINGLLM_UNAVAILABLE",
  "message": "无法连接 AnythingLLM http://localhost:3001",
  "detail": "Connection refused"
}
```

错误码：

| 错误码 | 场景 |
| --- | --- |
| `ANYTHINGLLM_VALIDATION` | 参数为空、工作区不存在、文件不存在、mode 非法、未知工具。 |
| `ANYTHINGLLM_TIMEOUT` | 请求 AnythingLLM 超时。 |
| `ANYTHINGLLM_UNAVAILABLE` | 连接失败。 |
| `ANYTHINGLLM_HTTP` | 上游返回非 2xx。 |
| `ANYTHINGLLM_UPSTREAM` | 上游 `success:false`、JSON 不可解析、问答返回 error。 |

## 7. 作为 MCP 客户端配置

```json
{
  "mcpServers": {
    "AnythingLLMMCP": {
      "type": "streamable_http",
      "url": "http://127.0.0.1:8765/mcp"
    }
  }
}
```

xAgent 会把工具暴露为 `AnythingLLMMCP__list_workspaces` 等，描述前缀 `[MCP:AnythingLLMMCP]`。

## 8. 自测

```powershell
python -m unittest tests.test_anythingllm_mcp -v
```

覆盖：缺少 Key 时所有工具均拒绝且不访问上游、工具 schema 约束、工作区不存在校验、上传+向量化双请求、问答参数与返回结构。

## 9. 常见问题

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| 启动日志 `未配置 ANYTHINGLLM_API_KEY` | 环境变量未设置 | 设置后重启服务。 |
| `ANYTHINGLLM_UNAVAILABLE` | AnythingLLM 未启动/地址错误 | 启动 AnythingLLM，检查 `ANYTHINGLLM_URL`。 |
| `ANYTHINGLLM_HTTP` 401/403 | Key 错误 | 重新生成 Key。 |
| 上传返回 `embedded:false` 且 `embedError` 非空 | 上传成功但向量化失败 | 查看 `embedError`，在 AnythingLLM 中检查嵌入模型/工作区状态后重试。 |
| `工作区不存在` | `workspace_slug` 拼写错误 | 先调用 `list_workspaces`。 |
