#!/usr/bin/env python3
"""Initialize a CollabMD workspace (plan/apply)."""
import argparse
import json
import sys
from pathlib import Path

import collabmd_common as C
import secret_screen

KEEPS = (
    "posts/.gitkeep",
    "posts/_files/.gitkeep",
    "meta/events/.gitkeep",
    "meta/cursors/.gitkeep",
    "meta/receipts/.gitkeep",
    "graph/.gitkeep",
)


def parse_channels(raw, handles):
    channels = {}
    for part in (raw or "").split(","):
        part = part.strip()
        if not part:
            continue
        pieces = [p.strip() for p in part.split("|")]
        if len(pieces) < 3:
            C.fail("bad_channels", f"Kanalangabe ungültig: {part}")
        channel_id, title, ctype = pieces[0], pieces[1], pieces[2]
        purpose = pieces[3] if len(pieces) > 3 else ""
        C.validate_channel_id(channel_id)
        if ctype not in C.CHANNEL_TYPES:
            C.fail("bad_channels", f"Kanaltyp ungültig: {ctype}")
        if ctype == "direct":
            C.fail("bad_channels", "Direkt-Kanäle entstehen durch Posts, nicht bei der Anlage")
        if channel_id in channels:
            C.fail("bad_channels", f"Kanal-ID doppelt: {channel_id}")
        channels[channel_id] = {
            "name": channel_id,
            "title": title,
            "type": ctype,
            "purpose": purpose,
            "members": list(handles),
            "created_by": None,
            "created": None,
            "archived": False,
            "archived_at": None,
        }
    return channels


def parse_members(raw):
    members = {}
    for part in (raw or "").split(","):
        part = part.strip()
        if not part:
            continue
        pieces = [p.strip() for p in part.split("|")]
        if len(pieces) < 3:
            C.fail("bad_members", f"Mitgliederangabe ungültig: {part}")
        handle, name, role = pieces[0], pieces[1], pieces[2]
        C.validate_handle(handle)
        if role not in C.ROLES:
            C.fail("bad_members", f"Rolle ungültig: {role}")
        if handle in members:
            C.fail("bad_members", f"Handle doppelt: {handle}")
        members[handle] = {"name": name, "role": role}
    return members


def write_content(content_dir, filename, text):
    path = Path(content_dir) / filename
    C.atomic_write(path, text)
    return path


