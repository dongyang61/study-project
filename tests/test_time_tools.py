"""时间与闰年工具测试（含 1900/2000 整百年规则）。"""

from __future__ import annotations

import sys
import unittest
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "LLM" / "agent" / "two"))

from xAgent.tools.time_tools import (  # noqa: E402
    get_current_time,
    is_leap,
    is_leap_year,
)


class LeapYearTests(unittest.TestCase):
    def test_century_rules(self):
        self.assertTrue(is_leap(2000))
        self.assertFalse(is_leap(1900))
        self.assertFalse(is_leap(2100))
        self.assertTrue(is_leap(2004))
        self.assertFalse(is_leap(2023))

    def test_tool_messages(self):
        self.assertEqual(is_leap_year(2000), "2000 年是闰年。")
        self.assertEqual(is_leap_year(1900), "1900 年不是闰年。")
        self.assertIn("必须是整数", is_leap_year("not-a-year"))


class CurrentTimeTests(unittest.TestCase):
    def test_local_time_has_iso_and_timestamp(self):
        text = get_current_time()
        self.assertIn("当前时间：", text)
        self.assertIn("时间戳：", text)
        iso = text.splitlines()[0].split("当前时间：", 1)[1]
        datetime.fromisoformat(iso)

    def test_named_timezone(self):
        text = get_current_time("UTC")
        self.assertIn("当前时间：", text)
        self.assertIn("+00:00", text)

    def test_invalid_timezone(self):
        text = get_current_time("Mars/Olympus")
        self.assertIn("未知时区", text)

    def test_invalid_format(self):
        text = get_current_time(format="xml")
        self.assertIn("format", text)


if __name__ == "__main__":
    unittest.main()
