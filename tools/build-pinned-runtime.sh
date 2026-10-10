#!/usr/bin/env bash
# Build BOTH Rust executables from source at the exact upstream commits.
# Intended for a CLEAN checked-out public release tree on each native runner.
set -euo pipefail
umask 077

ROOT="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)"
WORK="${CLAUDEX_BUILD_WORKDIR:-$ROOT/.build-from-source}"
SHUNT_REV="$(tr -d '\r\n' < "$ROOT/SHUNT_REVISION")"
CODEX_REV="$(tr -d '\r\n' < "$ROOT/CODEX_REVISION")"

for tool in git cargo rustc python3 uname; do
  command -v "$tool" >/dev/null 2>&1 || { echo "Missing build dependency: $tool" >&2; exit 2; }
done
case "$(uname -s)-$(uname -m)" in
  Darwin-arm64) target="darwin-arm64" ;;
  Darwin-x86_64) target="darwin-x86_64" ;;
  Linux-x86_64) target="linux-x86_64" ;;
  Linux-aarch64|Linux-arm64) target="linux-arm64" ;;
  *) echo "Unsupported build target: $(uname -s)-$(uname -m)" >&2; exit 2 ;;
esac
[[ "$SHUNT_REV" =~ ^[0-9a-f]{40}$ && "$CODEX_REV" =~ ^[0-9a-f]{40}$ ]] || {
  echo "Pinned revisions must be exact commit SHA-1s" >&2
  exit 2
}
# Allow only the Cargo compilation cache restored by CI. Never reuse
# checked-out upstream trees: each run must fetch and verify exact commits.
if [[ -e "$WORK" ]]; then
  [[ -d "$WORK" && ! -e "$WORK/shunt" && ! -e "$WORK/codex" && ! -e "$WORK/target-shunt" ]] || {
    echo "Build workdir contains a prior source checkout; choose a fresh CLAUDEX_BUILD_WORKDIR" >&2
    exit 2
  }
fi
mkdir -p "$WORK"
echo "Building $target from pinned source in $WORK"

checkout_pinned() {
  local url="$1" sha="$2" dest="$3"
  git init -q "$dest"
  git -C "$dest" remote add origin "$url"
  git -C "$dest" fetch -q --depth 1 origin "$sha"
  git -C "$dest" checkout -q --detach FETCH_HEAD
  [[ "$(git -C "$dest" rev-parse HEAD)" == "$sha" ]] || {
    echo "Refusing to build unexpected upstream revision in $dest" >&2
    exit 1
  }
}
checkout_pinned https://github.com/pleaseai/shunt.git "$SHUNT_REV" "$WORK/shunt"
checkout_pinned https://github.com/openai/codex.git "$CODEX_REV" "$WORK/codex"

git -C "$WORK/shunt" apply --check "$ROOT/patches/claudex-shunt.patch"
git -C "$WORK/shunt" apply "$ROOT/patches/claudex-shunt.patch"
mkdir -p "$WORK/codex/codex-rs/claudex-transport/src"
cp "$ROOT/transport-source/Cargo.toml" "$WORK/codex/codex-rs/claudex-transport/Cargo.toml"
cp "$ROOT/transport-source/main.rs" "$WORK/codex/codex-rs/claudex-transport/src/main.rs"
python3 - "$WORK/codex/codex-rs/Cargo.toml" <<'PY'
from pathlib import Path
import sys
p=Path(sys.argv[1])
s=p.read_text()
if '"claudex-transport",' not in s:
    marker='    "model-provider",'
    assert s.count(marker)==1, "Codex pinned workspace manifest changed unexpectedly"
    s=s.replace(marker,marker+'\n    "claudex-transport",',1)
p.write_text(s)
PY

# Remap the pinned source tree AND the runner's home, Cargo and rustup
# caches. Dependencies may embed source paths outside WORK, and the release
# audit rejects private user-home paths. ASCII US separates Cargo flags,
# including flags containing spaces in macOS development paths.
_cargo_flag_separator="$(printf '\037')"
export CARGO_ENCODED_RUSTFLAGS="--remap-path-prefix=$WORK=/build/claudex"
_cargo_home="$(printenv CARGO_HOME 2>/dev/null || true)"
_rustup_home="$(printenv RUSTUP_HOME 2>/dev/null || true)"
if [[ "$_cargo_home" == /* ]]; then
  CARGO_ENCODED_RUSTFLAGS+="$_cargo_flag_separator--remap-path-prefix=$_cargo_home=/build/cargo"
fi
if [[ "$_rustup_home" == /* ]]; then
  CARGO_ENCODED_RUSTFLAGS+="$_cargo_flag_separator--remap-path-prefix=$_rustup_home=/build/rustup"
fi
CARGO_ENCODED_RUSTFLAGS+="$_cargo_flag_separator--remap-path-prefix=$HOME=/build/builder-home"
export CARGO_ENCODED_RUSTFLAGS
export CARGO_PROFILE_RELEASE_DEBUG=0
export CARGO_PROFILE_RELEASE_STRIP=symbols
export CARGO_INCREMENTAL=0
jobs="${CLAUDEX_BUILD_JOBS:-2}"

(
  cd "$WORK/shunt"
  export CARGO_TARGET_DIR="$WORK/target-shunt"
  cargo test --release --locked --test responses_translate --jobs "$jobs"
  cargo build --release --locked --bin shunt --jobs "$jobs"
)
# GitHub's standard runners have limited disk; release the independent
# shunt build cache before compiling the larger Codex Rust workspace.
mkdir -p "$ROOT/bin/$target"
install -m 0755 "$WORK/target-shunt/release/shunt" "$ROOT/bin/$target/shunt"
cargo clean --manifest-path "$WORK/shunt/Cargo.toml" --target-dir "$WORK/target-shunt" >/dev/null
(
  cd "$WORK/codex/codex-rs"
  export CARGO_TARGET_DIR="$WORK/target-codex"
  cargo test -p claudex-transport --release --jobs "$jobs"
  cargo build -p claudex-transport --release --jobs "$jobs"
)
mkdir -p "$ROOT/bin/$target"
install -m 0755 "$WORK/target-codex/release/claudex-transport" "$ROOT/bin/$target/claudex-transport"

# Do not publish a binary that still embeds the builder's absolute paths.
python3 - "$ROOT/bin/$target/shunt" "$ROOT/bin/$target/claudex-transport" "$WORK" <<'PY'
from pathlib import Path
import sys
for name in sys.argv[1:3]:
    data=Path(name).read_bytes()
    assert sys.argv[3].encode() not in data, f"Builder absolute path in {name}"
print("ARCH_BUILD_PRIVACY_AUDIT=PASS")
PY
echo "PINNED_BUILD_SUCCESS target=$target"
