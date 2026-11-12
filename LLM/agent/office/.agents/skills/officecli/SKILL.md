---
name: officecli
description: 创建、读取、检查、修改 Word/Excel/PPT（.docx/.xlsx/.pptx），支持文本提取、结构查看、格式修改与预览。
---

# OfficeCLI

可执行文件（Windows）：

`D:\study\LLM\agent\office\OfficeCli_#SULP#_26sc1d\officecli-win-x64.exe`

通过 `RunCli` 调用：`command` 使用上面的完整路径，`args` 传参数数组，不要拼接 Shell 字符串。

## 常用命令

- 版本：`["--version"]`
- 帮助：`["help", "docx"]`、`["help", "docx", "paragraph"]`
- 新建：`["create", "report.docx"]`
- 查看结构：`["view", "report.docx", "outline"]`
- 提取文本：`["view", "report.docx", "text", "--max-lines", "200"]`
- 定位元素：`["get", "report.docx", "/body", "--depth", "1", "--json"]`
- 添加段落：`["add", "report.docx", "/body", "--type", "paragraph", "--prop", "text=正文"]`
- 修改格式：`["set", "report.docx", "/body/p[1]", "--prop", "bold=true"]`

## 工作流

1. 新建文档用 `create`；已有文档先 `view outline` / `view stats` 了解结构。
2. 用 `get` / `query` 定位元素，优先 `--json` 和稳定的 `@id=` 路径。
3. 用 `add` / `set` / `remove` 修改；不确定属性名时先执行 `help`。
4. 需要完整手册时，调用 `loadSkill` 加载本 Skill 的 `reference.md`。

## 注意

- 文件路径相对 Agent 的运行目录；写入前确认目录存在。
- 输出过长会被 `RunCli` 截断，尽量用 `--max-lines`、`query` 或 `get --depth` 缩小范围。
- 修改后如需交给 Word、python-docx 等外部程序读取，先执行 `save` 或 `close`。
- xlsx 的单元格路径形如 `/Sheet1/A1`；pptx 用 `/slide[1]`。