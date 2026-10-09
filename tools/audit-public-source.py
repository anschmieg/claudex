#!/usr/bin/env python3
"""Verify a public source commit contains no local state, DevKit bundle or secrets.

This is a fail-closed screening tool, not a legal, security or secret-leak
guarantee. Always review the exact Git tree and historical commits as well.
"""
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BLOCKED_PREFIXES = (
    "bin/", "dist/", "target/", ".build-from-source/",
    ".sideport-cargo/", "artifacts/",
    "source/siwc-helper/vendor/", "source/siwc-helper/node_modules/",
    "source/siwc-helper/dist/",
)
BLOCKED_PATHS = {
    "auth/claudex-siwc.mjs", "auth.json", "chatgpt-auth.json",
    "chatgpt-host.json", ".env", ".env.local",
}
SENSITIVE_SUFFIXES = (".pem", ".key", ".p12", ".p8", ".token", ".pid", ".sse")
SENSITIVE_PATTERNS = (
    (re.compile(rb"/(?:Users|home)/[A-Za-z][A-Za-z0-9_.-]+/"), "private home path"),
    (re.compile(rb"gh[pousr]_[A-Za-z0-9_]{20,}"), "GitHub token"),
    (re.compile(rb"sk-(?:proj-|svcacct-)?[A-Za-z0-9_-]{28,}"), "possible API key"),
    (re.compile(rb"-----BEGIN (?:RSA |OPENSSH |EC )?PRIVATE KEY-----"), "private key"),
    (re.compile(rb"(?i)(?:client_secret|refresh_token)\s*[=:]\s*[\"'][A-Za-z0-9_.-]{36,}"), "credential literal"),
)

proc = subprocess.run(
    ["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True
)
tracked = [p.decode("utf-8") for p in proc.stdout.split(b"\x00") if p]
if not tracked:
    sys.exit("PUBLIC_SOURCE_AUDIT=FAIL empty tracked source tree")

issues = []
for rel in tracked:
    path = ROOT / rel
    if rel in BLOCKED_PATHS or rel.endswith(SENSITIVE_SUFFIXES):
        issues.append((rel, "blocked private file"))
        continue
    if rel.startswith(BLOCKED_PREFIXES) or any("/"+p in rel for p in BLOCKED_PREFIXES):
        issues.append((rel, "blocked generated/vendor path"))
        continue
    if path.is_symlink() or not path.is_file():
        issues.append((rel, "unsafe non-file or symlink"))
        continue
    if path.stat().st_size > 450_000:
        issues.append((rel, "unexpected large file"))
        continue
    raw = path.read_bytes()
    if b"\x00" in raw:
        issues.append((rel, "binary source asset"))
        continue
    for expression, name in SENSITIVE_PATTERNS:
        if expression.search(raw):
            issues.append((rel, name))

for name in ("LICENSE", "README.md", "NOTICE.md", "THIRD_PARTY_LICENSES.md",
             "SECURITY.md", "auth/SIWC-DEVKIT-LICENSE",
             ".github/workflows/native-build.yml"):
    if name not in tracked:
        issues.append((name, "required public disclosure absent"))

workflow = (ROOT / ".github/workflows/native-build.yml").read_text()
for forbidden in ("upload-artifact@", "gh release create", "npm publish",
                  "cargo publish", "gh repo create", "GH_TOKEN:", "secrets."):
    if forbidden in workflow:
        issues.append((".github/workflows/native-build.yml", "publishing/secret-bearing workflow action"))

if issues:
    for path, reason in issues:
        print(f"PUBLIC_SOURCE_AUDIT=FAIL file={path!r} reason={reason}")
    sys.exit(1)

print(f"PUBLIC_SOURCE_AUDIT=PASS tracked_files={len(tracked)}")
print("NO_DEVKIT_VENDOR_OR_DISTRIBUTABLE_BUNDLE=PASS")
print("NO_COMMITTED_CREDENTIALS_BINARIES_OR_RELEASE_AUTOMATION=PASS")
