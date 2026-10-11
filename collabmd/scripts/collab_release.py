#!/usr/bin/env python3
"""Publish and verify CollabMD workspace releases."""
import argparse
import sys
from pathlib import Path

import collabmd_common as C
import collab_lint


def controlled_files(ws):
    out = {}
    for relpath in ("schema/collab.json", "schema/SOUL.md", "schema/members.json", "schema/channels.json", "meta/version", "meta/changes.md"):
        target = ws.safe_rel(relpath)
        if not target.is_file():
            C.fail("missing_controlled", f"Steuerdatei fehlt: {relpath}")
        out[relpath] = C.sha256_file(target)
    for base, _prefix in ((ws.schema, "schema"), (ws.posts, "posts"), (ws.events_dir, "meta/events")):
        if not base.is_dir():
            continue
        for path in sorted(base.rglob("*")):
            if path.is_file():
                out[ws.rel(path)] = C.sha256_file(path)
    return out


def do_release(args):
    ws = C.Workspace(args.target)
    ws.require_workspace()
    C.verify_claim(ws, args.token_file)
    members = ws.members_doc()
    C.require_permission(members, args.actor, "release.publish")
    report = collab_lint.run_lint(ws)
    if report["errors"]:
        C.fail("lint_failed", "Lint mit Fehlern: " + "; ".join(report["errors"][:5]))
    operation_id = args.operation_id
    if len(operation_id) != 32 or any(ch not in "0123456789abcdef" for ch in operation_id):
        C.fail("bad_operation_id", "Operation-ID muss 32 Hex-Zeichen sein")
    receipt_path = ws.meta / "receipts" / f"{operation_id}.json"
    if receipt_path.is_file():
        receipt = C.read_json(receipt_path)
        return {
            "already_published": True,
            "release_id": receipt.get("release_id"),
            "version": receipt.get("version"),
        }
    version_path = ws.meta / "version"
    if args.bump == "initial":
        if version_path.is_file():
            C.fail("version_exists", "Version existiert bereits; initial nur für neuen Stand")
        version = "0.1.0"
    else:
        if not version_path.is_file():
            C.fail("missing_version", "meta/version fehlt")
        current = version_path.read_text(encoding="utf-8").strip()
        version = C.bump_version(current, args.bump)
    manifest_path = ws.meta / "manifest.json"
    C.atomic_write(version_path, version + "\n")
    C.append_changes(ws, args.actor, "release", f"{version}")
    manifest = {
        "format": C.FORMAT,
        "release_id": operation_id,
        "operation_id": operation_id,
        "version": version,
        "published": C.now_iso(),
        "summary": args.summary,
        "files": controlled_files(ws),
    }
    C.write_json(manifest_path, manifest)
    C.write_json(receipt_path, {"release_id": operation_id, "version": version,
                                "published": manifest["published"]})
    return {
        "published": True,
        "release_id": operation_id,
        "version": version,
        "files": len(manifest["files"]),
        "manifest_sha256": C.sha256_file(manifest_path),
    }


def do_verify(args):
    ws = C.Workspace(args.target)
    ws.require_workspace()
    manifest_path = ws.meta / "manifest.json"
    if not manifest_path.is_file():
        C.fail("no_release", "Kein veröffentlichtes Manifest vorhanden")
    manifest = C.read_json(manifest_path)
    missing, mismatched, checked = [], [], 0
    for relpath, digest in sorted(manifest.get("files", {}).items()):
        target = ws.safe_rel(relpath) if relpath else None
        checked += 1
        if target is None or not target.is_file():
            missing.append(relpath)
            continue
        if C.sha256_file(target) != digest:
            mismatched.append(relpath)
    version_path = ws.meta / "version"
    version = version_path.read_text(encoding="utf-8").strip() if version_path.is_file() else None
    ok = not missing and not mismatched and version == manifest.get("version")
    return {
        "ok": ok,
        "release_id": manifest.get("release_id"),
        "version": manifest.get("version"),
        "workspace_version": version,
        "checked": checked,
        "missing": missing,
        "mismatched": mismatched,
    }


def main():
    parser = argparse.ArgumentParser(prog="collab_release.py")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("release")
    p.add_argument("--target", required=True)
    p.add_argument("--bump", required=True, choices=["initial", "patch", "minor", "major"])
    p.add_argument("--operation-id", required=True)
    p.add_argument("--summary", required=True)
    p.add_argument("--actor", required=True)
    p.add_argument("--token-file", required=True)
    p = sub.add_parser("verify")
    p.add_argument("--target", required=True)
    args = parser.parse_args()
    if args.command == "release":
        return C.run_main(lambda: do_release(args))
    return C.run_main(lambda: do_verify(args))


if __name__ == "__main__":
    sys.exit(main())
