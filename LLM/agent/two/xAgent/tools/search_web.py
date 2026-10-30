"""searchWeb：百度千帆联网搜索 Function Calling 工具。"""

from __future__ import annotations

import configparser
from pathlib import Path

import requests

TOOL_NAME = "searchWeb"

SEARCH_WEB_TOOL = {
    "type": "function",
    "function": {
        "name": TOOL_NAME,
        "description": "搜索互联网获取最新信息，返回搜索摘要、来源标题和 URL。",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "搜索关键词或问题。",
                }
            },
            "required": ["query"],
            "additionalProperties": False,
        },
    },
}

API_URL = "https://qianfan.baidubce.com/v2/ai_search/web_search"
CONFIG_PATH = Path(__file__).resolve().parents[1] / "config.ini"


class SearchWebError(RuntimeError):
    """搜索失败。"""


def _get_api_key() -> str:
    if not CONFIG_PATH.exists():
        raise SearchWebError(f"缺少配置文件：{CONFIG_PATH}")

    config = configparser.ConfigParser()
    config.read(CONFIG_PATH, encoding="utf-8")
    api_key = config.get("search", "baidu_qianfan_api_key", fallback="").strip()
    if not api_key:
        raise SearchWebError("config.ini 缺少 [search] baidu_qianfan_api_key 配置")
    return api_key


def search_web(query: str, timeout: int = 30) -> str:
    """调用百度千帆搜索 API，返回搜索摘要、来源标题及 URL。"""
    try:
        query = (query or "").strip()
        if not query:
            raise SearchWebError("搜索关键词不能为空")

        headers = {
            "Authorization": f"Bearer {_get_api_key()}",
            "Content-Type": "application/json",
        }
        payload = {
            "messages": [{"role": "user", "content": query}],
            "search_source": "baidu_search_v2",
            "resource_type_filter": [{"type": "web", "top_k": 5}],
        }

        try:
            response = requests.post(
                API_URL, headers=headers, json=payload, timeout=timeout
            )
        except requests.Timeout as exc:
            raise SearchWebError(f"搜索请求超时（{timeout} 秒）") from exc
        except requests.RequestException as exc:
            raise SearchWebError(f"搜索请求失败：{exc}") from exc

        try:
            data = response.json()
        except ValueError as exc:
            raise SearchWebError(
                f"搜索接口返回了无效数据（HTTP {response.status_code}）"
            ) from exc

        if response.status_code != 200:
            message = data.get("message") if isinstance(data, dict) else data
            raise SearchWebError(
                f"搜索接口返回错误（HTTP {response.status_code}）：{message}"
            )
        if isinstance(data, dict) and data.get("code"):
            raise SearchWebError(
                f"搜索接口返回错误：{data.get('message') or data['code']}"
            )

        references = data.get("references") or []
        if not references:
            return f"搜索词：{query}\n\n未找到相关搜索结果。"

        lines = [f"搜索词：{query}", ""]
        for index, reference in enumerate(references, 1):
            title = (reference.get("title") or reference.get("web_anchor") or "无标题").strip()
            content = (reference.get("content") or "").strip()
            if len(content) > 300:
                content = content[:300].rstrip() + "..."
            url = (reference.get("url") or "").strip()

            lines.append(f"{index}. {title}")
            if content:
                lines.append(f"   摘要：{content}")
            if url:
                lines.append(f"   URL：{url}")
            lines.append("")

        return "\n".join(lines).strip()
    except SearchWebError as exc:
        return f"搜索失败：{exc}"
    except Exception as exc:  # 兜底，避免工具异常中断 Agent 循环
        return f"搜索失败：{exc}"


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("用法: python search_web.py <query>")
        raise SystemExit(1)

    print(search_web(" ".join(sys.argv[1:])))