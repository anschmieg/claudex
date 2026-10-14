#!/usr/bin/env bash
# Goal Governor v0.2 in-place upgrade. No T3, Claudex or failure-recovery restart.
set -Eeuo pipefail
TARGET_USER="${CLAUDEX_TARGET_USER:-t3}"
TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"
TARGET_GROUP="$(id -gn "$TARGET_USER")"
[[ "$TARGET_HOME" = /* && "$TARGET_HOME" != "/" && -d "$TARGET_HOME" ]] || exit 3
SOURCE="$(cd "$(dirname "$0")" && pwd -P)"
BASE="$TARGET_HOME/.local/share/claudex/goal-governor"
PLUGIN="$TARGET_HOME/.claude/skills/goal-governor"
STATE="$TARGET_HOME/.local/state/claudex-governor"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
BACKUP="$STATE/backups/upgrade-$STAMP"
USER_PATH="$TARGET_HOME/.local/bin:$TARGET_HOME/.npm-global/bin:/usr/local/bin:/usr/bin:/bin"
TIMER="claudex-governor.timer"
SERVICE="claudex-governor.service"
MUTATED=false
PAUSED=false
SUCCESS=false

cleanup() {
  local status=$?
  trap - EXIT
  if [[ "$SUCCESS" == true ]]; then return 0; fi
  echo "Governor upgrade failed; restoring previous code and timer..." >&2
  if [[ "$MUTATED" == true ]]; then
    for file in state.py cli.py supervisor.py; do
      if sudo -n test -f "$BACKUP/runtime/$file"; then
        sudo -n install -o "$TARGET_USER" -g "$TARGET_GROUP" -m 0644 "$BACKUP/runtime/$file" "$BASE/$file" || true
      fi
    done
    for file in .claude-plugin/plugin.json hooks/hooks.json scripts/session.py \
       skills/start/SKILL.md skills/checkpoint/SKILL.md skills/status/SKILL.md; do
      if sudo -n test -f "$BACKUP/plugin/$file"; then
        sudo -n install -o "$TARGET_USER" -g "$TARGET_GROUP" -m 0644 "$BACKUP/plugin/$file" "$PLUGIN/$file" || true
      fi
    done
  fi
  if [[ "$PAUSED" == true ]]; then
    sudo -n systemctl --machine="$TARGET_USER@.host" --user start "$TIMER" || true
  fi
  echo "Protected browser operations, T3 threads and external credentials were not altered." >&2
  exit "$status"
}
trap cleanup EXIT

# Run isolated tests before touching installed files or user state.
for file in state.py tasks.py sync.py cli.py supervisor.py \
  test_governor.py test_integration.py test_sync.py test_hook.py; do
  test -f "$SOURCE/$file"
done
for file in .claude-plugin/plugin.json hooks/hooks.json scripts/session.py \
  skills/start/SKILL.md skills/checkpoint/SKILL.md skills/status/SKILL.md \
  skills/reconcile/SKILL.md skills/tasks/SKILL.md; do
  test -f "$SOURCE/plugin/$file"
done
for suite in test_governor.py test_integration.py test_sync.py test_hook.py; do
  PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 "$SOURCE/$suite" >/dev/null
done

sudo -n test -f "$BASE/supervisor.py"
sudo -n test -f "$STATE/ledger.json"
sudo -n systemctl --machine="$TARGET_USER@.host" --user is-active claudex-recovery.timer >/dev/null
sudo -n systemctl --machine="$TARGET_USER@.host" --user is-active t3code.service >/dev/null
sudo -n systemctl --machine="$TARGET_USER@.host" --user is-active "$TIMER" >/dev/null

# Stop only the governor TIMER; let any active oneshot complete naturally.
sudo -n systemctl --machine="$TARGET_USER@.host" --user stop "$TIMER"
PAUSED=true
for iteration in 1 2 3 4 5 6 7 8 9 10; do
  phase="$(sudo -n systemctl --machine="$TARGET_USER@.host" --user is-active "$SERVICE" 2>/dev/null || true)"
  [[ "$phase" != "active" && "$phase" != "activating" ]] && break
  sleep 2
done
[[ "$phase" != "active" && "$phase" != "activating" ]] || {
  echo "An active governor check did not finish; aborting without terminating it." >&2
  exit 5
}

# Save original runtime/plugin and durable goal history under t3-owned 0700.
sudo -n install -d -o "$TARGET_USER" -g "$TARGET_GROUP" -m 0700 "$STATE/backups"
sudo -n install -d -o "$TARGET_USER" -g "$TARGET_GROUP" -m 0700 "$BACKUP/runtime"
sudo -n install -d -o "$TARGET_USER" -g "$TARGET_GROUP" -m 0700 "$BACKUP/plugin"
sudo -n install -d -o "$TARGET_USER" -g "$TARGET_GROUP" -m 0700 "$BACKUP/state"
for file in state.py cli.py supervisor.py; do
  sudo -n cp -p "$BASE/$file" "$BACKUP/runtime/$file"
done
for file in .claude-plugin/plugin.json hooks/hooks.json scripts/session.py \
  skills/start/SKILL.md skills/checkpoint/SKILL.md skills/status/SKILL.md; do
  sudo -n install -d -o "$TARGET_USER" -g "$TARGET_GROUP" -m 0700 "$BACKUP/plugin/$(dirname "$file")"
  sudo -n cp -p "$PLUGIN/$file" "$BACKUP/plugin/$file"
done
sudo -n cp -p "$STATE/ledger.json" "$BACKUP/state/ledger.json"
sudo -n cp -p -R "$STATE/goals" "$BACKUP/state/goals"
MUTATED=true

# Install the upgrade beside originals and atomically replace each module.
atomic_install() {
  local src="$1" dst="$2" mode="$3"
  local pending="$dst.upgrade-$STAMP"
  sudo -n install -o "$TARGET_USER" -g "$TARGET_GROUP" -m "$mode" "$src" "$pending"
  sudo -n mv "$pending" "$dst"
  sudo -n cmp "$src" "$dst"
}
for file in state.py tasks.py sync.py cli.py supervisor.py; do
  atomic_install "$SOURCE/$file" "$BASE/$file" 0644
done
for dir in skills/reconcile skills/tasks; do
  sudo -n install -d -o "$TARGET_USER" -g "$TARGET_GROUP" -m 0755 "$PLUGIN/$dir"
done
for file in .claude-plugin/plugin.json hooks/hooks.json scripts/session.py \
  skills/start/SKILL.md skills/checkpoint/SKILL.md skills/status/SKILL.md \
  skills/reconcile/SKILL.md skills/tasks/SKILL.md; do
  atomic_install "$SOURCE/plugin/$file" "$PLUGIN/$file" 0644
done

CLAUDE="$TARGET_HOME/.npm-global/bin/claude"
sudo -n test -x "$CLAUDE"
sudo -n runuser -u "$TARGET_USER" -- env HOME="$TARGET_HOME" USER="$TARGET_USER" PATH="$USER_PATH" \
  "$CLAUDE" plugin validate "$PLUGIN"

# Reads existing T3 projections but never dispatches a command in dry-run.
sudo -n runuser -u "$TARGET_USER" -- env HOME="$TARGET_HOME" USER="$TARGET_USER" PATH="$USER_PATH" \
  PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 "$BASE/supervisor.py"

# Preserve enabled state and existing trigger cadence.
sudo -n systemctl --machine="$TARGET_USER@.host" --user start "$TIMER"
sudo -n systemctl --machine="$TARGET_USER@.host" --user is-active "$TIMER" >/dev/null
PAUSED=false
SUCCESS=true
echo "GOAL_GOVERNOR_V02_UPGRADED=PASS"
echo "RECOVERY_TIMER_AND_T3_UNCHANGED=PASS"
echo "GOVERNOR_TIMER_RESUMED=PASS"
echo "Original durable ledger and goal JSON preserved; backup in t3 private state."
