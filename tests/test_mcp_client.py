"""MCP 工具来源标记：始终 <server>__<tool>，description 前缀 [MCP:<server>]。"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "LLM" / "agent" / "two"))

import xAgent.mcp_client as mcp_client  # noqa: E402


class FakeTool:
    def __init__(self, name: str, description: str = "desc"):
        self.name = name
        self.description = description
        self.input_schema = {"type": "object", "properties": {}}


class SourceTagTests(unittest.TestCase):
    def test_names_are_always_prefixed(self):
        config = {
            "srv-one": {"type": "streamable_http", "url": "http://127.0.0.1:1/mcp"},
            "srv-two": {"type": "streamable_http", "url": "http://127.0.0.1:2/mcp"},
        }
        with tempfile.TemporaryDirectory() as raw, mock.patch.object(
            mcp_client, "load_mcp_config", return_value=config
        ), mock.patch.object(
            mcp_client._PersistentSession,
            "list_tools",
            return_value=[FakeTool("echo"), FakeTool("list_dir")],
        ), mock.patch.object(mcp_client._PersistentSession, "close"):
            manager = mcp_client.MCPManager(project_root=Path(raw))

        self.assertIn("srv-one__echo", manager.tools)
        self.assertIn("srv-two__echo", manager.tools)
        # 即使与本地工具同名，也会带来源前缀
        self.assertIn("srv-one__list_dir", manager.tools)
        self.assertNotIn("list_dir", manager.tools)
        schema = manager.tools["srv-one__echo"].schema()
        self.assertEqual(schema["function"]["name"], "srv-one__echo")
        self.assertTrue(schema["function"]["description"].startswith("[MCP:srv-one]"))

    def test_conflict_suffix_is_stable(self):
        # 两个 Server 的同一工具名已由前缀区分；这里验证 exposed_name 唯一。
        with tempfile.TemporaryDirectory() as raw, mock.patch.object(
            mcp_client,
            "load_mcp_config",
            return_value={
                "a": {"type": "streamable_http", "url": "http://127.0.0.1:1/mcp"}
            },
        ), mock.patch.object(
            mcp_client._PersistentSession,
            "list_tools",
            return_value=[FakeTool("same"), FakeTool("same")],
        ), mock.patch.object(mcp_client._PersistentSession, "close"):
            manager = mcp_client.MCPManager(project_root=Path(raw))
        self.assertIn("a__same", manager.tools)
        self.assertIn("a__same_2", manager.tools)


if __name__ == "__main__":
    unittest.main()
