#!/usr/bin/env python3
"""Detect and redact credentials in workspace content."""
import argparse
import re
import sys
from pathlib import Path

import collabmd_common as C

PATTERNS = (
    ("github-token", re.compile(r"\bgh[pousr]_[A-Za-z0-9]{16,}\b")),
    ("openai-key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}\b")),
    ("aws-access-key-id", re.compile(r"\bAKIA[0-9A-Z]{16}\b")),
    ("slack-token", re.compile(r"\bxox[baprs]-[A-Za-z0-9-]{10,}\b")),
    ("private-key-block", re.compile(r"-----BEGIN [A-Z0-9 ]*PRIVATE KEY-----[\s\S]*?-----END [A-Z0-9 ]*PRIVATE KEY-----")),
    ("bearer-token", re.compile(r"\bBearer\s+[A-Za-z0-9._~+/=-]{20,}\b")),
    ("credential-assignment", re.compile(r"(?i)\b(password|passwd|secret|api[_-]?key|token)\b\s*[:=]\s*['\"][^'\"]{8,}['\"]")),
)


def scan(text):
    hits = []
    for kind, pattern in PATTERNS:
        for match in pattern.finditer(text):
            hits.append({"kind": kind, "start": match.start(), "end": match.end()})
    hits.sort(key=lambda h: (h["start"], h["end"]))
    return hits


def redact(text):
    out = text
    count = 0
    for _, pattern in PATTERNS:
        out, n = pattern.subn("[credential removed]", out)
        count += n
    return out, count


def main():
    parser = argparse.ArgumentParser(prog="secret_screen.py")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("scan")
    p.add_argument("--file", required=True)
    p = sub.add_parser("redact")
    p.add_argument("--file", required=True)
    p.add_argument("--output", required=True)
    args = parser.parse_args()

    def run():
        text = Path(args.file).read_text(encoding="utf-8")
        if args.command == "scan":
            hits = scan(text)
            return {"ok": True, "hits": len(hits), "kinds": sorted({h["kind"] for h in hits})}
        out, count = redact(text)
        C.atomic_write(args.output, out)
        return {"ok": True, "redacted": count}

    return C.run_main(run)


if __name__ == "__main__":
    sys.exit(main())
