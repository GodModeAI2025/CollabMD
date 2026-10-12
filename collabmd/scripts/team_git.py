#!/usr/bin/env python3
"""CollabMD team-mode lifecycle: isolated agent drafts, previews, approvals, publication."""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

import collabmd_common as C
import collab_lint
import team_contract as T

RUNS_DIR_NAME = "collabmd-runs"
LOCAL_REMOTE_RE = re.compile(r"^[a-zA-Z0-9._/:-]+$")


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def run_git(args, cwd, check=True):
    env = {**os.environ, "GIT_TERMINAL_PROMPT": "0"}
    result = subprocess.run(["git", *args], cwd=str(cwd), capture_output=True, text=True, env=env)
    if check and result.returncode != 0:
        raise C.CollabError("git_failed", (result.stderr or result.stdout).strip()[:400])
    return result.stdout.strip()


def gh(args, check=True):
    result = subprocess.run(["gh", *args], capture_output=True, text=True)
    if check and result.returncode != 0:
        raise C.CollabError("gh_failed", (result.stderr or result.stdout).strip()[:400])
    return result.stdout.strip()


def load_team_config(ws):
    path = ws.schema / "team.json"
    if not path.is_file():
        C.fail("team_not_setup", "Kein Teammodus: schema/team.json fehlt")
    config = C.read_json(path)
    T.validate_config(config, ws.members_doc())
    return config


def runs_dir(rt_base):
    path = Path(rt_base) / RUNS_DIR_NAME
    path.mkdir(parents=True, exist_ok=True)
    return path


def run_state_path(runs, run_id):
    return runs / run_id / "state.json"


def load_run_state(runs, run_id):
    path = run_state_path(runs, run_id)
    if not path.is_file():
        C.fail("run_missing", f"Lauf unbekannt: {run_id}")
    return C.read_json(path)


