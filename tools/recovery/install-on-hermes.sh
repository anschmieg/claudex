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
RUN_WRAPPER="$TARGET/run-controller.sh"
STATE_ROOT="$TARGET_HOME/.local/state/claudex-recovery"
STATE="$TARGET_HOME/.local/state/claudex-recovery/config.json"

for suite in test_controller.py test_transport.py test_crash_guard.py; do
  test -f "$SOURCE/$suite" || exit 4
  PYTHONDONTWRITEBYTECODE=1 python3 "$SOURCE/$suite" >/dev/null || exit 4
done
for file in controller.py run-controller.sh README.md claudex-recovery.service claudex-recovery.timer; do
  test -f "$SOURCE/$file" || exit 4
done

sudo -n systemctl --machine="$TARGET_USER@.host" --user is-active t3code.service >/dev/null
sudo -n test -d "$TARGET_HOME/.t3/userdata"
sudo -n install -d -o "$TARGET_USER" -g "$TARGET_GROUP" -m 0755 "$TARGET"
sudo -n install -d -o "$TARGET_USER" -g "$TARGET_GROUP" -m 0755 "$UNIT_DIR"
for file in controller.py README.md; do
  sudo -n install -o "$TARGET_USER" -g "$TARGET_GROUP" -m 0644 "$SOURCE/$file" "$TARGET/$file"
done
sudo -n install -o "$TARGET_USER" -g "$TARGET_GROUP" -m 0755 "$SOURCE/run-controller.sh" "$RUN_WRAPPER"
for file in claudex-recovery.service claudex-recovery.timer; do
  sudo -n install -o "$TARGET_USER" -g "$TARGET_GROUP" -m 0644 "$SOURCE/$file" "$UNIT_DIR/$file"
done
sudo -n cmp "$SOURCE/controller.py" "$TARGET/controller.py"

# Resolve uv as t3, never use operator or root Python package environments.
# This is a user-owned ephemeral dependency cache, not a persistent venv.
UV_PATH="$(sudo -n runuser -u "$TARGET_USER" -- env HOME="$TARGET_HOME" USER="$TARGET_USER" PATH="$TARGET_HOME/.local/bin:$TARGET_HOME/.cargo/bin:/usr/local/bin:/usr/bin:/bin" bash -c 'command -v uv' 2>/dev/null || true)"
[[ -n "$UV_PATH" && "$UV_PATH" = /* ]] || {
  echo "uv not found for the target user; timer stays disabled." >&2
  exit 5
}

# Only errors after enrollment can ever cause an automatic turn.
if sudo -n test -f "$STATE"; then
  echo "Existing recovery enrollment: refusing to overwrite."
else
  sudo -n runuser -u "$TARGET_USER" -- env HOME="$TARGET_HOME" USER="$TARGET_USER" PATH=/usr/bin:/bin \
    "$PY" "$RUN_PY" --enroll-thread "$THREAD"
fi

# Prime pinned dependencies once while the network is available, then always
# use --offline via the same wrapper in the sandboxed systemd timer.
sudo -n runuser -u "$TARGET_USER" -- env HOME="$TARGET_HOME" USER="$TARGET_USER" \
  PATH="$TARGET_HOME/.local/bin:$TARGET_HOME/.cargo/bin:/usr/local/bin:/usr/bin:/bin" \
  UV_CACHE_DIR="$STATE_ROOT/uv-cache" UV_PYTHON_DOWNLOADS=never \
  "$UV_PATH" run --no-project --no-managed-python --python /usr/bin/python3 \
    --with 'websockets==16.0' python -c \
    'import websockets; assert websockets.__version__ == "16.0"; print("T3_RECOVERY_UV_PREFETCH=PASS")'

# Dry-run must not write an intent or send any recovery command.
sudo -n runuser -u "$TARGET_USER" -- env HOME="$TARGET_HOME" USER="$TARGET_USER" \
  PATH="$TARGET_HOME/.local/bin:$TARGET_HOME/.cargo/bin:/usr/local/bin:/usr/bin:/bin" \
  "$RUN_WRAPPER" --once

# Read-only authentication check. No token is logged or stored.
echo "Checking authenticated local T3 read endpoint..."
sudo -n runuser -u "$TARGET_USER" -- env HOME="$TARGET_HOME" USER="$TARGET_USER" \
  PATH="$TARGET_HOME/.local/bin:$TARGET_HOME/.cargo/bin:/usr/local/bin:/usr/bin:/bin" \
  "$RUN_WRAPPER" --probe-auth

sudo -n systemctl --machine="$TARGET_USER@.host" --user daemon-reload
# Verify the same sandboxed oneshot that the timer will run. If this fails,
# leave the timer disabled and preserve all T3 agent processes unmodified.
sudo -n systemctl --machine="$TARGET_USER@.host" --user start claudex-recovery.service
sudo -n systemctl --machine="$TARGET_USER@.host" --user enable --now claudex-recovery.timer
sudo -n systemctl --machine="$TARGET_USER@.host" --user is-active claudex-recovery.timer
echo "T3_CLAUDEX_RECOVERY_TIMER_ACTIVE=PASS"
echo "T3 Code and Claudex processes were not restarted."
