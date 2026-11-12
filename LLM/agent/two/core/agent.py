"""对话循环：请求 -> 执行工具 -> 继续请求，直到无工具调用。"""

from __future__ import annotations

import json

from .llm import stream_chat
from .tools import dispatch


def run_turn(llm: dict, messages: list[dict], user_text: str, on_event=None) -> None:
    """事件：text / tool_call / tool_result / error。"""
    emit = on_event or (lambda event: None)
    messages.append({"role": "user", "content": user_text})

    while True:
        try:
            content, calls = stream_chat(
                llm, messages, on_text=lambda text: emit({"type": "text", "text": text})
            )
        except Exception as exc:
            emit({"type": "error", "message": str(exc)})
            break

        if not calls:
            messages.append({"role": "assistant", "content": content})
            break

        messages.append(
            {"role": "assistant", "content": content or None, "tool_calls": calls}
        )
        for call in calls:
            name = call["function"]["name"]
            try:
                arguments = json.loads(call["function"]["arguments"] or "{}")
            except json.JSONDecodeError:
                result = "参数解析失败：工具参数不是有效 JSON。"
            else:
                emit({"type": "tool_call", "name": name, "arguments": arguments})
                result = dispatch(name, arguments)
                emit({"type": "tool_result", "name": name, "result": result})

            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": call["id"],
                    "content": result,
                }
            )