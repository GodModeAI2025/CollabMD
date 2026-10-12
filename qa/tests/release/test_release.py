#!/usr/bin/env python3
"""Releases: bumps, idempotency, lint gate, tamper detection."""
import json
import sys
import uuid
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support as S


def release(wiki, rt, token, bump, actor="alice", session=None):
    op = uuid.uuid4().hex
    args = ["collab_release.py", "release", "--target", wiki, "--bump", bump,
            "--operation-id", op, "--summary", "Test", "--actor", actor, "--token-file", token]
    if session is not None:
        args += ["--session-file", session]
    code, out = S.run(*args)
    return code, out, op


class ReleaseTests(unittest.TestCase):
    def setUp(self):
        self.wiki, self.rt = S.fresh("release")
        self.token = self.rt / "tok.json"
        self.sess = S.session(self.rt, self.wiki, "alice")

    def test_initial_release_and_bumps(self):
        code, out, _ = release(self.wiki, self.rt, self.token, "initial", session=self.sess)
        self.assertEqual(code, 0, out)
        self.assertEqual(out["version"], "0.1.0")
        for bump, expected in (("patch", "0.1.1"), ("minor", "0.2.0"), ("major", "1.0.0")):
            code, out, _ = release(self.wiki, self.rt, self.token, bump, session=self.sess)
            self.assertEqual(code, 0, out)
            self.assertEqual(out["version"], expected)

    def test_operation_id_idempotent(self):
        op = uuid.uuid4().hex
        code, out = S.run("collab_release.py", "release", "--target", self.wiki, "--bump", "initial",
                             "--operation-id", op, "--summary", "Test", "--actor", "alice",
                             "--token-file", self.token, "--session-file", self.sess)
        self.assertEqual(code, 0)
        code, out = S.run("collab_release.py", "release", "--target", self.wiki, "--bump", "initial",
                             "--operation-id", op, "--summary", "Test", "--actor", "alice",
                             "--token-file", self.token, "--session-file", self.sess)
        self.assertEqual(code, 0)
        self.assertTrue(out["already_published"])
        self.assertEqual(out["version"], "0.1.0")

    def test_verify_detects_tamper(self):
        code, out, _ = release(self.wiki, self.rt, self.token, "initial", session=self.sess)
        self.assertEqual(code, 0)
        code, out = S.run("collab_release.py", "verify", "--target", self.wiki)
        self.assertEqual(code, 0)
        self.assertTrue(out["ok"])
        soul = self.wiki / "schema" / "SOUL.md"
        soul.write_text(soul.read_text(encoding="utf-8") + "\nNachträglich\n", encoding="utf-8")
        code, out = S.run("collab_release.py", "verify", "--target", self.wiki)
        self.assertEqual(code, 0)
        self.assertFalse(out["ok"])
        self.assertIn("schema/SOUL.md", out["mismatched"])

    def test_release_blocked_by_lint_error(self):
        channels = self.wiki / "schema" / "channels.json"
        doc = json.loads(channels.read_text(encoding="utf-8"))
        doc["channels"]["general"]["type"] = "falsch"
        channels.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
        code, out, _ = release(self.wiki, self.rt, self.token, "initial", session=self.sess)
        self.assertEqual(code, 1)
        self.assertEqual(out["error"], "lint_failed")

    def test_verify_without_manifest_refused(self):
        code, out = S.run("collab_release.py", "verify", "--target", self.wiki)
        self.assertEqual(code, 1)
        self.assertEqual(out["error"], "no_release")

    def test_release_requires_session(self):
        code, out, _ = release(self.wiki, self.rt, self.token, "initial")
        self.assertEqual(code, 1)
        self.assertEqual(out["error"], "auth_required")

    def add_member(self, handle, role):
        code, out = S.run("collab_auth.py", "create-user", "--target", self.wiki, "--handle", handle,
                          "--role", role, "--passphrase-file", self.rt / "pp.txt",
                          "--actor", "alice", "--token-file", self.token,
                          "--content-dir", self.rt / "c", "--output", self.rt / f"plan-{handle}.json")
        self.assertEqual(code, 0, out)
        plan = json.loads((self.rt / f"plan-{handle}.json").read_text(encoding="utf-8"))
        code, out = S.run("collab_auth.py", "apply", "--target", self.wiki, "--handle", handle,
                          "--plan-file", self.rt / f"plan-{handle}.json",
                          "--expect-plan-sha256", plan["plan_sha256"], "--token-file", self.token,
                          "--session-file", self.sess)
        self.assertEqual(code, 0, out)

    def test_contributor_can_publish_release(self):
        self.add_member("bob", "contributor")
        code, out, _ = release(self.wiki, self.rt, self.token, "initial", actor="bob",
                               session=S.session(self.rt, self.wiki, "bob"))
        self.assertEqual(code, 0, out)
        self.assertEqual(out["version"], "0.1.0")

    def test_reader_cannot_publish_release(self):
        self.add_member("carol", "reader")
        code, out, _ = release(self.wiki, self.rt, self.token, "initial", actor="carol",
                               session=S.session(self.rt, self.wiki, "carol"))
        self.assertEqual(code, 1)
        self.assertEqual(out["error"], "permission_denied")

    def test_release_requires_lock(self):
        (self.rt / "tok-none.json").unlink(missing_ok=True)
        code, out, _ = release(self.wiki, self.rt, self.rt / "tok-none.json", "initial")
        self.assertEqual(code, 1)
        self.assertEqual(out["error"], "missing_token")


if __name__ == "__main__":
    unittest.main(verbosity=2)
