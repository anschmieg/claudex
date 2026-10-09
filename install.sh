#!/usr/bin/env bash
set -euo pipefail
umask 077

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
BIN_ROOT="${CLAUDEX_BIN_HOME:-$HOME/.local/bin}"
DATA_ROOT="${CLAUDEX_DATA_HOME:-$HOME/.local/share/claudex}"
STATE_ROOT="${CLAUDEX_STATE_HOME:-$HOME/.local/state/claudex}"
CFG_ROOT="${CLAUDEX_CONFIG_HOME:-$HOME/.config/claudex}"
SIWC_PROFILE_DIR="${CLAUDEX_SIWC_DIR:-$HOME/.config/claudex/chatgpt}"
NO_SETUP=0

if [[ "${1:-}" == "--no-setup" ]]; then
  NO_SETUP=1
elif [[ -n "${1:-}" ]]; then
  echo "Usage: ./install.sh [--no-setup]" >&2
  exit 2
fi

# Do not overwrite executable images mapped by an active local Claudex
# runtime. On macOS, lsof is available for an inexpensive listener check.
# A separate custom installation can use its own CLAUDEX_* paths and ports.
if [[ -x "$DATA_ROOT/shunt" || -x "$DATA_ROOT/claudex-transport" ]] && command -v lsof >/dev/null 2>&1; then
  for port in "${CLAUDEX_PORT:-3147}" "${CLAUDEX_TRANSPORT_PORT:-3150}"; do
    if [[ "$port" =~ ^[0-9]+$ ]] && lsof -nP -iTCP:"$port" -sTCP:LISTEN >/dev/null 2>&1; then
      printf 'claudex: local port %s is in use; close running Claudex sessions before installing. No package files changed.\n' "$port" >&2
      exit 3
    fi
  done
fi

# Reject an installer run when a tracked daemon PID is still alive. This
# works on Linux systems lacking lsof; port checks remain a second guard.
for pidfile in "$STATE_ROOT/shunt.pid" "$STATE_ROOT/transport.pid"; do
  if [[ -f "$pidfile" ]]; then
    running_pid="$(cat "$pidfile" 2>/dev/null || true)"
    if [[ "$running_pid" =~ ^[0-9]+$ ]] && kill -0 "$running_pid" 2>/dev/null; then
      echo "Refusing installation while a Claudex PID file refers to a live process: $pidfile" >&2
      exit 3
    fi
  fi
done

# Four planned native targets. Prebuilt binaries are required for install;
# never leave a half-installed shim on an unsupported or unbuilt platform.
platform="$(uname -s)-$(uname -m)"
case "$platform" in
  Darwin-arm64) target_dir="darwin-arm64" ;;
  Darwin-x86_64) target_dir="darwin-x86_64" ;;
  Linux-x86_64) target_dir="linux-x86_64" ;;
  Linux-aarch64|Linux-arm64) target_dir="linux-arm64" ;;
  *) echo "Unsupported Claudex operating system or architecture: $platform" >&2; exit 2 ;;
esac
for executable in shunt claudex-transport; do
  if [[ ! -x "$SCRIPT_DIR/bin/$target_dir/$executable" ]]; then
    echo "No prebuilt $target_dir/$executable in this preview; build pinned sources for $platform before installing. See BUILDING.md." >&2
    exit 4
  fi
done

# Reject symlinked preferences BEFORE changing any installed package files.
if [[ -L "$CFG_ROOT/native-siwc-enabled" ]]; then
  echo "Refusing symlinked SIWC preference marker" >&2
  exit 5
fi

# Protect all individual installer-owned destinations against symlink
# redirection before performing ANY writes. Directory symlinks may be user-
# managed (e.g. with chezmoi), but installer-owned files cannot be symlinks.
for managed_target in \
  "$DATA_ROOT/launcher" "$DATA_ROOT/shunt" "$DATA_ROOT/claudex-transport" \
  "$DATA_ROOT/claudex-siwc.mjs" "$DATA_ROOT/installed-wrapper-reference" \
  "$DATA_ROOT/installer-owned-wrapper" \
  "$DATA_ROOT/patches/claudex-shunt.patch" \
  "$DATA_ROOT/transport-source/Cargo.toml" "$DATA_ROOT/transport-source/main.rs" \
  "$STATE_ROOT/shunt-version" "$STATE_ROOT/codex-transport-version"; do
  if [[ -L "$managed_target" ]]; then
    echo "Refusing symlinked installer-owned file: $managed_target" >&2
    exit 5
  fi
