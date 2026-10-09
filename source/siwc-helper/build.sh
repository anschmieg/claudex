#!/usr/bin/env bash
set -euo pipefail
SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"
if [[ ! -f node_modules/@siwc/local/dist/index.js ]]; then
  echo "Install dependencies with npm ci before building" >&2
  exit 2
fi
./node_modules/.bin/esbuild cli.mjs --bundle --platform=node --format=esm --target=node22 \
  --outfile=dist/claudex-siwc.mjs \
  --banner:js='import{createRequire as __cr}from"node:module";const require=__cr(import.meta.url);'
node --check dist/claudex-siwc.mjs
