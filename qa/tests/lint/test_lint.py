#!/usr/bin/env python3
"""Lint: strict validation incl. cursor files; exit codes."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support as S


class LintTests(unittest.TestCase):
    def setUp(self):
        self.wiki, self.rt = S.fresh("lint")

    def lint(self):
        code, out = S.run("collab_lint.py", "lint", "--target", self.wiki)
        return code, out

    def test_clean_workspace_lints_ok(self):
        code, out = self.lint()
        self.assertEqual(code, 0)
        self.assertTrue(out["ok"])
        self.assertEqual(out["errors"], [])

    def test_cursor_unknown_channel_refused(self):
        cursor = self.wiki / "meta" / "cursors" / "alice.json"
        doc = {"handle": "alice", "channels": {"fremd": {"cursor": "2026-10-10T12:00:00Z", "updated": "2026-10-10T12:00:00Z"}}}
        cursor.write_text(json.dumps(doc), encoding="utf-8")
        code, out = self.lint()
        self.assertEqual(code, 1)
        self.assertFalse(out["ok"])
        self.assertTrue(any("fremd" in e for e in out["errors"]))

    def test_cursor_bad_timestamp_refused(self):
        cursor = self.wiki / "meta" / "cursors" / "alice.json"
        doc = {"handle": "alice", "channels": {"general": {"cursor": "kein-zeitstempel", "updated": "2026-10-10T12:00:00Z"}}}
        cursor.write_text(json.dumps(doc), encoding="utf-8")
        code, out = self.lint()
        self.assertEqual(code, 1)
        self.assertTrue(any("cursor ungültig" in e for e in out["errors"]))

    def test_cursor_handle_mismatch_refused(self):
        cursor = self.wiki / "meta" / "cursors" / "alice.json"
        doc = {"handle": "bob", "channels": {}}
        cursor.write_text(json.dumps(doc), encoding="utf-8")
        code, out = self.lint()
        self.assertEqual(code, 1)
        self.assertTrue(any("handle-Feld" in e for e in out["errors"]))

    def test_cursor_unknown_member_refused(self):
        cursor = self.wiki / "meta" / "cursors" / "ghost.json"
        doc = {"handle": "ghost", "channels": {}}
        cursor.write_text(json.dumps(doc), encoding="utf-8")
        code, out = self.lint()
        self.assertEqual(code, 1)
        self.assertTrue(any("unbekanntes Mitglied" in e for e in out["errors"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
