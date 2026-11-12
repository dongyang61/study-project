"""把 pethospital-mcp/test_server.py 纳入根目录 unittest discover。"""

from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
TEST_PATH = ROOT / "LLM" / "agent" / "office" / "pethospital-mcp" / "test_server.py"
SPEC = importlib.util.spec_from_file_location("pethospital_test_server", TEST_PATH)
SUBMODULE = importlib.util.module_from_spec(SPEC)
assert SPEC.loader is not None
SPEC.loader.exec_module(SUBMODULE)


def load_tests(loader, standard_tests, pattern):
    return unittest.TestSuite(
        [standard_tests, loader.loadTestsFromModule(SUBMODULE)]
    )


if __name__ == "__main__":
    unittest.main()