def save_run_state(runs, state):
    path = run_state_path(runs, state["run_id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    C.atomic_write(path, json.dumps(state, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    return path


def file_hashes_under(root, prefixes):
    out = {}
    for prefix in prefixes:
        base = Path(root) / prefix
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if path.is_file():
                rel = Path(prefix) / path.relative_to(base)
                out[str(rel)] = hashlib.sha256(path.read_bytes()).hexdigest()
    return out


def workspace_files(root):
    root = Path(root)
    return file_hashes_under(root, ("schema", "posts", "meta"))


def repo_head_sha(config, provider):
    if provider == "local":
        return run_git(["rev-parse", "refs/heads/" + config["branch"]], Path(config["repo"]))
    return gh(["api", f"repos/{config['repo']}/commits/{config['branch']}", "-q", ".sha"])


def do_setup(args):
    ws = C.Workspace(args.target)
    ws.require_workspace()
    C.verify_claim(ws, args.token_file)
    members = ws.members_doc()
    C.require_permission(members, args.actor, "team.setup")
    C.check_auth_session(ws, "team.setup", args.actor, args.session_file)
    if args.provider == "github":
        whoami = gh(["api", "user", "-q", ".id"])
        repo_ok = gh(["api", f"repos/{args.repo}", "-q", ".full_name"])
        if repo_ok != args.repo:
            C.fail("team_repo_not_found", f"Repo nicht erreichbar: {args.repo}")
        ids = {}
        for handle in sorted(members.get("members", {})):
            if handle == args.actor:
                ids[handle] = whoami
            else:
                C.fail("team_mapping_required", f"GitHub-ID für {handle} erforderlich: --github-id {handle}=<id>")
        for spec in (args.github_id or "").split(","):
            if not spec:
                continue
            handle, _, value = spec.partition("=")
            ids[handle] = value
    else:
        if not LOCAL_REMOTE_RE.match(str(args.repo)):
            C.fail("team_remote_invalid", f"Lokaler Remote-Pfad ungültig: {args.repo}")
        ids = {}
        for handle in sorted(members.get("members", {})):
            ids[handle] = str(1000 + len(ids))
        for spec in (args.github_id or "").split(","):
            if not spec:
                continue
            handle, _, value = spec.partition("=")
            ids[handle] = value
    config = {
        "format": T.TEAM_FORMAT,
        "provider": args.provider,
        "repo": str(args.repo),
        "branch": args.branch,
        "enforcement": "trusted-writers-beta",
        "github_ids": ids,
        "setup_at": now_iso(),
    }
    T.validate_config(config, members)
    ops = []
    content_dir = Path(args.content_dir)
    content_dir.mkdir(parents=True, exist_ok=True)
    team_path = ws.schema / "team.json"
    if team_path.is_file():
        C.fail("team_already_setup", "Teammodus ist bereits eingerichtet")
    cfile = content_dir / "team.json"
    C.atomic_write(cfile, json.dumps(config, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    ops.append(C.content_op("create", "schema/team.json", str(cfile)))
    preconditions = {"schema/team.json": None}
    script_dir = Path(__file__).resolve().parent
    runtime_files = ("collabmd_common.py", "collab_lint.py", "secret_screen.py",
                     "team_contract.py", "team_integrity.py")
    for name in runtime_files:
        source = script_dir / name
        if not source.is_file():
            C.fail("team_runtime_missing", f"Runtime-Skript fehlt im Skill: {name}")
        target = content_dir / f"runtime-{name}"
        target.write_bytes(source.read_bytes())
        relpath = f".github/collabmd-runtime/{name}"
        ops.append(C.content_op("create", relpath, str(target)))
        preconditions[relpath] = None
    workflow_source = script_dir.parent / "assets" / "team-integrity.yml"
    if not workflow_source.is_file():
        C.fail("team_runtime_missing", "Workflow-Datei fehlt im Skill: assets/team-integrity.yml")
    wtarget = content_dir / "team-integrity.yml"
    wtarget.write_bytes(workflow_source.read_bytes())
    ops.append(C.content_op("create", ".github/workflows/team-integrity.yml", str(wtarget)))
    preconditions[".github/workflows/team-integrity.yml"] = None
    plan = C.make_plan("team.setup", args.actor, preconditions, ops, ["team.setup provider=%s repo=%s" % (args.provider, args.repo)])
    C.write_json(args.output, plan)
    return {"ok": True, "plan_file": str(args.output), "plan_sha256": plan["plan_sha256"], "op": plan["op"]}


def do_apply(args):
    ws = C.Workspace(args.target)
    plan = C.read_json(args.plan_file)
    return C.apply_plan(ws, plan, args.expect_plan_sha256, args.token_file, args.session_file, {})


def do_start(args):
    ws = C.Workspace(args.target)
    ws.require_workspace()
    config = load_team_config(ws)
    C.require_permission(ws.members_doc(), args.actor, "team.start")
    base_sha = repo_head_sha(config, config["provider"])
    run_id = uuid.uuid4().hex
    staging = runs_dir(args.runtime) / run_id / "staging"
    staging.mkdir(parents=True)
    if config["provider"] == "local":
        remote = Path(config["repo"])
        if not (remote / f"refs/heads/{config['branch']}").exists():
            C.fail("team_remote_empty", "Lokaler Remote hat keine Basis; zuerst team_git.py seed ausführen")
        run_git(["clone", "-q", "--branch", config["branch"], str(remote), str(staging)], staging.parent)
    else:
        gh(["repo", "clone", config["repo"], str(staging), "--", "--branch", config["branch"]])
    state = {
        "format": "collabmd-run/1",
        "run_id": run_id,
        "actor": args.actor,
        "provider": config["provider"],
        "repo": config["repo"],
        "branch": config["branch"],
        "base_revision": base_sha,
        "staging": str(staging),
        "status": "started",
        "started_at": now_iso(),
    }
    save_run_state(runs_dir(args.runtime), state)
    return {"ok": True, "run_id": run_id, "staging": str(staging), "base_revision": base_sha}


def do_preview(args):
    state = load_run_state(runs_dir(args.runtime), args.run_id)
    if state["actor"] != args.actor:
        C.fail("team_run_actor_mismatch", "Lauf gehört zu einem anderen Akteur")
    staging = Path(state["staging"])
    ws = C.Workspace(str(staging))
    ws.require_workspace()
    report = collab_lint.run_lint(ws)
    if report["errors"]:
        C.fail("team_lint_failed", "Staging-Lint mit Fehlern: " + "; ".join(report["errors"][:5]))
    base_ws = C.Workspace(args.target)
    base_hashes = workspace_files(base_ws.root)
    staged = workspace_files(staging)
    changed = {rel: digest for rel, digest in staged.items() if base_hashes.get(rel) != digest}
    operations = []
    for rel in sorted(rel for rel in changed if rel.startswith("meta/events/") and rel.endswith(".md")):
        try:
            meta, body = C.parse_frontmatter((staging / rel).read_text(encoding="utf-8"))
        except C.CollabError:
            continue
        verb = ""
        for line in body.splitlines():
            if line.startswith("- "):
                verb = line[2:].split(" ", 1)[0]
                break
        operations.append({"file": rel, "actor": meta.get("actor"), "action": verb})
    preview = T.make_preview(state["base_revision"], args.actor, operations, changed)
    pfile = runs_dir(args.runtime) / state["run_id"] / "preview.json"
    C.write_json(pfile, preview)
    state["status"] = "previewed"
    state["preview_file"] = str(pfile)
    save_run_state(runs_dir(args.runtime), state)
    return {"ok": True, "run_id": state["run_id"], "preview_file": str(pfile),
            "preview_sha256": preview["preview_sha256"], "files": len(changed),
            "operations": len(operations), "lint_ok": True}


def do_approve(args):
    runs = runs_dir(args.runtime)
    state = load_run_state(runs, args.run_id)
    if state["actor"] != args.actor:
        C.fail("team_run_actor_mismatch", "Lauf gehört zu einem anderen Akteur")
    preview = C.read_json(args.preview_file)
    approval = T.approval_for(preview.get("preview_sha256"), args.actor)
    afile = runs / state["run_id"] / "approval.json"
    C.write_json(afile, approval)
    state["status"] = "approved"
    state["approval_file"] = str(afile)
    save_run_state(runs, state)
    return {"ok": True, "approval_file": str(afile), "approval_id": approval["approval_id"]}


def do_seed(args):
    ws = C.Workspace(args.target)
    ws.require_workspace()
    remote = Path(args.repo)
    if remote.exists() and any(remote.iterdir()):
        C.fail("team_remote_exists", "Lokaler Remote existiert bereits und ist nicht leer")
    remote.mkdir(parents=True)
    run_git(["init", "-q", "--bare", "-b", args.branch], remote)
    tmp = Path(args.runtime) / "seed-tmp"
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)
    C.atomic_write(tmp / ".seed", "seed")
    (tmp / "content").mkdir()
    C.atomic_write(tmp / "content" / "note.md", "seed\n")
    seed_dir = tmp / "seed"
    shutil.copytree(ws.root, seed_dir, ignore=shutil.ignore_patterns(".git", ".collabmd.lock"))
    run_git(["init", "-q", "-b", args.branch], seed_dir)
    run_git(["add", "-A"], seed_dir)
    run_git(["-c", "user.name=collabmd", "-c", "user.email=collabmd@local", "commit", "-q", "-m", "collabmd: seed"], seed_dir)
    run_git(["push", "-q", str(remote), f"{args.branch}:{args.branch}"], seed_dir)
    shutil.rmtree(tmp)
    return {"ok": True, "remote": str(remote), "branch": args.branch}


def do_submit(args):
    runs = runs_dir(args.runtime)
    state = load_run_state(runs, args.run_id)
    if state["actor"] != args.actor:
        C.fail("team_run_actor_mismatch", "Lauf gehört zu einem anderen Akteur")
    ws = C.Workspace(args.target)
    C.require_permission(ws.members_doc(), args.actor, "team.submit")
    C.check_auth_session(ws, "team.submit", args.actor, args.session_file)
    preview = C.read_json(args.preview_file)
    T.validate_approval(C.read_json(args.approval_file), preview["preview_sha256"], args.actor)
    config = {"branch": state["branch"], "repo": state["repo"]}
    current = repo_head_sha(config, state["provider"])
    if T.is_stale_base(config, current, preview):
        C.fail("stale_base", f"Remote-Basis {preview['base_revision'][:8]} != aktuell {current[:8]}; supersede erforderlich")
    staging = Path(state["staging"])
    branch = f"collabmd/{state['run_id'][8:24]}"
    body = T.pr_operation_block(preview, C.read_json(args.approval_file)) + "execution: local-draft\n"
    remote = str(state["repo"]) if state["provider"] == "local" else "origin"
    run_git(["checkout", "-q", "-B", branch], staging)
    run_git(["add", "-A"], staging)
    run_git(["-c", "user.name=collabmd", "-c", "user.email=collabmd@local", "commit", "-q", "-m",
             f"collabmd: run {state['run_id'][:8]} by {args.actor}", "--allow-empty"], staging)
    if state["provider"] == "local":
        run_git(["push", "-q", remote, f"HEAD:{branch}"], staging)
        pr_number = f"local-{state['run_id'][:8]}"
    else:
        run_git(["push", "-u", "-q", "origin", branch], staging)
        pr_number = gh(["pr", "create", "--repo", state["repo"], "--head", branch, "--base", state["branch"],
                        "--title", f"collabmd run {state['run_id'][:8]}", "--body", body])
    state["status"] = "submitted"
    state["draft_branch"] = branch
    state["pr"] = pr_number
    state["pr_body"] = body
    save_run_state(runs, state)
    return {"ok": True, "run_id": state["run_id"], "draft_branch": branch, "pr": pr_number}


def do_publish(args):
    runs = runs_dir(args.runtime)
    state = load_run_state(runs, args.run_id)
    if state["actor"] != args.actor:
        C.fail("team_run_actor_mismatch", "Lauf gehört zu einem anderen Akteur")
    if state["status"] != "submitted":
        C.fail("team_run_not_submitted", "Lauf ist nicht submitted")
    ws = C.Workspace(args.target)
    C.require_permission(ws.members_doc(), args.actor, "team.publish")
    C.check_auth_session(ws, "team.publish", args.actor, args.session_file)
    preview = C.read_json(state["preview_file"])
    config = {"branch": state["branch"], "repo": state["repo"]}
    current = repo_head_sha(config, state["provider"])
    if T.is_stale_base(config, current, preview):
        C.fail("stale_base", f"Basis {preview['base_revision'][:8]} != aktueller Stand {current[:8]}; supersede erforderlich")
    head = None
    if state["provider"] == "local":
        remote = Path(state["repo"])
        main_sha = run_git(["rev-parse", f"refs/heads/{state['branch']}"], remote)
        if main_sha != preview["base_revision"]:
            C.fail("stale_base", "Remote-Basis hat sich parallel geändert; supersede erforderlich")
        draft_sha = run_git(["rev-parse", f"refs/heads/{state['draft_branch']}"], remote)
        run_git(["merge-base", "--is-ancestor", main_sha, draft_sha], remote)
        run_git(["update-ref", f"refs/heads/{state['branch']}", draft_sha], remote)
        run_git(["branch", "-q", "-D", state["draft_branch"]], remote)
        head = draft_sha
    else:
        gh(["pr", "merge", state["pr"], "--repo", state["repo"], "--squash", "--delete-branch"])
    state["status"] = "published"
    state["published_at"] = now_iso()
    save_run_state(runs, state)
    return {"ok": True, "run_id": state["run_id"], "published": True, "pr": state["pr"], "head": head}


def do_sync(args):
    ws = C.Workspace(args.target)
    ws.require_workspace()
    C.verify_claim(ws, args.token_file)
    config = load_team_config(ws)
    tmp = Path(args.runtime) / "sync-tmp"
    if tmp.exists():
        shutil.rmtree(tmp)
    tmp.mkdir(parents=True)
    if config["provider"] == "local":
        run_git(["clone", "-q", "--branch", config["branch"], config["repo"], str(tmp / "work")], tmp)
    else:
        gh(["repo", "clone", config["repo"], str(tmp / "work"), "--", "--branch", config["branch"]])
    work = tmp / "work"
    for entry in list(ws.root.iterdir()):
        if entry.name == ".collabmd.lock":
            continue
        if entry.is_dir():
            shutil.rmtree(entry)
        else:
            entry.unlink()
    for entry in work.iterdir():
        if entry.name == ".git":
            continue
        dest = ws.root / entry.name
        if entry.is_dir():
            shutil.copytree(entry, dest)
        else:
            shutil.copy2(entry, dest)
    shutil.rmtree(tmp)
    return {"ok": True, "synced": True, "branch": config["branch"]}


def do_read(args):
    ws = C.Workspace(args.target)
    ws.require_workspace()
    config = load_team_config(ws)
    return {"ok": True, "mode": "team", "provider": config["provider"], "repo": config["repo"],
            "branch": config["branch"], "enforcement": config["enforcement"],
            "hint": "Nur-Lesen: sync mit Sperre, danach collab_query.py auf dem Ziel"}


def do_read_run(args):
    runs = runs_dir(args.runtime)
    state = load_run_state(runs, args.run_id)
    out = {"ok": True, "run_id": state["run_id"], "status": state["status"],
           "actor": state["actor"], "base_revision": state["base_revision"],
           "branch": state["branch"], "draft_branch": state.get("draft_branch"), "pr": state.get("pr")}
    for key in ("preview_file", "approval_file"):
        if state.get(key) and Path(state[key]).is_file():
            out[key] = str(state[key])
    return out


def do_cancel(args):
    runs = runs_dir(args.runtime)
    state = load_run_state(runs, args.run_id)
    if state["actor"] != args.actor:
        C.fail("team_run_actor_mismatch", "Lauf gehört zu einem anderen Akteur")
    if state["status"] == "submitted":
        draft = state.get("draft_branch")
        if draft:
            if state["provider"] == "github":
                gh(["pr", "close", str(state["pr"]), "--repo", state["repo"]], check=False)
                gh(["repo", "delete-branch", draft, "--repo", state["repo"]], check=False)
            else:
                run_git(["branch", "-q", "-D", draft], Path(state["repo"]), check=False)
    state["status"] = "cancelled"
    state["cancelled_at"] = now_iso()
    save_run_state(runs, state)
    return {"ok": True, "run_id": state["run_id"], "cancelled": True}


def do_supersede(args):
    runs = runs_dir(args.runtime)
    state = load_run_state(runs, args.run_id)
    if state["actor"] != args.actor:
        C.fail("team_run_actor_mismatch", "Lauf gehört zu einem anderen Akteur")
    if state["status"] in ("published", "cancelled"):
        C.fail("team_run_finished", "Lauf ist bereits beendet")
    ws = C.Workspace(args.target)
    config = load_team_config(ws)
    new_base = repo_head_sha(config, config["provider"])
    old_base = state["base_revision"]
    staging = Path(state["staging"])
    if state["status"] == "submitted" and state.get("draft_branch"):
        if config["provider"] == "local":
            run_git(["branch", "-q", "-D", state["draft_branch"]], Path(config["repo"]), check=False)
        else:
            gh(["repo", "delete-branch", state["draft_branch"], "--repo", config["repo"]], check=False)
    if staging.is_dir():
        run_git(["fetch", "-q", "origin"], staging, check=False)
        run_git(["checkout", "-q", "-B", config["branch"], f"origin/{config['branch']}"], staging)
        run_git(["reset", "-q", "--hard", f"origin/{config['branch']}"], staging)
    state["base_revision"] = new_base
    state["status"] = "started"
    state["superseded_from"] = old_base
    state["superseded_at"] = now_iso()
    state.pop("preview_file", None)
    state.pop("approval_file", None)
    state.pop("draft_branch", None)
    state.pop("pr", None)
    state.pop("pr_body", None)
    save_run_state(runs, state)
    return {"ok": True, "run_id": state["run_id"], "superseded": True,
            "old_base": old_base, "new_base": new_base,
            "hint": "Staging liegt auf dem neuen Stand; Plan die Operation neu erstellen"}


def do_recover(args):
    runs = runs_dir(args.runtime)
    open_runs = []
    if runs.is_dir():
        for path in sorted(runs.glob("*/state.json")):
            state = C.read_json(path)
            if state.get("status") not in ("published", "cancelled"):
                open_runs.append({"run_id": state["run_id"], "status": state["status"],
                                  "actor": state["actor"], "started_at": state.get("started_at")})
    return {"ok": True, "open_runs": open_runs}


def do_cleanup(args):
    runs = runs_dir(args.runtime)
    removed = []
    if runs.is_dir():
        for path in sorted(runs.glob("*/state.json")):
            state = C.read_json(path)
            if state.get("status") not in ("published", "cancelled"):
                if not args.all:
                    C.fail("team_open_runs", "Offene Läufe vorhanden: --all erforderlich")
            removed.append(state["run_id"])
            shutil.rmtree(path.parent)
    return {"ok": True, "removed": removed}


def main():
    parser = argparse.ArgumentParser(prog="team_git.py")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("setup")
    p.add_argument("--target", required=True)
    p.add_argument("--actor", required=True)
    p.add_argument("--provider", required=True, choices=["github", "local"])
    p.add_argument("--repo", required=True)
    p.add_argument("--branch", default="main")
    p.add_argument("--github-id", default=None, help="handle=github-id,handle=github-id")
    p.add_argument("--token-file", required=True)
    p.add_argument("--session-file", default=None)
    p.add_argument("--content-dir", required=True)
    p.add_argument("--output", required=True)
    for name in ("start", "preview", "approve", "submit", "publish", "read-run", "cancel", "supersede", "recover"):
        p = sub.add_parser(name)
        p.add_argument("--runtime", required=True)
        if name not in ("recover", "cleanup", "start"):
            p.add_argument("--run-id", required=True)
        if name == "start":
            p.add_argument("--target", required=True)
            p.add_argument("--actor", required=True)
        if name in ("preview", "approve", "submit", "publish", "cancel", "supersede"):
            p.add_argument("--actor", required=True)
        if name in ("preview", "submit", "publish", "supersede"):
            p.add_argument("--target", required=True)
        if name in ("approve",):
            p.add_argument("--preview-file", required=True)
        if name in ("submit",):
            p.add_argument("--preview-file", required=True)
            p.add_argument("--approval-file", required=True)
            p.add_argument("--session-file", default=None)
        if name in ("publish",):
            p.add_argument("--session-file", default=None)
    p = sub.add_parser("apply")
    p.add_argument("--target", required=True)
    p.add_argument("--plan-file", required=True)
    p.add_argument("--expect-plan-sha256", required=True)
    p.add_argument("--token-file", required=True)
    p.add_argument("--session-file", default=None)
    p = sub.add_parser("sync")
    p.add_argument("--target", required=True)
    p.add_argument("--token-file", required=True)
    p.add_argument("--runtime", required=True)
    p = sub.add_parser("read")
    p.add_argument("--target", required=True)
    p = sub.add_parser("seed")
    p.add_argument("--target", required=True)
    p.add_argument("--repo", required=True)
    p.add_argument("--branch", default="main")
    p.add_argument("--runtime", required=True)
    p = sub.add_parser("cleanup")
    p.add_argument("--runtime", required=True)
    p.add_argument("--all", action="store_true")
    args = parser.parse_args()
    if args.command == "setup":
        return C.run_main(lambda: do_setup(args))
    if args.command == "apply":
        return C.run_main(lambda: do_apply(args))
    if args.command == "seed":
        return C.run_main(lambda: do_seed(args))
    if args.command == "start":
        return C.run_main(lambda: do_start(args))
    if args.command == "preview":
        return C.run_main(lambda: do_preview(args))
    if args.command == "approve":
        return C.run_main(lambda: do_approve(args))
    if args.command == "submit":
        return C.run_main(lambda: do_submit(args))
    if args.command == "publish":
        return C.run_main(lambda: do_publish(args))
    if args.command == "sync":
        return C.run_main(lambda: do_sync(args))
    if args.command == "read":
        return C.run_main(lambda: do_read(args))
    if args.command == "read-run":
        return C.run_main(lambda: do_read_run(args))
    if args.command == "cancel":
        return C.run_main(lambda: do_cancel(args))
    if args.command == "supersede":
        return C.run_main(lambda: do_supersede(args))
    if args.command == "recover":
        return C.run_main(lambda: do_recover(args))
    return C.run_main(lambda: do_cleanup(args))


if __name__ == "__main__":
    sys.exit(main())
