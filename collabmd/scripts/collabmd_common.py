#!/usr/bin/env python3
"""Shared runtime for CollabMD skill helpers."""
from __future__ import annotations

import hashlib
import hmac
import json
import os
import re
import secrets
import shutil
import socket
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

FORMAT = "collabmd/1"
TS_FMT = "%Y-%m-%dT%H:%M:%SZ"
HANDLE_RE = re.compile(r"^[a-z][a-z0-9-]{1,31}$")
CHANNEL_ID_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}$")
POST_ID_RE = re.compile(r"^[0-9a-f]{32}$")
SHA_RE = re.compile(r"^[0-9a-f]{64}$")
SEMVER_RE = re.compile(r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$")
ROLES = ("owner", "maintainer", "contributor", "reader")
ROLE_RANK = {"owner": 4, "maintainer": 3, "contributor": 2, "reader": 1}
CHANNEL_TYPES = ("public", "private", "direct", "group")
GATE_EXEMPT_ACTIONS = ("init", "cursor.set", "graph.build")
DELETION_MARKER = "[gelöscht]"
DEFAULT_KDF = "pbkdf2-sha256"
DEFAULT_ITERATIONS = 600000
SESSION_TTL_SECONDS = 600
LOCK_LEASE_SECONDS = 900


class CollabError(Exception):
    def __init__(self, code, message):
        super().__init__(message)
        self.code = code
        self.message = message


def fail(code, message):
    raise CollabError(code, message)


def now_dt():
    return datetime.now(timezone.utc)


def now_iso():
    return now_dt().strftime(TS_FMT)


def parse_iso(value):
    try:
        return datetime.strptime(value, TS_FMT).replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def sha256_bytes(data):
    return hashlib.sha256(data).hexdigest()


def sha256_text(text):
    return sha256_bytes(text.encode("utf-8"))


def sha256_file(path):
    return sha256_bytes(Path(path).read_bytes())


def file_hash_or_none(path):
    path = Path(path)
    if not path.is_file():
        return None
    return sha256_file(path)


def canonical_json(obj):
    return json.dumps(obj, sort_keys=True, separators=(",", ":"), ensure_ascii=False)


def atomic_write(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".collabmd-")
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(text)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def atomic_write_bytes(path, data):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".collabmd-")
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def atomic_copy(src, dst):
    dst = Path(dst)
    dst.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(dst.parent), prefix=".collabmd-")
    os.close(fd)
    try:
        shutil.copyfile(src, tmp)
        os.replace(tmp, dst)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def write_private(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(str(path), os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
        handle.write(text)


def read_json(path):
    try:
        return json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        fail("invalid_json", f"{path}: {exc}")


def write_json(path, obj):
    atomic_write(path, json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False) + "\n")


def default_maintainer():
    import getpass
    return f"{getpass.getuser()}@{socket.gethostname()}"


def validate_handle(handle):
    if not isinstance(handle, str) or not HANDLE_RE.match(handle):
        fail("invalid_handle", f"ungültiges Handle: {handle!r}")
    return handle


def validate_channel_id(channel_id):
    if not isinstance(channel_id, str) or not CHANNEL_ID_RE.match(channel_id):
        fail("invalid_channel_id", f"ungültige Kanal-ID: {channel_id!r}")
    return channel_id


def validate_post_id(post_id):
    if not isinstance(post_id, str) or not POST_ID_RE.match(post_id):
        fail("invalid_post_id", f"ungültige Post-ID: {post_id!r}")
    return post_id


INT_KEYS = frozenset({"edits"})

POST_FIELD_ORDER = (
    "type", "id", "channel", "author", "created",
    "edited", "edited_at", "edits", "deleted", "deleted_at",
    "pinned", "thread_root", "reactions", "files",
)
EVENT_FIELD_ORDER = ("type", "op", "actor", "created")


def parse_frontmatter(text):
    lines = text.split("\n")
    if not lines or lines[0].strip() != "---":
        fail("bad_frontmatter", "Frontmatter fehlt")
    meta = {}
    index = 1
    while index < len(lines):
        line = lines[index]
        if line.strip() == "---":
            return meta, "\n".join(lines[index + 1:])
        stripped = line.strip()
        if stripped:
            if ":" not in line:
                fail("bad_frontmatter", f"ungültige Zeile: {line!r}")
            key, _, raw = line.partition(":")
            key = key.strip()
            raw = raw.strip()
            if raw == "" or raw == "null":
                meta[key] = None
            elif raw == "true":
                meta[key] = True
            elif raw == "false":
                meta[key] = False
            elif raw[0] in "{[\"":
                try:
                    meta[key] = json.loads(raw)
                except json.JSONDecodeError:
                    fail("bad_frontmatter", f"ungültiger JSON-Wert für {key}")
            elif key in INT_KEYS:
                try:
                    meta[key] = int(raw)
                except ValueError:
                    fail("bad_frontmatter", f"ganzzahliger Wert erwartet für {key}")
            else:
                meta[key] = raw
        index += 1
    fail("bad_frontmatter", "Frontmatter nicht beendet")


def render_frontmatter(meta, order):
    lines = ["---"]
    for key in order:
        if key not in meta:
            continue
        value = meta[key]
        rendered = value if isinstance(value, str) else canonical_json(value)
        lines.append(f"{key}: {rendered}")
    lines.append("---")
    return "\n".join(lines) + "\n"


class Workspace:
    def __init__(self, target):
        self.root = Path(target)
        self.schema = self.root / "schema"
        self.posts = self.root / "posts"
        self.files_dir = self.posts / "_files"
        self.meta = self.root / "meta"
        self.events_dir = self.meta / "events"
        self.receipts_dir = self.meta / "receipts"
        self.cursors_dir = self.meta / "cursors"
        self.graph = self.root / "graph"
        self.lock_dir = self.root / ".collabmd.lock"

    def profile(self):
        return read_json(self.schema / "collab.json")

    def members_doc(self):
        return read_json(self.schema / "members.json")

    def channels_doc(self):
        return read_json(self.schema / "channels.json")

    def require_workspace(self):
        if not (self.schema / "collab.json").is_file():
            fail("not_a_workspace", f"{self.root} ist kein CollabMD-Arbeitsraum")

    def rel(self, path):
        return Path(path).relative_to(self.root).as_posix()

    def safe_rel(self, relpath):
        pure = Path(relpath)
        if not relpath or pure.is_absolute() or ".." in pure.parts or relpath.startswith((".", "/")):
            fail("unsafe_path", f"Pfad außerhalb des Arbeitsraums: {relpath}")
        return self.root / relpath

    def post_path(self, channel_id, post_id):
        return self.posts / channel_id / f"{post_id}.md"

    def load_post(self, relpath):
        text = (self.root / relpath).read_text(encoding="utf-8")
        meta, body = parse_frontmatter(text)
        return meta, body

    def list_posts(self, channel_id=None):
        found = []
        base = self.posts
        if not base.is_dir():
            return found
        for path in sorted(base.rglob("*.md")):
            if "_files" in path.parts:
                continue
            relpath = self.rel(path)
            meta, body = self.load_post(relpath)
            if channel_id is None or meta.get("channel") == channel_id:
                found.append((relpath, meta, body))
        return found


def member_entry(members_doc, handle):
    return members_doc.get("members", {}).get(handle)


def effective_role(members_doc, handle):
    entry = member_entry(members_doc, handle)
    if not entry or entry.get("disabled"):
        return None
    role = entry.get("role")
    return role if role in ROLE_RANK else None


def role_at_least(role, minimum):
    return role is not None and ROLE_RANK.get(role, 0) >= ROLE_RANK[minimum]


def require_permission(members_doc, actor, action, ctx=None):
    role = effective_role(members_doc, actor)
    if role is None:
        fail("permission_denied", f"Akteur {actor} hat keine aktive Mitgliedschaft")
    ctx = ctx or {}
    if action == "init":
        return role
    if action in ("auth.reset-passphrase", "auth.disable-user", "auth.enable-user", "team.setup", "team.membership"):
        minimum = "owner"
    elif action == "members.update-profile":
        minimum = None if ctx.get("self") else "maintainer"
    elif action in ("auth.create-user", "channels.create", "channels.rename", "channels.archive", "channels.unarchive", "channels.join-private"):
        minimum = "maintainer"
    elif action in ("posts.edit-other", "posts.delete-other", "posts.pin-other", "posts.unpin-other"):
        minimum = "maintainer"
    elif action in ("release.publish", "posts.create", "channels.join", "posts.edit-self", "posts.delete-self", "posts.pin-self", "posts.unpin-self"):
        minimum = "contributor"
    else:
        minimum = "reader"
    if minimum is not None and not role_at_least(role, minimum):
        fail("permission_denied", f"Rolle {role} reicht für {action} nicht (mindestens {minimum})")
    return role


def lock_claim_path(ws):
    return ws.lock_dir / "claim.json"


def acquire_lock(ws, owner, maintainer, operation, token_file, lease_seconds=LOCK_LEASE_SECONDS):
    token_path = Path(token_file)
    if token_path.exists():
        fail("token_file_exists", f"Token-Datei existiert bereits: {token_path}")
    claim_path = lock_claim_path(ws)
    if claim_path.is_file():
        existing = read_json(claim_path)
        expires = parse_iso(existing.get("expires_at"))
        state = "held" if (expires and expires > now_dt()) else "expired"
        return {
            "acquired": False,
            "state": state,
            "maintainer": existing.get("maintainer"),
            "owner": existing.get("owner"),
            "operation": existing.get("operation"),
            "acquired_at": existing.get("acquired_at"),
            "expires_at": existing.get("expires_at"),
        }
    token = secrets.token_hex(32)
    acquired = now_dt()
    claim = {
        "owner": owner,
        "maintainer": maintainer,
        "operation": operation,
        "acquired_at": acquired.strftime(TS_FMT),
        "expires_at": (acquired + timedelta(seconds=lease_seconds)).strftime(TS_FMT),
        "lease_seconds": lease_seconds,
        "token_sha256": sha256_text(token),
    }
    ws.lock_dir.mkdir(parents=True, exist_ok=True)
    atomic_write(claim_path, json.dumps(claim, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    write_private(token_path, token + "\n")
    return {
        "acquired": True,
        "state": "acquired",
        "maintainer": maintainer,
        "owner": owner,
        "operation": operation,
        "acquired_at": claim["acquired_at"],
        "expires_at": claim["expires_at"],
    }


def read_token(token_file):
    path = Path(token_file)
    if not path.is_file():
        fail("missing_token", f"Token-Datei fehlt: {path}")
    return path.read_text(encoding="utf-8").strip()


def verify_claim(ws, token_file):
    claim_path = lock_claim_path(ws)
    if not claim_path.is_file():
        fail("no_claim", "Kein aktiver Wartungsanspruch vorhanden")
    claim = read_json(claim_path)
    token = read_token(token_file)
    if not hmac.compare_digest(claim.get("token_sha256", ""), sha256_text(token)):
        fail("token_mismatch", "Token passt nicht zum Anspruch")
    expires = parse_iso(claim.get("expires_at"))
    if not expires or expires <= now_dt():
        fail("claim_expired", "Lease des Anspruchs abgelaufen")
    return claim


def release_lock(ws, token_file, remove_token_file=True):
    claim = verify_claim(ws, token_file)
    os.unlink(lock_claim_path(ws))
    if remove_token_file:
        os.unlink(Path(token_file))
    return {"released": True, "maintainer": claim.get("maintainer"), "owner": claim.get("owner")}


def heartbeat_lock(ws, token_file, lease_seconds=None):
    claim = verify_claim(ws, token_file)
    lease = lease_seconds or int(claim.get("lease_seconds", LOCK_LEASE_SECONDS))
    claim["expires_at"] = (now_dt() + timedelta(seconds=lease)).strftime(TS_FMT)
    claim["lease_seconds"] = lease
    atomic_write(lock_claim_path(ws), json.dumps(claim, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    return {"state": "held", "expires_at": claim["expires_at"]}


def hash_passphrase(passphrase, iterations=DEFAULT_ITERATIONS):
    salt = secrets.token_bytes(32)
    derived = hashlib.pbkdf2_hmac("sha256", passphrase.encode("utf-8"), salt, iterations)
    return {"kdf": DEFAULT_KDF, "salt": salt.hex(), "iterations": int(iterations), "hash": derived.hex()}


def verify_passphrase(passphrase, record):
    try:
        salt = bytes.fromhex(record["salt"])
        iterations = int(record["iterations"])
        expected = record["hash"]
    except (KeyError, ValueError, TypeError):
        fail("bad_auth_record", "Auth-Record ist ungültig")
    derived = hashlib.pbkdf2_hmac("sha256", passphrase.encode("utf-8"), salt, iterations)
    return hmac.compare_digest(derived.hex(), expected)


def create_auth_session(members_doc, handle, passphrase_file, session_file):
    entry = member_entry(members_doc, handle)
    if not entry or entry.get("disabled"):
        fail("permission_denied", f"{handle} hat keine aktive Mitgliedschaft")
    record = entry.get("auth")
    if not record:
        fail("no_auth", f"{handle} hat keine Passphrase gesetzt")
    passphrase = Path(passphrase_file).read_text(encoding="utf-8").rstrip("\n")
    if not verify_passphrase(passphrase, record):
        fail("auth_failed", "Passphrase passt nicht")
    created = now_dt()
    session = {
        "handle": handle,
        "created": created.strftime(TS_FMT),
        "expires": (created + timedelta(seconds=SESSION_TTL_SECONDS)).strftime(TS_FMT),
        "ttl_seconds": SESSION_TTL_SECONDS,
    }
    write_private(Path(session_file), json.dumps(session, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    return {"ok": True, "handle": handle, "created": session["created"], "expires": session["expires"]}


def check_auth_session(ws, action, actor, session_file):
    if action in GATE_EXEMPT_ACTIONS:
        return
    profile = ws.profile()
    auth_cfg = profile.get("auth", {}) or {}
    if not auth_cfg.get("write_gate", True):
        return
    members = ws.members_doc()
    if action == "auth.create-user" and not members.get("members"):
        return
    if effective_role(members, actor) is None:
        fail("permission_denied", f"Akteur {actor} hat keine aktive Mitgliedschaft")
    session_path = Path(session_file) if session_file else None
    if session_path is None or not session_path.is_file():
        fail("auth_required", "Schreiboperationen benötigen eine gültige Auth-Session")
    try:
        session = read_json(session_path)
    except CollabError:
        fail("auth_required", "Auth-Session-Datei ist ungültig")
    if session.get("handle") != actor:
        fail("auth_session_mismatch", "Auth-Session gehört zu einem anderen Mitglied")
    expires = parse_iso(session.get("expires"))
    if not expires or expires <= now_dt():
        fail("auth_session_expired", "Auth-Session abgelaufen")


def make_plan(action, actor, preconditions, ops, events, destructive=False):
    plan = {
        "format": FORMAT,
        "op": uuid.uuid4().hex,
        "action": action,
        "actor": actor,
        "created": now_iso(),
        "preconditions": preconditions,
        "ops": ops,
        "events": events,
        "destructive": destructive,
    }
    plan["plan_sha256"] = sha256_text(canonical_json(plan))
    return plan


def plan_sha256_of(plan):
    return sha256_text(canonical_json({k: v for k, v in plan.items() if k != "plan_sha256"}))


def content_op(action, relpath, content_path):
    data = Path(content_path).read_text(encoding="utf-8")
    return {"action": action, "path": relpath, "content_file": str(content_path), "content_sha256": sha256_text(data)}


def append_event(ws, op, actor, lines):
    if not lines:
        return
    path = ws.events_dir / f"{op}.md"
    if path.exists():
        fail("event_exists", f"Operation bereits protokolliert: {op}")
    header = render_frontmatter({"type": "event", "op": op, "actor": actor, "created": now_iso()}, EVENT_FIELD_ORDER)
    body = "\n".join(f"- {line}" for line in lines) + "\n"
    atomic_write(path, header + "\n" + body)


def append_changes(ws, actor, action, detail=""):
    path = ws.meta / "changes.md"
    line = f"- {now_iso()} {actor} {action}"
    if detail:
        line += f" {detail}"
    line += "\n"
    existing = path.read_text(encoding="utf-8") if path.is_file() else "# Änderungen\n\n"
    atomic_write(path, existing + line)


def emit(obj):
    print(json.dumps(obj, indent=2, sort_keys=True, ensure_ascii=False))


def run_main(fn):
    try:
        emit(fn())
        return 0
    except CollabError as exc:
        emit({"ok": False, "error": exc.code, "message": exc.message})
        return 1


def bump_version(version, bump):
    match = SEMVER_RE.match(version)
    if not match:
        fail("bad_version", f"ungültige Version: {version}")
    major, minor, patch = (int(match.group(i)) for i in (1, 2, 3))
    if bump == "major":
        return f"{major + 1}.0.0"
    if bump == "minor":
        return f"{major}.{minor + 1}.0"
    if bump == "patch":
        return f"{major}.{minor}.{patch + 1}"
    fail("bad_bump", f"ungültiger Bump: {bump}")


def apply_plan(ws, plan, expect_sha256, token_file, session_file=None, ctx=None):
    if plan.get("format") != FORMAT:
        fail("bad_plan", "unbekanntes Plan-Format")
    if not expect_sha256 or not hmac.compare_digest(str(plan.get("plan_sha256", "")), str(expect_sha256)):
        fail("stale_plan", "Plan-Hash weicht vom bestätigten Plan ab")
    verify_claim(ws, token_file)
    actor = plan.get("actor")
    action = plan.get("action")
    if action != "init":
        members = ws.members_doc()
        require_permission(members, actor, action, ctx)
        check_auth_session(ws, action, actor, session_file)
    for relpath, expected in sorted(plan.get("preconditions", {}).items()):
        current = file_hash_or_none(ws.safe_rel(relpath))
        if current != expected:
            fail("stale_plan", f"Voraussetzung geändert: {relpath}")
    tmp = tempfile.mkdtemp(prefix="collabmd-apply-")
    try:
        mirror = Path(tmp) / "mirror"
        shutil.copytree(ws.root, mirror, ignore=shutil.ignore_patterns(".git"))
        for op in plan.get("ops", []):
            relpath = op.get("path", "")
            pure = Path(relpath)
            if not relpath or pure.is_absolute() or ".." in pure.parts:
                fail("unsafe_path", relpath)
            dest = mirror / relpath
            kind = op.get("action")
            if kind in ("create", "update"):
                if kind == "create" and dest.exists():
                    fail("file_exists", relpath)
                if kind == "update" and not dest.exists():
                    fail("file_missing", relpath)
                source = Path(op.get("content_file", ""))
                if op.get("binary"):
                    data_bytes = source.read_bytes()
                    if not hmac.compare_digest(sha256_bytes(data_bytes), str(op.get("content_sha256", ""))):
                        fail("content_mismatch", relpath)
                    atomic_write_bytes(dest, data_bytes)
                else:
                    data = source.read_text(encoding="utf-8")
                    if not hmac.compare_digest(sha256_text(data), str(op.get("content_sha256", ""))):
                        fail("content_mismatch", relpath)
                    atomic_write(dest, data)
            elif kind == "delete":
                if not dest.exists():
                    fail("file_missing", relpath)
                dest.unlink()
            else:
                fail("bad_plan", f"unbekannte Operation: {kind}")
        changed = []
        for op in plan.get("ops", []):
            relpath = op["path"]
            target = ws.safe_rel(relpath)
            if op.get("action") == "delete":
                target.unlink()
                changed.append(f"delete {relpath}")
            else:
                atomic_copy(mirror / relpath, target)
                changed.append(f"{op['action']} {relpath}")
        append_event(ws, plan["op"], actor, plan.get("events", []))
        append_changes(ws, actor, action)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return {
        "applied": True,
        "op": plan["op"],
        "action": action,
        "actor": actor,
        "destructive": bool(plan.get("destructive")),
        "files": changed,
    }
