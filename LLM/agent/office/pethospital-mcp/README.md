# Pet Hospital MCP Server

把本地宠物医院 REST API（`pethospital.exe`，默认 `http://127.0.0.1:8080`）包装成 MCP 工具。
仅使用 Python 标准库，Streamable HTTP、无状态，兼容 2025-* 与 2026-07-28 协议。

## 启动

```powershell
# 1) 先启动宠物医院（若尚未运行）
D:\study\study one-pethospital\pethospital.exe

# 2) 启动 MCP Server
python D:\study\LLM\agent\office\pethospital-mcp\server.py
```

或一键启动三个依赖：

```powershell
powershell -ExecutionPolicy Bypass -File D:\study\LLM\agent\office\start-mcp.ps1
```

端点：`http://127.0.0.1:8090/mcp`（仅 POST）。

## 环境变量

| 变量 | 默认值 |
| --- | --- |
| `PET_HOSPITAL_URL` | `http://127.0.0.1:8080` |
| `MCP_HOST` | `127.0.0.1` |
| `MCP_PORT` | `8090` |

## 工具

| 工具 | 说明 |
| --- | --- |
| `pet_list` | 分页查询，支持关键词/种类/医生/状态/花费区间等过滤；返回精简字段 |
| `pet_get` | 按 ID 查完整档案（含病历、消费明细） |
| `pet_search` | 全文检索（跨字段，含病历全文） |
| `pet_create` | 新增档案 |
| `pet_update` | 局部更新（`fields` 传要改的字段） |
| `pet_delete` | 删除档案 |
| `pet_stats` | 经营统计，消费排行默认 5 条、最多 20 条 |
| `pet_add_record` | 追加历史病历 |
| `pet_add_charge` | 追加收费（总花费自动累计） |
| `pet_summary` | 单只宠物费用与就诊汇总 |

列表类工具 `pageSize` 上限 100；`pet_list` / `pet_search` / `pet_stats` 会裁剪
`records`、`charges` 等大字段，需要完整数据时调用 `pet_get`。

## 客户端配置

配置文件：`D:\study\LLM\agent\office\.mcp.json`

```json
{
  "mcpServers": {
    "PetHospitalMCP": {
      "type": "streamable_http",
      "url": "http://127.0.0.1:8090/mcp"
    }
  }
}
```
