#!/usr/bin/env bash
# Test real Linux Secret Service storage using ONLY synthetic credentials.
# Requires an explicitly isolated D-Bus session on a disposable CI runner.
set -euo pipefail
umask 077

[[ "${CLAUDEX_TEST_ISOLATED_KEYRING:-}" == 1 ]] || {
  echo "Refusing to access an existing keyring. Set CLAUDEX_TEST_ISOLATED_KEYRING=1 in a fresh dbus-run-session." >&2
  exit 2
}
[[ -n "${DBUS_SESSION_BUS_ADDRESS:-}" && "$(uname -s)" == Linux ]] || {
  echo "Requires Linux and a disposable dbus-run-session." >&2
  exit 2
}
for executable in gnome-keyring-daemon secret-tool node; do
  command -v "$executable" >/dev/null 2>&1 || {
    echo "Missing test dependency: $executable" >&2
    exit 2
  }
done

# Do not use the CI runner's real home or any existing desktop keyring.
export HOME="$(mktemp -d)"
export XDG_CONFIG_HOME="$HOME/.config"
export XDG_DATA_HOME="$HOME/.local/share"
mkdir -p "$HOME/.local/share/keyrings" "$XDG_CONFIG_HOME"
chmod 700 "$HOME" "$HOME/.local/share/keyrings" "$XDG_CONFIG_HOME"

# The unlock passphrase and all keyring entries are fixed test values.
eval "$(printf 'synthetic-ci-only-passphrase\n' | gnome-keyring-daemon --daemonize --login --components=secrets)"
eval "$(gnome-keyring-daemon --start --components=secrets)"

printf 'synthetic-canary' |
  secret-tool store --label='Claudex CI synthetic canary' application claudex account ci-synthetic-canary
test "$(secret-tool lookup application claudex account ci-synthetic-canary)" = synthetic-canary
echo 'REAL_SECRET_SERVICE_CANARY=PASS'

node --input-type=module <<'NODE'
import assert from 'node:assert/strict';
import { createSecretServiceEncryption } from './source/siwc-helper/secret-service-store.mjs';

const options = { account: 'ci-synthetic-only', service: 'com.claudex.siwc.test.integration' };
const first = createSecretServiceEncryption(options);
const ciphertext = await first.encrypt('SYNTHETIC_TEST_CREDENTIAL');

assert.equal(ciphertext[0], 2, 'versioned AES-GCM envelope');
assert.equal(ciphertext.includes(Buffer.from('SYNTHETIC_TEST_CREDENTIAL')), false);

const second = createSecretServiceEncryption(options);
assert.equal(await second.decrypt(ciphertext), 'SYNTHETIC_TEST_CREDENTIAL');

const updated = await second.encrypt('UPDATED_SYNTHETIC_TEST_CREDENTIAL');
assert.equal(
  await createSecretServiceEncryption(options).decrypt(updated),
  'UPDATED_SYNTHETIC_TEST_CREDENTIAL'
);

await assert.rejects(
  createSecretServiceEncryption({ ...options, account: 'unknown-account' }).decrypt(ciphertext),
  'a different identity must not decrypt another account\'s key'
);
console.log('REAL_LINUX_SECRET_SERVICE_ENCRYPTION=PASS');
NODE
