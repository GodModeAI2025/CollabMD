#!/usr/bin/env python3
"""Passphrase hashes, sessions and the write gate."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support as S


class AuthTests(unittest.TestCase):
    def setUp(self):
        self.wiki, self.rt = S.fresh("auth")
        self.token = self.rt / "tok.json"
        self.sess = S.session(self.rt, self.wiki, "alice")

    def test_verify_correct_and_wrong_passphrase(self):
        code, out = S.run("collab_auth.py", "verify", "--target", self.wiki, "--handle", "alice",
                          "--passphrase-file", self.rt / "pp.txt")
        self.assertEqual(code, 0)
        self.assertTrue(out["ok"])
        wrong = self.rt / "wrong.txt"
        wrong.write_text("falsch-falsch-falsch\n", encoding="utf-8")
        code, out = S.run("collab_auth.py", "verify", "--target", self.wiki, "--handle", "alice",
                          "--passphrase-file", wrong)
        self.assertEqual(code, 1)
        self.assertEqual(out["error"], "auth_failed")

    def test_create_user_needs_session(self):
        code, out = S.run("collab_auth.py", "create-user", "--target", self.wiki, "--handle", "bob",
                          "--role", "contributor", "--passphrase-file", self.rt / "pp.txt",
                          "--actor", "alice", "--token-file", self.token,
                          "--content-dir", self.rt / "c", "--output", self.rt / "plan-bob.json")
        self.assertEqual(code, 0)
        self.assertTrue(out["ok"])
        plan = json.loads((self.rt / "plan-bob.json").read_text(encoding="utf-8"))
        code, out = S.run("collab_auth.py", "apply", "--target", self.wiki, "--handle", "bob",
                          "--plan-file", self.rt / "plan-bob.json",
                          "--expect-plan-sha256", plan["plan_sha256"], "--token-file", self.token)
        self.assertEqual(code, 1)
        self.assertEqual(out["error"], "auth_required")

    def test_create_user_with_session_and_gate(self):
        code, out = S.run("collab_auth.py", "create-user", "--target", self.wiki, "--handle", "bob",
                          "--role", "contributor", "--passphrase-file", self.rt / "pp.txt",
                          "--actor", "alice", "--token-file", self.token,
                          "--content-dir", self.rt / "c", "--output", self.rt / "plan-bob.json")
        self.assertEqual(code, 0)
        plan = json.loads((self.rt / "plan-bob.json").read_text(encoding="utf-8"))
        code, out = S.run("collab_auth.py", "apply", "--target", self.wiki, "--handle", "bob",
                          "--plan-file", self.rt / "plan-bob.json",
                          "--expect-plan-sha256", plan["plan_sha256"], "--token-file", self.token,
                          "--session-file", self.sess)
        self.assertEqual(code, 0)
        members = json.loads((self.wiki / "schema/members.json").read_text(encoding="utf-8"))
        self.assertIn("bob", members["members"])
        self.assertTrue(members["members"]["bob"]["auth"]["hash"])
        self.assertNotIn("test-passwort-123", (self.wiki / "schema/members.json").read_text(encoding="utf-8"))

    def test_reader_cannot_create_user(self):
        (self.rt / "pp-carl.txt").write_text("carl-passwort-123\n", encoding="utf-8")
        code, out = S.run("collab_auth.py", "create-user", "--target", self.wiki, "--handle", "carl",
                          "--role", "reader", "--passphrase-file", self.rt / "pp-carl.txt",
                          "--actor", "alice", "--token-file", self.token,
                          "--content-dir", self.rt / "c", "--output", self.rt / "plan-carl.json")
        self.assertEqual(code, 0, out)
        plan = json.loads((self.rt / "plan-carl.json").read_text(encoding="utf-8"))
        code, out = S.run("collab_auth.py", "apply", "--target", self.wiki, "--handle", "carl",
                          "--plan-file", self.rt / "plan-carl.json",
                          "--expect-plan-sha256", plan["plan_sha256"], "--token-file", self.token,
                          "--session-file", self.sess)
        self.assertEqual(code, 0, out)
        code, out = S.run("collab_auth.py", "create-user", "--target", self.wiki, "--handle", "dave",
                          "--role", "reader", "--passphrase-file", self.rt / "pp.txt",
                          "--actor", "carl", "--token-file", self.token,
                          "--content-dir", self.rt / "c", "--output", self.rt / "plan-dave.json")
        self.assertEqual(code, 1)
        self.assertEqual(out["error"], "permission_denied")

    def test_nonmember_cannot_create_user(self):
        code, out = S.run("collab_auth.py", "create-user", "--target", self.wiki, "--handle", "bob",
                          "--role", "reader", "--passphrase-file", self.rt / "pp.txt",
                          "--actor", "nobody", "--token-file", self.token,
                          "--content-dir", self.rt / "c", "--output", self.rt / "plan-nobody.json")
        self.assertEqual(code, 1)
        self.assertEqual(out["error"], "permission_denied")

    def test_session_wrong_handle_rejected_for_apply(self):
        bob_pp = self.rt / "pp-bob.txt"
        bob_pp.write_text("bob-passwort-456\n", encoding="utf-8")
        code, out = S.run("collab_auth.py", "create-user", "--target", self.wiki, "--handle", "bob",
                          "--role", "contributor", "--passphrase-file", bob_pp,
                          "--actor", "alice", "--token-file", self.token,
                          "--content-dir", self.rt / "c", "--output", self.rt / "plan-bob.json")
        self.assertEqual(code, 0, out)
        plan = json.loads((self.rt / "plan-bob.json").read_text(encoding="utf-8"))
        bob_sess = self.rt / "sess-bob.json"
        bob_sess.write_text(json.dumps({"handle": "bob", "created": "2099-01-01T00:00:00Z",
                                        "expires": "2099-01-01T00:10:00Z",
                                        "ttl_seconds": 600}, indent=2) + "\n", encoding="utf-8")
        code, out = S.run("collab_auth.py", "apply", "--target", self.wiki, "--handle", "bob",
                          "--plan-file", self.rt / "plan-bob.json",
                          "--expect-plan-sha256", plan["plan_sha256"], "--token-file", self.token,
                          "--session-file", bob_sess)
        self.assertEqual(code, 1)
        self.assertEqual(out["error"], "auth_session_mismatch")

    def test_expired_session_rejected(self):
        code, out = S.run("collab_auth.py", "create-user", "--target", self.wiki, "--handle", "bob",
                          "--role", "contributor", "--passphrase-file", self.rt / "pp.txt",
                          "--actor", "alice", "--token-file", self.token,
                          "--content-dir", self.rt / "c", "--output", self.rt / "plan-bob.json")
        self.assertEqual(code, 0, out)
        plan = json.loads((self.rt / "plan-bob.json").read_text(encoding="utf-8"))
        old_sess = self.rt / "sess-old.json"
        old_sess.write_text(json.dumps({"handle": "alice", "created": "2000-01-01T00:00:00Z",
                                        "expires": "2000-01-01T00:10:00Z",
                                        "ttl_seconds": 600}, indent=2) + "\n", encoding="utf-8")
        code, out = S.run("collab_auth.py", "apply", "--target", self.wiki, "--handle", "bob",
                          "--plan-file", self.rt / "plan-bob.json",
                          "--expect-plan-sha256", plan["plan_sha256"], "--token-file", self.token,
                          "--session-file", old_sess)
        self.assertEqual(code, 1)
        self.assertEqual(out["error"], "auth_session_expired")

    def test_disable_user_blocks_session(self):
        code, out = S.run("collab_auth.py", "disable-user", "--target", self.wiki, "--handle", "alice",
                          "--actor", "alice", "--token-file", self.token,
                          "--content-dir", self.rt / "c", "--output", self.rt / "plan-dis.json")
        plan = json.loads((self.rt / "plan-dis.json").read_text(encoding="utf-8"))
        code, out = S.run("collab_auth.py", "apply", "--target", self.wiki, "--handle", "alice",
                          "--plan-file", self.rt / "plan-dis.json",
                          "--expect-plan-sha256", plan["plan_sha256"], "--token-file", self.token,
                          "--session-file", self.sess)
        self.assertEqual(code, 0)
        code, out = S.run("collab_auth.py", "session", "--target", self.wiki, "--handle", "alice",
                          "--passphrase-file", self.rt / "pp.txt", "--session-file", self.rt / "sess-dis.json")
        self.assertEqual(code, 1)
        self.assertEqual(out["error"], "permission_denied")


if __name__ == "__main__":
    unittest.main(verbosity=2)
