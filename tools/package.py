#!/usr/bin/env python3
"""Build the installable skill package and its SHA-256 checksum."""
import hashlib
import sys
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SKILL_DIR = ROOT / "collabmd"
DIST = ROOT / "dist"


def build():
    if not (SKILL_DIR / "SKILL.md").is_file():
        print("collabmd/SKILL.md not found; nothing to package", file=sys.stderr)
        return 1
    files = sorted(
        p for p in SKILL_DIR.rglob("*")
        if p.is_file()
        and "__pycache__" not in p.parts
        and p.suffix != ".pyc"
    )
    if not files:
        print("skill directory is empty", file=sys.stderr)
        return 1
    DIST.mkdir(parents=True, exist_ok=True)
    out = DIST / "collabmd.skill"
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as zf:
        for path in files:
            arc = str(path.relative_to(ROOT)).replace("\\", "/")
            info = zipfile.ZipInfo(arc, date_time=(2026, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            zf.writestr(info, path.read_bytes())
    digest = hashlib.sha256(out.read_bytes()).hexdigest()
    (DIST / "collabmd.skill.sha256").write_text(f"{digest}  collabmd.skill\n", encoding="utf-8")
    print(f"packaged {len(files)} files -> {out.relative_to(ROOT)}")
    print(f"sha256 {digest}")
    return 0


if __name__ == "__main__":
    sys.exit(build())
