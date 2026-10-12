#!/usr/bin/env python3
"""Server-side integrity check for CollabMD team PRs (advisory on GitHub Free)."""
import argparse
import subprocess
import sys
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
sys.path.insert(0, str(SCRIPT_DIR))

import collabmd_common as C
import collab_lint
import secret_screen
import team_contract as T

def diff_names(base_sha, cwd):
    out = subprocess.run(["git", "diff", "--name-only", base_sha, "HEAD"], capture_output=True, text=True, cwd=str(cwd))
    if out.returncode != 0:
        raise C.CollabError("integrity_git_failed", out.stderr[:200])
    return [line for line in out.stdout.splitlines() if line.strip()]


def diff_added_text(base_sha, cwd):
    out = subprocess.run(["git", "diff", "--no-color", base_sha, "HEAD"], capture_output=True, text=True, cwd=str(cwd))
    if out.returncode != 0:
        raise C.CollabError("integrity_git_failed", out.stderr[:200])
    added = "\n".join(line[1:] for line in out.stdout.splitlines()
                      if line.startswith("+") and not line.startswith("+++"))
    return added


def check(worktree, base_sha, body_text, actor_github_id):
    ws = C.Workspace(str(worktree))
    ws.require_workspace()
    members = ws.members_doc()
    config = C.read_json(ws.schema / "team.json")
    T.validate_config(config, members)
    fields = T.parse_pr_operation_block(body_text)
    try:
        handle = T.actor_for(config, actor_github_id)
    except C.CollabError:
        raise C.CollabError("integrity_actor_unknown", "PR-Autor ist keinem Mitglied zugeordnet")
    if handle != fields["actor"]:
        raise C.CollabError("integrity_actor_mismatch", "PR-Autor weicht vom Akteur im Operation-Block ab")
    T.validate_pr_body(body_text, {"actor": fields["actor"], "base_revision": base_sha,
                                   "preview_sha256": fields["preview-sha256"]})
    paths = diff_names(base_sha, worktree)
    T.allowed_diff_paths(paths)
    report = collab_lint.run_lint(ws)
    if report["errors"]:
        raise C.CollabError("integrity_lint_failed", "; ".join(report["errors"][:5]))
    findings = secret_screen.scan(diff_added_text(base_sha, worktree))
    if findings:
        raise C.CollabError("integrity_secrets_found", f"{len(findings)} mutmaßliche Zugangsdaten in der diff")
    events = []
    for rel in sorted(p for p in paths if p.startswith("meta/events/") and p.endswith(".md")):
        fpath = ws.safe_rel(rel)
        if fpath is None or not fpath.is_file():
            continue
        for line in fpath.read_text(encoding="utf-8").splitlines():
            if line.startswith("- "):
                events.append(line[2:].split(" ", 1)[0])
                break
    return {
        "ok": True,
        "actor": fields["actor"],
        "base_revision": base_sha,
        "files_changed": len(paths),
        "events": events,
        "lint_ok": True,
        "secrets": 0,
    }


def main():
    parser = argparse.ArgumentParser(prog="team_integrity.py")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("check")
    p.add_argument("--worktree", required=True)
    p.add_argument("--base-sha", required=True)
    p.add_argument("--pr-body-file", required=True)
    p.add_argument("--actor-github-id", required=True)
    args = parser.parse_args()
    return C.run_main(lambda: check(Path(args.worktree), args.base_sha,
                                    Path(args.pr_body_file).read_text(encoding="utf-8"),
                                    args.actor_github_id))


if __name__ == "__main__":
    sys.exit(main())
