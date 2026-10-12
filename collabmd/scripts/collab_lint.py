#!/usr/bin/env python3
"""Validate a CollabMD workspace (strict, no auto-fix)."""
import argparse
import sys
from pathlib import Path

import collabmd_common as C
import secret_screen


def check_profile(ws, errors, warnings):
    try:
        profile = ws.profile()
    except C.CollabError as exc:
        errors.append(f"schema/collab.json: {exc.message}")
        return
    if profile.get("format") != C.FORMAT:
        errors.append("schema/collab.json: unbekanntes Format")
    if not isinstance(profile.get("name"), str) or not profile.get("name", "").strip():
        errors.append("schema/collab.json: Name fehlt")
    if not isinstance(profile.get("purpose"), str) or not profile.get("purpose", "").strip():
        errors.append("schema/collab.json: Zweck fehlt")
    language = profile.get("language")
    if not isinstance(language, str) or not (2 <= len(language) <= 3):
        errors.append("schema/collab.json: Sprachcode ungültig")
    auth = profile.get("auth")
    if not isinstance(auth, dict):
        errors.append("schema/collab.json: auth fehlt")
        return
    if auth.get("kdf") != C.DEFAULT_KDF:
        errors.append("schema/collab.json: auth.kdf ungültig")
    if not isinstance(auth.get("iterations"), int) or auth.get("iterations", 0) < 100000:
        errors.append("schema/collab.json: auth.iterations ungültig")
    if not isinstance(auth.get("write_gate", True), bool):
        errors.append("schema/collab.json: auth.write_gate ungültig")


def check_members(ws, errors, warnings):
    try:
        doc = ws.members_doc()
    except C.CollabError as exc:
        errors.append(f"schema/members.json: {exc.message}")
        return {}
    if doc.get("format") != C.FORMAT:
        errors.append("schema/members.json: unbekanntes Format")
    members = doc.get("members")
    if not isinstance(members, dict) or not members:
        errors.append("schema/members.json: keine Mitglieder")
        return {}
    owners = 0
    for handle, entry in sorted(members.items()):
        if not isinstance(handle, str) or not C.HANDLE_RE.match(handle):
            errors.append(f"schema/members.json: Handle ungültig: {handle!r}")
            continue
        if not isinstance(entry, dict):
            errors.append(f"schema/members.json: Eintrag ungültig: {handle}")
            continue
        role = entry.get("role")
        if role not in C.ROLES:
            errors.append(f"schema/members.json: Rolle ungültig für {handle}: {role!r}")
        elif role == "owner":
            owners += 1
        if not isinstance(entry.get("name"), str) or not entry.get("name", "").strip():
            errors.append(f"schema/members.json: Name fehlt für {handle}")
        if not isinstance(entry.get("disabled", False), bool):
            errors.append(f"schema/members.json: disabled ungültig für {handle}")
        github_id = entry.get("github_id")
        if github_id is not None and (not isinstance(github_id, int) or github_id <= 0):
            errors.append(f"schema/members.json: github_id ungültig für {handle}")
        auth = entry.get("auth")
        if auth is not None:
            if not isinstance(auth, dict):
                errors.append(f"schema/members.json: auth ungültig für {handle}")
            else:
                if auth.get("kdf") != C.DEFAULT_KDF:
                    errors.append(f"schema/members.json: auth.kdf ungültig für {handle}")
                if not C.SHA_RE.match(str(auth.get("salt", ""))):
                    errors.append(f"schema/members.json: auth.salt ungültig für {handle}")
                if not C.SHA_RE.match(str(auth.get("hash", ""))):
                    errors.append(f"schema/members.json: auth.hash ungültig für {handle}")
                if not isinstance(auth.get("iterations"), int) or auth.get("iterations", 0) < 100000:
                    errors.append(f"schema/members.json: auth.iterations ungültig für {handle}")
    if owners == 0:
        errors.append("schema/members.json: kein owner vorhanden")
    return members


