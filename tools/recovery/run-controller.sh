#!/usr/bin/env bash
# Private, offline, uv-managed runtime for the T3 Claudex recovery controller.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")" && pwd -P)"
CONTROLLER="$ROOT/controller.py"
STATE="$HOME/.local/state/claudex-recovery"
[[ -f "$CONTROLLER" && -d "$STATE" && ! -L "$STATE" ]] || {
  echo "Recovery controller or private state directory is missing" >&2
  exit 3
}

UV=""
if command -v uv >/dev/null 2>&1; then
  UV="$(command -v uv)"
else
  for candidate in "$HOME/.local/bin/uv" "$HOME/.cargo/bin/uv" /usr/local/bin/uv /usr/bin/uv; do
    if [[ -x "$candidate" ]]; then UV="$candidate"; break; fi
  done
fi
[[ -n "$UV" ]] || { echo "uv is unavailable to this account" >&2; exit 4; }

export UV_CACHE_DIR="$STATE/uv-cache"
export UV_PYTHON_DOWNLOADS=never
export PYTHONDONTWRITEBYTECODE=1

# Installer primes uv's cache before the timer is enabled. Offline mode
# prevents packages being fetched when a real API outage needs recovery.
exec "$UV" run --no-project --offline --no-managed-python   --python /usr/bin/python3 --with 'websockets==16.0' python "$CONTROLLER" "$@"
