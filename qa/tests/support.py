#!/usr/bin/env python3
"""Shared helpers for CollabMD regression suites (offline, synthetic data)."""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SCRIPTS = ROOT / "collabmd" / "scripts"
TEST_WIKIS = ROOT / "qa" / "test-wikis"
TEST_RT = ROOT / "qa" / "test-runtimes"


def run(script, *args):
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    result = subprocess.run(
        [sys.executable, str(SCRIPTS / script), *[str(a) for a in args]],
        capture_output=True, text=True, env=env,
    )
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError:
        data = {"raw": result.stdout, "stderr": result.stderr}
    return result.returncode, data


def fresh(name):
    wiki = TEST_WIKIS / name
    rt = TEST_RT / name
    shutil.rmtree(wiki, ignore_errors=True)
    shutil.rmtree(rt, ignore_errors=True)
    (rt / "content").mkdir(parents=True)
    (rt / "soul.md").write_text("Zweck: Testraum\nTon: sachlich\n", encoding="utf-8")
    (rt / "pp.txt").write_text("test-passwort-123\n", encoding="utf-8")
    code, out = run("wiki_lock.py", "acquire", "--target", wiki, "--owner", "test",
                    "--operation", "init", "--token-file", rt / "tok.json")
    assert code == 0 and out.get("acquired"), out
    code, out = run("collab_init.py", "plan", "--target", wiki, "--name", "Testraum",
                    "--purpose", "Zweck der Tests", "--language", "de", "--language-label", "Deutsch",
                    "--soul-file", rt / "soul.md", "--owner-handle", "alice",
                    "--passphrase-file", rt / "pp.txt", "--content-dir", rt / "content",
                    "--output", rt / "plan.json")
    assert code == 0 and out.get("ok"), out
    plan = json.loads((rt / "plan.json").read_text(encoding="utf-8"))
    code, out = run("collab_init.py", "apply", "--target", wiki, "--plan-file", rt / "plan.json",
                    "--expect-plan-sha256", plan["plan_sha256"], "--token-file", rt / "tok.json")
    assert code == 0 and out.get("applied"), out
    return wiki, rt


def session(rt, wiki, handle="alice"):
    path = rt / f"sess-{handle}.json"
    code, out = run("collab_auth.py", "session", "--target", wiki, "--handle", handle,
                    "--passphrase-file", rt / "pp.txt", "--session-file", path)
    assert code == 0 and out.get("ok"), out
    return path


def plan_apply(wiki, rt, script, plan_args, token, session_file=None, actor=None, handle=None):
    code, out = run(script, "plan", *plan_args)
    assert code == 0 and out.get("ok"), (script, plan_args, out)
    plan = json.loads((Path(str(plan_args[-1])).parent / Path(str(plan_args[-1])).name).read_text(encoding="utf-8"))
    args = ["apply", "--target", wiki, "--plan-file", plan_args[-1],
            "--expect-plan-sha256", plan["plan_sha256"], "--token-file", token]
    if session_file:
        args += ["--session-file", session_file]
    if script == "collab_auth.py" and handle:
        args += ["--handle", handle]
    if script == "collab_members.py" and handle:
        args += ["--handle", handle]
    code, out = run(script, *args)
    return code, out


def post_plan(wiki, rt, op, channel, actor, body, token, sess, extra=()):
    body_file = rt / f"body-{op}-{int(__import__('time').time()*1000)}.txt"
    body_file.write_text(body, encoding="utf-8")
    out = rt / f"plan-{op}-{body_file.name}.json"
    args = ["plan", "--op", op, "--target", wiki, "--channel", channel, "--body-file", body_file,
            "--actor", actor, "--content-dir", rt / "content", "--output", out, *extra]
    code, plan_result = run("collab_posts.py", *args)
    assert code == 0 and plan_result.get("ok"), (op, plan_result)
    code, data = run("collab_posts.py", "apply", "--target", wiki, "--plan-file", out,
                     "--expect-plan-sha256", plan_result["plan_sha256"], "--token-file", token,
                     "--session-file", sess)
    return code, data, plan_result
