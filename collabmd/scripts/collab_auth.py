#!/usr/bin/env python3
"""Manage members and passphrase hashes (hashes only, never plaintext)."""
import argparse
import json
import sys
from pathlib import Path

import collabmd_common as C


def load_members(ws):
    return ws.members_doc()


def members_file_text(doc):
    return json.dumps(doc, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def plan_user_change(args, build):
    ws = C.Workspace(args.target)
    ws.require_workspace()
    members = load_members(ws)
    actor = args.actor
    action = args.action
    ctx = {"self": True} if args.handle == actor else {}
    C.require_permission(members, actor, action, ctx)
    preconditions = {"schema/members.json": C.sha256_file(ws.schema / "members.json")}
    ops = []
    events = []
    destructive = False
    new_doc = build(members, args)
    content_dir = Path(args.content_dir)
    content_dir.mkdir(parents=True, exist_ok=True)
    content_path = content_dir / "members.json"
    C.atomic_write(content_path, members_file_text(new_doc))
    ops.append(C.content_op("update", "schema/members.json", str(content_path)))
    handle = args.handle
    if action == "auth.create-user":
        if handle in members.get("members", {}):
            C.fail("user_exists", f"Handle existiert bereits: {handle}")
        events.append(f"member.created handle={handle} role={args.role}")
    elif action == "auth.change-passphrase-self":
        events.append(f"member.passphrase-changed handle={handle}")
    elif action == "auth.reset-passphrase":
        if handle not in members.get("members", {}):
            C.fail("user_missing", f"Handle unbekannt: {handle}")
        events.append(f"member.passphrase-reset handle={handle}")
        destructive = True
    elif action in ("auth.disable-user", "auth.enable-user"):
        if handle not in members.get("members", {}):
            C.fail("user_missing", f"Handle unbekannt: {handle}")
        events.append(f"member.{'disabled' if action.endswith('disable-user') else 'enabled'} handle={handle}")
        destructive = True
    plan = C.make_plan(action, actor, preconditions, ops, events, destructive)
    C.write_json(args.output, plan)
    return {
        "ok": True,
        "plan_file": str(args.output),
        "plan_sha256": plan["plan_sha256"],
        "op": plan["op"],
        "action": action,
        "handle": handle,
        "destructive": destructive,
    }


def build_create(members, args):
    C.validate_handle(args.handle)
    if args.role not in C.ROLES:
        C.fail("bad_role", f"Rolle ungültig: {args.role}")
    if not args.passphrase_file:
        C.fail("missing_passphrase", "Passphrase-Datei fehlt")
    passphrase = Path(args.passphrase_file).read_text(encoding="utf-8").rstrip("\n")
    if len(passphrase) < 8:
        C.fail("passphrase_too_short", "Passphrase muss mindestens 8 Zeichen haben")
    doc = json.loads(members_file_text(members))
    entry = {
        "name": args.name or args.handle,
        "role": args.role,
        "github_id": None,
        "created": C.now_iso(),
        "disabled": False,
        "auth": C.hash_passphrase(passphrase),
    }
    doc["members"][args.handle] = entry
    return doc


def build_change(members, args):
    handle = args.handle
    entry = members.get("members", {}).get(handle)
    if not entry:
        C.fail("user_missing", f"Handle unbekannt: {handle}")
    passphrase = Path(args.passphrase_file).read_text(encoding="utf-8").rstrip("\n")
    if len(passphrase) < 8:
        C.fail("passphrase_too_short", "Passphrase muss mindestens 8 Zeichen haben")
    doc = json.loads(members_file_text(members))
    doc["members"][handle]["auth"] = C.hash_passphrase(passphrase)
    return doc


def build_reset(members, args):
    handle = args.handle
    if handle not in members.get("members", {}):
        C.fail("user_missing", f"Handle unbekannt: {handle}")
    passphrase = Path(args.passphrase_file).read_text(encoding="utf-8").rstrip("\n")
    if len(passphrase) < 8:
        C.fail("passphrase_too_short", "Passphrase muss mindestens 8 Zeichen haben")
    doc = json.loads(members_file_text(members))
    doc["members"][handle]["auth"] = C.hash_passphrase(passphrase)
    return doc


def build_disable(members, args, enable):
    handle = args.handle
    if handle not in members.get("members", {}):
        C.fail("user_missing", f"Handle unbekannt: {handle}")
    doc = json.loads(members_file_text(members))
    doc["members"][handle]["disabled"] = not enable
    return doc


BUILDERS = {
    "auth.create-user": build_create,
    "auth.change-passphrase-self": build_change,
    "auth.reset-passphrase": build_reset,
    "auth.disable-user": lambda m, a: build_disable(m, a, False),
    "auth.enable-user": lambda m, a: build_disable(m, a, True),
}


def do_verify(args):
    ws = C.Workspace(args.target)
    ws.require_workspace()
    members = ws.members_doc()
    handle = C.validate_handle(args.handle)
    entry = members.get("members", {}).get(handle)
    if not entry or entry.get("disabled"):
        C.fail("permission_denied", f"{handle} hat keine aktive Mitgliedschaft")
    record = entry.get("auth")
    if not record:
        C.fail("no_auth", f"{handle} hat keine Passphrase gesetzt")
    passphrase = Path(args.passphrase_file).read_text(encoding="utf-8").rstrip("\n")
    if not C.verify_passphrase(passphrase, record):
        C.fail("auth_failed", "Passphrase passt nicht")
    return {"ok": True, "handle": handle}


def do_session(args):
    ws = C.Workspace(args.target)
    ws.require_workspace()
    members = ws.members_doc()
    handle = C.validate_handle(args.handle)
    return C.create_auth_session(members, handle, args.passphrase_file, args.session_file)


def do_apply(args):
    ws = C.Workspace(args.target)
    plan = C.read_json(args.plan_file)
    ctx = {"self": True} if plan.get("actor") == args.handle else {}
    return C.apply_plan(ws, plan, args.expect_plan_sha256, args.token_file, args.session_file, ctx)


def main():
    parser = argparse.ArgumentParser(prog="collab_auth.py")
    sub = parser.add_subparsers(dest="command", required=True)
    for name in ("create-user", "change-passphrase", "reset-passphrase", "disable-user", "enable-user"):
        p = sub.add_parser(name)
        p.add_argument("--target", required=True)
        p.add_argument("--handle", required=True)
        p.add_argument("--passphrase-file", default=None)
        p.add_argument("--name", default=None)
        p.add_argument("--role", default=None)
        p.add_argument("--actor", required=True)
        p.add_argument("--token-file", required=True)
        p.add_argument("--session-file", default=None)
        p.add_argument("--content-dir", required=True)
        p.add_argument("--output", required=True)
    p = sub.add_parser("verify")
    p.add_argument("--target", required=True)
    p.add_argument("--handle", required=True)
    p.add_argument("--passphrase-file", required=True)
    p = sub.add_parser("session")
    p.add_argument("--target", required=True)
    p.add_argument("--handle", required=True)
    p.add_argument("--passphrase-file", required=True)
    p.add_argument("--session-file", required=True)
    p = sub.add_parser("apply")
    p.add_argument("--target", required=True)
    p.add_argument("--handle", required=True)
    p.add_argument("--plan-file", required=True)
    p.add_argument("--expect-plan-sha256", required=True)
    p.add_argument("--token-file", required=True)
    p.add_argument("--session-file", default=None)
    args = parser.parse_args()

    action_map = {
        "create-user": "auth.create-user",
        "change-passphrase": "auth.change-passphrase-self",
        "reset-passphrase": "auth.reset-passphrase",
        "disable-user": "auth.disable-user",
        "enable-user": "auth.enable-user",
    }
    if args.command in action_map:
        args.action = action_map[args.command]
        return C.run_main(lambda: plan_user_change(args, BUILDERS[args.action]))
    if args.command in ("verify", "session"):
        return C.run_main(lambda: do_verify(args) if args.command == "verify" else do_session(args))
    return C.run_main(lambda: do_apply(args))


if __name__ == "__main__":
    sys.exit(main())
