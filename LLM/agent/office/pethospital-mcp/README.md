# Pet Hospital MCP Server

把本地宠物医院 REST API（`pethospital.exe`，默认 `http://127.0.0.1:8080`）包装成 MCP 工具。仅使用 Python 标准库，Streamable HTTP、无状态，兼容 2025-* 与 2026-07-28 协议。

## 1. 前置条件

- Python 3.13+（仅标准库）；
- 宠物医院 REST 服务已启动：`study one-pethospital/pethospital.exe`（上游发行包，未提交到 Git）；
- 默认端口 8080 未被占用。

## 2. 启动

```powershell
# 以下命令均在仓库根目录执行
# 1) 启动宠物医院（若尚未运行）
& "study one-pethospital\pethospital.exe" -no-color

# 2) 启动 MCP Server
python LLM/agent/office/pethospital-mcp/server.py
```

或一键启动三个依赖：

```powershell
powershell -ExecutionPolicy Bypass -File LLM/agent/office/start-mcp.ps1
```

`start-mcp.ps1` 从脚本位置推导仓库根目录，不再依赖固定盘符；会跳过已监听端口，找不到宠物医院 exe 时明确告警。

端点：`http://127.0.0.1:8090/mcp`（仅 POST）。

## 3. 环境变量

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `PET_HOSPITAL_URL` | `http://127.0.0.1:8080` | 上游 REST 地址。 |
| `MCP_HOST` | `127.0.0.1` | 监听地址。 |
| `MCP_PORT` | `8090` | 监听端口。 |

超时固定 30 秒（`REQUEST_TIMEOUT=30`）；GET 失败最多重试一次，基础退避 0.5 秒。

## 4. 工具（10 个）

| 工具 | 必填/关键参数 | 说明 |
| --- | --- | --- |
| `pet_list` | 无 | 分页查询；支持关键词、名字、主人、电话、种类、性别、医生、疾病、状态、花费区间、排序。 |
| `pet_get` | `id` | 按 ID 查完整档案（含病历、消费明细）。 |
| `pet_search` | `q` | 全文检索，跨字段，空格分词 AND，含病历全文。 |
| `pet_create` | `name`, `species`, `ownerName`, `ownerPhone` | 新增档案，ID 自动生成。 |
| `pet_update` | `id`, `fields` | 局部更新；`fields` 必须是非空对象。 |
| `pet_delete` | `id` | 删除档案。 |
| `pet_stats` | 无 | 经营统计；`top` 默认 5、范围 1..20。 |
| `pet_add_record` | `id` | 追加病历。 |
| `pet_add_charge` | `id`, `item`, `category`, `amount` | 追加收费，总花费自动累计。 |
| `pet_summary` | `id` | 单只宠物费用与就诊汇总。 |

### 4.1 Schema 约束

- `status`：enum `["待就诊","就诊中","住院中","已康复","慢性病随访"]`（`pet_list`、`pet_create`）。
- `order`：enum `["asc","desc"]`。
- `page`：整数，最小 1。
- `pageSize`：整数，1..100。
- `pet_stats.top`：整数，1..20。
- `min`/`max`：number，最小 0。
- `pet_get`/`pet_delete`/`pet_summary`/`pet_add_record`/`pet_add_charge` 的 `id` 必填；空字符串由服务端返回 `PET_VALIDATION`。
- `pet_create` 的 `name`/`species`/`ownerName`/`ownerPhone` 必填；`pet_update` 的 `fields` 必填且非空。

列表类工具会裁剪 `records`、`charges` 等大字段；需要完整数据时调用 `pet_get`。

## 5. 错误语义

所有工具错误都保留 `isError: true`，同时通过：

- `content[0].text`：一行 JSON 字符串；
- `structuredContent`：同一个结构化对象。

对象格式：

```json
{
  "code": "PET_TIMEOUT | PET_UNAVAILABLE | PET_VALIDATION | PET_UPSTREAM",
  "message": "可读说明",
  "detail": "上游响应/异常细节"
}
```

| 错误码 | 触发场景 | 上游请求次数 |
| --- | --- | --- |
| `PET_VALIDATION` | 空 id、`pageSize`/`top` 越界、`order`/`status` 非法、`fields` 为空、未知工具、`arguments` 非对象。 | 0 |
| `PET_TIMEOUT` | 连接或读取超时（30 秒）。 | GET 最多 2 次；写操作 1 次 |
| `PET_UNAVAILABLE` | 连接被拒绝、DNS/网络失败等。 | GET 最多 2 次；写操作 1 次 |
| `PET_UPSTREAM` | HTTP 4xx/5xx、上游 JSON 不可解析、业务 `code != 200`。 | GET 5xx 最多 2 次；写操作 1 次 |

重试规则：

