#!/usr/bin/env python3
"""Maintenance lock for CollabMD workspaces."""
import argparse
import hmac
import sys

import collabmd_common as C


def acquire(args):
    ws = C.Workspace(args.target)
    maintainer = args.maintainer or C.default_maintainer()
    return C.acquire_lock(ws, args.owner, maintainer, args.operation, args.token_file, args.lease_seconds)


def release(args):
    ws = C.Workspace(args.target)
    return C.release_lock(ws, args.token_file)


def verify(args):
    ws = C.Workspace(args.target)
    claim_path = C.lock_claim_path(ws)
    if not claim_path.is_file():
        return {"state": "missing"}
    claim = C.read_json(claim_path)
    expires = C.parse_iso(claim.get("expires_at"))
    base = {
        "maintainer": claim.get("maintainer"),
        "owner": claim.get("owner"),
        "operation": claim.get("operation"),
        "acquired_at": claim.get("acquired_at"),
        "expires_at": claim.get("expires_at"),
    }
    if not expires or expires <= C.now_dt():
        return {"state": "expired", **base}
    try:
        token = C.read_token(args.token_file)
    except C.CollabError:
        return {"state": "held", "token_verified": False, **base}
    if not hmac.compare_digest(claim.get("token_sha256", ""), C.sha256_text(token)):
        return {"state": "held", "token_verified": False, **base}
    return {"state": "held", "token_verified": True, **base}


def heartbeat(args):
    ws = C.Workspace(args.target)
    return C.heartbeat_lock(ws, args.token_file, args.lease_seconds)


def main():
    parser = argparse.ArgumentParser(prog="wiki_lock.py")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("acquire")
    p.add_argument("--target", required=True)
    p.add_argument("--owner", required=True)
    p.add_argument("--operation", required=True)
    p.add_argument("--token-file", required=True)
    p.add_argument("--maintainer", default=None)
    p.add_argument("--lease-seconds", type=int, default=C.LOCK_LEASE_SECONDS)
    for name in ("release", "verify"):
        p = sub.add_parser(name)
        p.add_argument("--target", required=True)
        p.add_argument("--token-file", required=True)
    p = sub.add_parser("heartbeat")
    p.add_argument("--target", required=True)
    p.add_argument("--token-file", required=True)
    p.add_argument("--lease-seconds", type=int, default=None)
    args = parser.parse_args()
    handlers = {"acquire": acquire, "release": release, "verify": verify, "heartbeat": heartbeat}
    return C.run_main(lambda: handlers[args.command](args))


if __name__ == "__main__":
    sys.exit(main())
