"""fetchWeb: 获取网页正文并转换为 Markdown 的 Function Calling 工具。

依赖：
    - 系统可用的 curl（Windows 10+ / Linux / macOS 通常已自带）
    - Python 包 trafilatura（pip install trafilatura）

用法：
    from xAgent.tools.fetch_web import FETCH_WEB_TOOL, fetch_web

    tools = [FETCH_WEB_TOOL]
    result = fetch_web("https://example.com/article")
"""

from __future__ import annotations

import re
import shutil
import subprocess
from urllib.parse import urlparse

__all__ = [
    "TOOL_NAME",
    "FETCH_WEB_TOOL",
    "FetchWebError",
    "fetch_web",
]

TOOL_NAME = "fetchWeb"

# OpenAI / 兼容接口的 Function Calling 工具定义
FETCH_WEB_TOOL = {
    "type": "function",
    "function": {
        "name": TOOL_NAME,
        "description": (
            "获取指定网页的主要内容，自动去除导航栏、广告、页脚等无关内容，"
            "并以 Markdown 格式返回正文（保留标题、段落、列表、表格和链接）。"
            "当需要阅读某个网页的详细内容时调用此工具。"
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "url": {
                    "type": "string",
                    "description": "要抓取的网页 URL，必须以 http:// 或 https:// 开头。",
                }
            },
            "required": ["url"],
            "additionalProperties": False,
        },
    },
}

# 默认超时时间（秒）
DEFAULT_TIMEOUT = 30

_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)


class FetchWebError(RuntimeError):
    """抓取或解析网页失败。"""


def _find_curl() -> str:
    """定位 curl 可执行文件，找不到时交给 subprocess 抛出 FileNotFoundError。"""
    return shutil.which("curl") or ("curl.exe" if shutil.which("curl.exe") else "curl")


def _validate_url(url: str) -> str:
    if not isinstance(url, str) or not url.strip():
        raise FetchWebError("URL 不能为空。")

    url = url.strip()
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise FetchWebError(f"无效的 URL：{url}（仅支持 http:// 或 https://）。")

    return url


def _decode_html(raw: bytes) -> str:
    """按 meta charset、UTF-8、GB18030 的顺序解码 HTML。"""
    if not raw:
        return ""

    encodings = []
    match = re.search(
        rb"charset\s*=\s*[\"']?\s*([A-Za-z0-9._-]+)", raw[:4096], re.IGNORECASE
    )
    if match:
        encodings.append(match.group(1).decode("ascii", "ignore"))

    encodings.extend(["utf-8", "gb18030"])

    for encoding in encodings:
        try:
            return raw.decode(encoding).lstrip("\ufeff")
        except (LookupError, UnicodeDecodeError):
            continue

    return raw.decode("utf-8", errors="replace")


def _download_html(url: str, timeout: int) -> str:
    """通过 curl 下载网页 HTML，使用参数列表调用，不使用 shell=True。"""
    curl = _find_curl()
    connect_timeout = max(1, min(10, timeout))

    command = [
        curl,
        "--location",
        "--fail",
        "--silent",
        "--show-error",
        "--compressed",
        "--max-redirs",
        "5",
        "--connect-timeout",
        str(connect_timeout),
        "--max-time",
        str(timeout),
        "--proto",
        "=http,https",
        "--proto-redir",
        "=http,https",
        "--user-agent",
        _USER_AGENT,
        "--header",
        "Accept: text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "--header",
        "Accept-Language: zh-CN,zh;q=0.9,en;q=0.8",
        "--url",
        url,
    ]

    try:
        completed = subprocess.run(
            command,
            capture_output=True,
            timeout=timeout + 5,
            check=False,
        )
    except FileNotFoundError as exc:
        raise FetchWebError(
            "未找到 curl 程序，请先安装 curl 并确保它位于 PATH 中。"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise FetchWebError(f"访问网页超时（超过 {timeout} 秒）：{url}") from exc
    except OSError as exc:
        raise FetchWebError(f"启动 curl 失败：{exc}") from exc

    if completed.returncode != 0:
        error = completed.stderr.decode("utf-8", errors="replace").strip()
        raise FetchWebError(
            f"访问网页失败（curl 退出码 {completed.returncode}）："
            f"{error or '未知错误'}"
        )

    html = _decode_html(completed.stdout)
    if not html.strip():
        raise FetchWebError("网页返回了空内容。")

    if "<" not in html or ">" not in html:
        raise FetchWebError("返回内容不是有效的 HTML。")

    return html


def _extract_markdown(html: str, url: str) -> str:
    """使用 trafilatura 提取正文并转换为 Markdown。"""
    try:
        import trafilatura
    except ImportError as exc:
        raise FetchWebError(
            "缺少依赖 trafilatura，请先执行：pip install trafilatura"
        ) from exc

    try:
        markdown = trafilatura.extract(
            html,
            url=url,
            output_format="markdown",
            include_links=True,
            include_tables=True,
            include_formatting=True,
            include_images=False,
            deduplicate=True,
        )
    except Exception as exc:  # trafilatura 解析异常类型较多，统一包装
        raise FetchWebError(f"HTML 解析失败：{exc}") from exc

    if not markdown or not markdown.strip():
        raise FetchWebError("无法从网页中提取正文内容。")

    return markdown.strip()


def _extract_title(html: str, url: str) -> str:
    """尽量获取网页标题，失败时返回空字符串，不影响正文提取。"""
    try:
        import trafilatura

        metadata = trafilatura.extract_metadata(html, default_url=url)
        if metadata and metadata.title:
            return metadata.title.strip()
    except Exception:
        pass

    match = re.search(r"<title[^>]*>(.*?)</title>", html, re.IGNORECASE | re.DOTALL)
    if match:
        return re.sub(r"\s+", " ", match.group(1)).strip()

    return ""


def fetch_web(url: str, timeout: int = DEFAULT_TIMEOUT) -> str:
    """抓取网页并返回 Markdown 正文及原始 URL。

    参数:
        url: 网页地址，仅支持 http/https。
        timeout: 下载超时时间（秒）。

    返回:
        包含原始 URL、标题和 Markdown 正文的字符串。失败时返回以
        ``获取网页失败：`` 开头的错误说明，便于直接作为工具结果传给 LLM。
    """
    try:
        url = _validate_url(url)
        if not isinstance(timeout, (int, float)) or timeout <= 0:
            timeout = DEFAULT_TIMEOUT

        html = _download_html(url, int(timeout))
        markdown = _extract_markdown(html, url)
        title = _extract_title(html, url)

        parts = [f"原始 URL：{url}"]
        if title:
            parts.append(f"标题：{title}")
        parts.append("")
        parts.append(markdown)
        return "\n".join(parts)
    except FetchWebError as exc:
        return f"获取网页失败：{exc}"
    except Exception as exc:  # 兜底，避免工具异常中断 Agent 循环
        return f"获取网页失败：{exc}"


if __name__ == "__main__":
    import sys

    if len(sys.argv) < 2:
        print("用法: python fetch_web.py <url>")
        raise SystemExit(1)

    print(fetch_web(sys.argv[1]))