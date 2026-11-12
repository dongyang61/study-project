"""xAgent：工具集合、Agent Skills 与 MCP Client。"""

from .mcp_client import (
    MCPError,
    MCPManager,
    MCPTool,
    call_mcp_tool,
    get_mcp_manager,
    load_mcp_config,
    mcp_tool_schemas,
    reset_mcp_manager,
)
from .skills import (
    Skill,
    SkillRegistry,
    build_system_prompt,
    get_registry,
    init_skills,
)

__all__ = [
    "MCPError",
    "MCPManager",
    "MCPTool",
    "Skill",
    "SkillRegistry",
    "build_system_prompt",
    "call_mcp_tool",
    "get_mcp_manager",
    "get_registry",
    "init_skills",
    "load_mcp_config",
    "mcp_tool_schemas",
    "reset_mcp_manager",
]