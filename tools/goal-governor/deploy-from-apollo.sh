#!/usr/bin/env bash
# Run on Apollo, using the existing ssh hermes alias; copies only versioned files.
set -euo pipefail
[[ "$(uname -s)" == Darwin ]] || { echo "Run on Apollo/macOS" >&2;exit 2; }
REMOTE="${CLAUDEX_REMOTE_HOST:-hermes}"
SOURCE="$(cd "$(dirname "$0")" && pwd -P)"
HOME_REMOTE="$(ssh "$REMOTE" 'printf "%s" "$HOME"')"
[[ "$HOME_REMOTE" = /* && "$HOME_REMOTE" != "/" && "$HOME_REMOTE" != *"'"* && "$HOME_REMOTE" != *$'\n'* ]] || exit 3
DEST="$HOME_REMOTE/.local/src/claudex/goal-governor-stage-v1"
ssh "$REMOTE" 'mkdir -p "$HOME/.local/src/claudex/goal-governor-stage-v1"'
# Tar includes only approved payload paths, not the untracked workspace.
tar -C "$SOURCE" -cf - \
  state.py cli.py supervisor.py run-governor.sh \
  test_governor.py test_integration.py \
  claudex-governor.service claudex-governor.timer \
  install-on-hermes.sh activate-goal-on-hermes.sh README.md \
  plugin/.claude-plugin/plugin.json plugin/hooks/hooks.json \
  plugin/scripts/session.py \
  plugin/skills/start/SKILL.md \
  plugin/skills/checkpoint/SKILL.md \
  plugin/skills/status/SKILL.md | \
  ssh "$REMOTE" "tar -xf - -C '$DEST'"
ssh "$REMOTE" "bash '$DEST/install-on-hermes.sh'"
