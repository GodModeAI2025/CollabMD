#!/usr/bin/env python3
"""Pure team-mode contract: validation, actor mapping, previews, approvals. No I/O."""
import hashlib
import json
import re
import uuid

from collabmd_common import ROLE_RANK, CollabError

TEAM_FORMAT = "collabmd-team/1"
ENFORCEMENTS = ("trusted-writers-beta",)
TEAM_GITHUB_ID_RE = re.compile(r"^[0-9]{1,19}$")
TEAM_REPO_RE = re.compile(r"^[a-z0-9][a-z0-9-]*/[a-z0-9][a-z0-9.-]*$")
TEAM_BRANCH_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9._/-]{0,127}$")
APPROVAL_TTL_SECONDS = 3600
PR_BODY_MARKER = "collabmd-op/1"


def fail(code, message):
    raise CollabError(code, message)


def validate_config(doc, members_doc):
    if not isinstance(doc, dict):
        fail("team_config_invalid", "team.json muss ein Objekt sein")
    if doc.get("format") != TEAM_FORMAT:
        fail("team_config_invalid", "unbekanntes team-Format")
    if doc.get("provider") not in ("github", "local"):
        fail("team_config_invalid", "Provider muss github oder local sein")
    if doc.get("enforcement") not in ENFORCEMENTS:
        fail("team_config_invalid", f"enforcement muss eines sein: {', '.join(ENFORCEMENTS)}")
    repo = doc.get("repo")
    if doc.get("provider") == "github":
        if not isinstance(repo, str) or not TEAM_REPO_RE.match(repo):
            fail("team_config_invalid", "repo muss owner/name sein")
    else:
        if not isinstance(repo, str) or not repo:
            fail("team_config_invalid", "repo (lokaler Bare-Remote-Pfad) fehlt")
    branch = doc.get("branch")
    if not isinstance(branch, str) or not TEAM_BRANCH_RE.match(branch):
        fail("team_config_invalid", "branch ungültig")
    ids = doc.get("github_ids")
    if not isinstance(ids, dict) or not ids:
        fail("team_config_invalid", "github_ids fehlt")
    seen = set()
    for handle, value in ids.items():
        if not isinstance(value, str) or not TEAM_GITHUB_ID_RE.match(value):
            fail("team_config_invalid", f"github-id für {handle} muss eine Zahl sein")
        if value in seen:
            fail("team_config_invalid", f"github-id {value} ist mehrfach vergeben")
        seen.add(value)
    members = (members_doc or {}).get("members", {})
    for handle, entry in members.items():
        if entry.get("disabled"):
            continue
        if handle not in ids:
            fail("team_mapping_incomplete", f"Mitglied {handle} hat keine GitHub-ID")
        if entry.get("role") not in ROLE_RANK:
            fail("team_config_invalid", f"Rolle für {handle} ungültig")
    return True


def actor_for(config, github_id):
    ids = config.get("github_ids", {})
    for handle, value in ids.items():
        if str(value) == str(github_id):
            return handle
    fail("unknown_actor", f"GitHub-ID {github_id} ist keinem Mitglied zugeordnet")


def permission(config, members_doc, actor, action):
    from collabmd_common import require_permission
    return require_permission(members_doc, actor, action)


def _canon(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def make_preview(base_revision, actor, operations, file_hashes):
    if not base_revision or len(base_revision) != 40:
        fail("team_base_invalid", "base_revision muss eine 40-hex-SHA sein")
    payload = {
        "format": "collabmd-preview/1",
        "base_revision": base_revision,
        "actor": actor,
        "operations": operations,
        "files": file_hashes,
    }
    digest = hashlib.sha256(_canon(payload).encode("utf-8")).hexdigest()
    payload["preview_sha256"] = digest
    return payload


def approval_for(preview_sha256, actor, approval_id=None):
    if not preview_sha256 or len(preview_sha256) != 64:
        fail("team_preview_invalid", "preview_sha256 ungültig")
    return {
        "format": "collabmd-approval/1",
        "approval_id": approval_id or uuid.uuid4().hex,
        "preview_sha256": preview_sha256,
        "actor": actor,
        "granted": True,
    }


def validate_approval(approval, preview_sha256, actor, now_ts=None):
    if not isinstance(approval, dict) or approval.get("format") != "collabmd-approval/1":
        fail("team_approval_invalid", "Approval-Format ungültig")
    if not approval.get("granted"):
        fail("team_approval_invalid", "Approval erteilt nicht")
    if approval.get("preview_sha256") != preview_sha256:
        fail("team_approval_mismatch", "Approval gehört zu einem anderen Preview")
    if approval.get("actor") != actor:
        fail("team_approval_mismatch", "Approval gehört zu einem anderen Akteur")
    if not approval.get("approval_id"):
        fail("team_approval_invalid", "approval_id fehlt")
    return True


def pr_operation_block(preview, approval):
    lines = [PR_BODY_MARKER,
             f"operation-id: {approval.get('approval_id')}",
             f"actor: {preview.get('actor')}",
             f"base-revision: {preview.get('base_revision')}",
             f"preview-sha256: {preview.get('preview_sha256')}"]
    return "\n".join(lines) + "\n"


def parse_pr_operation_block(body):
    if not isinstance(body, str) or PR_BODY_MARKER not in body:
        fail("team_pr_block_missing", "PR-Body enthält keinen collabmd-Operation-Block")
    fields = {}
    in_block = False
    for line in body.splitlines():
        if line.strip() == PR_BODY_MARKER:
            in_block = True
            continue
        if in_block:
            if not line.strip():
                continue
            if ":" not in line:
                break
            key, _, value = line.partition(":")
            fields[key.strip()] = value.strip()
    for required in ("operation-id", "actor", "base-revision", "preview-sha256"):
        if not fields.get(required):
            fail("team_pr_block_missing", f"Operation-Block-Feld fehlt: {required}")
    return fields


def validate_pr_body(body, preview):
    fields = parse_pr_operation_block(body)
    if fields["actor"] != preview.get("actor"):
        fail("team_pr_actor_mismatch", "PR-Akteur weicht vom Preview ab")
    if fields["base-revision"] != preview.get("base_revision"):
        fail("team_pr_base_mismatch", "PR-Basis weicht vom Preview ab")
    if fields["preview-sha256"] != preview.get("preview_sha256"):
        fail("team_pr_preview_mismatch", "PR-Preview weicht ab")
    return fields


def allowed_diff_paths(paths, allow_workflow=False):
    allowed = []
    for rel in paths:
        rel = rel.replace("\\", "/")
        while rel.startswith("./"):
            rel = rel[2:]
        if rel.startswith(".collabmd.lock/"):
            fail("team_diff_forbidden", f"Datei aus dem Sperren-Verzeichnis in der diff: {rel}")
        if rel.startswith(".git/"):
            fail("team_diff_forbidden", f"Git-interne Datei in der diff: {rel}")
        ok = rel.startswith(("schema/", "posts/", "meta/"))
        if ok and rel.startswith("meta/") and not rel.startswith(("meta/events/", "meta/cursors/", "meta/changes.md", "meta/version", "meta/manifest.json", "meta/receipts/")):
            ok = False
        if rel == ".github/workflows/team-integrity.yml" and allow_workflow:
            ok = True
        if not ok:
            fail("team_diff_forbidden", f"Pfad außerhalb der erlaubten Bereiche: {rel}")
        allowed.append(rel)
    return allowed


def is_stale_base(config, current_main_sha, preview):
    return bool(current_main_sha) and current_main_sha != preview.get("base_revision")
