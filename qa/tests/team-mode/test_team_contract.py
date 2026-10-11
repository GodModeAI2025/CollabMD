#!/usr/bin/env python3
"""Pure team-mode contract: config, actor mapping, previews, approvals, diff rules."""
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "collabmd" / "scripts"))
import team_contract as T
from collabmd_common import CollabError


MEMBERS = {
    "format": "collabmd/1",
    "members": {
        "alice": {"role": "owner", "disabled": False},
        "bob": {"role": "contributor", "disabled": False},
        "carl": {"role": "reader", "disabled": True},
    },
}


def config(**over):
    base = {
        "format": T.TEAM_FORMAT,
        "provider": "github",
        "repo": "godmodeai/team",
        "branch": "main",
        "enforcement": "trusted-writers-beta",
        "github_ids": {"alice": "1001", "bob": "1002"},
    }
    base.update(over)
    return base


class ConfigTests(unittest.TestCase):
    def test_valid(self):
        self.assertTrue(T.validate_config(config(), MEMBERS))

    def test_bad_format(self):
        with self.assertRaises(CollabError) as ctx:
            T.validate_config(config(format="collabmd-team/9"), MEMBERS)
        self.assertEqual(ctx.exception.code, "team_config_invalid")

    def test_bad_repo(self):
        with self.assertRaises(CollabError):
            T.validate_config(config(repo="../evil"), MEMBERS)

    def test_duplicate_github_ids(self):
        with self.assertRaises(CollabError) as ctx:
            T.validate_config(config(github_ids={"alice": "1", "bob": "1"}), MEMBERS)
        self.assertEqual(ctx.exception.code, "team_config_invalid")

    def test_missing_mapping_for_active_member(self):
        with self.assertRaises(CollabError) as ctx:
            T.validate_config(config(github_ids={"alice": "1"}), MEMBERS)
        self.assertEqual(ctx.exception.code, "team_mapping_incomplete")

    def test_disabled_member_needs_no_mapping(self):
        cfg = config(github_ids={"alice": "1", "bob": "2"})
        self.assertTrue(T.validate_config(cfg, MEMBERS))


class ActorTests(unittest.TestCase):
    def test_actor_for(self):
        self.assertEqual(T.actor_for(config(), "1001"), "alice")

    def test_actor_unknown(self):
        with self.assertRaises(CollabError) as ctx:
            T.actor_for(config(), "9999")
        self.assertEqual(ctx.exception.code, "unknown_actor")


class PreviewApprovalTests(unittest.TestCase):
    BASE = "a" * 40

    def make_preview(self):
        return T.make_preview(self.BASE, "alice", [{"file": "meta/events/1.md", "action": "posts.create"}],
                              {"posts/general/1.md": "b" * 64})

    def test_preview_deterministic(self):
        p1 = self.make_preview()
        p2 = self.make_preview()
        self.assertEqual(p1["preview_sha256"], p2["preview_sha256"])

    def test_approval_roundtrip(self):
        preview = self.make_preview()
        approval = T.approval_for(preview["preview_sha256"], "alice")
        T.validate_approval(approval, preview["preview_sha256"], "alice")

    def test_approval_wrong_preview(self):
        preview = self.make_preview()
        other = T.make_preview(self.BASE, "bob", [], {})
        approval = T.approval_for(preview["preview_sha256"], "alice")
        with self.assertRaises(CollabError) as ctx:
            T.validate_approval(approval, other["preview_sha256"], "alice")
        self.assertEqual(ctx.exception.code, "team_approval_mismatch")

    def test_approval_wrong_actor(self):
        preview = self.make_preview()
        approval = T.approval_for(preview["preview_sha256"], "alice")
        with self.assertRaises(CollabError):
            T.validate_approval(approval, preview["preview_sha256"], "bob")

    def test_pr_block_roundtrip(self):
        preview = self.make_preview()
        approval = T.approval_for(preview["preview_sha256"], "alice")
        body = T.pr_operation_block(preview, approval) + "execution: local-draft\n"
        T.validate_pr_body(body, preview)
        fields = T.parse_pr_operation_block(body)
        self.assertEqual(fields["actor"], "alice")
        self.assertEqual(fields["base-revision"], self.BASE)

    def test_pr_body_missing_marker(self):
        with self.assertRaises(CollabError) as ctx:
            T.parse_pr_operation_block("kein block")
        self.assertEqual(ctx.exception.code, "team_pr_block_missing")

    def test_stale_base(self):
        preview = self.make_preview()
        self.assertFalse(T.is_stale_base({}, self.BASE, preview))
        self.assertTrue(T.is_stale_base({}, "c" * 40, preview))


class DiffPathTests(unittest.TestCase):
    def test_allowed(self):
        out = T.allowed_diff_paths(["schema/members.json", "posts/general/1.md", "meta/events/x.md"])
        self.assertEqual(len(out), 3)

    def test_lock_forbidden(self):
        with self.assertRaises(CollabError) as ctx:
            T.allowed_diff_paths([".collabmd.lock/claim.json"])
        self.assertEqual(ctx.exception.code, "team_diff_forbidden")

    def test_outer_path_forbidden(self):
        with self.assertRaises(CollabError):
            T.allowed_diff_paths(["README.md"])

    def test_meta_subpath_restricted(self):
        with self.assertRaises(CollabError):
            T.allowed_diff_paths(["meta/fremd.json"])

    def test_workflow_only_with_flag(self):
        with self.assertRaises(CollabError):
            T.allowed_diff_paths([".github/workflows/team-integrity.yml"])
        self.assertEqual(T.allowed_diff_paths([".github/workflows/team-integrity.yml"], allow_workflow=True),
                         [".github/workflows/team-integrity.yml"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
