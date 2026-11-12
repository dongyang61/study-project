"""技能创建、拒绝覆盖、附件越界、加载上限与渐进注入测试。"""

from __future__ import annotations

import importlib.util
import io
import sys
import tempfile
import unittest
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "LLM" / "agent" / "two"))

from xAgent.skills import SKILLS_DIR, SKILL_FILE, SkillRegistry, _parse_frontmatter  # noqa: E402
from xAgent.tools.create_skill import create_skill  # noqa: E402


def load_validator():
    path = ROOT / "LLM" / "agent" / "two" / "xAgent" / "scripts" / "validate_skills.py"
    spec = importlib.util.spec_from_file_location("validate_skills", path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


class CreateSkillTests(unittest.TestCase):
    def test_create_with_attachment_and_discovery(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            result = create_skill(
                "demo-skill",
                "演示技能",
                "FULL-CONTENT-MARKER",
                [{"path": "notes/a.md", "content": "附件"}],
                project_root=root,
            )
            self.assertIn("已创建 Skill", result)
            skill_dir = root / SKILLS_DIR / "demo-skill"
            self.assertTrue((skill_dir / SKILL_FILE).is_file())
            self.assertTrue((skill_dir / "notes" / "a.md").is_file())
            meta = _parse_frontmatter(skill_dir / SKILL_FILE)
            self.assertEqual(meta["name"], "demo-skill")
            self.assertEqual(meta["description"], "演示技能")

            registry = SkillRegistry(root)
            self.assertIn("demo-skill", registry.skills)
            self.assertIn("FULL-CONTENT-MARKER", registry.load("demo-skill"))
            prompt = registry.build_system_prompt("base")
            self.assertIn("demo-skill", prompt)
            self.assertIn("演示技能", prompt)
            self.assertNotIn("FULL-CONTENT-MARKER", prompt)

    def test_duplicate_is_refused_with_available_list(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            create_skill("demo-skill", "第一次", "body", project_root=root)
            result = create_skill("demo-skill", "第二次", "changed", project_root=root)
            self.assertIn("拒绝覆盖", result)
            self.assertIn("demo-skill", result)
            text = (root / SKILLS_DIR / "demo-skill" / SKILL_FILE).read_text(
                encoding="utf-8"
            )
            self.assertIn("第一次", text)
            self.assertNotIn("第二次", text)

    def test_invalid_name(self):
        with tempfile.TemporaryDirectory() as raw:
            result = create_skill("Bad Name", "d", "c", project_root=Path(raw))
        self.assertIn("执行失败", result)
        self.assertIn("name", result)

    def test_attachment_traversal_rejected(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            result = create_skill(
                "demo-skill",
                "d",
                "c",
                [{"path": "../evil.txt", "content": "x"}],
                project_root=root,
            )
            self.assertIn("不能包含 '..'", result)
            self.assertFalse((root / SKILLS_DIR / "demo-skill").exists())

    def test_attachment_absolute_rejected(self):
        with tempfile.TemporaryDirectory() as raw:
            result = create_skill(
                "demo-skill",
                "d",
                "c",
                [{"path": "C:/evil.txt", "content": "x"}],
                project_root=Path(raw),
            )
        self.assertIn("绝对路径", result)

    def test_load_skill_truncates_and_blocks_escape(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "AGENT.md").write_text("outside", encoding="utf-8")
            create_skill("big-skill", "d", "X" * 200, project_root=root)
            registry = SkillRegistry(root, max_chars=50)
            content = registry.load("big-skill")
            self.assertIn("（已截断", content)
            self.assertLess(len(content), 200)
            escaped = registry.load("big-skill", "../AGENT.md")
            self.assertIn("拒绝读取", escaped)
            absolute = registry.load("big-skill", str(root / "AGENT.md"))
            self.assertIn("相对路径", absolute)


class ValidateSkillsTests(unittest.TestCase):
    def test_valid_skill_passes(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            create_skill("good-skill", "ok", "body", project_root=root)
            validator = load_validator()
            errors, _warnings = validator.validate(root)
            self.assertEqual(errors, [])
            self.assertEqual(validator.main(["--root", str(root)]), 0)

    def test_name_mismatch_and_missing_frontmatter_fail(self):
        with tempfile.TemporaryDirectory() as raw:
            root = Path(raw)
            skills = root / SKILLS_DIR
            mismatch = skills / "actual-name"
            mismatch.mkdir(parents=True)
            (mismatch / SKILL_FILE).write_text(
                "---\nname: other-name\ndescription: d\n---\nbody",
                encoding="utf-8",
            )
            broken = skills / "broken"
            broken.mkdir()
            (broken / SKILL_FILE).write_text("no frontmatter", encoding="utf-8")
            validator = load_validator()
            errors, _warnings = validator.validate(root)
            joined = "\n".join(errors)
            self.assertIn("与目录名不一致", joined)
            self.assertIn("缺少 name", joined)
            with redirect_stdout(io.StringIO()):
                self.assertEqual(validator.main(["--root", str(root)]), 1)


if __name__ == "__main__":
    unittest.main()
