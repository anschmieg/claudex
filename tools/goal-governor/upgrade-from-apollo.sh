#!/usr/bin/env bash
# Apollo -> Hermes in-place Goal Governor v0.2 hot-upgrade.
# Keeps T3, Claudex and crash-recovery running; only pauses governor timer.
set -euo pipefail
[[ "$(uname -s)" == "Darwin" ]] || { echo "Run on Apollo/macOS" >&2; exit 2; }
REMOTE="${CLAUDEX_REMOTE_HOST:-hermes}"
SOURCE="$(cd "$(dirname "$0")" && pwd -P)"
REMOTE_HOME="$(ssh "$REMOTE" 'printf "%s" "$HOME"')"
[[ "$REMOTE_HOME" = /* && "$REMOTE_HOME" != "/" && "$REMOTE_HOME" != *"'"* && "$REMOTE_HOME" != *$'\n'* ]] || {
  echo "Unexpected remote HOME" >&2; exit 3;
}
DEST="$REMOTE_HOME/.local/src/claudex/goal-governor-upgrade-v02"
ssh "$REMOTE" 'mkdir -p "$HOME/.local/src/claudex/goal-governor-upgrade-v02"'
# Standard POSIX archive omits Apple file xattr metadata. Whitelist payload.
COPYFILE_DISABLE=1 tar --format=ustar -C "$SOURCE" -cf - \
  state.py tasks.py sync.py cli.py supervisor.py \
  test_governor.py test_integration.py test_sync.py test_hook.py \
  upgrade-on-hermes.sh README.md \
  plugin/.claude-plugin/plugin.json plugin/hooks/hooks.json \
  plugin/scripts/session.py plugin/skills/start/SKILL.md \
  plugin/skills/checkpoint/SKILL.md plugin/skills/status/SKILL.md \
  plugin/skills/reconcile/SKILL.md plugin/skills/tasks/SKILL.md | \
  ssh "$REMOTE" "tar -xf - -C '$DEST'"
echo "Staged Governor v0.2. Upgrading with t3-private backup and rollback..."
ssh "$REMOTE" "bash '$DEST/upgrade-on-hermes.sh'"