def check_channels(ws, errors, warnings, members):
    try:
        doc = ws.channels_doc()
    except C.CollabError as exc:
        errors.append(f"schema/channels.json: {exc.message}")
        return {}
    if doc.get("format") != C.FORMAT:
        errors.append("schema/channels.json: unbekanntes Format")
    channels = doc.get("channels")
    if not isinstance(channels, dict):
        errors.append("schema/channels.json: keine Kanäle")
        return {}
    seen_names = {}
    for channel_id, channel in sorted(channels.items()):
        if not isinstance(channel_id, str) or not C.CHANNEL_ID_RE.match(channel_id):
            errors.append(f"schema/channels.json: Kanal-ID ungültig: {channel_id!r}")
            continue
        if not isinstance(channel, dict):
            errors.append(f"schema/channels.json: Eintrag ungültig: {channel_id}")
            continue
        ctype = channel.get("type")
        if ctype not in C.CHANNEL_TYPES:
            errors.append(f"schema/channels.json: Typ ungültig für {channel_id}: {ctype!r}")
        title = channel.get("title")
        if not isinstance(title, str) or not title.strip():
            errors.append(f"schema/channels.json: Titel fehlt für {channel_id}")
        else:
            key = title.strip().lower()
            if key in seen_names:
                errors.append(f"schema/channels.json: Titel doppelt: {title} ({channel_id}, {seen_names[key]})")
            else:
                seen_names[key] = channel_id
        handles = channel.get("members")
        if not isinstance(handles, list) or not handles:
            errors.append(f"schema/channels.json: Mitglieder fehlen für {channel_id}")
            handles = []
        for handle in handles:
            if handle not in members:
                errors.append(f"schema/channels.json: unbekanntes Mitglied {handle} in {channel_id}")
        if len(set(handles)) != len(handles):
            errors.append(f"schema/channels.json: doppelte Mitglieder in {channel_id}")
        if ctype == "direct":
            if len(handles) != 2:
                errors.append(f"schema/channels.json: Direkt-Kanal braucht genau 2 Mitglieder: {channel_id}")
            else:
                expected = "dm-" + "-".join(sorted(handles))
                if channel_id != expected:
                    errors.append(f"schema/channels.json: Direkt-Kanal-ID falsch: {channel_id} (erwartet {expected})")
        if not isinstance(channel.get("archived", False), bool):
            errors.append(f"schema/channels.json: archived ungültig für {channel_id}")
        if channel.get("archived"):
            if not C.parse_iso(channel.get("archived_at")):
                errors.append(f"schema/channels.json: archived_at fehlt für {channel_id}")
    return channels


def check_posts(ws, errors, warnings, members, channels):
    posts = ws.list_posts()
    by_id = {}
    for relpath, meta, body in posts:
        by_id[meta.get("id")] = (relpath, meta)
    for relpath, meta, body in posts:
        where = relpath
        if meta.get("type") != "post":
            errors.append(f"{where}: type ist kein post")
        post_id = meta.get("id")
        if not isinstance(post_id, str) or not C.POST_ID_RE.match(post_id):
            errors.append(f"{where}: Post-ID ungültig")
        elif Path(relpath).stem != post_id:
            errors.append(f"{where}: Dateiname weicht von Post-ID ab")
        channel_id = meta.get("channel")
        if channel_id not in channels:
            errors.append(f"{where}: unbekannter Kanal {channel_id!r}")
        author = meta.get("author")
        if author not in members:
            errors.append(f"{where}: unbekannter Autor {author!r}")
        if not C.parse_iso(meta.get("created")):
            errors.append(f"{where}: created ungültig")
        for field in ("edited", "deleted", "pinned"):
            if not isinstance(meta.get(field), bool):
                errors.append(f"{where}: {field} ungültig")
        if not isinstance(meta.get("edits", 0), int) or meta.get("edits", 0) < 0:
            errors.append(f"{where}: edits ungültig")
        if meta.get("edited") and not C.parse_iso(meta.get("edited_at")):
            errors.append(f"{where}: edited_at fehlt")
        if meta.get("deleted") and body.strip() != C.DELETION_MARKER:
            errors.append(f"{where}: gelöschter Post muss nur den Marker enthalten")
        root = meta.get("thread_root")
        if root is not None:
            if root == post_id:
                errors.append(f"{where}: Thread-Root ist der Post selbst")
            else:
                target = by_id.get(root)
                if target is None:
                    errors.append(f"{where}: Thread-Root existiert nicht: {root}")
                elif target[1].get("channel") != channel_id:
                    errors.append(f"{where}: Thread-Root liegt in anderem Kanal")
                elif target[1].get("thread_root") is not None:
                    errors.append(f"{where}: verschachtelte Threads sind nicht erlaubt")
        reactions = meta.get("reactions", {})
        if not isinstance(reactions, dict):
            errors.append(f"{where}: reactions ungültig")
        else:
            for emoji, handles in reactions.items():
                if not isinstance(emoji, str) or not emoji.strip():
                    errors.append(f"{where}: Reaktions-Emoji ungültig")
                if not isinstance(handles, list) or any(h not in members for h in handles):
                    errors.append(f"{where}: Reaktions-Mitglieder ungültig für {emoji!r}")
        files = meta.get("files", [])
        if not isinstance(files, list):
            errors.append(f"{where}: files ungültig")
        else:
            for digest in files:
                if not C.SHA_RE.match(str(digest)):
                    errors.append(f"{where}: Datei-Hash ungültig: {digest!r}")
                elif not (ws.files_dir / digest).is_file():
                    errors.append(f"{where}: Anhang fehlt im Dateispeicher: {digest}")
        if len(body) > 50000:
            warnings.append(f"{where}: Post sehr groß ({len(body)} Zeichen)")
    return posts


