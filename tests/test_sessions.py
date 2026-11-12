"""会话 JSONL 持久化、列表与非法 ID 防护。"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "LLM" / "agent" / "two"))

from xAgent.sessions import SessionError, SessionStore  # noqa: E402


class SessionStoreTests(unittest.TestCase):
    def test_save_load_list(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            store = SessionStore(root)
            sid = store.new_id()
            messages = [
                {"role": "system", "content": "S"},
                {"role": "user", "content": "hello"},
            ]
            path = store.save(
                sid,
                messages=messages,
                created_at="2026-01-01T00:00:00+08:00",
                cwd=str(root),
                model="m",
                last_tokens=42,
                last_usage={"total_tokens": 42},
            )
            self.assertTrue(path.is_file())
            self.assertEqual(path.parent, root / ".agents" / "sessions")
            data = store.load(sid)
            self.assertEqual(data["messages"], messages)
            self.assertEqual(data["meta"]["cwd"], str(root))
            self.assertEqual(data["meta"]["model"], "m")
            self.assertEqual(data["meta"]["lastTokens"], 42)
            self.assertEqual(data["meta"]["messageCount"], 2)
            listed = store.list()
            self.assertEqual(len(listed), 1)
            self.assertEqual(listed[0]["sessionId"], sid)
            self.assertEqual(list(path.parent.glob("*.tmp")), [])

    def test_invalid_session_id_rejected(self):
        with tempfile.TemporaryDirectory() as raw:
            store = SessionStore(Path(raw))
            for bad in ("../escape", "a/b", "", "..", "x" * 200):
                with self.assertRaises(SessionError):
                    store.path(bad)

    def test_missing_session_raises(self):
        with tempfile.TemporaryDirectory() as raw:
            store = SessionStore(Path(raw))
            with self.assertRaises(SessionError):
                store.load("20260101-000000-abcdef")


if __name__ == "__main__":
    unittest.main()
