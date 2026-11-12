"""LLM 流式调用。"""

from __future__ import annotations

import json

import requests

from .tools import TOOLS


def stream_chat(llm: dict, messages: list[dict], on_text=None) -> tuple[str, list[dict]]:
    response = requests.post(
        f"{llm['base_url'].rstrip('/')}/chat/completions",
        headers={"Authorization": f"Bearer {llm['api_key']}"},
        json={
            "model": llm["model"],
            "messages": messages,
            "tools": TOOLS,
            "stream": True,
        },
        stream=True,
        timeout=120,
    )
    response.raise_for_status()

    content_parts = []
    tool_calls: dict[int, dict] = {}

    for line in response.iter_lines(decode_unicode=True):
        if not line or not line.startswith("data: "):
            continue
        data = line[6:]
        if data == "[DONE]":
            break
        delta = json.loads(data)["choices"][0].get("delta") or {}

        if delta.get("content"):
            content_parts.append(delta["content"])
            if on_text:
                on_text(delta["content"])

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

    return "".join(content_parts), [tool_calls[i] for i in sorted(tool_calls)]