#!/usr/bin/env python3
"""Search, attachments, secret screening."""
import hashlib
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support as S


class SearchFilesTests(unittest.TestCase):
    def setUp(self):
        self.wiki, self.rt = S.fresh("search")
        self.token = self.rt / "tok.json"
        self.sess = S.session(self.rt, self.wiki, "alice")
        for body in ("Quanten-Computing diskutiert", "Kaffee und Kuchen", "Quanten-Verschränkung erklärt"):
            code, out, _ = S.post_plan(self.wiki, self.rt, "create", "general", "alice", body + "\n",
                                       self.token, self.sess)
            self.assertEqual(code, 0, out)

    def test_search_text(self):
        code, out = S.run("collab_query.py", "search", "--target", self.wiki, "--text", "Quanten")
        self.assertEqual(code, 0)
        self.assertEqual(out["count"], 2)

    def test_search_case_insensitive_and_limit(self):
        code, out = S.run("collab_query.py", "search", "--target", self.wiki, "--text", "kaffee", "--limit", "1")
        self.assertEqual(code, 0)
        self.assertEqual(out["count"], 1)
        self.assertEqual(len(out["hits"]), 1)

    def test_attachment_stored_by_sha256(self):
        data = "Anhang-Inhalt für die Suche\n".encode("utf-8")
        attach = self.rt / "attach.bin"
        attach.write_bytes(data)
        digest = hashlib.sha256(data).hexdigest()
        code, out, plan = S.post_plan(self.wiki, self.rt, "create", "general", "alice", "Mit Anhang\n",
                                      self.token, self.sess, extra=("--files", attach))
        self.assertEqual(code, 0, out)
        stored = self.wiki / "posts" / "_files" / digest
        self.assertTrue(stored.is_file())
        self.assertEqual(hashlib.sha256(stored.read_bytes()).hexdigest(), digest)
        text = (self.wiki / "posts" / "general" / f"{plan['post_id']}.md").read_text(encoding="utf-8")
        self.assertIn(digest, text)

    def test_secret_in_post_refused(self):
        body = self.rt / "secret-body.txt"
        body.write_text("Mein Token ist sk-abcdefghijklmnopqrstuvwx\n", encoding="utf-8")
        code, out = S.run("collab_posts.py", "plan", "--op", "create", "--target", self.wiki,
                          "--channel", "general", "--body-file", body, "--actor", "alice",
                          "--content-dir", self.rt / "c", "--output", self.rt / "plan-secret.json")
        self.assertEqual(code, 1)
        self.assertEqual(out["error"], "secrets_found")

    def test_lint_detects_tampered_file_hash(self):
        code, out, plan = S.post_plan(self.wiki, self.rt, "create", "general", "alice", "Tamper\n",
                                      self.token, self.sess)
        self.assertEqual(code, 0, out)
        attach = self.rt / "attach2.bin"
        attach.write_bytes(b"original")
        code, out, plan2 = S.post_plan(self.wiki, self.rt, "create", "general", "alice", "Mit Anhang 2\n",
                                       self.token, self.sess, extra=("--files", attach))
        self.assertEqual(code, 0, out)
        digest = hashlib.sha256(b"original").hexdigest()
        (self.wiki / "posts" / "_files" / digest).write_text("gefaelscht", encoding="utf-8")
        code, out = S.run("collab_lint.py", "lint", "--target", self.wiki)
        self.assertEqual(code, 1)
        self.assertTrue(any("Hash weicht" in e for e in out["errors"]))

    def test_lint_detects_unknown_thread_root(self):
        posts = list((self.wiki / "posts" / "general").glob("*.md"))
        target = posts[0]
        text = target.read_text(encoding="utf-8")
        text = text.replace("thread_root: null", "thread_root: " + "f" * 32)
        target.write_text(text, encoding="utf-8")
        code, out = S.run("collab_lint.py", "lint", "--target", self.wiki)
        self.assertEqual(code, 1)
        self.assertTrue(any("Thread-Root existiert nicht" in e for e in out["errors"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
