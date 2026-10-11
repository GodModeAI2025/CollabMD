#!/usr/bin/env python3
"""Threads, direct messages, mentions, cursors."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support as S


class ThreadDmTests(unittest.TestCase):
    def setUp(self):
        self.wiki, self.rt = S.fresh("threads")
        self.token = self.rt / "tok.json"
        self.sess = S.session(self.rt, self.wiki, "alice")
        code, out = S.run("collab_auth.py", "create-user", "--target", self.wiki, "--handle", "bob",
                          "--role", "contributor", "--passphrase-file", self.rt / "pp.txt",
                          "--actor", "alice", "--token-file", self.token,
                          "--content-dir", self.rt / "c", "--output", self.rt / "plan-bob.json")
        self.assertEqual(code, 0, out)
        plan = json.loads((self.rt / "plan-bob.json").read_text(encoding="utf-8"))
        code, out = S.run("collab_auth.py", "apply", "--target", self.wiki, "--handle", "bob",
                          "--plan-file", self.rt / "plan-bob.json",
                          "--expect-plan-sha256", plan["plan_sha256"], "--token-file", self.token,
                          "--session-file", self.sess)
        self.assertEqual(code, 0, out)
        self.bob_sess = S.session(self.rt, self.wiki, "bob")
        code, out = S.run("collab_channels.py", "plan", "--action", "channels.join",
                          "--target", self.wiki, "--id", "general", "--actor", "bob",
                          "--content-dir", self.rt / "c", "--output", self.rt / "plan-join.json")
        self.assertEqual(code, 0, out)
        plan = json.loads((self.rt / "plan-join.json").read_text(encoding="utf-8"))
        code, out = S.run("collab_channels.py", "apply", "--target", self.wiki,
                          "--plan-file", self.rt / "plan-join.json",
                          "--expect-plan-sha256", plan["plan_sha256"], "--token-file", self.token,
                          "--session-file", self.bob_sess)
        self.assertEqual(code, 0, out)
        code, out, self.root_plan = S.post_plan(self.wiki, self.rt, "create", "general", "alice",
                                                "Thread-Root mit @bob\n", self.token, self.sess)
        self.assertEqual(code, 0, out)

    def test_thread_reply_and_query(self):
        code, out, _ = S.post_plan(self.wiki, self.rt, "reply", "general", "bob", "Antwort\n",
                                   self.token, self.bob_sess, extra=("--post", self.root_plan["post_id"]))
        self.assertEqual(code, 0, out)
        code, out = S.run("collab_query.py", "thread", "--target", self.wiki, "--channel", "general",
                          "--post", self.root_plan["post_id"])
        self.assertEqual(code, 0)
        self.assertEqual(out["root"]["id"], self.root_plan["post_id"])
        self.assertEqual(len(out["replies"]), 1)
        self.assertEqual(out["replies"][0]["author"], "bob")

    def test_nested_thread_refused(self):
        code, out, reply_plan = S.post_plan(self.wiki, self.rt, "reply", "general", "bob", "Antwort\n",
                                            self.token, self.bob_sess, extra=("--post", self.root_plan["post_id"]))
        self.assertEqual(code, 0, out)
        body = self.rt / "body-nested.txt"
        body.write_text("Schachtel\n", encoding="utf-8")
        code, out = S.run("collab_posts.py", "plan", "--op", "reply", "--target", self.wiki,
                          "--channel", "general", "--body-file", body, "--actor", "alice",
                          "--content-dir", self.rt / "c", "--output", self.rt / "plan-nested.json",
                          "--post", reply_plan["post_id"])
        self.assertEqual(code, 1)
        self.assertEqual(out["error"], "bad_thread_root")

    def test_dm_auto_creates_channel(self):
        code, out, plan = S.post_plan(self.wiki, self.rt, "create", "dm:alice", "bob", "Hallo in der DM\n",
                                      self.token, self.bob_sess)
        self.assertEqual(code, 0, out)
        channels = json.loads((self.wiki / "schema/channels.json").read_text(encoding="utf-8"))
        self.assertIn("dm-alice-bob", channels["channels"])
        channel = channels["channels"]["dm-alice-bob"]
        self.assertEqual(channel["type"], "direct")
        self.assertEqual(channel["members"], ["alice", "bob"])
        code, out = S.run("collab_query.py", "channel", "--target", self.wiki, "--id", "dm-alice-bob")
        self.assertEqual(out["count"], 1)

    def test_mentions_query(self):
        code, out = S.run("collab_query.py", "mentions", "--target", self.wiki, "--handle", "bob")
        self.assertEqual(code, 0)
        self.assertEqual(out["count"], 1)
        self.assertEqual(out["hits"][0]["author"], "alice")

    def test_cursor_unread(self):
        code, out = S.run("collab_query.py", "unread", "--target", self.wiki, "--handle", "bob")
        self.assertEqual(code, 0)
        product = {c["channel"]: c for c in out["channels"]}
        self.assertEqual(product["general"]["unread"], 1)
        code, out = S.run("collab_posts.py", "cursor-set", "--target", self.wiki, "--handle", "bob",
                          "--actor", "bob", "--channel", "general", "--cursor", "2099-01-01T00:00:00Z",
                          "--token-file", self.token)
        self.assertEqual(code, 0)
        code, out = S.run("collab_query.py", "unread", "--target", self.wiki, "--handle", "bob")
        product = {c["channel"]: c for c in out["channels"]}
        self.assertEqual(product["general"]["unread"], 0)

    def test_cursor_set_other_handle_refused(self):
        code, out = S.run("collab_posts.py", "cursor-set", "--target", self.wiki, "--handle", "bob",
                          "--actor", "alice", "--channel", "general", "--cursor", "2099-01-01T00:00:00Z",
                          "--token-file", self.token)
        self.assertEqual(code, 1)
        self.assertEqual(out["error"], "not_self")


if __name__ == "__main__":
    unittest.main(verbosity=2)
