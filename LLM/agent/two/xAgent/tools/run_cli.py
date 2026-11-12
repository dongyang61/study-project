"""RunCli：调用本地命令行程序的 Function Calling 工具。

使用参数列表 + ``shell=False`` 执行，避免拼接 Shell 字符串。
仅用于受控教学实验环境：不做命令白名单、黑名单或审批，
命令以运行 xAgent 的当前用户权限执行。
"""

from __future__ import annotations

import subprocess

__all__ = [
    "TOOL_NAME",
    "RUN_CLI_TOOL",
    "RunCliError",
    "run_cli",
]

TOOL_NAME = "RunCli"

RUN_CLI_TOOL = {
    "type": "function",
    "function": {
        "name": TOOL_NAME,
        "description": (
            "运行本地已安装的命令行程序（如 git、python、node），返回标准输出、"
            "标准错误和退出码。command 必须是可执行程序名称或路径，不能是 Shell 内置命令；"
            "参数通过 args 列表逐个传入。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "要执行的程序名称或路径，例如 git、python、C:/tools/foo.exe。",
                },
                "args": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "传给程序的参数列表，例如 [\"status\", \"--short\"]。",
                },
            },
            "required": ["command"],
            "additionalProperties": False,
        },
    },
}

DEFAULT_TIMEOUT = 30
MAX_TIMEOUT = 120
MAX_OUTPUT_CHARS = 6000


class RunCliError(RuntimeError):
    """命令执行失败。"""


def _truncate(text: str) -> str:
    if len(text) <= MAX_OUTPUT_CHARS:
        return text
    omitted = len(text) - MAX_OUTPUT_CHARS
    return (
        text[:MAX_OUTPUT_CHARS]
        + f"\n...（输出已截断：仅显示前 {MAX_OUTPUT_CHARS} 字符，省略 {omitted} 字符）"
    )


def _format_result(
    command_line: str,
    returncode: int | str,
    stdout: str,
    stderr: str,
    note: str = "",
) -> str:
    parts = [f"命令：{command_line}", f"退出码：{returncode}"]
    if note:
        parts.append(note)
    parts.extend(
        [
            "",
            "标准输出：",
            _truncate(stdout) or "（空）",
            "",
            "标准错误：",
            _truncate(stderr) or "（空）",
        ]
    )
    return "\n".join(parts)


def _as_text(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bytes):
        return value.decode("utf-8", errors="replace")
    return value


def run_cli(command: str, args: list[str] | None = None, timeout: int = DEFAULT_TIMEOUT) -> str:
    """执行命令并返回 stdout、stderr、退出码；失败时返回错误说明。"""
    try:
        if not isinstance(command, str) or not command.strip():
            raise RunCliError("command 不能为空。")

        if args is None:
            args = []
        if not isinstance(args, list):
            raise RunCliError("args 必须是字符串列表。")
        if not all(isinstance(item, str) for item in args):
            raise RunCliError("args 中的每一项都必须是字符串。")

        if not isinstance(timeout, (int, float)) or timeout <= 0:
            timeout = DEFAULT_TIMEOUT
        timeout = min(int(timeout), MAX_TIMEOUT)

        command = command.strip()
        command_line = " ".join([command, *args])

        try:
            completed = subprocess.run(
                [command, *args],
                shell=False,
                capture_output=True,
                text=True,
                errors="replace",
                timeout=timeout,
                check=False,
            )
        except FileNotFoundError:
            return f"执行失败：未找到命令 {command!r}，请确认已安装并在 PATH 中。"
        except subprocess.TimeoutExpired as exc:
            return _format_result(
                command_line,
                "超时",
                _as_text(exc.stdout),
                _as_text(exc.stderr),
                f"执行超时：超过 {timeout} 秒，进程已终止。",
            )
        except OSError as exc:
            return f"执行失败：无法启动 {command!r}：{exc}"

        return _format_result(
            command_line, completed.returncode, completed.stdout, completed.stderr
        )
    except RunCliError as exc:
        return f"RunCli 执行失败：{exc}"
    except Exception as exc:  # 兜底，避免工具异常中断 Agent 循环
        return f"RunCli 执行失败：{exc}"


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("用法: python run_cli.py <command> [args...]")
        raise SystemExit(1)

    print(run_cli(sys.argv[1], sys.argv[2:]))