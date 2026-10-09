#!/usr/bin/env python3
import py_compile
import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]


class SmokeTests(unittest.TestCase):
    def test_python_version(self):
        self.assertGreaterEqual(sys.version_info, (3, 9))

    def test_repo_files_exist(self):
        for name in (
            "LICENSE",
            "NOTICE",
            "README.md",
            "tools/check.py",
            "tools/package.py",
        ):
            self.assertTrue((ROOT / name).is_file(), name)

    def test_scripts_compile(self):
        scripts = ROOT / "collabmd" / "scripts"
        if not scripts.is_dir():
            self.skipTest("scripts not present yet")
        found = False
        for path in sorted(scripts.glob("*.py")):
            found = True
            with self.subTest(path=path.name):
                py_compile.compile(str(path), doraise=True)
        self.assertTrue(found, "no scripts found")

    def test_yaml_files_parse(self):
        try:
            import yaml
        except ImportError:
            self.skipTest("pyyaml not available")
        for pattern in ("*.yml", "*.yaml"):
            for path in sorted(ROOT.rglob(pattern)):
                if ".git" in path.parts:
                    continue
                with self.subTest(path=str(path.relative_to(ROOT))):
                    data = yaml.safe_load(path.read_text(encoding="utf-8"))
                    self.assertIsInstance(data, dict)


if __name__ == "__main__":
    unittest.main(verbosity=2)
