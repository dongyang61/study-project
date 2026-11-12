"""配置加载。"""

from __future__ import annotations

import configparser
from pathlib import Path


class ConfigError(RuntimeError):
    """配置加载错误。"""


def load_llm_config(path) -> dict:
    path = Path(path)
    if not path.exists():
        raise ConfigError(
            f"缺少配置文件：{path}\n请创建 [llm] 小节并填写 base_url、api_key、model。"
        )
    config = configparser.ConfigParser()
    config.read(path, encoding="utf-8")
    if not config.has_section("llm"):
        raise ConfigError("config.ini 缺少 [llm] 小节。")
    return dict(config["llm"])