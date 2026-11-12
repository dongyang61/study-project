"""xAgent 最小 CLI 入口：本地工具 + Skills + MCP 工具统一调度。"""

from __future__ import annotations

import configparser
import json
import sys
from pathlib import Path

import requests

from .context import (
    COMPACT_THRESHOLD,
    archive_context,
    context_window,
    estimate_tokens,
    summary_messages,
    usage_tokens,
)
from .mcp_client import get_mcp_manager
from .skills import build_system_prompt
from .tools import all_tools, dispatch

BASE_PROMPT = "你是一个可以调用本地工具和 MCP 工具的助手，请根据工具返回结果继续完成任务。"
CONFIG_CANDIDATES = [Path.cwd() / "config.ini", Path(__file__).resolve().parents[1] / "config.ini"]
COMPACT_THRESHOLD_HINT = f"上下文使用量已达模型窗口的 {COMPACT_THRESHOLD:.0%}"


def load_llm_config(path=None) -> dict:
    candidates = [Path(path)] if path else CONFIG_CANDIDATES
    for candidate in candidates:
        if not candidate.is_file():
            continue
        config = configparser.ConfigParser()
        config.read(candidate, encoding="utf-8")
        if config.has_section("llm"):
            return dict(config["llm"])
    raise SystemExit("找不到包含 [llm] 的 config.ini。")


def stream_chat(llm: dict, messages: list[dict], tools: list[dict], echo: bool = True):
    response = requests.post(
        f"{llm['base_url'].rstrip('/')}/chat/completions",
        headers={"Authorization": f"Bearer {llm['api_key']}"},
        json={
            "model": llm["model"],
            "messages": messages,
            "tools": tools,
            "stream": True,
            "stream_options": {"include_usage": True},
        },
        stream=True,
        timeout=120,
    )
    response.raise_for_status()

    content_parts = []
    tool_calls: dict[int, dict] = {}
    usage: dict | None = None
    for line in response.iter_lines(decode_unicode=True):
        if not line or not line.startswith("data: "):
            continue
        data = line[6:]
        if data == "[DONE]":
            break
        chunk = json.loads(data)
        if chunk.get("usage"):
            usage = chunk["usage"]
        choices = chunk.get("choices") or []
        if not choices:
            continue
        delta = choices[0].get("delta") or {}
        if delta.get("content"):
            content_parts.append(delta["content"])
            if echo:
                sys.stdout.write(delta["content"])
                sys.stdout.flush()
        for call in delta.get("tool_calls") or []:
            index = call.get("index", 0)
            item = tool_calls.setdefault(
                index,
                {"id": "", "type": "function", "function": {"name": "", "arguments": ""}},
            )
            if call.get("id"):
                item["id"] = call["id"]
            function = call.get("function") or {}
            if function.get("name"):
                item["function"]["name"] += function["name"]
            if function.get("arguments"):
                item["function"]["arguments"] += function["arguments"]

    return "".join(content_parts), [tool_calls[i] for i in sorted(tool_calls)], usage


def compact(llm: dict, messages: list[dict]) -> Path:
    """归档原文 -> 生成摘要 -> 替换上下文；任一步失败都不修改 messages。"""
    path = archive_context(messages)
    summary, _calls, _usage = stream_chat(llm, summary_messages(messages), [], echo=False)
    if not summary.strip():
        raise RuntimeError("摘要为空。")
    head = messages[0] if messages and messages[0].get("role") == "system" else None
    replacement = [head] if head else []
    replacement.append({"role": "assistant", "content": f"[历史上下文摘要]\n{summary.strip()}"})
    messages[:] = replacement
    return path


def main() -> None:
    llm = load_llm_config()
    window = context_window(llm)
    tools = all_tools()
    manager = get_mcp_manager()
    for error in manager.errors:
        print(f"[MCP] {error}", file=sys.stderr)
    print(f"已加载 {len(tools)} 个工具，其中 MCP 工具 {len(manager.tools)} 个。")
    print("输入 exit 或 quit 退出，/compact 压缩上下文。")

    messages = [{"role": "system", "content": build_system_prompt(BASE_PROMPT)}]
    state = "normal"  # normal / compacting / blocked
    last_tokens = estimate_tokens(messages)

    def check_context(usage: dict | None) -> None:
        nonlocal state, last_tokens
        last_tokens = usage_tokens(usage) or estimate_tokens(messages)
        if last_tokens >= window * COMPACT_THRESHOLD and state != "blocked":
            state = "blocked"
            print(
                f"\n[上下文] 约 {last_tokens}/{window} tokens，{COMPACT_THRESHOLD_HINT}，"
                "请执行 /compact 压缩上下文。"
            )

    while True:
        try:
            question = input("你: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if question.lower() in {"exit", "quit"}:
            break
        if not question:
            continue

        if question.lower() == "/compact":
            if state == "compacting":
                print("[上下文] 正在压缩，请稍候。")
                continue
            if len(messages) <= 1:
                print("[上下文] 当前没有可压缩的内容。")
                continue
            previous_state = state
            state = "compacting"
            print("AI: 正在压缩上下文……")
            try:
                path = compact(llm, messages)
            except Exception as exc:
                state = previous_state
                print(f"[上下文] 压缩失败：{exc}\n原上下文保持不变，可重试 /compact。")
                continue
            state = "normal"
            last_tokens = estimate_tokens(messages)
            print(f"[上下文] 压缩完成，原始记录已保存：{path}")
            continue

        if state == "blocked":
            print(
                f"[上下文] 约 {last_tokens}/{window} tokens，{COMPACT_THRESHOLD_HINT}，"
                "请先执行 /compact 再继续。"
            )
            continue

        messages.append({"role": "user", "content": question})
        while True:
            print("AI: ", end="", flush=True)
            try:
                content, calls, usage = stream_chat(llm, messages, tools)
            except Exception as exc:
                print(f"\n请求失败：{exc}")
                break
            print()

            if not calls:
                messages.append({"role": "assistant", "content": content})
                check_context(usage)
                break

            messages.append(
                {"role": "assistant", "content": content or None, "tool_calls": calls}
            )
            check_context(usage)
            for call in calls:
                name = call["function"]["name"]
                try:
                    arguments = json.loads(call["function"]["arguments"] or "{}")
                except json.JSONDecodeError:
                    result = "参数解析失败：工具参数不是有效 JSON。"
                else:
                    print(f"[工具] {name} {arguments}")
                    result = dispatch(name, arguments)
                    if name == "createMCP" and result.startswith("已保存"):
                        tools = all_tools()

                messages.append(
                    {"role": "tool", "tool_call_id": call["id"], "content": result}
                )


if __name__ == "__main__":
    main()