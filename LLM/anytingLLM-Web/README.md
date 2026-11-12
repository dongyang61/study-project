# AnythingLLM 文档管理网页

一个无构建步骤的静态单页：在浏览器中管理 AnythingLLM 工作区文档。真实调用 AnythingLLM REST API，不使用假数据。

## 1. 启动

前置条件：

- AnythingLLM 已启动，默认 API 地址 `http://localhost:3001`；
- 在 AnythingLLM「设置 → 工具 → API Key」生成 Key。

直接双击 `index.html`，或从仓库根目录启动静态服务：

```powershell
python -m http.server 8000 --directory LLM/anytingLLM-Web
```

打开 <http://127.0.0.1:8000/>。

如果浏览器以 `file://` 打开并因 CORS 拒绝请求，请使用 HTTP 静态服务，并确保 AnythingLLM 允许该来源。

## 2. API Key 输入

页面顶部有独立的 **API Key** 卡片：

- 输入框类型为 `password`，点击“保存”写入浏览器 `localStorage`，键名 `anythingllm_api_key`；
- 点击“清除”删除该键并立即禁用所有操作；
- 刷新页面会从 `localStorage` 读取；读取失败（浏览器禁用存储）时显示保存失败；
- **未配置 Key 时**：上传、刷新、工作区选择全部 `disabled`，状态显示“未配置，所有操作已禁用”，列表区显示红色“未配置 API Key：请在页面顶部输入并保存”；
- 所有请求通过 `authHeaders()` 统一加 `Authorization: Bearer <Key>`；没有 Key 时直接抛出可见错误，不会发出无鉴权请求；
- Key 不写入 HTML/JS，也不发送到 AnythingLLM 之外的服务器。

> 代码中只保留 `API = "http://localhost:3001/api"` 和存储键名，不含任何真实 Key。

## 3. 使用的 AnythingLLM 接口

| 方法 | 路径 | 用途 |
| --- | --- | --- |
| GET | `/api/v1/workspaces` | 加载工作区下拉框。 |
| GET | `/api/v1/workspace/{slug}` | 加载当前工作区文档列表。 |
| POST | `/api/v1/document/upload` | 多文件上传；`FormData` 含 `file` 与 `addToWorkspaces=<slug>`。 |
| POST | `/api/v1/workspace/{slug}/update-embeddings` | 删除文件：`{"adds":[],"deletes":[docpath]}`。 |

鉴权头：`Authorization: Bearer <API Key>`。上传使用 `multipart/form-data`，删除使用 `application/json`。

## 4. 功能流程

### 4.1 加载工作区

1. 保存 Key 后调用 `GET /v1/workspaces`；
2. 工作区数组填充 `<select>`，默认选中第一个；
3. 调用 `GET /v1/workspace/{slug}` 加载文档；
4. 文档字段兼容 `metadata` 为对象或 JSON 字符串：标题、类型、词数、发布时间、`docpath` 来源路径。

### 4.2 上传并嵌入

1. 选择一个或多个文件；
2. 对每个文件单独构造 `FormData`，追加 `file` 和 `addToWorkspaces=<slug>`；
3. `POST /v1/document/upload`；
4. 每个文件显示“等待 / 上传中 / 成功 / 失败：原因”；
5. 成功数 > 0 时重新拉取列表，并按返回的 `location`/`docpath` 高亮 2 秒；
6. 底部日志显示成功/失败数量。

上传过程中按钮、文件选择、工作区选择全部禁用；结束后恢复。

### 4.3 删除

1. 点击文档行“删除”，`confirm()` 二次确认；
2. 行变半透明，按钮显示“删除中…”；
3. `POST /v1/workspace/{slug}/update-embeddings`，`deletes` 传 `docpath`；
4. 优先用响应中的 `documents` 校验文件是否真的消失；响应不含列表时重新拉取；
5. 仍存在则报“接口返回成功，但文件仍在工作区中”，避免假成功；
6. 成功后显示“已从工作区移除”，失败恢复行并显示原因。

### 4.4 搜索

列表上方输入框按文件名前端过滤，不额外请求；显示“共 N 个文件（筛选后 M 个）”。

## 5. 三种状态

| 状态 | 表现 |
| --- | --- |
| 加载中 | 工作区“加载中…”、列表“加载中…”、刷新按钮“刷新中…”。 |
| 成功 | 工作区数量、文件总数、绿色“已保存/已从工作区移除”、上传成功计数。 |
| 失败 | 红色状态文本与底部日志；工作区/列表清空；Key 错误、网络错误、HTTP 错误、JSON 解析错误分别有可读消息。 |

## 6. 安全说明

- 无硬编码 Key；`grep -rn "Bearer [A-Za-z0-9]"` 在源码中无命中（仅运行时拼接）。
- 所有来自接口的文本用 `textContent` 渲染，不拼接 `innerHTML`，避免 XSS。
- Key 存在 `localStorage`，同源脚本可读；不要在共享电脑上保存长期 Key，使用后点“清除”。
- 删除前有 `confirm()`，且调用后再次校验列表，降低误删/假成功。

## 7. 常见问题

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| 页面显示“未配置 API Key” | 未保存 Key 或已清除 | 在顶部输入并保存。 |
| “网络请求失败，请确认 AnythingLLM 服务已启动” | 3001 未启动或地址不对 | 启动 AnythingLLM；如改过端口，修改 `index.html` 的 `API` 常量。 |
| 请求失败（401/403） | Key 错误或无权限 | 重新生成 Key；确认工作区可见。 |
| 请求失败（CORS） | 静态页与 API 不同源 | 用 HTTP 服务打开页面，或调整 AnythingLLM 的允许来源。 |
| 没有可用的工作区 | AnythingLLM 中尚未创建工作区 | 先在 AnythingLLM 创建工作区。 |
| 上传成功但列表没有 | 向量化/加入工作区失败 | 查看底部每文件状态；在 AnythingLLM 中确认文档是否已加入工作区。 |
| 删除提示“文件仍在工作区中” | 接口返回成功但实际未移除 | 刷新重试；检查 `docpath` 是否与列表一致。 |

## 8. 验证

1. 清除 localStorage 后刷新：所有操作禁用且显示红色错误。
2. 保存有效 Key：工作区下拉框有数据，文件列表来自接口。
3. 上传一个小 `.md`：逐文件状态变为成功，列表出现新文件并高亮。
4. 删除该文件并确认：列表消失，底部显示“已从工作区移除”。
5. 在开发者工具 Sources 中搜索 Key：源码无真实 Key。
