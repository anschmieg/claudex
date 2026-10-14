#!/usr/bin/env bash
# Offline, user-owned runtime for independent Goal Governor oneshot.
set -euo pipefail
TARGET="$HOME/.local/share/claudex/goal-governor"
PROGRAM="$TARGET/supervisor.py"
CACHE="$HOME/.local/state/claudex-recovery/uv-cache"
[[ -f "$PROGRAM" && -d "$CACHE" ]] || { echo "Governor runtime/cache unavailable" >&2; exit 3; }
UV=""
for path in "$HOME/.local/bin/uv" "$HOME/.cargo/bin/uv" /usr/local/bin/uv /usr/bin/uv; do
  if [[ -x "$path" && -f "$path" ]]; then UV="$path";break;fi
done
[[ -n "$UV" ]] || { echo "uv unavailable for governor service" >&2; exit 4; }
export UV_CACHE_DIR="$CACHE"
export UV_PYTHON_DOWNLOADS=never
export PYTHONDONTWRITEBYTECODE=1
exec "$UV" run --no-project --offline --no-managed-python --python /usr/bin/python3 --with 'websockets==16.0' python "$PROGRAM" "$@"
