#!/usr/bin/env python3
"""Manage channels (plan/apply)."""
import argparse
import json
import sys
from pathlib import Path

import collabmd_common as C


def load_channels(ws):
    return ws.channels_doc()


def channels_text(doc):
    return json.dumps(doc, indent=2, sort_keys=True, ensure_ascii=False) + "\n"


def plan_channel_change(args, build):
    ws = C.Workspace(args.target)
    ws.require_workspace()
    channels = load_channels(ws)
    members = ws.members_doc()
    actor = args.actor
    action = args.action
    if action in ("channels.rename", "channels.archive", "channels.unarchive"):
        if args.id not in channels.get("channels", {}):
            C.fail("channel_missing", f"Kanal unbekannt: {args.id}")
    ctx = None
    C.require_permission(members, actor, action, ctx)
    args._members = members
    preconditions = {"schema/channels.json": C.sha256_file(ws.schema / "channels.json")}
    new_doc, events, destructive = build(channels, args)
    content_dir = Path(args.content_dir)
    content_dir.mkdir(parents=True, exist_ok=True)
    content_path = content_dir / "channels.json"
    C.atomic_write(content_path, channels_text(new_doc))
    ops = [C.content_op("update", "schema/channels.json", str(content_path))]
    plan = C.make_plan(action, actor, preconditions, ops, events, destructive)
    C.write_json(args.output, plan)
    return {
        "ok": True,
        "plan_file": str(args.output),
        "plan_sha256": plan["plan_sha256"],
        "op": plan["op"],
        "action": action,
        "destructive": destructive,
    }


def build_create(channels, args):
    channel_id = C.validate_channel_id(args.id)
    if channel_id in channels.get("channels", {}):
        C.fail("channel_exists", f"Kanal existiert bereits: {channel_id}")
    if args.type not in ("public", "private"):
        C.fail("bad_type", "Neue Kanäle sind public oder private")
    members = [C.validate_handle(h) for h in (args.members or "").split(",") if h.strip()]
    doc = json.loads(channels_text(channels))
    doc["channels"][channel_id] = {
        "name": channel_id,
        "title": args.title,
        "type": args.type,
        "purpose": args.purpose or "",
        "members": sorted(set(members)),
        "created_by": args.actor,
        "created": C.now_iso(),
        "archived": False,
        "archived_at": None,
    }
    return doc, [f"channel.created id={channel_id} type={args.type}"], False


def build_rename(channels, args):
    doc = json.loads(channels_text(channels))
    doc["channels"][args.id]["title"] = args.title
    return doc, [f"channel.renamed id={args.id}"], False


def build_archive(channels, args, archive):
    doc = json.loads(channels_text(channels))
    channel = doc["channels"][args.id]
    channel["archived"] = archive
    channel["archived_at"] = C.now_iso() if archive else None
    verb = "archived" if archive else "unarchived"
    return doc, [f"channel.{verb} id={args.id}"], archive


def build_join(channels, args, join):
    doc = json.loads(channels_text(channels))
    channel = doc["channels"][args.id]
    if channel.get("archived"):
        C.fail("channel_archived", f"Kanal ist archiviert: {args.id}")
    if join and channel.get("type") == "private":
        members_doc = getattr(args, "_members", {})
        if not C.role_at_least(C.effective_role(members_doc, args.actor), "maintainer"):
            C.fail("permission_denied", "Private Kanäle werden nur von maintainer/owner betreten")
    handles = set(channel.get("members", []))
    if join:
        if args.actor in handles:
            C.fail("already_member", f"{args.actor} ist bereits Mitglied")
        handles.add(args.actor)
        events = [f"channel.joined id={args.id} by={args.actor}"]
    else:
        if args.actor not in handles:
            C.fail("not_member", f"{args.actor} ist nicht Mitglied")
        handles.discard(args.actor)
        if not handles:
            C.fail("last_member", "Der letzte Mitgliedskanal kann nicht verlassen werden; Kanal archivieren")
        events = [f"channel.left id={args.id} by={args.actor}"]
    channel["members"] = sorted(handles)
    return doc, events, False


BUILDERS = {
    "channels.create": build_create,
    "channels.rename": build_rename,
    "channels.archive": lambda c, a: build_archive(c, a, True),
    "channels.unarchive": lambda c, a: build_archive(c, a, False),
    "channels.join": lambda c, a: build_join(c, a, True),
    "channels.leave": lambda c, a: build_join(c, a, False),
}


def do_apply(args):
    ws = C.Workspace(args.target)
    plan = C.read_json(args.plan_file)
    return C.apply_plan(ws, plan, args.expect_plan_sha256, args.token_file, args.session_file)


def main():
    parser = argparse.ArgumentParser(prog="collab_channels.py")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("plan")
    p.add_argument("--action", required=True, choices=sorted(BUILDERS))
    p.add_argument("--target", required=True)
    p.add_argument("--id", default=None)
    p.add_argument("--title", default=None)
    p.add_argument("--type", default=None)
    p.add_argument("--purpose", default=None)
    p.add_argument("--members", default=None)
    p.add_argument("--actor", required=True)
    p.add_argument("--content-dir", required=True)
    p.add_argument("--output", required=True)
    p = sub.add_parser("apply")
    p.add_argument("--target", required=True)
    p.add_argument("--plan-file", required=True)
    p.add_argument("--expect-plan-sha256", required=True)
    p.add_argument("--token-file", required=True)
    p.add_argument("--session-file", default=None)
    args = parser.parse_args()

    def run_plan():
        if args.action == "channels.create" and not args.title:
            C.fail("missing_title", "Titel fehlt")
        if args.action in ("channels.rename",) and not args.title:
            C.fail("missing_title", "Titel fehlt")
        if args.action in ("channels.rename", "channels.archive", "channels.unarchive", "channels.join", "channels.leave") and not args.id:
            C.fail("missing_id", "Kanal-ID fehlt")
        if args.action == "channels.create" and not args.id:
            C.fail("missing_id", "Kanal-ID fehlt")
        return plan_channel_change(args, BUILDERS[args.action])

    if args.command == "plan":
        return C.run_main(run_plan)
    return C.run_main(lambda: do_apply(args))


if __name__ == "__main__":
    sys.exit(main())
