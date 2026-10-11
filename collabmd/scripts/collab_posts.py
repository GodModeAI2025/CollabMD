#!/usr/bin/env python3
"""Create and maintain posts, threads, reactions, pins, attachments (plan/apply)."""
import argparse
import json
import sys
import uuid
from pathlib import Path

import collabmd_common as C
import secret_screen


def post_text(meta, body):
    return C.render_frontmatter(meta, C.POST_FIELD_ORDER) + body


def meta_key_order(meta):
    ordered = [k for k in C.POST_FIELD_ORDER if k in meta]
    ordered += [k for k in meta if k not in C.POST_FIELD_ORDER]
    return ordered


def new_post_meta(channel, author, created, thread_root=None):
    return {
        "type": "post",
        "id": uuid.uuid4().hex,
        "channel": channel,
        "author": author,
        "created": created,
        "edited": False,
        "edited_at": None,
        "edits": 0,
        "deleted": False,
        "deleted_at": None,
        "pinned": False,
        "thread_root": thread_root,
        "reactions": {},
        "files": [],
    }


def read_body(args):
    body = Path(args.body_file).read_text(encoding="utf-8")
    if not body.strip():
        C.fail("empty_body", "Post-Text ist leer")
    hits = secret_screen.scan(body)
    if hits:
        C.fail("secrets_found", f"Post-Text enthält {len(hits)} mögliche Zugangsdaten")
    if not body.endswith("\n"):
        body += "\n"
    return body


def load_channel(ws, channel_id):
    channels = ws.channels_doc()["channels"]
    channel = channels.get(channel_id)
    if channel is None:
        C.fail("channel_missing", f"Kanal unbekannt: {channel_id}")
    return channel


def require_channel_member(ws, channel_id, actor, allow_archived=False):
    channel = load_channel(ws, channel_id)
    if channel.get("archived") and not allow_archived:
        C.fail("channel_archived", f"Kanal ist archiviert: {channel_id}")
    if actor not in channel.get("members", []):
        C.fail("not_member", f"{actor} ist nicht Mitglied von {channel_id}")
    return channel


def load_post(ws, channel_id, post_id):
    C.validate_post_id(post_id)
    relpath = f"posts/{channel_id}/{post_id}.md"
    if not (ws.root / relpath).is_file():
        C.fail("post_missing", f"Post unbekannt: {post_id} in {channel_id}")
    meta, body = ws.load_post(relpath)
    if meta.get("channel") != channel_id:
        C.fail("post_wrong_channel", "Post liegt in anderem Kanal")
    return relpath, meta, body




def resolve_channel(ws, args, actor):
    target = args.channel
    if target.startswith("dm:"):
        other = C.validate_handle(target[3:])
        if other == actor:
            C.fail("bad_dm", "Direkt-Kanal mit sich selbst ist ungültig")
        handles = sorted([actor, other])
        channel_id = "dm-" + "-".join(handles)
        channels = ws.channels_doc()["channels"]
        if channel_id in channels:
            channel = channels[channel_id]
        else:
            channel = {
                "name": channel_id,
                "title": "Direkt: " + " / ".join(handles),
                "type": "direct",
                "purpose": "Direktnachrichten",
                "members": handles,
                "created_by": actor,
                "created": C.now_iso(),
                "archived": False,
                "archived_at": None,
            }
            return channel_id, channel, True
        return channel_id, channel, False
    return target, load_channel(ws, target), False


def collect_files(ws, args):
    digests = []
    for name in (args.files or "").split(","):
        name = name.strip()
        if not name:
            continue
        source = Path(name)
        if not source.is_file():
            C.fail("file_missing", f"Anhang fehlt: {name}")
        data = source.read_bytes()
        digest = C.sha256_bytes(data)
        if not (ws.files_dir / digest).is_file():
            digests.append((digest, data))
    return digests


