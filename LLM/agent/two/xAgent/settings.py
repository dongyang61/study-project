"""配置读取：统一 [llm] / [search] / [agent] 的定位与类型转换。

配置文件查找顺序（前者优先）：
1. 显式传入的路径；
2. 进程当前目录下的 config.ini；
3. xAgent 上一级目录（LLM/agent/two）下的 config.ini。

真实 config.ini 已被 .gitignore 忽略，仓库只交付 config.example.ini。
"""

from __future__ import annotations

import configparser
from pathlib import Path

CONFIG_NAME = "config.ini"

DEFAULT_AGENT_FILE = "AGENT.md"
FALLBACK_AGENT_FILE = "AGENTS.md"
DEFAULT_AGENT_MAX_CHARS = 8000
DEFAULT_MAX_STEPS = 20
DEFAULT_TURN_TIMEOUT = 300
DEFAULT_SKILL_MAX_CHARS = 50000


def config_candidates() -> list[Path]:
    return [
        Path.cwd() / CONFIG_NAME,
        Path(__file__).resolve().parents[1] / CONFIG_NAME,
    ]


def find_config(path=None) -> Path | None:
    candidates = [Path(path)] if path else config_candidates()
    for candidate in candidates:
        if candidate.is_file():
            return candidate.resolve()
    return None


def read_config(path=None) -> configparser.ConfigParser:
    config = configparser.ConfigParser()
    found = find_config(path)
    if found is not None:
        config.read(found, encoding="utf-8")
    return config


def _as_bool(value, default: bool) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def _as_int(value, default: int, minimum: int | None = None) -> int:
    try:
        number = int(str(value).strip())
    except (TypeError, ValueError):
        number = default
    if minimum is not None and number < minimum:
        number = default
    return number


def _as_float(value, default: float, minimum: float | None = None) -> float:
    try:
        number = float(str(value).strip())
    except (TypeError, ValueError):
        number = default
    if minimum is not None and number < minimum:
        number = default
    return number


def agent_settings(path=None) -> dict:
    """读取 [agent] 段，缺省值与代码中的安全默认一致。"""
    config = read_config(path)
    section = config["agent"] if config.has_section("agent") else {}

    agent_file = str(section.get("agent_file", DEFAULT_AGENT_FILE)).strip()
    return {
        "agent_file": agent_file or DEFAULT_AGENT_FILE,
        "agent_file_enabled": _as_bool(
            section.get("agent_file_enabled"), True
        ),
        "agent_file_max_chars": _as_int(
            section.get("agent_file_max_chars"), DEFAULT_AGENT_MAX_CHARS, minimum=1
        ),
        "workspace_allow_outside": _as_bool(
            section.get("workspace_allow_outside"), False
        ),
        "max_steps": _as_int(section.get("max_steps"), DEFAULT_MAX_STEPS, minimum=1),
        "turn_timeout": _as_float(
            section.get("turn_timeout"), float(DEFAULT_TURN_TIMEOUT), minimum=1
        ),
        "skill_max_chars": _as_int(
            section.get("skill_max_chars"), DEFAULT_SKILL_MAX_CHARS, minimum=1
        ),
    }


def search_api_key(path=None) -> str:
    config = read_config(path)
    if not config.has_section("search"):
        return ""
    return str(config.get("search", "baidu_qianfan_api_key", fallback="")).strip()
