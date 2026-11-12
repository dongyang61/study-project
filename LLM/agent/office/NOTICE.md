# 第三方产物说明

本目录包含随课程资料提供的第三方 OfficeCli 产物。它们**不是本项目原创实现**，不计入自研技能生态：

| 路径 | 性质 | 来源/状态 |
| --- | --- | --- |
| `.agents/skills/officecli/SKILL.md` | OfficeCli 的 Agent Skill 说明（frontmatter + 使用命令） | 随课程资料提供的 OfficeCli 资料；为适配本地路径写入了 Windows 可执行文件位置。 |
| `.agents/skills/officecli/reference.md` | OfficeCli 完整命令参考 | 同上，随包资料。 |
| `OfficeCli_#SULP#_26sc1d/OfficeCli操作说明.md` | OfficeCli 官方/随包操作说明 | 随课程资料提供；文件名在 Git 中可能显示为转义形式。 |
| `OfficeCli_#SULP#_26sc1d/officecli-win-x64.exe` | OfficeCli Windows 可执行文件 | 随课程资料提供；被 `.gitignore` 的 `*.exe` 忽略，不随 Git 交付。 |
| `OfficeCli_#SULP#_26sc1d/officecli-win-x64.exe.old`、`.exe.update` | 升级残留文件 | 本地文件，已由 `.gitignore` 忽略，不随 Git 交付。 |

说明：

- 上游项目仓库地址未随发行包提供，无法在仓库内给出可核验的 URL；如需升级，请以课程资料/OfficeCli 官方发行渠道为准。
- 本仓库未修改 OfficeCli 可执行文件；`SKILL.md` 中的可执行文件路径是本机绝对路径，迁移到其他电脑时需同步修改。
- `scripts/validate_skills.py` 会校验该 Skill 的 frontmatter 与附件路径，但不会把它算作自研技能。
