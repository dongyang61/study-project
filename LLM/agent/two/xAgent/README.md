# xAgent：本地工具 Agent

`xAgent` 是 `LLM/agent/two` 下的会话核心：OpenAI 兼容流式对话 + 工具循环 + Agent Skills + MCP 客户端 + AGENT.md + 会话持久化。CLI 与 Textual TUI 共用同一个 `AgentSession`。

## 1. 目录与分层

| 文件/目录 | 职责 |
| --- | --- |
| `agent.py` | `AgentSession`、工具循环、步数/超时保护、CLI 入口 |
| `settings.py` | 定位 `config.ini`，解析 `[llm]`/`[search]`/`[agent]` 默认值 |
| `agent_md.py` | 读取 `AGENT.md`/`AGENTS.md`、截断、生成注入段落 |
| `skills.py` | 扫描 `.agents/skills/*/SKILL.md`，frontmatter 解析、渐进注入、按需读取 |
| `sessions.py` | `.agents/sessions/<id>.jsonl` 原子读写、元信息、列表 |
| `mcp_client.py` | 读取 `.mcp.json`，持久 ClientSession，stdio/Streamable HTTP，来源前缀 |
| `context.py` | token 估算、60% 阈值、原文归档、摘要消息构造 |
| `logger.py` | 统一最小日志（时间、级别、logger 名、消息） |
| `tools/` | 18 个本地工具及 schema、统一 `dispatch` |
| `scripts/validate_skills.py` | 技能目录静态校验，错误退出码 1 |
| `requirements.txt` | Python 依赖（`mcp>=2.3.0,<3`、`httpx2>=2.0` 等） |
| `config.example.ini` | 配置模板，复制为 `../config.ini` 后填写 |

## 2. 安装与启动

要求 Python 3.13+（已验证 3.13.7）。

```powershell
# 安装与配置（在 LLM/agent/two 下执行一次）
cd LLM/agent/two
python -m pip install -r xAgent/requirements.txt
python -m pip install -r requirements.txt
Copy-Item xAgent/config.example.ini config.ini
# 编辑 config.ini，填写 [llm] 的 base_url / api_key / model
```

仅用本地工具时，当前目录就是工作目录：

```powershell
cd LLM/agent/two
python -m xAgent     # CLI
python -m tui        # Textual TUI
```

要加载 `LLM/agent/office/.mcp.json` 与 office 下的技能，把工作目录切到 office，并用 `PYTHONPATH` 指向 `two`：

```powershell
cd LLM/agent/office
$env:PYTHONPATH = (Resolve-Path '..\two').Path
python -m xAgent     # CLI
python -m tui        # Textual TUI
```

Agent 的 `.mcp.json` 与 `.agents/skills/` 都相对于**启动工作目录**读取；切换目录即切换工作区。
`config.ini` 查找顺序：显式传入路径 → 当前目录 → `LLM/agent/two/config.ini`。真实 `config.ini` 不提交。

## 3. 配置字段

| 小节 | 字段 | 默认 | 作用 |
| --- | --- | --- | --- |
| `[llm]` | `base_url` | 无 | OpenAI 兼容 API 基址，代码拼接 `/chat/completions`。 |
| `[llm]` | `api_key` | 无 | Bearer Key。 |
| `[llm]` | `model` | 无 | 模型名。 |
| `[llm]` | `context_window` | `65536` | 上下文窗口；用量达到 60% 时阻塞并提示 `/compact`。 |
| `[search]` | `baidu_qianfan_api_key` | 空 | `searchWeb` 使用；为空返回配置错误。 |
| `[agent]` | `agent_file` | `AGENT.md` | 长期规则文件名。 |
| `[agent]` | `agent_file_enabled` | `true` | 是否读取/注入。 |
| `[agent]` | `agent_file_max_chars` | `8000` | 截断阈值。 |
| `[agent]` | `workspace_allow_outside` | `false` | 是否允许文件工具越出工作目录。 |
| `[agent]` | `max_steps` | `20` | 单轮最多请求步数。 |
| `[agent]` | `turn_timeout` | `300` | 单轮总超时（秒）。 |
| `[agent]` | `skill_max_chars` | `50000` | `loadSkill` 单文件上限。 |

