"""最小日志器：统一时间、级别、事件名，运行时不直接 print 诊断信息。

CLI/TUI 的用户可见输出仍由事件回调负责；本模块只记录诊断/调用事件。
"""

from __future__ import annotations

import logging
import sys

FORMAT = "%(asctime)s %(levelname)s [%(name)s] %(message)s"
DATEFMT = "%Y-%m-%d %H:%M:%S"


def get_logger(name: str = "xAgent") -> logging.Logger:
    logger = logging.getLogger(name)
    if not logger.handlers:
        handler = logging.StreamHandler(sys.stderr)
        handler.setFormatter(logging.Formatter(FORMAT, datefmt=DATEFMT))
        logger.addHandler(handler)
        logger.setLevel(logging.INFO)
        logger.propagate = False
    return logger