def check_files(ws, errors, warnings, posts):
    if not ws.files_dir.is_dir():
        return
    referenced = set()
    for _, meta, _ in posts:
        for digest in meta.get("files", []):
            if isinstance(digest, str):
                referenced.add(digest)
    for path in sorted(ws.files_dir.iterdir()):
        if not path.is_file():
            continue
        if path.name == ".gitkeep":
            continue
        if not C.SHA_RE.match(path.name):
            errors.append(f"posts/_files/{path.name}: Dateiname ist kein SHA-256")
            continue
        if C.sha256_file(path) != path.name:
            errors.append(f"posts/_files/{path.name}: Hash weicht vom Inhalt ab")
        elif path.name not in referenced:
            warnings.append(f"posts/_files/{path.name}: von keinem Post referenziert")


def check_events(ws, errors, warnings, members):
    if not ws.events_dir.is_dir():
        return
    seen = set()
    for path in sorted(ws.events_dir.iterdir()):
        if not path.is_file() or path.name == ".gitkeep":
            continue
        text = path.read_text(encoding="utf-8")
        try:
            meta, _ = C.parse_frontmatter(text)
        except C.CollabError as exc:
            errors.append(f"meta/events/{path.name}: {exc.message}")
            continue
        op = meta.get("op")
        if op in seen:
            errors.append(f"meta/events/{path.name}: Operation doppelt: {op}")
        seen.add(op)
        if meta.get("type") != "event":
            errors.append(f"meta/events/{path.name}: type ist kein event")
        if meta.get("actor") not in members:
            warnings.append(f"meta/events/{path.name}: unbekannter Akteur {meta.get('actor')!r}")
        if not C.parse_iso(meta.get("created")):
            errors.append(f"meta/events/{path.name}: created ungültig")


def check_cursors(ws, errors, warnings, members, channels):
    if not ws.cursors_dir.is_dir():
        return
    for path in sorted(ws.cursors_dir.iterdir()):
        if not path.is_file() or path.suffix != ".json":
            if path.suffix != ".json" and path.name != ".gitkeep":
                errors.append(f"meta/cursors/{path.name}: unerwartete Datei (erwartet <handle>.json)")
            continue
        rel = f"meta/cursors/{path.name}"
        try:
            handle = C.validate_handle(path.stem)
        except C.CollabError:
            errors.append(f"{rel}: Dateiname ist kein gültiger Handle")
            continue
        try:
            doc = C.read_json(path)
        except C.CollabError as exc:
            errors.append(f"{rel}: {exc.message}")
            continue
        if doc.get("handle") != handle:
            errors.append(f"{rel}: handle-Feld weicht vom Dateinamen ab")
        if handle not in members:
            errors.append(f"{rel}: unbekanntes Mitglied {handle!r}")
        chans = doc.get("channels")
        if not isinstance(chans, dict):
            errors.append(f"{rel}: channels muss ein Objekt sein")
            continue
        for channel_id, entry in sorted(chans.items()):
            try:
                C.validate_channel_id(channel_id)
            except C.CollabError:
                errors.append(f"{rel}: ungültige Kanal-ID {channel_id!r}")
                continue
            if channel_id not in channels:
                errors.append(f"{rel}: unbekannter Kanal {channel_id!r}")
                continue
            if not isinstance(entry, dict):
                errors.append(f"{rel}/{channel_id}: Eintrag muss ein Objekt sein")
                continue
            for field in ("cursor", "updated"):
                if not C.parse_iso(entry.get(field)):
                    errors.append(f"{rel}/{channel_id}: {field} ungültig")


