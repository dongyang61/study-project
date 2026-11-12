"""文件工具工作目录边界与破坏性操作 confirm 测试。"""

from __future__ import annotations

import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "LLM" / "agent" / "two"))

from xAgent.tools import files  # noqa: E402
from xAgent.tools.files import ToolError  # noqa: E402


class FileBoundaryTests(unittest.TestCase):
    def setUp(self):
        self._original = files.get_workspace()
        self._tmp = tempfile.TemporaryDirectory()
        self.workspace = Path(self._tmp.name)
        files.set_workspace(self.workspace)

    def tearDown(self):
        files.set_workspace(self._original)
        self._tmp.cleanup()

    def test_create_read_inside_workspace(self):
        result = files.create_file(str(self.workspace), "a.txt", "hello")
        self.assertIn("已创建文件", result)
        self.assertEqual(files.read_text_file("a.txt"), "hello")

    def test_write_outside_workspace_is_rejected(self):
        outside_dir = self.workspace.parent
        with self.assertRaises(ToolError) as ctx:
            files.create_file(str(outside_dir), "outside-guard-test.txt", "x")
        self.assertIn("不在工作目录", str(ctx.exception))

    def test_delete_file_requires_confirm(self):
        target = self.workspace / "a.txt"
        target.write_text("x", encoding="utf-8")
        blocked = files.delete_file("a.txt")
        self.assertIn("需要 confirm=true", blocked)
        self.assertTrue(target.exists())
        done = files.delete_file("a.txt", confirm=True)
        self.assertIn("已删除文件", done)
        self.assertFalse(target.exists())

    def test_delete_dir_requires_confirm(self):
        folder = self.workspace / "dir"
        folder.mkdir()
        (folder / "x.txt").write_text("x", encoding="utf-8")
        blocked = files.delete_dir("dir")
        self.assertIn("需要 confirm=true", blocked)
        self.assertIn("目录", blocked)
        self.assertTrue(folder.exists())
        done = files.delete_dir("dir", confirm=True)
        self.assertIn("已删除目录", done)
        self.assertFalse(folder.exists())

    def test_overwrite_requires_confirm(self):
        target = self.workspace / "a.txt"
        target.write_text("old", encoding="utf-8")
        blocked = files.edit_text_file("a.txt", "new")
        self.assertIn("需要 confirm=true", blocked)
        self.assertEqual(target.read_text(encoding="utf-8"), "old")
        files.edit_text_file("a.txt", "new", confirm=True)
        self.assertEqual(target.read_text(encoding="utf-8"), "new")

    def test_rename_requires_confirm(self):
        target = self.workspace / "a.txt"
        target.write_text("x", encoding="utf-8")
        blocked = files.rename_path("a.txt", "b.txt")
        self.assertIn("需要 confirm=true", blocked)
        self.assertTrue(target.exists())
        files.rename_path("a.txt", "b.txt", confirm=True)
        self.assertTrue((self.workspace / "b.txt").exists())

    def test_allow_outside_switch(self):
        outside = self.workspace.parent / "outside-allowed-test.txt"
        if outside.exists():
            outside.unlink()
        try:
            with mock.patch.object(
                files, "agent_settings", return_value={"workspace_allow_outside": True}
            ):
                files.create_file(str(self.workspace.parent), outside.name, "x")
            self.assertTrue(outside.exists())
        finally:
            outside.unlink(missing_ok=True)

    def test_confirm_is_required_in_schema(self):
        by_name = {tool["function"]["name"]: tool for tool in files.FILE_TOOLS}
        for name in ("delete_dir", "delete_file", "rename_path", "edit_text_file"):
            schema = by_name[name]["function"]["parameters"]
            self.assertIn("confirm", schema["required"])
            self.assertEqual(schema["properties"]["confirm"]["type"], "boolean")


if __name__ == "__main__":
    unittest.main()
