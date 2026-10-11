#!/usr/bin/env python3
"""Team-mode lifecycle on a local bare remote (no network)."""
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import support as S


class TeamLocalTests(unittest.TestCase):
    def setUp(self):
        self.wiki, self.rt = S.fresh("team")
        self.token = self.rt / "tok.json"
        self.sess = S.session(self.rt, self.wiki, "alice")
        self.rt_base = self.rt / "team-rt"
        self.remote = self.rt / "bare.git"
        code, out = S.run("team_git.py", "setup", "--target", self.wiki, "--actor", "alice",
                          "--provider", "local", "--repo", self.remote, "--branch", "main",
                          "--token-file", self.token, "--session-file", self.sess,
                          "--content-dir", self.rt / "c", "--output", self.rt / "plan-setup.json")
        self.assertEqual(code, 0, out)
        plan = json.loads((self.rt / "plan-setup.json").read_text(encoding="utf-8"))
        code, out = S.run("team_git.py", "apply", "--target", self.wiki,
                          "--plan-file", self.rt / "plan-setup.json",
                          "--expect-plan-sha256", plan["plan_sha256"], "--token-file", self.token,
                          "--session-file", self.sess)
        self.assertEqual(code, 0, out)
        code, out = S.run("team_git.py", "seed", "--target", self.wiki, "--repo", self.remote,
                          "--branch", "main", "--runtime", self.rt_base)
        self.assertEqual(code, 0, out)

    def start_run(self, actor="alice"):
        code, out = S.run("team_git.py", "start", "--target", self.wiki, "--actor", actor,
                          "--runtime", self.rt_base)
        self.assertEqual(code, 0, out)
        return out["run_id"], Path(out["staging"])

    def stage_post(self, run_id, staging, actor, channel, text, sess_file):
        stok = self.rt / f"stok-{run_id[:8]}.json"
        code, out = S.run("wiki_lock.py", "acquire", "--target", staging, "--owner", actor,
                          "--operation", "stage", "--token-file", stok)
        self.assertEqual(code, 0, out)
        code, out, plan = S.post_plan(staging, self.rt, "create", channel, actor, text, stok, sess_file)
        self.assertEqual(code, 0, out)
        code, out = S.run("wiki_lock.py", "release", "--target", staging, "--token-file", stok)
        self.assertEqual(code, 0, out)
        return plan["post_id"]

    def stage_create_user(self, run_id, staging, handle, actor, sess_file):
        stok = self.rt / f"stok-{run_id[:8]}.json"
        code, out = S.run("wiki_lock.py", "acquire", "--target", staging, "--owner", actor,
                          "--operation", "stage-user", "--token-file", stok)
        self.assertEqual(code, 0, out)
        code, out = S.run("collab_auth.py", "create-user", "--target", staging, "--handle", handle,
                          "--role", "contributor", "--passphrase-file", self.rt / "pp.txt",
                          "--actor", actor, "--token-file", stok,
                          "--content-dir", self.rt / "c", "--output", self.rt / f"plan-{handle}.json")
        self.assertEqual(code, 0, out)
        plan = json.loads((self.rt / f"plan-{handle}.json").read_text(encoding="utf-8"))
        code, out = S.run("collab_auth.py", "apply", "--target", staging, "--handle", handle,
                          "--plan-file", self.rt / f"plan-{handle}.json",
                          "--expect-plan-sha256", plan["plan_sha256"], "--token-file", stok,
                          "--session-file", sess_file)
        self.assertEqual(code, 0, out)
        code, out = S.run("wiki_lock.py", "release", "--target", staging, "--token-file", stok)
        self.assertEqual(code, 0, out)

    def publish_run(self, run_id, actor, stage_id=None):
        code, pv = S.run("team_git.py", "preview", "--run-id", run_id, "--actor", actor,
                         "--target", self.wiki, "--runtime", self.rt_base)
        self.assertEqual(code, 0, pv)
        code, ap = S.run("team_git.py", "approve", "--run-id", run_id, "--actor", actor,
                         "--preview-file", pv["preview_file"], "--runtime", self.rt_base)
        self.assertEqual(code, 0, ap)
        code, sm = S.run("team_git.py", "submit", "--run-id", run_id, "--actor", actor,
                         "--target", self.wiki, "--preview-file", pv["preview_file"],
                         "--approval-file", ap["approval_file"], "--runtime", self.rt_base)
        self.assertEqual(code, 0, sm)
        code, pub = S.run("team_git.py", "publish", "--run-id", run_id, "--actor", actor,
                          "--target", self.wiki, "--runtime", self.rt_base)
        return code, pub

    def sync(self):
        code, out = S.run("team_git.py", "sync", "--target", self.wiki,
                          "--token-file", self.token, "--runtime", self.rt_base)
        self.assertEqual(code, 0, out)

    def test_full_flow(self):
        run_id, staging = self.start_run("alice")
        self.stage_post(run_id, staging, "alice", "general", "Team-Post\n", self.sess)
        code, pub = self.publish_run(run_id, "alice")
        self.assertEqual(code, 0, pub)
        self.assertTrue(pub["published"])
        self.sync()
        self.assertTrue((self.wiki / "schema" / "team.json").is_file())
        self.assertTrue((self.wiki / ".github" / "collabmd-runtime" / "team_integrity.py").is_file())
        posts = list((self.wiki / "posts" / "general").glob("*.md"))
        self.assertEqual(len(posts), 1)
        self.assertIn("Team-Post", posts[0].read_text(encoding="utf-8"))

    def test_stale_base_then_supersede(self):
        run_a, staging_a = self.start_run("alice")
        run_b, staging_b = self.start_run("alice")
        self.stage_post(run_a, staging_a, "alice", "general", "Post A\n", self.sess)
        code_a, pub_a = self.publish_run(run_a, "alice")
        self.assertEqual(code_a, 0, pub_a)
        self.sync()
        code, pv = S.run("team_git.py", "preview", "--run-id", run_b, "--actor", "alice",
                         "--target", self.wiki, "--runtime", self.rt_base)
        self.assertEqual(code, 0, pv)
        code, ap = S.run("team_git.py", "approve", "--run-id", run_b, "--actor", "alice",
                         "--preview-file", pv["preview_file"], "--runtime", self.rt_base)
        self.assertEqual(code, 0, ap)
        code, sm = S.run("team_git.py", "submit", "--run-id", run_b, "--actor", "alice",
                         "--target", self.wiki, "--preview-file", pv["preview_file"],
                         "--approval-file", ap["approval_file"], "--runtime", self.rt_base)
        self.assertEqual(code, 1)
        self.assertEqual(sm["error"], "stale_base")
        code, out = S.run("team_git.py", "supersede", "--run-id", run_b, "--actor", "alice",
                          "--target", self.wiki, "--runtime", self.rt_base)
        self.assertEqual(code, 0, out)
        self.assertTrue(out["superseded"])
        self.stage_post(run_b, staging_b, "alice", "general", "Post B nach Supersede\n", self.sess)
        code_b, pub_b = self.publish_run(run_b, "alice")
        self.assertEqual(code_b, 0, pub_b)
        self.sync()
        texts = [p.read_text(encoding="utf-8") for p in (self.wiki / "posts" / "general").glob("*.md")]
        self.assertTrue(any("Post A" in t for t in texts))
        self.assertTrue(any("Post B nach Supersede" in t for t in texts))

    def test_preview_lint_failure(self):
        run_id, staging = self.start_run("alice")
        members = staging / "schema" / "members.json"
        doc = json.loads(members.read_text(encoding="utf-8"))
        doc["members"]["alice"]["role"] = "kaputt"
        members.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")
        code, out = S.run("team_git.py", "preview", "--run-id", run_id, "--actor", "alice",
                          "--target", self.wiki, "--runtime", self.rt_base)
        self.assertEqual(code, 1)
        self.assertEqual(out["error"], "team_lint_failed")

    def test_recover_and_cleanup(self):
        run_id, staging = self.start_run("alice")
        self.stage_post(run_id, staging, "alice", "general", "Offener Lauf\n", self.sess)
        code, out = S.run("team_git.py", "recover", "--runtime", self.rt_base)
        self.assertEqual(code, 0, out)
        self.assertEqual(len(out["open_runs"]), 1)
        self.assertEqual(out["open_runs"][0]["run_id"], run_id)
        code, out = S.run("team_git.py", "cleanup", "--runtime", self.rt_base)
        self.assertEqual(code, 1)
        self.assertEqual(out["error"], "team_open_runs")
        code, out = S.run("team_git.py", "cancel", "--run-id", run_id, "--actor", "alice",
                          "--runtime", self.rt_base)
        self.assertEqual(code, 0, out)
        code, out = S.run("team_git.py", "cleanup", "--runtime", self.rt_base)
        self.assertEqual(code, 0, out)
        self.assertEqual(out["removed"], [run_id])


if __name__ == "__main__":
    unittest.main(verbosity=2)
