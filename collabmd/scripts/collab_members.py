#!/usr/bin/env python3
"""Manage member profiles (plan/apply)."""
import argparse
import json
import sys
from pathlib import Path

import collabmd_common as C


def do_plan(args):
    ws = C.Workspace(args.target)
    ws.require_workspace()
    members = ws.members_doc()
    handle = C.validate_handle(args.handle)
    if handle not in members.get("members", {}):
        C.fail("user_missing", f"Handle unbekannt: {handle}")
    ctx = {"self": True} if handle == args.actor else {}
    C.require_permission(members, args.actor, "members.update-profile", ctx)
    preconditions = {"schema/members.json": C.sha256_file(ws.schema / "members.json")}
    doc = json.loads(json.dumps(members, ensure_ascii=False))
    doc["members"][handle]["name"] = args.name
    content_dir = Path(args.content_dir)
    content_dir.mkdir(parents=True, exist_ok=True)
    content_path = content_dir / "members.json"
    C.atomic_write(content_path, json.dumps(doc, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    ops = [C.content_op("update", "schema/members.json", str(content_path))]
    plan = C.make_plan(
        "members.update-profile", args.actor, preconditions, ops,
        [f"member.profile-updated handle={handle}"],
    )
    C.write_json(args.output, plan)
    return {
        "ok": True,
        "plan_file": str(args.output),
        "plan_sha256": plan["plan_sha256"],
        "op": plan["op"],
        "action": "members.update-profile",
        "handle": handle,
        "name": args.name,
        "destructive": False,
    }


def do_apply(args):
    ws = C.Workspace(args.target)
    plan = C.read_json(args.plan_file)
    ctx = {"self": True} if plan.get("actor") == args.handle else {}
    return C.apply_plan(ws, plan, args.expect_plan_sha256, args.token_file, args.session_file, ctx)


def main():
    parser = argparse.ArgumentParser(prog="collab_members.py")
    sub = parser.add_subparsers(dest="command", required=True)
    for name, fn in (("plan", do_plan), ("apply", do_apply)):
        p = sub.add_parser(name)
        if name == "plan":
            p.add_argument("--target", required=True)
            p.add_argument("--handle", required=True)
            p.add_argument("--name", required=True)
            p.add_argument("--actor", required=True)
            p.add_argument("--content-dir", required=True)
            p.add_argument("--output", required=True)
        else:
            p.add_argument("--target", required=True)
            p.add_argument("--handle", required=True)
            p.add_argument("--plan-file", required=True)
            p.add_argument("--expect-plan-sha256", required=True)
            p.add_argument("--token-file", required=True)
            p.add_argument("--session-file", default=None)
    args = parser.parse_args()
    return C.run_main(lambda: (do_plan(args) if args.command == "plan" else do_apply(args)))


if __name__ == "__main__":
    sys.exit(main())
