"""xAgent 工具集合。"""

from .fetch_web import FETCH_WEB_TOOL, FetchWebError, fetch_web
from .search_web import SEARCH_WEB_TOOL, SearchWebError, search_web

__all__ = [
    "FETCH_WEB_TOOL",
    "FetchWebError",
    "fetch_web",
    "SEARCH_WEB_TOOL",
    "SearchWebError",
    "search_web",
]