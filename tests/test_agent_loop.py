"""Agent 主循环：最大步数、超时、错误可见与自动保存。"""

from __future__ import annotations

import sys
import tempfile
import time
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "LLM" / "agent" / "two"))

import xAgent.agent as agent_module  # noqa: E402
from xAgent.agent import AgentSession  # noqa: E402

LLM = {
    "base_url": "http://127.0.0.1:1",
    "api_key": "test-key",
    "model": "test-model",
    "context_window": 100000,
}


def tool_call(index: int) -> dict:
    return {
        "id": f"call-{index}",
        "type": "function",
        "function": {"name": "get_cwd", "arguments": "{}"},
    }


class LoopTests(unittest.TestCase):
    def test_max_steps_stops_and_leaves_system_note(self):
        calls = {"n": 0}

        def fake_stream(llm, messages, tools, on_text=None):
            calls["n"] += 1
            return "", [tool_call(calls["n"])], None

        events = []
        with tempfile.TemporaryDirectory() as raw, mock.patch.object(
            agent_module, "stream_chat", side_effect=fake_stream
        ):
            workspace = Path(raw)
            session = AgentSession(
                LLM, events.append, workspace=workspace, max_steps=3
            )
            session.run_turn("go")

        self.assertEqual(calls["n"], 3)
        self.assertEqual(sum(1 for m in session.messages if m["role"] == "tool"), 3)
        self.assertIn("[系统提示]", session.messages[-1]["content"])
        self.assertIn("最大步数", session.messages[-1]["content"])
        limits = [e for e in events if e["type"] == "limit"]
        self.assertEqual(len(limits), 1)
        self.assertEqual(limits[0]["steps"], 3)

    def test_timeout_stops_before_unexecuted_tool(self):
        def slow_stream(llm, messages, tools, on_text=None):
            time.sleep(0.06)
            return "", [tool_call(1)], None

        events = []
        with tempfile.TemporaryDirectory() as raw, mock.patch.object(
            agent_module, "stream_chat", side_effect=slow_stream
        ):
            workspace = Path(raw)
            session = AgentSession(
                LLM, events.append, workspace=workspace, max_steps=10, turn_timeout=0.05
            )
            session.run_turn("go")

        limits = [e for e in events if e["type"] == "limit"]
        self.assertEqual(len(limits), 1)
        self.assertIn("超时", limits[0]["reason"])
        self.assertTrue(
            any(
                m["role"] == "tool" and m["content"].startswith("未执行")
                for m in session.messages
            )
        )

    def test_error_is_emitted_and_not_raised(self):
        events = []
        with tempfile.TemporaryDirectory() as raw, mock.patch.object(
            agent_module, "stream_chat", side_effect=RuntimeError("network down")
        ):
            session = AgentSession(
                LLM, events.append, workspace=Path(raw), max_steps=2
            )
            session.run_turn("go")

        self.assertTrue(any(e["type"] == "error" for e in events))
        self.assertIn("network down", [e for e in events if e["type"] == "error"][0]["message"])

    def test_turn_saves_session_file(self):
        with tempfile.TemporaryDirectory() as raw, mock.patch.object(
            agent_module, "stream_chat", return_value=("done", [], None)
        ):
            workspace = Path(raw)
            session = AgentSession(LLM, workspace=workspace)
            session.run_turn("hello")
            files = list((workspace / ".agents" / "sessions").glob("*.jsonl"))

        self.assertEqual(len(files), 1)
        self.assertEqual(session.messages[-1]["content"], "done")


if __name__ == "__main__":
    unittest.main()