## 4. 工具清单（18 个本地工具 + 动态 MCP）

### 4.1 文件/目录（10）

| 工具 | 行为 | 关键约束 |
| --- | --- | --- |
| `get_cwd` | 返回当前会话工作目录的绝对路径。 | 恢复会话后跟随会话 meta 的 `cwd`。 |
| `list_dir` | 枚举真实目录项，目录在前。 | 路径不存在报错。 |
| `get_file_type` | 返回类型、扩展名、是否 UTF-8 纯文本。 | 真实读取文件头判断二进制。 |
| `read_text_file` | 读取 UTF-8 文本。 | 非文本/非 UTF-8 明确拒绝。 |
| `create_file` | 在已存在目录下创建新文件。 | 已存在拒绝，不覆盖。 |
| `edit_text_file` | 覆盖写入文本。 | 必须 `confirm=true`，否则只返回目标摘要。 |
| `create_dir` | 创建多级目录。 | 目录已存在返回提示。 |
| `delete_dir` | 递归删除目录。 | 必须 `confirm=true`。 |
| `delete_file` | 删除文件。 | 必须 `confirm=true`。 |
| `rename_path` | 重命名/移动文件或目录。 | 必须 `confirm=true`；目标已存在拒绝。 |

写/删/改名默认限制在 `<workspace>` 内：`Path.resolve()` 后必须 `is_relative_to(workspace)`；越界返回“拒绝…不在工作目录内”，并提示 `workspace_allow_outside=true` 的风险开关。

### 4.2 时间与闰年（2）

| 工具 | 行为 |
| --- | --- |
| `getCurrentTime` | `datetime.now()` + `zoneinfo`；`timezone=local` 或 IANA 名称（`Asia/Shanghai`、`UTC`）；`format=iso/text/timestamp`；返回 ISO 与 Unix 秒级时间戳。 |
| `isLeapYear` | 规则 `year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)`；1900 否、2000 是。 |

`LLM/agent/two/chat-stream-tool-isLeapYear.py` 复用 `xAgent.tools.time_tools.is_leap_year`，不再维护第二份规则。

### 4.3 网络与命令（3）

| 工具 | 行为 |
| --- | --- |
| `searchWeb` | 调百度千帆搜索 API，返回摘要、标题、URL；Key 来自 `[search]`。 |
| `fetchWeb` | 下载网页并用 trafilatura 提取正文，输出 Markdown，自动去导航/广告。 |
| `RunCli` | 执行本机已安装命令（`command` + `args` 列表），不经过 Shell；返回 stdout/stderr/退出码，超长截断。 |

### 4.4 技能（2）

| 工具 | 行为 |
| --- | --- |
| `loadSkill` | `name` 读取 `SKILL.md` 全文；`filename` 读取技能目录内相对附件；单文件 >50000 字符截断并提示；拒绝绝对路径与 `..`。 |
| `createSkill` | 原子创建 `<workspace>/.agents/skills/<name>/SKILL.md` 与附件；拒绝覆盖并返回现有技能列表。 |

### 4.5 MCP（1 + 动态）

| 工具 | 行为 |
| --- | --- |
| `createMCP` | 把 MCP Server 配置写入工作目录 `.mcp.json`，支持 stdio 与 streamable_http。 |
| `<server>__<tool>` | 启动时从 `.mcp.json` 动态发现；描述前缀 `[MCP:<server>]`；重名自动加 `_2`。 |

## 5. 技能机制

### 5.1 目录与格式

```text
<workspace>/.agents/skills/
└── pdf-report/
    ├── SKILL.md
    └── examples/demo.md
```

`SKILL.md` 必须以 YAML frontmatter 开头：

```markdown
---
name: pdf-report
description: 生成 PDF 周报，包含表格与图表。
---

# 使用说明

正文按需加载，不进入启动提示。
```

