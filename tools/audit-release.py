#!/usr/bin/env python3
"""Reject personal absolute paths in public release trees."""
import argparse
import re
from pathlib import Path

parser = argparse.ArgumentParser()
parser.add_argument("package", type=Path)
parser.add_argument("--forbid", action="append", default=[],
                    help="additional private string to scan for at release time")
args = parser.parse_args()
root = args.package.resolve()
if not root.is_dir():
    parser.error("package must be a directory")

prefixes = {str(Path.home()), *args.forbid}
prefixes = {p.encode() for p in prefixes if p and len(p) >= 5}
account_home = re.compile(rb"/(?:Users|home)/[A-Za-z0-9_.-]{2,}/")
found = []
checked = 0
for path in sorted(root.rglob("*")):
    if not path.is_file() or path.name == "SHA256SUMS":
        continue
    checked += 1
    data = path.read_bytes()
    if any(p in data for p in prefixes) or account_home.search(data):
        found.append(str(path.relative_to(root)))
if found:
    print("DIST_AUDIT=FAIL")
    for name in found:
        print("FILE:", name)
    raise SystemExit(1)
print(f"DIST_AUDIT=PASS files_checked={checked}")
