#!/usr/bin/env bash
# Run on the remote machine as an operator with passwordless sudo.
set -euo pipefail
THREAD="${1:?Usage: install-on-hermes.sh <T3 thread UUID>}"
[[ "$THREAD" =~ ^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$ ]] || { echo "Invalid thread ID" >&2; exit 2; }

TARGET_USER="${CLAUDEX_TARGET_USER:-t3}"
TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"
TARGET_GROUP="$(id -gn "$TARGET_USER")"
[[ "$TARGET_HOME" = /* && "$TARGET_HOME" != "/" && -d "$TARGET_HOME" ]] || {
  echo "Target user has no valid home" >&2; exit 3;
}
SOURCE="$(cd "$(dirname "$0")" && pwd -P)"
TARGET="$TARGET_HOME/.local/share/claudex/recovery"
UNIT_DIR="$TARGET_HOME/.config/systemd/user"
RUN_PY="$TARGET/controller.py"
STATE="$TARGET_HOME/.local/state/claudex-recovery/config.json"

for suite in test_controller.py test_transport.py test_crash_guard.py; do
  test -f "$SOURCE/$suite" || exit 4
  PYTHONDONTWRITEBYTECODE=1 python3 "$SOURCE/$suite" >/dev/null || exit 4
done
for file in controller.py README.md claudex-recovery.service claudex-recovery.timer; do
  test -f "$SOURCE/$file" || exit 4
done

sudo -n systemctl --machine="$TARGET_USER@.host" --user is-active t3code.service >/dev/null
sudo -n test -d "$TARGET_HOME/.t3/userdata"
sudo -n install -d -o "$TARGET_USER" -g "$TARGET_GROUP" -m 0755 "$TARGET"
sudo -n install -d -o "$TARGET_USER" -g "$TARGET_GROUP" -m 0755 "$UNIT_DIR"
for file in controller.py README.md; do
  sudo -n install -o "$TARGET_USER" -g "$TARGET_GROUP" -m 0644 "$SOURCE/$file" "$TARGET/$file"
done
for file in claudex-recovery.service claudex-recovery.timer; do
  sudo -n install -o "$TARGET_USER" -g "$TARGET_GROUP" -m 0644 "$SOURCE/$file" "$UNIT_DIR/$file"
done
sudo -n cmp "$SOURCE/controller.py" "$TARGET/controller.py"

# Only errors after enrollment can ever cause an automatic turn.
if sudo -n test -f "$STATE"; then
  echo "Existing recovery enrollment: refusing to overwrite."
else
  sudo -n runuser -u "$TARGET_USER" -- env HOME="$TARGET_HOME" USER="$TARGET_USER" PATH=/usr/bin:/bin \
    python3 "$RUN_PY" --enroll-thread "$THREAD"
fi

# Dry-run cannot create recovery intents or send T3 commands.
sudo -n runuser -u "$TARGET_USER" -- env HOME="$TARGET_HOME" USER="$TARGET_USER" PATH=/usr/bin:/bin \
  python3 "$RUN_PY" --once

# Ensure the exact runtime user can load the WebSocket client before a
# background failure would need it; do not run the app with operator privileges.
sudo -n runuser -u "$TARGET_USER" -- env HOME="$TARGET_HOME" USER="$TARGET_USER" PATH=/usr/bin:/bin \
  python3 -c 'import websockets; print("T3_RECOVERY_WEBSOCKETS=PASS")'

# Short-lived credential remains in local process memory; no token is logged.
echo "Checking authenticated local T3 read endpoint..."
sudo -n runuser -u "$TARGET_USER" -- env HOME="$TARGET_HOME" USER="$TARGET_USER" PATH=/usr/bin:/bin \
  python3 "$RUN_PY" --probe-auth

sudo -n systemctl --machine="$TARGET_USER@.host" --user daemon-reload
# Verify the same sandboxed oneshot that the timer will run. If this fails,
# leave the timer disabled and preserve all T3 agent processes unmodified.
sudo -n systemctl --machine="$TARGET_USER@.host" --user start claudex-recovery.service
sudo -n systemctl --machine="$TARGET_USER@.host" --user enable --now claudex-recovery.timer
sudo -n systemctl --machine="$TARGET_USER@.host" --user is-active claudex-recovery.timer
echo "T3_CLAUDEX_RECOVERY_TIMER_ACTIVE=PASS"
echo "T3 Code and Claudex processes were not restarted."