done
# Refuse to overwrite a pre-existing command unless our installer created
# it and the current bytes still match its last recorded reference.
# This check precedes ALL package writes (including mkdir).
installer_created_wrapper=0
if [[ -e "$BIN_ROOT/claudex" || -L "$BIN_ROOT/claudex" ]]; then
  if [[ -L "$BIN_ROOT/claudex" ]] || [[ ! -f "$DATA_ROOT/installer-owned-wrapper" ]] \
      || [[ ! -f "$DATA_ROOT/installed-wrapper-reference" ]] \
      || ! cmp -s "$BIN_ROOT/claudex" "$DATA_ROOT/installed-wrapper-reference"; then
    echo "Refusing to replace an externally-managed or edited Claudex command wrapper: $BIN_ROOT/claudex" >&2
    exit 5
  fi
else
  installer_created_wrapper=1
fi

mkdir -p "$BIN_ROOT" "$DATA_ROOT/patches" "$DATA_ROOT/transport-source" "$STATE_ROOT"
install -m 0755 "$SCRIPT_DIR/claudex" "$DATA_ROOT/launcher"
install -m 0755 "$SCRIPT_DIR/wrapper/claudex" "$BIN_ROOT/claudex"
install -m 0644 "$SCRIPT_DIR/wrapper/claudex" "$DATA_ROOT/installed-wrapper-reference"
if [[ "$installer_created_wrapper" == 1 ]]; then
  : > "$DATA_ROOT/installer-owned-wrapper"
fi
install -m 0644 "$SCRIPT_DIR/patches/claudex-shunt.patch" "$DATA_ROOT/patches/claudex-shunt.patch"
install -m 0644 "$SCRIPT_DIR/transport-source/Cargo.toml" "$DATA_ROOT/transport-source/Cargo.toml"
install -m 0644 "$SCRIPT_DIR/transport-source/main.rs" "$DATA_ROOT/transport-source/main.rs"

install -m 0755 "$SCRIPT_DIR/bin/$target_dir/shunt" "$DATA_ROOT/shunt"
install -m 0755 "$SCRIPT_DIR/bin/$target_dir/claudex-transport" "$DATA_ROOT/claudex-transport"
install -m 0755 "$SCRIPT_DIR/auth/claudex-siwc.mjs" "$DATA_ROOT/claudex-siwc.mjs"
# Restore the native SIWC preference only when the OS-backed key store is
# supported. Do not copy, decrypt or regenerate the existing profile or key.
# Linux reinstallations must also preserve Secret Service profile selection.
can_reuse_siwc=0
case "$platform" in
  Darwin-*) can_reuse_siwc=1 ;;
  Linux-*) command -v secret-tool >/dev/null 2>&1 && can_reuse_siwc=1 ;;
esac
if [[ "$can_reuse_siwc" == 1 && -s "$SIWC_PROFILE_DIR/chatgpt-auth.json" ]]; then
  mkdir -p "$CFG_ROOT"
  : > "$CFG_ROOT/native-siwc-enabled"
  chmod 600 "$CFG_ROOT/native-siwc-enabled"
fi
install -m 0644 "$SCRIPT_DIR/SHUNT_REVISION" "$STATE_ROOT/shunt-version"
install -m 0644 "$SCRIPT_DIR/CODEX_REVISION" "$STATE_ROOT/codex-transport-version"

echo "Installed Claudex 0.6.0-dev for $target_dir to $BIN_ROOT/claudex"

if [[ "$NO_SETUP" -eq 1 ]]; then
  echo "Run: claudex setup"
  exit 0
fi

if command -v claude >/dev/null 2>&1   && command -v codex >/dev/null 2>&1   && codex login status >/dev/null 2>&1; then
  "$BIN_ROOT/claudex" setup
  echo
  echo "Next: claudex smoke"
  echo "Then: claudex smoke-claude"
else
  echo
  echo "Finish setup with:"
  echo "  codex login        # if not already logged in"
  echo "  claudex setup"
  echo "  claudex smoke"
fi
