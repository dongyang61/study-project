# AnythingLLM MCP Server

单工具 MCP 服务：读取本机 AnythingLLM **第一个工作区**的文件信息。

## 启动

```powershell
python D:\study\LLM\anytingLLM-MCP\server.py
```

端点：`http://127.0.0.1:8765/mcp`（仅 POST，无状态）。

## 工具

- `first_workspace_files`：无需参数，返回工作区信息及文件列表（标题、来源路径、作者、发布时间、词数、token 数、置顶状态、docId 等）。

## 协议支持

同一个端点同时兼容：

- 旧版：2025-03-26 / 2025-06-18 / 2025-11-25，支持 `initialize` 握手（不强制 session）。
- 新版：2026-07-28，无握手、无 session、无长连接；支持 `server/discover`，请求可带 `MCP-Protocol-Version`、`Mcp-Method`、`Mcp-Name` 头。

响应统一为 JSON（非 SSE），每个 POST 独立处理。

## 环境变量

| 变量 | 默认值 |
| --- | --- |
| `ANYTHINGLLM_URL` | `http://localhost:3001` |
| `ANYTHINGLLM_API_KEY` | 已内置当前实例的 Key |
| `MCP_HOST` | `127.0.0.1` |
| `MCP_PORT` | `8765` |

## 客户端配置

配置文件：`D:\LLM-Course\Playground\mcp.json`

```json
{
  "mcpServers": {
    "anythingllm": {
      "type": "streamable-http",
      "url": "http://127.0.0.1:8765/mcp"
    }
  }
}
```

不同客户端的 `type` 命名可能不同（如 `http`、`remote`），URL 不变。
