"""流式对话 + Function Calling 基础示例：isLeapYear。"""

from __future__ import annotations

import configparser
import json
import sys
from pathlib import Path

import requests

CONFIG_PATH = Path(__file__).with_name("config.ini")


def is_leap_year(year: int) -> str:
    leap = year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)
    return f"{year} 年是闰年。" if leap else f"{year} 年不是闰年。"


TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "isLeapYear",
            "description": "判断指定年份是否为闰年。",
            "parameters": {
                "type": "object",
                "properties": {
                    "year": {"type": "integer", "description": "要判断的年份。"}
                },
                "required": ["year"],
                "additionalProperties": False,
            },
        },
    }
]

FUNCTIONS = {"isLeapYear": is_leap_year}


def dispatch(name: str, arguments: dict) -> str:
    func = FUNCTIONS.get(name)
    if not func:
        return f"未知工具：{name}"
    try:
        return func(**arguments)
    except TypeError as exc:
        return f"参数错误：{exc}"
    except Exception as exc:
        return f"执行失败：{exc}"


def load_llm_config() -> dict:
    if not CONFIG_PATH.exists():
        raise SystemExit(
            f"缺少配置文件：{CONFIG_PATH}\n请创建 [llm] 小节并填写 base_url、api_key、model。"
        )
    config = configparser.ConfigParser()
    config.read(CONFIG_PATH, encoding="utf-8")
    if not config.has_section("llm"):
        raise SystemExit("config.ini 缺少 [llm] 小节。")
    return dict(config["llm"])


def stream_chat(llm: dict, messages: list[dict]) -> tuple[str, list[dict]]:
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

    return "".join(content_parts), [tool_calls[i] for i in sorted(tool_calls)]


def main() -> None:
    llm = load_llm_config()
    messages: list[dict] = []

    print("输入 exit 或 quit 退出。")
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

        messages.append({"role": "user", "content": question})

        while True:
            print("AI: ", end="", flush=True)
            try:
                content, calls = stream_chat(llm, messages)
            except Exception as exc:
                print(f"\n请求失败：{exc}")
                break
            print()

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
                    print(f"[工具] {name} {arguments}")
                    result = dispatch(name, arguments)

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": call["id"],
                        "content": result,
                    }
                )


if __name__ == "__main__":
    main()