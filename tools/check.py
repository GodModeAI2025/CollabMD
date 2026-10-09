#!/usr/bin/env python3
"""Run the local regression suites, stopping on any failure."""
import os
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]


def main():
    tests_root = ROOT / "qa" / "tests"
    suites = sorted(tests_root.glob("*/test_*.py"))
    if not suites:
        print("No regression suites found under qa/tests/", file=sys.stderr)
        return 1
    for suite in suites:
        print(f"Running {suite.relative_to(ROOT)}", flush=True)
        result = subprocess.run(
            [sys.executable, str(suite)],
            cwd=ROOT,
            env={**os.environ, "PYTHONDONTWRITEBYTECODE": "1"},
        )
        if result.returncode:
            sys.exit(result.returncode)
    print("All regression suites passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