### 5.2 创建

模型调用示例：

```json
{
  "name": "pdf-report",
  "description": "生成 PDF 周报",
  "content": "# 步骤\n1. 收集数据\n2. 生成 PDF",
  "files": [
    {"path": "examples/demo.md", "content": "示例"}
  ]
}
```

真实行为：

- `name` 必须匹配 `^[a-z0-9][a-z0-9-_]{0,63}$`；
- 同名目录已存在 → `拒绝覆盖…现有技能：…`；
- 附件只允许技能目录内相对路径，拒绝绝对路径、`..`、覆盖 `SKILL.md`；
- 先写 `.tmp-<name>-<随机>`，再 `os.replace` 到目标目录；失败清理临时目录；
- 创建成功后立即刷新技能索引，重启后启动扫描同样能发现。

命令行校验：

```powershell
python LLM/agent/two/xAgent/scripts/validate_skills.py --root <项目根目录>
```

校验项：`SKILL.md` 存在、frontmatter 的 `name`/`description`、命名正则、name 与目录名一致、name 唯一、附件/符号链接不越界。有错误退出码 1。

### 5.3 发现与渐进加载

- 启动时只解析 frontmatter，把 `name` + `description` 注入 system prompt；
- 正文不会进入 system prompt；
- 模型需要细节时调用 `loadSkill`；
- 加载附件时只允许技能目录内相对路径，并在读取后按 `skill_max_chars` 截断；
- 同一轮内技能索引不变；`createSkill` 成功会刷新。

## 6. AGENT.md 长期规则

- 默认读取 `<workspace>/AGENT.md`；不存在时兼容 `<workspace>/AGENTS.md`；
- 受 `[agent] agent_file_enabled` 控制；缺失/关闭都静默，不报错、不注入；
- 超过 `agent_file_max_chars` 截断，末尾追加 `（已截断）`；
- 注入一次到 system prompt，位于基础提示与技能列表之后；
- `/resume` 会按会话保存的 `cwd` 重新读取 AGENT.md，并重建唯一 system 消息，不重复叠加。

## 7. MCP 接入

配置文件：`<workspace>/.mcp.json`。

```json
{
  "mcpServers": {
    "PetHospitalMCP": {
      "type": "streamable_http",
      "url": "http://127.0.0.1:8090/mcp"
    },
    "local-demo": {
      "type": "stdio",
      "command": "python",
      "args": ["demo_server.py"],
      "env": {"TOKEN": "..."},
      "timeout": 60
    }
  }
}
```

行为：

- 每个 Server 一个后台事件循环上的持久 `ClientSession`，跨调用复用；断开后下次自动重建；
- `type` 兼容 `streamable_http`/`streamable-http`/`streamablehttp`/`http`，缺省时按 `command`/`url` 推断；
- 外部工具统一命名 `<server>__<tool>`，与本地工具或其他 Server 重名也不会覆盖；
- `tools/list` 只列已连接成功的 Server；连接失败写入 `manager.errors`、日志告警，主流程继续；
- 工具调用错误以文本返回给模型；`isError` 会在结果前标注；
- `createMCP` 成功后下一轮重新执行 `all_tools()`，新工具立即可用。

## 8. 会话持久化与恢复

保存位置：`<workspace>/.agents/sessions/<session-id>.jsonl`。

- 第 1 行 `{"type":"meta",...}`：`sessionId`、`createdAt`、`updatedAt`、`cwd`、`model`、`messageCount`、`lastTokens`、`lastUsage`、`state`；
- 后续行 `{"type":"message","message":{...}}`；
- 写入使用同目录临时文件 + `fsync` + `os.replace`，避免半截文件；
- 每轮结束与 `/compact` 后自动保存。

命令：