def check_version_manifest(ws, errors):
    version_path = ws.meta / "version"
    version = None
    if version_path.is_file():
        version = version_path.read_text(encoding="utf-8").strip()
        if not C.SEMVER_RE.match(version):
            errors.append(f"meta/version: ungültig: {version!r}")
    manifest_path = ws.meta / "manifest.json"
    if manifest_path.is_file():
        if version is None:
            errors.append("meta/version: fehlt, aber Manifest vorhanden")
        try:
            manifest = C.read_json(manifest_path)
        except C.CollabError as exc:
            errors.append(f"meta/manifest.json: {exc.message}")
            return
        if manifest.get("version") != version:
            errors.append("meta/manifest.json: Version weicht von meta/version ab")
        files = manifest.get("files")
        if not isinstance(files, dict) or not files:
            errors.append("meta/manifest.json: files fehlen")
            return
        for relpath, digest in sorted(files.items()):
            target = ws.safe_rel(relpath) if relpath else None
            if target is None or not target.is_file():
                errors.append(f"meta/manifest.json: Datei fehlt: {relpath}")
                continue
            if C.sha256_file(target) != digest:
                errors.append(f"meta/manifest.json: Hash weicht ab: {relpath}")


def check_secrets(ws, errors):
    soul = ws.schema / "SOUL.md"
    if soul.is_file():
        hits = secret_screen.scan(soul.read_text(encoding="utf-8"))
        if hits:
            errors.append(f"schema/SOUL.md: {len(hits)} mögliche Zugangsdaten")
    for relpath, _, body in ws.list_posts():
        hits = secret_screen.scan(body)
        if hits:
            errors.append(f"{relpath}: {len(hits)} mögliche Zugangsdaten")
    if ws.events_dir.is_dir():
        for path in sorted(ws.events_dir.iterdir()):
            if path.is_file() and path.name != ".gitkeep":
                hits = secret_screen.scan(path.read_text(encoding="utf-8"))
                if hits:
                    errors.append(f"meta/events/{path.name}: mögliche Zugangsdaten")


def run_lint(ws):
    errors, warnings = [], []
    check_profile(ws, errors, warnings)
    members = check_members(ws, errors, warnings)
    channels = check_channels(ws, errors, warnings, members)
    posts = check_posts(ws, errors, warnings, members, channels)
    check_files(ws, errors, warnings, posts)
    check_events(ws, errors, warnings, members)
    check_cursors(ws, errors, warnings, members, channels)
    check_version_manifest(ws, errors)
    check_secrets(ws, errors)
    stats = {
        "members": len(members),
        "channels": len(channels),
        "posts": len(posts),
        "events": len(list(ws.events_dir.glob("*.md"))) if ws.events_dir.is_dir() else 0,
    }
    return {"errors": errors, "warnings": warnings, "stats": stats}


def main():
    parser = argparse.ArgumentParser(prog="collab_lint.py")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("lint")
    p.add_argument("--target", required=True)
    args = parser.parse_args()

    def run():
        ws = C.Workspace(args.target)
        ws.require_workspace()
        report = run_lint(ws)
        result = {
            "ok": not report["errors"],
            "errors": report["errors"],
            "warnings": report["warnings"],
            "stats": report["stats"],
        }
        C.emit(result)
        return 0 if not report["errors"] else 1

    try:
        return run()
    except C.CollabError as exc:
        C.emit({"ok": False, "error": exc.code, "message": exc.message})
        return 1


if __name__ == "__main__":
    sys.exit(main())
