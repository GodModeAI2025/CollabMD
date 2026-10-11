#!/usr/bin/env python3
"""Workspace initialization, lock, plan/apply integrity."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support as S


class InitTests(unittest.TestCase):
    def setUp(self):
        self.wiki, self.rt = S.fresh("init")

    def test_structure_created(self):
        for rel in ("schema/collab.json", "schema/SOUL.md", "schema/members.json",
                    "schema/channels.json", "meta/changes.md", "posts/.gitkeep",
                    "posts/_files/.gitkeep", "meta/events/.gitkeep", "meta/cursors/.gitkeep",
                    "meta/receipts/.gitkeep", "graph/.gitkeep"):
            self.assertTrue((self.wiki / rel).exists(), rel)
        profile = json.loads((self.wiki / "schema/collab.json").read_text(encoding="utf-8"))
        self.assertEqual(profile["format"], "collabmd/1")
        self.assertTrue(profile["auth"]["write_gate"])
        self.assertEqual(profile["auth"]["kdf"], "pbkdf2-sha256")

    def test_no_plaintext_passphrase_anywhere(self):
        for path in self.wiki.rglob("*"):
            if path.is_file() and path.suffix in (".md", ".json"):
                self.assertNotIn("test-passwort-123", path.read_text(encoding="utf-8", errors="ignore"))

    def test_owner_has_hashed_auth(self):
        members = json.loads((self.wiki / "schema/members.json").read_text(encoding="utf-8"))
        auth = members["members"]["alice"]["auth"]
        self.assertEqual(len(auth["salt"]), 64)
        self.assertEqual(len(auth["hash"]), 64)

    def test_second_acquire_refused(self):
        code, out = S.run("wiki_lock.py", "acquire", "--target", self.wiki, "--owner", "other",
                          "--operation", "x", "--token-file", self.rt / "tok2.json")
        self.assertEqual(code, 0)
        self.assertFalse(out["acquired"])
        self.assertEqual(out["state"], "held")

    def test_release_with_wrong_token_refused(self):
        (self.rt / "tok-wrong.json").write_text("f" * 64 + "\n", encoding="utf-8")
        code, out = S.run("wiki_lock.py", "release", "--target", self.wiki, "--token-file", self.rt / "tok-wrong.json")
        self.assertEqual(code, 1)
        self.assertEqual(out["error"], "token_mismatch")
        self.assertTrue((self.wiki / ".collabmd.lock" / "claim.json").is_file())

    def test_stale_plan_hash_refused(self):
        code, out = S.run("collab_init.py", "apply", "--target", self.wiki, "--plan-file", self.rt / "plan.json",
                          "--expect-plan-sha256", "0" * 64, "--token-file", self.rt / "tok.json")
        self.assertEqual(code, 1)
        self.assertEqual(out["error"], "stale_plan")

    def test_init_into_nonempty_target_refused(self):
        (self.rt / "junk.md").write_text("alt\n", encoding="utf-8")
        (self.wiki / "fremd.md").write_text("fremd\n", encoding="utf-8")
        code, out = S.run("collab_init.py", "plan", "--target", self.wiki, "--name", "X",
                          "--purpose", "Y", "--language", "de", "--soul-file", self.rt / "soul.md",
                          "--owner-handle", "carl", "--content-dir", self.rt / "c2",
                          "--output", self.rt / "plan2.json")
        self.assertEqual(code, 1)
        self.assertEqual(out["error"], "target_not_empty")

    def test_init_rejects_secrets_in_soul(self):
        soul = self.rt / "soul-secret.md"
        soul.write_text("Token: ghp_ABCDEFGHIJKLMNOPQRSTUV\n", encoding="utf-8")
        code, out = S.run("collab_init.py", "plan", "--target", self.rt / "soulwiki", "--name", "X",
                          "--purpose", "Y", "--language", "de", "--soul-file", soul,
                          "--owner-handle", "carl", "--content-dir", self.rt / "c3",
                          "--output", self.rt / "plan3.json")
        self.assertEqual(code, 1)
        self.assertEqual(out["error"], "secrets_found")

    def test_reapplying_same_plan_refused(self):
        # Ein Plan ist einmalig: die Create-Voraussetzungen (Datei darf nicht
        # existieren) sind nach dem ersten Apply verletzt -> stale_plan, null Schreibvorgänge.
        plan = json.loads((self.rt / "plan.json").read_text(encoding="utf-8"))
        code, out = S.run("collab_init.py", "apply", "--target", self.wiki, "--plan-file", self.rt / "plan.json",
                          "--expect-plan-sha256", plan["plan_sha256"], "--token-file", self.rt / "tok.json")
        self.assertEqual(code, 1)
        self.assertEqual(out["error"], "stale_plan")

    def test_lock_released_after_release(self):
        code, out = S.run("wiki_lock.py", "release", "--target", self.wiki, "--token-file", self.rt / "tok.json")
        self.assertEqual(code, 0)
        self.assertTrue(out["released"])
        self.assertFalse((self.wiki / ".collabmd.lock" / "claim.json").exists())
        self.assertFalse((self.rt / "tok.json").exists())


if __name__ == "__main__":
    unittest.main(verbosity=2)