- **只有幂等 GET** 在首次失败后等待 `0.5 * 2^attempt` 秒重试一次；
- POST/PATCH/DELETE 永不重放，避免重复建档/收费；
- GET 重试只针对 5xx、超时、连接失败；4xx 与 JSON 解析错误不重试。

## 6. 调用示例

### 6.1 initialize

```bash
curl -sS -X POST http://127.0.0.1:8090/mcp \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":1,"method":"initialize","params":{"protocolVersion":"2025-03-26"}}'
```

响应（节选）：

```json
{
  "jsonrpc": "2.0",
  "id": 1,
  "result": {
    "protocolVersion": "2025-03-26",
    "capabilities": {"tools": {"listChanged": false}},
    "serverInfo": {"name": "pethospital-mcp", "version": "1.1.0"},
    "instructions": "使用 pet_* 工具查询或维护本地宠物医院数据。"
  }
}
```

### 6.2 tools/list

```bash
curl -sS -X POST http://127.0.0.1:8090/mcp \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":2,"method":"tools/list","params":{}}'
```

响应中 `result.tools` 为 10 个工具，`inputSchema` 带 `required`、`enum`、`minimum`、`maximum`。

### 6.3 tools/call 成功

```bash
curl -sS -X POST http://127.0.0.1:8090/mcp \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":3,"method":"tools/call","params":{"name":"pet_stats","arguments":{"top":5}}}'
```

响应（`structuredContent` 字段与真实 REST 返回一致；数值来自当前测试库，随数据变化）：

```json
{
  "jsonrpc": "2.0",
  "id": 3,
  "result": {
    "content": [
      {
        "type": "text",
        "text": "{\n  \"totalPets\": 1008,\n  \"totalRevenue\": 3680172.85,\n  \"topSpenders\": [...]\n}"
      }
    ],
    "structuredContent": {
      "totalPets": 1008,
      "totalRevenue": 3680172.85,
      "topSpenders": []
    },
    "isError": false
  }
}
```

### 6.4 tools/call 校验错误

```bash
curl -sS -X POST http://127.0.0.1:8090/mcp \
  -H 'Content-Type: application/json' \
  -d '{"jsonrpc":"2.0","id":4,"method":"tools/call","params":{"name":"pet_get","arguments":{"id":""}}}'
```

```json
{
  "jsonrpc": "2.0",
  "id": 4,
  "result": {
    "content": [
      {
        "type": "text",
        "text": "{\"code\":\"PET_VALIDATION\",\"message\":\"id 不能为空\",\"detail\":\"''\"}"
      }
    ],
    "structuredContent": {
      "code": "PET_VALIDATION",
      "message": "id 不能为空",
      "detail": "''"
    },
    "isError": true
  }
}
```

### 6.5 上游不可用

关闭 `pethospital.exe` 后调用：

```json
{
  "code": "PET_UNAVAILABLE",
  "message": "无法连接宠物医院 http://127.0.0.1:8080（请先运行 pethospital.exe）",
  "detail": "[WinError 10061] ..."
}
```

## 7. 客户端配置

配置文件：`LLM/agent/office/.mcp.json`。

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

xAgent 会把工具暴露为 `PetHospitalMCP__pet_list` 等，描述前缀 `[MCP:PetHospitalMCP]`。

## 8. 协议支持

- 旧版：2025-03-26 / 2025-06-18 / 2025-11-25，`initialize` 握手；
- 新版：2026-07-28，支持 `server/discover`，校验 `MCP-Protocol-Version`、`Mcp-Method`、`Mcp-Name` 头；
- 响应 JSON（非 SSE），通知无响应；
- 未实现方法旧协议返回 200 + JSON-RPC error，新协议返回 404。

## 9. 测试

```powershell
python -m unittest LLM/agent/office/pethospital-mcp/test_server.py -v
# 或从仓库根目录：
python -m unittest discover -s tests
```

`test_server.py` 覆盖：空 id、非法 `pageSize`、非法 `order`、上游 500、超时、连接失败、未知工具、意外异常、成功返回结构、GET 重试、POST 不重试、schema 约束。测试通过 `mock` 替换 `_request`/`urlopen`，不依赖真实宠物医院服务。

## 10. 常见问题

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| `PET_UNAVAILABLE` | 8080 未启动或 `PET_HOSPITAL_URL` 错 | 启动 `pethospital.exe`，检查环境变量。 |
| `PET_TIMEOUT` | 上游 30 秒无响应 | 检查宠物医院状态/负载；GET 已自动重试一次。 |
| `PET_VALIDATION` | 参数类型/范围/枚举错误 | 按 `detail` 修正；`pageSize` ≤100，`top` ≤20。 |
| `PET_UPSTREAM` | 上游 4xx/5xx 或业务错误 | 查看 `detail`；GET 5xx 会自动重试一次。 |
| `tools/list` 正常但调用失败 | 上游 REST 未启动 | MCP 进程与 REST 是独立进程。 |
