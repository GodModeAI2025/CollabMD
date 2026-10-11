#!/usr/bin/env python3
"""Channels, posts, edits, pins, reactions, deletes."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support as S


def add_member(wiki, rt, token, sess, handle="bob"):
    code, out = S.run("collab_auth.py", "create-user", "--target", wiki, "--handle", handle,
                      "--role", "contributor", "--passphrase-file", rt / "pp.txt",
                      "--actor", "alice", "--token-file", token,
                      "--content-dir", rt / "c", "--output", rt / f"plan-{handle}.json")
    assert code == 0, out
    plan = json.loads((rt / f"plan-{handle}.json").read_text(encoding="utf-8"))
    code, out = S.run("collab_auth.py", "apply", "--target", wiki, "--handle", handle,
                      "--plan-file", rt / f"plan-{handle}.json",
                      "--expect-plan-sha256", plan["plan_sha256"], "--token-file", token,
                      "--session-file", sess)
    assert code == 0, out


class ChannelTests(unittest.TestCase):
    def setUp(self):
        self.wiki, self.rt = S.fresh("chats")
        self.token = self.rt / "tok.json"
        self.sess = S.session(self.rt, self.wiki, "alice")
        add_member(self.wiki, self.rt, self.token, self.sess)

    def create_channel(self, channel_id="product", title="Produkt", ctype="public", actor="alice", sess=None):
        sess = sess or self.sess
        code, out = S.run("collab_channels.py", "plan", "--action", "channels.create",
                          "--target", self.wiki, "--id", channel_id, "--title", title, "--type", ctype,
                          "--members", "alice,bob", "--actor", actor,
                          "--content-dir", self.rt / "c", "--output", self.rt / f"plan-{channel_id}.json")
        self.assertEqual(code, 0, out)
        plan = json.loads((self.rt / f"plan-{channel_id}.json").read_text(encoding="utf-8"))
        code, out = S.run("collab_channels.py", "apply", "--target", self.wiki,
                          "--plan-file", self.rt / f"plan-{channel_id}.json",
                          "--expect-plan-sha256", plan["plan_sha256"], "--token-file", self.token,
                          "--session-file", sess)
        self.assertEqual(code, 0, out)

    def test_channel_create_join_leave(self):
        self.create_channel()
        code, out = S.run("collab_channels.py", "plan", "--action", "channels.leave",
                          "--target", self.wiki, "--id", "product", "--actor", "bob",
                          "--content-dir", self.rt / "c", "--output", self.rt / "plan-leave.json")
        self.assertEqual(code, 0)
        plan = json.loads((self.rt / "plan-leave.json").read_text(encoding="utf-8"))
        code, out = S.run("collab_channels.py", "apply", "--target", self.wiki,
                          "--plan-file", self.rt / "plan-leave.json",
                          "--expect-plan-sha256", plan["plan_sha256"], "--token-file", self.token,
                          "--session-file", S.session(self.rt, self.wiki, "bob"))
        self.assertEqual(code, 0)
        channels = json.loads((self.wiki / "schema/channels.json").read_text(encoding="utf-8"))
        self.assertEqual(channels["channels"]["product"]["members"], ["alice"])

    def test_post_lifecycle(self):
        self.create_channel()
        code, out, plan = S.post_plan(self.wiki, self.rt, "create", "product", "alice", "Erster Post\n", self.token, self.sess)
        self.assertEqual(code, 0, out)
        post_id = plan["post_id"]
        code, out, _ = S.post_plan(self.wiki, self.rt, "edit", "product", "alice", "Bearbeiteter Post\n", self.token, self.sess,
                                   extra=("--post", post_id))
        self.assertEqual(code, 0, out)
        text = (self.wiki / "posts" / "product" / f"{post_id}.md").read_text(encoding="utf-8")
        self.assertIn("Bearbeiteter Post", text)
        self.assertIn("edited: true", text)
        code, out, _ = S.post_plan(self.wiki, self.rt, "pin", "product", "alice", "x", self.token, self.sess,
                                   extra=("--post", post_id))
        self.assertEqual(code, 0, out)
        code, out, _ = S.post_plan(self.wiki, self.rt, "react", "product", "bob", "x", self.token,
                                   S.session(self.rt, self.wiki, "bob"),
                                   extra=("--post", post_id, "--emoji", "thumbsup"))
        self.assertEqual(code, 0, out)
        code, out, _ = S.post_plan(self.wiki, self.rt, "delete", "product", "alice", "x", self.token, self.sess,
                                   extra=("--post", post_id))
        self.assertEqual(code, 0, out)
        text = (self.wiki / "posts" / "product" / f"{post_id}.md").read_text(encoding="utf-8")
        self.assertIn("deleted: true", text)
        self.assertIn("[gelöscht]", text)

    def test_nonmember_cannot_post(self):
        self.create_channel()
        (self.rt / "pp-carl.txt").write_text("carl-passwort-123\n", encoding="utf-8")
        code, out = S.run("collab_auth.py", "create-user", "--target", self.wiki, "--handle", "carl",
                          "--role", "contributor", "--passphrase-file", self.rt / "pp-carl.txt",
                          "--actor", "alice", "--token-file", self.token,
                          "--content-dir", self.rt / "c", "--output", self.rt / "plan-carl.json")
        plan = json.loads((self.rt / "plan-carl.json").read_text(encoding="utf-8"))
        code, out = S.run("collab_auth.py", "apply", "--target", self.wiki, "--handle", "carl",
                          "--plan-file", self.rt / "plan-carl.json",
                          "--expect-plan-sha256", plan["plan_sha256"], "--token-file", self.token,
                          "--session-file", self.sess)
        self.assertEqual(code, 0)
        body = self.rt / "body-carl.txt"
        body.write_text("Hallo\n", encoding="utf-8")
        code, out = S.run("collab_posts.py", "plan", "--op", "create", "--target", self.wiki,
                          "--channel", "product", "--body-file", body, "--actor", "carl",
                          "--content-dir", self.rt / "c", "--output", self.rt / "plan-post-carl.json")
        self.assertEqual(code, 1)
        self.assertEqual(out["error"], "not_member")

    def test_post_into_archived_channel_refused(self):
        self.create_channel()
        code, out = S.run("collab_channels.py", "plan", "--action", "channels.archive",
                          "--target", self.wiki, "--id", "product", "--actor", "alice",
                          "--content-dir", self.rt / "c", "--output", self.rt / "plan-arch.json")
        plan = json.loads((self.rt / "plan-arch.json").read_text(encoding="utf-8"))
        code, out = S.run("collab_channels.py", "apply", "--target", self.wiki,
                          "--plan-file", self.rt / "plan-arch.json",
                          "--expect-plan-sha256", plan["plan_sha256"], "--token-file", self.token,
                          "--session-file", self.sess)
        self.assertEqual(code, 0)
        body = self.rt / "body-arch.txt"
        body.write_text("Spaet\n", encoding="utf-8")
        code, out = S.run("collab_posts.py", "plan", "--op", "create", "--target", self.wiki,
                          "--channel", "product", "--body-file", body, "--actor", "alice",
                          "--content-dir", self.rt / "c", "--output", self.rt / "plan-post-arch.json")
        self.assertEqual(code, 1)
        self.assertEqual(out["error"], "channel_archived")


if __name__ == "__main__":
    unittest.main(verbosity=2)
