#!/usr/bin/env bash
# Run from Apollo's local Terminal (Darwin), not in an SSH session.
set -euo pipefail
THREAD="${1:?Usage: bash tools/recovery/deploy-from-apollo.sh <T3 thread UUID>}"
[[ "$THREAD" =~ ^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$ ]] || { echo "Invalid thread UUID" >&2; exit 2; }
[[ "$(uname -s)" == "Darwin" ]] || { echo "Run this on the local macOS host." >&2; exit 2; }
REMOTE="${CLAUDEX_REMOTE_HOST:-hermes}"
SOURCE="$(cd "$(dirname "$0")" && pwd -P)"
for file in controller.py test_controller.py test_transport.py test_crash_guard.py \
  claudex-recovery.service claudex-recovery.timer README.md install-on-hermes.sh; do
  test -f "$SOURCE/$file" || { echo "Missing $SOURCE/$file" >&2; exit 3; }
done

echo "Connecting to existing SSH host: $REMOTE"
REMOTE_HOME="$(ssh "$REMOTE" 'printf "%s" "$HOME"')"
[[ "$REMOTE_HOME" = /* && "$REMOTE_HOME" != "/" && "$REMOTE_HOME" != *"'"* ]] || {
  echo "Invalid remote home path" >&2; exit 4;
}
REMOTE_DIR="$REMOTE_HOME/.local/src/claudex/recovery-stage-v1"
ssh "$REMOTE" 'mkdir -p "$HOME/.local/src/claudex/recovery-stage-v1"'
echo "Staging isolated tested recovery source on $REMOTE..."
scp -q "$SOURCE"/controller.py "$SOURCE"/test_controller.py "$SOURCE"/test_transport.py \
    "$SOURCE"/test_crash_guard.py "$SOURCE"/claudex-recovery.service \
    "$SOURCE"/claudex-recovery.timer "$SOURCE"/README.md "$SOURCE"/install-on-hermes.sh \
    "$REMOTE:$REMOTE_DIR/"
echo "Installing independently supervised recovery; T3 Code is not restarted."
ssh "$REMOTE" "bash '$REMOTE_DIR/install-on-hermes.sh' '$THREAD'"
