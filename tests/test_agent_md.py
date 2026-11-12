"""AGENT.md 读取、截断、缺失兼容与会话恢复不重复注入。"""

from __future__ import annotations

import shutil
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "LLM" / "agent" / "two"))

from xAgent.agent import AgentSession  # noqa: E402
from xAgent.agent_md import TRUNCATED_SUFFIX, load_agent_rules  # noqa: E402

LLM = {
    "base_url": "http://127.0.0.1:1",
    "api_key": "test-key",
    "model": "test-model",
    "context_window": 100000,
}


class AgentFileTests(unittest.TestCase):
    def test_missing_file_is_silent(self):
        with tempfile.TemporaryDirectory() as raw:
            rules, meta = load_agent_rules(Path(raw))
        self.assertEqual(rules, "")
        self.assertIsNone(meta)

    def test_agents_md_fallback(self):
        with tempfile.TemporaryDirectory() as raw:
            workspace = Path(raw)
            (workspace / "AGENTS.md").write_text("FALLBACK-RULE", encoding="utf-8")
            rules, meta = load_agent_rules(workspace)
        self.assertIn("FALLBACK-RULE", rules)
        self.assertEqual(meta["name"], "AGENTS.md")

    def test_truncation_appends_marker(self):
        with tempfile.TemporaryDirectory() as raw:
            workspace = Path(raw)
            (workspace / "AGENT.md").write_text("A" * 50, encoding="utf-8")
            options = {
                "agent_file": "AGENT.md",
                "agent_file_enabled": True,
                "agent_file_max_chars": 10,
            }
            rules, meta = load_agent_rules(workspace, options)
        self.assertTrue(rules.startswith("A" * 10))
        self.assertTrue(rules.endswith(TRUNCATED_SUFFIX))
        self.assertTrue(meta["truncated"])
        self.assertEqual(meta["original_chars"], 50)

    def test_disabled_switch(self):
        with tempfile.TemporaryDirectory() as raw:
            workspace = Path(raw)
            (workspace / "AGENT.md").write_text("RULE", encoding="utf-8")
            rules, meta = load_agent_rules(
                workspace,
                {
                    "agent_file": "AGENT.md",
                    "agent_file_enabled": False,
                    "agent_file_max_chars": 8000,
                },
            )
        self.assertEqual(rules, "")
        self.assertIsNone(meta)


class InjectionTests(unittest.TestCase):
    def test_injected_once_and_restored_once(self):
        with tempfile.TemporaryDirectory() as raw:
            workspace = Path(raw)
            (workspace / "AGENT.md").write_text("RULE-ONE", encoding="utf-8")
            session = AgentSession(LLM, workspace=workspace)
            system = [m for m in session.messages if m["role"] == "system"]
            self.assertEqual(len(system), 1)
            self.assertEqual(system[0]["content"].count("RULE-ONE"), 1)

            session.messages.append({"role": "user", "content": "hello"})
            session.messages.append({"role": "assistant", "content": "hi"})
            session.save_session(silent=True)

            restored = AgentSession(LLM, workspace=workspace)
            restored.resume(session.session_id)
            system = [m for m in restored.messages if m["role"] == "system"]
            self.assertEqual(len(system), 1)
            self.assertEqual(system[0]["content"].count("RULE-ONE"), 1)
            self.assertEqual(restored.session_id, session.session_id)
            self.assertEqual(restored.messages[-1]["content"], "hi")

    def test_resume_uses_saved_workspace(self):
        with tempfile.TemporaryDirectory() as first, tempfile.TemporaryDirectory() as second:
            first_path = Path(first)
            (first_path / "AGENT.md").write_text("SAVED-WORKSPACE-RULE", encoding="utf-8")
            session = AgentSession(LLM, workspace=first_path)
            session.save_session(silent=True)

            # 模拟从另一个工作目录启动后仍能按 ID 找到会话文件。
            other = Path(second)
            target_dir = other / ".agents" / "sessions"
            target_dir.mkdir(parents=True)
            source = first_path / ".agents" / "sessions" / f"{session.session_id}.jsonl"
            shutil.copy(source, target_dir / source.name)

            restored = AgentSession(LLM, workspace=other)
            restored.resume(session.session_id)
            self.assertEqual(restored.workspace, first_path.resolve())
            self.assertIn("SAVED-WORKSPACE-RULE", restored.messages[0]["content"])

            # 恢复后继续保存应写回会话所属工作目录，而不是启动目录。
            restored.messages.append({"role": "user", "content": "AFTER-RESUME"})
            restored.save_session(silent=True)
            saved = first_path / ".agents" / "sessions" / f"{session.session_id}.jsonl"
            copied = target_dir / source.name
            self.assertIn("AFTER-RESUME", saved.read_text(encoding="utf-8"))
            self.assertNotIn("AFTER-RESUME", copied.read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
