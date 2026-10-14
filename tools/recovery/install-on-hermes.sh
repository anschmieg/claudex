#!/usr/bin/env bash
# Run on Hermes as the existing operator with passwordless sudo.
# Installs the recovery worker for the separate t3 account, no T3 restarts.
set -euo pipefail
THREAD="${1:?Usage: install-on-hermes.sh <T3 thread UUID>}"
[[ "$THREAD" =~ ^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$ ]] || {
  echo "Invalid thread UUID" >&2; exit 2;
}

TARGET_USER="${CLAUDEX_TARGET_USER:-t3}"
TARGET_HOME="$(getent passwd "$TARGET_USER" | cut -d: -f6)"
TARGET_GROUP="$(id -gn "$TARGET_USER")"
[[ "$TARGET_HOME" = /* && "$TARGET_HOME" != "/" && -d "$TARGET_HOME" ]] || {
  echo "Invalid target account home" >&2; exit 3;
}
SOURCE="$(cd "$(dirname "$0")" && pwd -P)"
TARGET="$TARGET_HOME/.local/share/claudex/recovery"
UNIT_DIR="$TARGET_HOME/.config/systemd/user"
RUN_PY="$TARGET/controller.py"
RUN_WRAPPER="$TARGET/run-controller.sh"
STATE_ROOT="$TARGET_HOME/.local/state/claudex-recovery"
STATE="$STATE_ROOT/config.json"
USER_PATH="$TARGET_HOME/.local/bin:$TARGET_HOME/.cargo/bin:/usr/local/bin:/usr/bin:/bin"

for suite in test_controller.py test_transport.py test_crash_guard.py; do
  test -f "$SOURCE/$suite" || exit 4
  PYTHONDONTWRITEBYTECODE=1 python3 "$SOURCE/$suite" >/dev/null
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
sudo -n cmp "$SOURCE/controller.py" "$RUN_PY"

# Resolve uv as the service user. If only the operator has uv, copy that
# existing executable to t3-owned ~/.local/bin, without system package changes.
UV_PATH="$(sudo -n runuser -u "$TARGET_USER" -- env HOME="$TARGET_HOME" USER="$TARGET_USER" PATH="$USER_PATH" bash -c 'command -v uv' 2>/dev/null || true)"
if [[ -z "$UV_PATH" || "$UV_PATH" != /* ]]; then
  OPERATOR_UV="$(command -v uv 2>/dev/null || true)"
  if [[ "$OPERATOR_UV" != /* || ! -f "$OPERATOR_UV" || ! -x "$OPERATOR_UV" ]]; then
    OPERATOR_UV=""
    for candidate in "$HOME/.local/bin/uv" "$HOME/.cargo/bin/uv" /usr/local/bin/uv /usr/bin/uv; do
      if [[ -f "$candidate" && -x "$candidate" ]]; then OPERATOR_UV="$candidate"; break; fi
    done
  fi
  if [[ -z "$OPERATOR_UV" || ! -f "$OPERATOR_UV" || ! -x "$OPERATOR_UV" ]]; then
    echo "uv not found for either account; recovery timer remains disabled." >&2
    exit 5
  fi
  UV_PATH="$TARGET_HOME/.local/bin/uv"
  if sudo -n test -e "$UV_PATH" || sudo -n test -L "$UV_PATH"; then
    echo "Existing but unusable t3 uv path; refusing to overwrite it." >&2
    exit 5
  fi
  if sudo -n test -L "$TARGET_HOME/.local/bin"; then
    echo "Refusing symlinked target executable directory." >&2
    exit 5
  fi
  echo "Copying existing operator uv into t3's private executable directory..."
  sudo -n install -d -o "$TARGET_USER" -g "$TARGET_GROUP" -m 0755 "$TARGET_HOME/.local/bin"
  sudo -n install -o "$TARGET_USER" -g "$TARGET_GROUP" -m 0755 "$OPERATOR_UV" "$UV_PATH"
  sudo -n cmp "$OPERATOR_UV" "$UV_PATH"
fi
sudo -n runuser -u "$TARGET_USER" -- env HOME="$TARGET_HOME" USER="$TARGET_USER" PATH="$USER_PATH" "$UV_PATH" --version

# Already enrolled by a prior interrupted installation: retain the precise
# original enrollment timestamp and ledger, never overwrite or replay history.
if sudo -n test -f "$STATE"; then
  echo "Existing recovery enrollment retained."
else
  sudo -n runuser -u "$TARGET_USER" -- env HOME="$TARGET_HOME" USER="$TARGET_USER" PATH="$USER_PATH" \
    /usr/bin/python3 "$RUN_PY" --enroll-thread "$THREAD"
fi

# Populate a private cache once. Real recoveries will run offline only.
sudo -n runuser -u "$TARGET_USER" -- env HOME="$TARGET_HOME" USER="$TARGET_USER" PATH="$USER_PATH" \
  UV_CACHE_DIR="$STATE_ROOT/uv-cache" UV_PYTHON_DOWNLOADS=never \
  "$UV_PATH" run --no-project --no-managed-python --python /usr/bin/python3 \
    --with 'websockets==16.0' python -c \
    'import websockets; assert websockets.__version__ == "16.0"; print("T3_RECOVERY_UV_PREFETCH=PASS")'

# Dry run does not write a durable intent or send a message to T3.
sudo -n runuser -u "$TARGET_USER" -- env HOME="$TARGET_HOME" USER="$TARGET_USER" PATH="$USER_PATH" \
  "$RUN_WRAPPER" --once
echo "Checking authenticated T3 read endpoint (no recovery command)..."
sudo -n runuser -u "$TARGET_USER" -- env HOME="$TARGET_HOME" USER="$TARGET_USER" PATH="$USER_PATH" \
  "$RUN_WRAPPER" --probe-auth

sudo -n systemctl --machine="$TARGET_USER@.host" --user daemon-reload
# Actual sandboxed one-shot must succeed before timer is enabled.
sudo -n systemctl --machine="$TARGET_USER@.host" --user start claudex-recovery.service
sudo -n systemctl --machine="$TARGET_USER@.host" --user enable --now claudex-recovery.timer
sudo -n systemctl --machine="$TARGET_USER@.host" --user is-active claudex-recovery.timer
echo "T3_CLAUDEX_RECOVERY_TIMER_ACTIVE=PASS"
echo "T3 Code and Claudex were not restarted."
