#!/usr/bin/env bash
# Read-only post-install health and old Claude Code cron-ID inspection.
# Run on the Mac with the existing SSH alias for Hermes.
set -euo pipefail
[[ "$(uname -s)" == "Darwin" ]] || { echo "Run on Apollo (macOS)" >&2; exit 2; }
REMOTE="${CLAUDEX_REMOTE_HOST:-hermes}"
SRC="$(cd "$(dirname "$0")" && pwd -P)/inspect-on-hermes.py"
[[ -f "$SRC" ]] || { echo "Inspector not found" >&2; exit 2; }
REMOTE_HOME="$(ssh "$REMOTE" 'printf "%s" "$HOME"')"
[[ "$REMOTE_HOME" = /* && "$REMOTE_HOME" != "/" && "$REMOTE_HOME" != *"'"* && "$REMOTE_HOME" != *$'\n'* ]] || {
  echo "Invalid SSH home" >&2; exit 3;
}
DEST="$REMOTE_HOME/.local/src/claudex/recovery-stage-v1"
ssh "$REMOTE" 'mkdir -p "$HOME/.local/src/claudex/recovery-stage-v1"'
scp -q "$SRC" "$REMOTE:$DEST/inspect-on-hermes.py"
ssh "$REMOTE" "sudo -n /usr/bin/python3 '$DEST/inspect-on-hermes.py'"
