"""上下文压缩支持：Token 统计、原文归档、摘要提示。"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

CONTEXT_DIR = Path(".agents") / "context"
COMPACT_THRESHOLD = 0.6
DEFAULT_CONTEXT_WINDOW = 65536

SUMMARY_SYSTEM = (
    "你是上下文压缩器。把对话压缩成结构化中文摘要，供后续对话继续使用。"
    "必须保留：用户目标与约束、已完成的关键操作与结论、工具调用得到的重要事实"
    "（文件路径、命令、数据）、未完成事项。删除寒暄与重复内容。"
    "只输出摘要正文，不要调用工具。"
)
SUMMARY_INSTRUCTION = "请压缩以上完整对话。"


class ArchiveError(RuntimeError):
    """原始上下文归档失败。"""


def context_window(llm: dict) -> int:
    """模型上下文窗口，可由 [llm] 的 context_window 覆盖。"""
    try:
        value = int(llm.get("context_window") or DEFAULT_CONTEXT_WINDOW)
    except (TypeError, ValueError):
        value = DEFAULT_CONTEXT_WINDOW
    return value if value > 0 else DEFAULT_CONTEXT_WINDOW


def estimate_tokens(messages: list[dict]) -> int:
    """无 usage 时的估算：ASCII 约 4 字符 1 token，非 ASCII 按 1 字符 1 token。"""
    total = 0
    for message in messages:
        total += 4
        content = message.get("content")
        if isinstance(content, str):
            total += _estimate_text(content)
        elif content:
            total += _estimate_text(json.dumps(content, ensure_ascii=False))
        for call in message.get("tool_calls") or []:
            total += _estimate_text(json.dumps(call, ensure_ascii=False))
    return total


def _estimate_text(text: str) -> int:
    ascii_count = sum(1 for char in text if ord(char) < 128)
    return ascii_count // 4 + (len(text) - ascii_count)


def usage_tokens(usage: dict | None) -> int:
    """优先使用 API 返回的 total_tokens，其次 prompt + completion。"""
    if not usage:
        return 0
    total = usage.get("total_tokens")
    if isinstance(total, int) and total > 0:
        return total
    prompt = usage.get("prompt_tokens") or 0
    completion = usage.get("completion_tokens") or 0
    return int(prompt) + int(completion)


def archive_context(messages: list[dict], root=None) -> Path:
    """逐条写入 JSONL；写盘成功才返回路径，失败抛 ArchiveError。

    root 用于跟随会话工作目录；省略时沿用进程当前目录。
    """
    directory = (Path(root).resolve() if root else Path.cwd()) / CONTEXT_DIR
    try:
        directory.mkdir(parents=True, exist_ok=True)
        path = _unique_path(directory)
        with path.open("w", encoding="utf-8") as fh:
            for message in messages:
                fh.write(json.dumps(message, ensure_ascii=False) + "\n")
            fh.flush()
    except OSError as exc:
        raise ArchiveError(f"归档原始上下文失败：{exc}") from exc
    return path


def _unique_path(directory: Path) -> Path:
    stem = datetime.now().strftime("%Y%m%d-%H%M%S")
    path = directory / f"{stem}.jsonl"
    index = 1
    while path.exists():
        path = directory / f"{stem}-{index}.jsonl"
        index += 1
    return path


def summary_messages(messages: list[dict]) -> list[dict]:
    """在原始对话前后加上压缩指令；去掉原 system 避免重复。"""
    body = [message for message in messages if message.get("role") != "system"]
    return [
        {"role": "system", "content": SUMMARY_SYSTEM},
        *body,
        {"role": "user", "content": SUMMARY_INSTRUCTION},
    ]