def plan_init(args):
    target = C.Workspace(args.target)
    if target.root.exists() and any(p.name != ".collabmd.lock" for p in target.root.iterdir()):
        C.fail("target_not_empty", "Zielordner ist nicht leer; Anlage wird abgelehnt")
    name = (args.name or "").strip()
    purpose = (args.purpose or "").strip()
    if not name:
        C.fail("missing_name", "Name fehlt")
    if not purpose:
        C.fail("missing_purpose", "Zweck fehlt")
    if not args.language or not (2 <= len(args.language) <= 3):
        C.fail("bad_language", "Sprachcode ungültig (z. B. de, en)")
    owner = C.validate_handle(args.owner_handle)
    write_gate = args.write_gate != "false"
    iterations = C.DEFAULT_ITERATIONS
    created = C.now_iso()
    extra = parse_members(args.members)
    if owner in extra:
        C.fail("bad_members", f"Handle doppelt: {owner}")
    channels = parse_channels(args.channels, [owner] + sorted(extra))
    if "general" not in channels:
        channels["general"] = {
            "name": "general", "title": "Allgemein", "type": "public",
            "purpose": "Gemeinsamer Kanal", "members": [owner] + sorted(extra),
            "created_by": None, "created": None,
            "archived": False, "archived_at": None,
        }
    for channel in channels.values():
        channel["created_by"] = owner
        channel["created"] = created
    soul_path = Path(args.soul_file)
    if not soul_path.is_file():
        C.fail("missing_soul", f"SOUL-Datei fehlt: {soul_path}")
    soul = soul_path.read_text(encoding="utf-8")
    if not soul.strip():
        C.fail("empty_soul", "SOUL.md ist leer")
    hits = secret_screen.scan(soul)
    if hits:
        C.fail("secrets_found", "SOUL.md enthält mutmaßlich Zugangsdaten; bitte entfernen")
    members_doc = {
        "format": C.FORMAT,
        "members": {
            owner: {
                "name": args.owner_name or owner,
                "role": "owner",
                "github_id": None,
                "created": created,
                "disabled": False,
            }
        },
    }
    for handle, meta in sorted(extra.items()):
        members_doc["members"][handle] = {
            "name": meta["name"], "role": meta["role"],
            "github_id": None, "created": created, "disabled": False,
        }
    auth = {"write_gate": write_gate, "kdf": C.DEFAULT_KDF, "iterations": iterations}
    profile = {
        "format": C.FORMAT,
        "name": name,
        "purpose": purpose,
        "language": args.language,
        "language_label": args.language_label or args.language,
        "created": created,
        "auth": auth,
    }
    channels_doc = {"format": C.FORMAT, "channels": {cid: ch for cid, ch in sorted(channels.items())}}
    if write_gate:
        if not args.passphrase_file:
            C.fail("missing_passphrase", "Write-Gate aktiv: Passphrase-Datei fehlt")
        passphrase = Path(args.passphrase_file).read_text(encoding="utf-8").rstrip("\n")
        if len(passphrase) < 8:
            C.fail("passphrase_too_short", "Passphrase muss mindestens 8 Zeichen haben")
        members_doc["members"][owner]["auth"] = C.hash_passphrase(passphrase, iterations)
    content_dir = Path(args.content_dir)
    content_dir.mkdir(parents=True, exist_ok=True)
    files = {
        "schema/collab.json": json.dumps(profile, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        "schema/SOUL.md": soul,
        "schema/members.json": json.dumps(members_doc, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        "schema/channels.json": json.dumps(channels_doc, indent=2, sort_keys=True, ensure_ascii=False) + "\n",
        "meta/changes.md": "# Änderungen\n\n",
    }
    for keep in KEEPS:
        files[keep] = ""
    ops = []
    for relpath in sorted(files):
        safe_name = relpath.replace("/", "__")
        ops.append(C.content_op("create", relpath, str(write_content(content_dir, safe_name, files[relpath]))))
    plan = C.make_plan(
        "init", owner,
        {"schema/collab.json": None, "schema/members.json": None, "schema/channels.json": None},
        ops,
        [f"workspace.created name={name} language={args.language} channels={len(channels)}"],
    )
    C.write_json(args.output, plan)
    return {
        "ok": True,
        "plan_file": str(args.output),
        "plan_sha256": plan["plan_sha256"],
        "op": plan["op"],
        "name": name,
        "language": args.language,
        "owner": owner,
        "members": len(members_doc["members"]),
        "channels": {cid: ch["type"] for cid, ch in sorted(channels.items())},
        "write_gate": write_gate,
        "files": len(files),
        "destructive": False,
    }


def apply_init(args):
    ws = C.Workspace(args.target)
    plan = C.read_json(args.plan_file)
    return C.apply_plan(ws, plan, args.expect_plan_sha256, args.token_file)


def main():
    parser = argparse.ArgumentParser(prog="collab_init.py")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("plan")
    p.add_argument("--target", required=True)
    p.add_argument("--name", required=True)
    p.add_argument("--purpose", required=True)
    p.add_argument("--language", required=True)
    p.add_argument("--language-label", default=None)
    p.add_argument("--soul-file", required=True)
    p.add_argument("--owner-handle", required=True)
    p.add_argument("--owner-name", default=None)
    p.add_argument("--passphrase-file", default=None)
    p.add_argument("--channels", default=None)
    p.add_argument("--members", default=None)
    p.add_argument("--write-gate", default="true")
    p.add_argument("--content-dir", required=True)
    p.add_argument("--output", required=True)
    p = sub.add_parser("apply")
    p.add_argument("--target", required=True)
    p.add_argument("--plan-file", required=True)
    p.add_argument("--expect-plan-sha256", required=True)
    p.add_argument("--token-file", required=True)
    args = parser.parse_args()
    if args.command == "plan":
        return C.run_main(lambda: plan_init(args))
    return C.run_main(lambda: apply_init(args))


if __name__ == "__main__":
    sys.exit(main())
