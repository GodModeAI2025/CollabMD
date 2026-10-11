#!/usr/bin/env python3
"""Read-only queries on a CollabMD workspace (no lock, no session)."""
import argparse
import json
import sys

import collabmd_common as C


def revision(ws):
    out = {"workspace_version": None, "release_id": None}
    version_path = ws.meta / "version"
    if version_path.is_file():
        out["workspace_version"] = version_path.read_text(encoding="utf-8").strip()
    manifest_path = ws.meta / "manifest.json"
    if manifest_path.is_file():
        try:
            out["release_id"] = C.read_json(manifest_path).get("release_id")
        except C.CollabError:
            pass
    return out


def post_view(meta, body):
    return {
        "id": meta.get("id"),
        "channel": meta.get("channel"),
        "author": meta.get("author"),
        "created": meta.get("created"),
        "edited": meta.get("edited"),
        "edited_at": meta.get("edited_at"),
        "edits": meta.get("edits"),
        "deleted": meta.get("deleted"),
        "pinned": meta.get("pinned"),
        "thread_root": meta.get("thread_root"),
        "reactions": meta.get("reactions", {}),
        "files": meta.get("files", []),
        "body": body,
    }


def do_workspace(args):
    ws = C.Workspace(args.target)
    ws.require_workspace()
    profile = ws.profile()
    channels = ws.channels_doc()["channels"]
    members = ws.members_doc()["members"]
    posts = ws.list_posts()
    return {
        "ok": True,
        "name": profile.get("name"),
        "purpose": profile.get("purpose"),
        "language": profile.get("language"),
        "write_gate": (profile.get("auth") or {}).get("write_gate", True),
        "channels": len(channels),
        "members": len(members),
        "posts": len(posts),
        **revision(ws),
    }


def do_channels(args):
    ws = C.Workspace(args.target)
    ws.require_workspace()
    members = ws.members_doc()["members"]
    out = []
    for channel_id, channel in sorted(ws.channels_doc()["channels"].items()):
        if args.member and args.member not in channel.get("members", []):
            continue
        last = None
        for relpath, meta, _ in ws.list_posts(channel_id):
            if not meta.get("deleted"):
                last = meta
        out.append({
            "id": channel_id,
            "title": channel.get("title"),
            "type": channel.get("type"),
            "purpose": channel.get("purpose"),
            "members": channel.get("members", []),
            "archived": channel.get("archived", False),
            "last_post": {
                "id": last.get("id"),
                "author": last.get("author"),
                "created": last.get("created"),
            } if last else None,
        })
    return {"ok": True, "channels": out, **revision(ws)}


def do_channel(args):
    ws = C.Workspace(args.target)
    ws.require_workspace()
    if args.id not in ws.channels_doc()["channels"]:
        C.fail("channel_missing", f"Kanal unbekannt: {args.id}")
    after = C.parse_iso(args.after) if args.after else None
    posts = []
    for relpath, meta, body in ws.list_posts(args.id):
        if meta.get("deleted") and not args.include_deleted:
            continue
        created = C.parse_iso(meta.get("created"))
        if after and created and created <= after:
            continue
        posts.append(post_view(meta, body))
    total = len(posts)
    if args.limit and args.limit > 0:
        posts = posts[-args.limit:]
    cursor = posts[-1]["created"] if posts else None
    return {
        "ok": True,
        "channel": args.id,
        "count": total,
        "posts": posts,
        "newest_cursor": cursor,
        **revision(ws),
    }


def do_thread(args):
    ws = C.Workspace(args.target)
    ws.require_workspace()
    root_rel, root_meta, root_body = None, None, None
    replies = []
    for relpath, meta, body in ws.list_posts(args.channel):
        if meta.get("id") == args.post:
            root_rel, root_meta, root_body = relpath, meta, body
        elif meta.get("thread_root") == args.post:
            replies.append(post_view(meta, body))
    if root_meta is None:
        C.fail("post_missing", f"Post unbekannt: {args.post} in {args.channel}")
    replies.sort(key=lambda p: p["created"] or "")
    return {
        "ok": True,
        "channel": args.channel,
        "root": post_view(root_meta, root_body),
        "replies": replies,
        **revision(ws),
    }


def do_search(args):
    ws = C.Workspace(args.target)
    ws.require_workspace()
    needle = (args.text or "").strip().lower()
    if not needle:
        C.fail("empty_query", "Suchtext fehlt")
    hits = []
    for relpath, meta, body in ws.list_posts(args.channel if args.channel else None):
        if meta.get("deleted"):
            continue
        if needle in body.lower() or needle in json.dumps(meta, ensure_ascii=False).lower():
            hits.append(post_view(meta, body))
    total = len(hits)
    if args.limit and args.limit > 0:
        hits = hits[:args.limit]
    return {"ok": True, "query": args.text, "count": total, "hits": hits, **revision(ws)}