| 命令 | 行为 |
| --- | --- |
| `/save` | 立即保存并显示路径。 |
| `/sessions` | 按更新时间倒序列出 ID、时间、消息数、模型、cwd。 |
| `/resume <id>` | 读取当前工作目录 `.agents/sessions` 下的会话；若 meta 的 cwd 存在则切换过去，重建文件边界、技能索引与 AGENT.md，恢复消息与 token/usage。 |
| `/new` | 先保存当前会话，再新建 ID 与空上下文。 |
| `/compact` | 归档原文到 `.agents/context/`，调用模型生成摘要，替换上下文；失败不修改原消息。 |

注意：会话按工作目录隔离。若从另一个工作目录启动，需要把原 `.jsonl` 放到该目录的 `.agents/sessions/`，或从保存它的工作目录启动。

## 9. 单轮限制与上下文

- `max_steps`：每次模型请求算一步；达到上限停止工具循环；
- `turn_timeout`：从用户提交开始计时；超时后未执行的 tool_call 也会补一条“未执行”结果，保证消息结构完整；
- 到达任一限制会追加 `[系统提示] ...` 消息并发出 `limit` 事件，CLI 打印 `[限制] ...`，TUI 红色显示；控制权返回用户；
- 上下文用量优先取 API `usage.total_tokens`，否则估算；达到窗口 60% 进入 `blocked`，要求 `/compact`。

## 10. TUI 与 CLI

CLI：`python -m xAgent`。TUI：`python -m tui`。

TUI 只渲染事件：

- `text`：流式追加；
- `tool_call`：黄色显示工具名与参数；
- `warning`/`error`：红色；
- `limit`：显示停止原因与步数；
- `session_saved`/`session_resumed`/`session_new`/`session_error`：绿色/红色状态。

输入框支持 `/compact`、`/save`、`/sessions`、`/resume <id>`、`/new`、`/help`、`/exit`。TUI 运行工具时禁用输入，结束后恢复。

## 11. 示例对话（示意）

```text
你: 帮我创建一个写周报的技能，名字叫 weekly-report
[工具] createSkill {"name":"weekly-report","description":"生成周报","content":"# 周报\n..."}
AI: 已创建 Skill「weekly-report」…当前可用：weekly-report
你: 用 weekly-report 的说明帮我列一个提纲
[工具] loadSkill {"name":"weekly-report"}
AI: 根据技能说明，提纲如下…
```

实际输出取决于模型；工具调用与落盘行为由上述代码保证。

## 12. 常见错误

| 现象 | 原因 | 处理 |
| --- | --- | --- |
| `找不到包含 [llm] 的 config.ini` | 未复制模板或路径不对 | 复制 `config.example.ini` 为 `two/config.ini`，填 `[llm]`。 |
| `searchWeb 未配置...` | `[search]` Key 为空 | 填 `baidu_qianfan_api_key`。 |
| `拒绝创建/删除/重命名：... 不在工作目录` | 路径越界 | 改用工作目录内路径，或明确设置 `workspace_allow_outside=true`。 |
| `需要 confirm=true 才能...` | 破坏性操作首次调用 | 向用户确认后以 `confirm=true` 重试。 |
| `拒绝覆盖：Skill ... 已存在` | 同名技能 | 换名或手动删除旧目录。 |
| `MCP Server ... 不可用` | 端口/URL/鉴权错误 | 检查 `.mcp.json`、服务是否启动；失败不会阻塞本地工具。 |
| 上下文达到 60% 被阻塞 | 历史太长 | `/compact` 压缩后继续。 |
| `/resume` 找不到会话 | 当前工作目录不是保存时的目录 | 从原工作目录启动，或复制 `.jsonl` 到当前 `.agents/sessions/`。 |

## 13. 自测

```powershell
python -m compileall LLM/agent/two/xAgent
python -m unittest discover -s tests
python LLM/agent/two/xAgent/scripts/validate_skills.py --root LLM/agent/office
```

测试覆盖：闰年 1900/2000、AGENT.md 截断/缺失/恢复、技能创建/拒绝覆盖/路径逃逸/渐进注入、文件边界与 confirm、步数限制、会话保存恢复、MCP 来源前缀、AnythingLLM 缺 Key、宠物医院错误契约。
