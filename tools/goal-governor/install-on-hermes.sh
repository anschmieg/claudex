#!/usr/bin/env bash
# Install Goal Governor alongside Claudex; no core edits or automatic activation.
set -euo pipefail
TARGET_USER="${CLAUDEX_TARGET_USER:-t3}"
TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"
TARGET_GROUP="$(id -gn "$TARGET_USER")"
[[ "$TARGET_HOME" = /* && "$TARGET_HOME" != "/" && -d "$TARGET_HOME" ]] || exit 3
SOURCE="$(cd "$(dirname "$0")" && pwd -P)"
RUNTIME="$TARGET_HOME/.local/share/claudex/goal-governor"
PLUGIN="$TARGET_HOME/.claude/skills/goal-governor"
UNIT_DIR="$TARGET_HOME/.config/systemd/user"
USER_PATH="$TARGET_HOME/.local/bin:$TARGET_HOME/.npm-global/bin:/usr/local/bin:/usr/bin:/bin"

for f in state.py cli.py supervisor.py test_governor.py test_integration.py;do
  test -f "$SOURCE/$f" || { echo "Missing governor file: $f" >&2;exit 4; }
done
PYTHONDONTWRITEBYTECODE=1 python3 "$SOURCE/test_governor.py" >/dev/null
PYTHONDONTWRITEBYTECODE=1 python3 "$SOURCE/test_integration.py" >/dev/null
sudo -n systemctl --machine="$TARGET_USER@.host" --user is-active t3code.service >/dev/null
sudo -n systemctl --machine="$TARGET_USER@.host" --user is-active claudex-recovery.timer >/dev/null
sudo -n test -f "$TARGET_HOME/.local/share/claudex/recovery/controller.py"
sudo -n test -f "$TARGET_HOME/.local/state/claudex-recovery/config.json"

# No replacing unrelated plugins or symlinked user locations.
if sudo -n test -L "$PLUGIN" || sudo -n test -L "$RUNTIME";then
  echo "Refusing symlinked governor installation target" >&2;exit 5
fi
sudo -n install -d -o "$TARGET_USER" -g "$TARGET_GROUP" -m 0755 "$RUNTIME"
sudo -n install -d -o "$TARGET_USER" -g "$TARGET_GROUP" -m 0755 "$UNIT_DIR"
for f in state.py cli.py supervisor.py;do
  sudo -n install -o "$TARGET_USER" -g "$TARGET_GROUP" -m 0644 "$SOURCE/$f" "$RUNTIME/$f"
done
sudo -n install -o "$TARGET_USER" -g "$TARGET_GROUP" -m 0755 "$SOURCE/run-governor.sh" "$RUNTIME/run-governor.sh"
for f in claudex-governor.service claudex-governor.timer;do
  sudo -n install -o "$TARGET_USER" -g "$TARGET_GROUP" -m 0644 "$SOURCE/$f" "$UNIT_DIR/$f"
done

# Install Claude Code plugin as a self-contained namespaced user plugin.
for dir in .claude-plugin hooks scripts skills/start skills/checkpoint skills/status;do
  sudo -n install -d -o "$TARGET_USER" -g "$TARGET_GROUP" -m 0755 "$PLUGIN/$dir"
done
for f in .claude-plugin/plugin.json hooks/hooks.json scripts/session.py \
    skills/start/SKILL.md skills/checkpoint/SKILL.md skills/status/SKILL.md;do
  sudo -n install -o "$TARGET_USER" -g "$TARGET_GROUP" -m 0644 "$SOURCE/plugin/$f" "$PLUGIN/$f"
done

# Validate the package using the actual installed t3 Claude Code version,
# not only the Apollo development CLI. A mismatch blocks timer installation.
CLAUDE_CLI="$TARGET_HOME/.npm-global/bin/claude"
if ! sudo -n test -x "$CLAUDE_CLI"; then
  echo "Target Claude Code executable not found" >&2; exit 5
fi
sudo -n runuser -u "$TARGET_USER" -- env HOME="$TARGET_HOME" USER="$TARGET_USER" PATH="$USER_PATH" \
  "$CLAUDE_CLI" plugin validate "$PLUGIN"

# Dry-run and real sandbox smoke with NO enrolled goals and NO LLM dispatch.
sudo -n runuser -u "$TARGET_USER" -- env HOME="$TARGET_HOME" USER="$TARGET_USER" PATH="$USER_PATH" \
  /usr/bin/python3 "$RUNTIME/supervisor.py"
sudo -n systemctl --machine="$TARGET_USER@.host" --user daemon-reload
sudo -n systemctl --machine="$TARGET_USER@.host" --user start claudex-governor.service
# Intentionally do not enable the goal timer yet. Current T3 cron and goal
# acceptance must first be reconciled, to avoid competing writers.
TIMER_STATE="$(sudo -n systemctl --machine="$TARGET_USER@.host" --user is-enabled claudex-governor.timer 2>/dev/null || true)"
if [[ "$TIMER_STATE" == "enabled" ]]; then
  echo "The governor timer is already enabled; refusing to overwrite its policy." >&2
  exit 6
fi
echo "CLAUDEX_GOAL_GOVERNOR_INSTALLED=PASS"
echo "GOAL_GOVERNOR_TIMER_DISABLED=PASS"
echo "No Claudex, T3 Code, or browser provider process was restarted."