def plan_post_create(args, thread_root=None):
    ws = C.Workspace(args.target)
    ws.require_workspace()
    actor = args.actor
    body = read_body(args)
    channel_id, channel, new_channel = resolve_channel(ws, args, actor)
    if new_channel and channel.get("type") == "direct":
        pass
    if not new_channel:
        require_channel_member(ws, channel_id, actor)
    attachments = collect_files(ws, args)
    created = C.now_iso()
    meta = new_post_meta(channel_id, actor, created, thread_root)
    meta["files"] = [d for d, _ in attachments]
    preconditions = {}
    ops = []
    events = []
    channels_doc = ws.channels_doc()
    if new_channel:
        preconditions["schema/channels.json"] = C.sha256_file(ws.schema / "channels.json")
        doc = json.loads(json.dumps(channels_doc, ensure_ascii=False))
        doc["channels"][channel_id] = channel
        content_dir = Path(args.content_dir)
        content_dir.mkdir(parents=True, exist_ok=True)
        path = content_dir / "channels.json"
        C.atomic_write(path, json.dumps(doc, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
        ops.append(C.content_op("update", "schema/channels.json", str(path)))
        events.append(f"channel.created id={channel_id} type=direct")
    else:
        preconditions["schema/channels.json"] = C.file_hash_or_none(ws.schema / "channels.json")
    for digest, data in attachments:
        preconditions[f"posts/_files/{digest}"] = None
        content_dir = Path(args.content_dir)
        file_area = content_dir / "_files"
        file_area.mkdir(parents=True, exist_ok=True)
        target = file_area / digest
        target.write_bytes(data)
        ops.append({"action": "create", "path": f"posts/_files/{digest}", "content_sha256": digest, "binary": True, "content_file": str(target)})
    post_path = f"posts/{channel_id}/{meta['id']}.md"
    preconditions[post_path] = None
    content_dir = Path(args.content_dir)
    content_dir.mkdir(parents=True, exist_ok=True)
    pfile = content_dir / f"{meta['id']}.md"
    C.atomic_write(pfile, post_text(meta, body))
    ops.append(C.content_op("create", post_path, str(pfile)))
    events.append(f"post.created channel={channel_id} id={meta['id']}")
    plan = C.make_plan("posts.create", actor, preconditions, ops, events)
    C.write_json(args.output, plan)
    return {
        "ok": True,
        "plan_file": str(args.output),
        "plan_sha256": plan["plan_sha256"],
        "op": plan["op"],
        "post_id": meta["id"],
        "channel": channel_id,
        "files": len(attachments),
        "thread_root": thread_root,
        "destructive": False,
    }


EVENT_VERBS = {
    "posts.edit": "post.edited",
    "posts.delete": "post.deleted",
    "posts.pin": "post.pinned",
    "posts.unpin": "post.unpinned",
    "posts.react": "post.reacted",
}


def plan_post_update(args, mutate, action, destructive=False, allow_archived=False):
    ws = C.Workspace(args.target)
    ws.require_workspace()
    actor = args.actor
    require_channel_member(ws, args.channel, actor, allow_archived=allow_archived)
    relpath, meta, body = load_post(ws, args.channel, args.post)
    if meta.get("deleted") and action not in ("posts.delete",):
        C.fail("post_deleted", "Post ist gelöscht")
    if action in ("posts.edit", "posts.delete", "posts.pin", "posts.unpin") and meta.get("author") != actor:
        C.require_permission(ws.members_doc(), actor, action + "-other")
    preconditions = {relpath: C.sha256_file(ws.root / relpath)}
    if action == "posts.edit":
        if not (hasattr(args, "body_file") and args.body_file):
            C.fail("missing_args", "edit braucht --body-file")
        new_body = read_body(args)
    elif action == "posts.delete":
        new_body = C.DELETION_MARKER + "\n"
    else:
        new_body = body
    new_meta = mutate(dict(meta), args, actor, new_body, relpath)
    if action in ("posts.edit", "posts.delete", "posts.pin", "posts.unpin"):
        plan_action = action + ("-self" if meta.get("author") == actor else "-other")
    else:
        plan_action = action
    content_dir = Path(args.content_dir)
    content_dir.mkdir(parents=True, exist_ok=True)
    pfile = content_dir / f"{meta['id']}.md"
    C.atomic_write(pfile, post_text(new_meta, new_body))
    ops = [C.content_op("update", relpath, str(pfile))]
    verb = EVENT_VERBS.get(action, action)
    events = [f"{verb} channel={args.channel} id={meta['id']}"]
    plan = C.make_plan(plan_action, actor, preconditions, ops, events, destructive)
    C.write_json(args.output, plan)
    return {
        "ok": True,
        "plan_file": str(args.output),
        "plan_sha256": plan["plan_sha256"],
        "op": plan["op"],
        "post_id": meta["id"],
        "channel": args.channel,
        "action": action,
        "destructive": destructive,
    }


def mutate_edit(meta, args, actor, body, relpath):
    meta["edited"] = True
    meta["edited_at"] = C.now_iso()
    meta["edits"] = int(meta.get("edits", 0)) + 1
    return meta


def mutate_delete(meta, args, actor, body, relpath):
    meta["deleted"] = True
    meta["deleted_at"] = C.now_iso()
    meta["pinned"] = False
    return meta


def mutate_pin(meta, args, actor, body, relpath, pin=True):
    meta["pinned"] = pin
    return meta


def mutate_react(meta, args, actor, body, relpath, remove=False):
    emoji = args.emoji
    if not isinstance(emoji, str) or not emoji.strip():
        C.fail("bad_emoji", "Emoji fehlt")
    reactions = meta.get("reactions", {})
    if not isinstance(reactions, dict):
        C.fail("bad_reactions", "Reaktionen ungültig")
    handles = reactions.get(emoji, [])
    if not isinstance(handles, list):
        handles = []
    if remove:
        handles = [h for h in handles if h != actor]
    elif actor not in handles:
        handles = handles + [actor]
    if handles:
        reactions[emoji] = handles
    else:
        reactions.pop(emoji, None)
    meta["reactions"] = reactions
    return meta


def do_cursor_set(args):
    ws = C.Workspace(args.target)
    ws.require_workspace()
    handle = C.validate_handle(args.handle)
    if handle != args.actor:
        C.fail("not_self", "Cursor kann nur für den eigenen Handle gesetzt werden")
    members = ws.members_doc()
    C.require_permission(members, handle, "cursor.set")
    cursor = args.cursor
    if not C.parse_iso(cursor):
        C.fail("bad_cursor", "Cursor-Zeitstempel ungültig (ISO-UTC erwartet)")
    channel_id = C.validate_channel_id(args.channel)
    if channel_id not in ws.channels_doc()["channels"]:
        C.fail("channel_missing", f"Kanal unbekannt: {channel_id}")
    relpath = f"meta/cursors/{handle}.json"
    path = ws.safe_rel(relpath)
    if path.is_file():
        doc = C.read_json(path)
    else:
        doc = {"handle": handle, "channels": {}}
    doc["channels"][channel_id] = {"cursor": cursor, "updated": C.now_iso()}
    C.verify_claim(ws, args.token_file)
    C.atomic_write(path, json.dumps(doc, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    return {
        "ok": True,
        "handle": handle,
        "channel": channel_id,
        "cursor": cursor,
        "path": relpath,
    }


def do_apply(args):
    ws = C.Workspace(args.target)
    plan = C.read_json(args.plan_file)
    return C.apply_plan(ws, plan, args.expect_plan_sha256, args.token_file, args.session_file)


def main():
    parser = argparse.ArgumentParser(prog="collab_posts.py")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("plan")
    p.add_argument("--op", required=True, choices=["create", "reply", "edit", "delete", "pin", "unpin", "react", "unreact"])
    p.add_argument("--target", required=True)
    p.add_argument("--channel", default=None)
    p.add_argument("--post", default=None)
    p.add_argument("--body-file", default=None)
    p.add_argument("--files", default=None)
    p.add_argument("--emoji", default=None)
    p.add_argument("--actor", required=True)
    p.add_argument("--content-dir", required=True)
    p.add_argument("--output", required=True)
    p = sub.add_parser("apply")
    p.add_argument("--target", required=True)
    p.add_argument("--plan-file", required=True)
    p.add_argument("--expect-plan-sha256", required=True)
    p.add_argument("--token-file", required=True)
    p.add_argument("--session-file", default=None)
    p = sub.add_parser("cursor-set")
    p.add_argument("--target", required=True)
    p.add_argument("--handle", required=True)
    p.add_argument("--actor", required=True)
    p.add_argument("--channel", required=True)
    p.add_argument("--cursor", required=True)
    p.add_argument("--token-file", required=True)
    args = parser.parse_args()

    def run_plan():
        if args.op == "create":
            if not args.channel or not args.body_file:
                C.fail("missing_args", "create braucht --channel und --body-file")
            return plan_post_create(args)
        if args.op == "reply":
            if not args.channel or not args.post or not args.body_file:
                C.fail("missing_args", "reply braucht --channel, --post und --body-file")
            root_rel, root_meta, _ = load_post(ws_ref(), args.channel, args.post)
            if root_meta.get("thread_root") is not None:
                C.fail("bad_thread_root", "Nur auf Root-Posts kann geantwortet werden")
            return plan_post_create(args, thread_root=args.post)
        if args.op in ("edit", "delete", "pin", "unpin", "react", "unreact"):
            if not args.channel or not args.post:
                C.fail("missing_args", f"{args.op} braucht --channel und --post")
            if args.op in ("react", "unreact") and not args.emoji:
                C.fail("missing_args", f"{args.op} braucht --emoji")
            action = f"posts.{args.op}"
            if args.op == "edit":
                if not args.body_file:
                    C.fail("missing_args", "edit braucht --body-file")
                return plan_post_update(args, mutate_edit, action)
            if args.op == "delete":
                return plan_post_update(args, mutate_delete, action, destructive=True)
            if args.op == "pin":
                return plan_post_update(args, lambda m, a, x, b, r: mutate_pin(m, a, x, b, r, True), action)
            if args.op == "unpin":
                return plan_post_update(args, lambda m, a, x, b, r: mutate_pin(m, a, x, b, r, False), action)
            remove = args.op == "unreact"
            return plan_post_update(args, lambda m, a, x, b, r: mutate_react(m, a, x, b, r, remove), action, allow_archived=True)
        C.fail("bad_op", f"unbekannte Operation: {args.op}")

    def ws_ref():
        return C.Workspace(args.target)

    if args.command == "plan":
        return C.run_main(run_plan)
    if args.command == "apply":
        return C.run_main(lambda: do_apply(args))
    return C.run_main(lambda: do_cursor_set(args))


if __name__ == "__main__":
    sys.exit(main())
