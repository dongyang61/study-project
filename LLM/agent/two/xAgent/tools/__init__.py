"""xAgent 工具集合：本地工具 + 动态 MCP 工具。"""

from .create_mcp import CREATE_MCP_TOOL, create_mcp
from .fetch_web import FETCH_WEB_TOOL, FetchWebError, fetch_web
from .load_skill import LOAD_SKILL_TOOL, load_skill
from .run_cli import RUN_CLI_TOOL, RunCliError, run_cli
from .search_web import SEARCH_WEB_TOOL, SearchWebError, search_web

__all__ = [
    "CREATE_MCP_TOOL",
    "create_mcp",
    "FETCH_WEB_TOOL",
    "FetchWebError",
    "fetch_web",
    "LOAD_SKILL_TOOL",
    "load_skill",
    "LOCAL_TOOLS",
    "LOCAL_FUNCTIONS",
    "RUN_CLI_TOOL",
    "RunCliError",
    "run_cli",
    "SEARCH_WEB_TOOL",
    "SearchWebError",
    "search_web",
    "all_tools",
    "dispatch",
]

LOCAL_TOOLS = [
    SEARCH_WEB_TOOL,
    FETCH_WEB_TOOL,
    RUN_CLI_TOOL,
    LOAD_SKILL_TOOL,
    CREATE_MCP_TOOL,
]

LOCAL_FUNCTIONS = {
    "searchWeb": search_web,
    "fetchWeb": fetch_web,
    "RunCli": run_cli,
    "loadSkill": load_skill,
    "createMCP": create_mcp,
}


def all_tools(include_mcp: bool = True) -> list[dict]:
    """返回全部工具 schema；include_mcp=True 时动态发现 MCP 工具。"""
    tools = list(LOCAL_TOOLS)
    if include_mcp:
        from ..mcp_client import mcp_tool_schemas

        tools.extend(mcp_tool_schemas())
    return tools


def dispatch(name: str, arguments: dict) -> str:
    """统一调度本地工具与 MCP 工具。"""
    func = LOCAL_FUNCTIONS.get(name)
    if func:
        try:
            return func(**arguments)
        except TypeError as exc:
            return f"参数错误：{exc}"
        except Exception as exc:
            return f"执行失败：{exc}"

    from ..mcp_client import call_mcp_tool, is_mcp_tool

    if is_mcp_tool(name):
        return call_mcp_tool(name, arguments)
    return f"未知工具：{name}"