def do_mentions(args):
    ws = C.Workspace(args.target)
    ws.require_workspace()
    handle = C.validate_handle(args.handle)
    after = C.parse_iso(args.after) if args.after else None
    needle = "@" + handle
    hits = []
    for relpath, meta, body in ws.list_posts():
        if meta.get("deleted"):
            continue
        if meta.get("author") == handle:
            continue
        if needle in body:
            created = C.parse_iso(meta.get("created"))
            if after and created and created <= after:
                continue
            hits.append(post_view(meta, body))
    return {"ok": True, "handle": handle, "count": len(hits), "hits": hits, **revision(ws)}


def do_unread(args):
    ws = C.Workspace(args.target)
    ws.require_workspace()
    handle = C.validate_handle(args.handle)
    cursor_path = ws.cursors_dir / f"{handle}.json"
    cursors = C.read_json(cursor_path).get("channels", {}) if cursor_path.is_file() else {}
    out = []
    for channel_id, channel in sorted(ws.channels_doc()["channels"].items()):
        if handle not in channel.get("members", []):
            continue
        cursor = (cursors.get(channel_id) or {}).get("cursor")
        parsed = C.parse_iso(cursor) if cursor else None
        count = 0
        latest = None
        for relpath, meta, _ in ws.list_posts(channel_id):
            if meta.get("deleted"):
                continue
            created = C.parse_iso(meta.get("created"))
            if created and (parsed is None or created > parsed):
                count += 1
                latest = meta.get("created")
        out.append({
            "channel": channel_id,
            "title": channel.get("title"),
            "unread": count,
            "cursor": cursor,
            "latest": latest,
        })
    return {"ok": True, "handle": handle, "channels": out, **revision(ws)}


def do_pins(args):
    ws = C.Workspace(args.target)
    ws.require_workspace()
    if args.channel not in ws.channels_doc()["channels"]:
        C.fail("channel_missing", f"Kanal unbekannt: {args.channel}")
    pins = [post_view(m, b) for _, m, b in ws.list_posts(args.channel) if m.get("pinned") and not m.get("deleted")]
    pins.sort(key=lambda p: p["created"] or "")
    return {"ok": True, "channel": args.channel, "pins": pins, **revision(ws)}


def do_members(args):
    ws = C.Workspace(args.target)
    ws.require_workspace()
    out = []
    for handle, entry in sorted(ws.members_doc()["members"].items()):
        out.append({
            "handle": handle,
            "name": entry.get("name"),
            "role": entry.get("role"),
            "disabled": bool(entry.get("disabled")),
            "github_id": entry.get("github_id"),
            "has_passphrase": bool(entry.get("auth")),
            "created": entry.get("created"),
        })
    return {"ok": True, "members": out, **revision(ws)}


def main():
    parser = argparse.ArgumentParser(prog="collab_query.py")
    sub = parser.add_subparsers(dest="command", required=True)
    handlers = {
        "workspace": (do_workspace, []),
        "channels": (do_channels, ["--member"]),
        "channel": (do_channel, ["--limit", "--after", "--include-deleted"]),
        "thread": (do_thread, []),
        "search": (do_search, ["--limit"]),
        "mentions": (do_mentions, ["--after"]),
        "unread": (do_unread, []),
        "pins": (do_pins, []),
        "members": (do_members, []),
    }
    for name, (_, extra) in handlers.items():
        p = sub.add_parser(name)
        p.add_argument("--target", required=True)
        if name in ("channels",):
            p.add_argument("--member", default=None)
        if name in ("channel", "search", "thread"):
            p.add_argument("--id", default=None)
            p.add_argument("--channel", default=None)
            p.add_argument("--post", default=None)
            p.add_argument("--limit", type=int, default=None)
        if name in ("channel",):
            p.add_argument("--after", default=None)
            p.add_argument("--include-deleted", action="store_true")
        if name in ("search",):
            p.add_argument("--text", default=None)
        if name in ("mentions", "unread"):
            p.add_argument("--handle", default=None)
            if name == "mentions":
                p.add_argument("--after", default=None)
        if name in ("pins",):
            p.add_argument("--channel", default=None)
    args = parser.parse_args()
    handler, _ = handlers[args.command]
    if args.command == "channel":
        args.id = args.id or args.channel
        if not args.id:
            C.fail("missing_id", "Kanal-ID fehlt")
    if args.command in ("thread", "search") and not getattr(args, "channel", None):
        args.channel = None
    if args.command == "thread" and not getattr(args, "post", None):
        C.fail("missing_post", "Post-ID fehlt")
    return C.run_main(lambda: handler(args))


if __name__ == "__main__":
    sys.exit(main())
