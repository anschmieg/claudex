# Source builds and synthetic CI

## Scope

This is the public, **source-only** development tree. Standard CI compiles pinned Shunt and Codex-native transport code, tests the independently authored storage adapters and local authorization, and exercises a synthetic fake-Claude launcher/installer. CI neither signs in to any ChatGPT account nor uses model inference, and it publishes no binaries or packages.

Official SIWC DevKit code and its compiled helper are intentionally omitted. This means an end-user install is not a supported way to run this checkout. Reproducing an optional SIWC helper requires separately obtaining official DevKit code after reviewing its noncommercial license and service terms; read docs/SIWC_AND_SECURITY.md first.

## Pinned native Rust build

Requirements: Bash, Git, Rust/Cargo, Python 3.9+, and build dependencies normally available on supported macOS/Linux runners. The exact upstream revisions are in SHUNT_REVISION and CODEX_REVISION.

~~~bash
bash tools/build-pinned-runtime.sh
python3 tools/test-local-auth.py
PYTHONDONTWRITEBYTECODE=1 python3 tools/test-launcher-concurrency.py
~~~

The native build script fetches the pinned upstream sources, applies the reviewed Shunt patch, compiles the Rust transport from this repository, runs Rust translation/authentication tests and audits binary source paths. Binaries are written under ignored bin/; inspect them locally, but do not upload or redistribute them as releases without proper provenance, licensing and signing reviews.

## Credential adapter tests: no official DevKit needed

~~~bash
node --test source/siwc-helper/keychain-store.test.mjs source/siwc-helper/secret-service-store.test.mjs
~~~

These adapters are independently written and can be tested with synthetic values only. Passing these tests is not evidence that SIWC login/refresh is available to an arbitrary user account.

## Synthetic fresh-user installer regression

The installer currently expects a helper bundle in auth/claudex-siwc.mjs. That bundle is **not shipped**. CI provides a short-lived, ignored placeholder that exits without performing any authentication:

~~~bash
mkdir -p auth
printf '#!/usr/bin/env node\nprocess.exit(99);\n' > auth/claudex-siwc.mjs
chmod 700 auth/claudex-siwc.mjs
PYTHONDONTWRITEBYTECODE=1 python3 tools/test-fresh-install.py
~~~

Do not treat this placeholder as a functional SIWC helper. The fresh-install test uses separate fake credentials and a disposable test HOME. It validates file permissions, bearer-auth, setup, safe stop, symlink rejection and preservation of user-owned data during uninstall, without any account connection. Delete the ignored placeholder when finished if you don't need it.

## Optional SIWC DevKit integration (not automated in public CI)

Upstream: https://github.com/openai/sign-in-with-chatgpt-devkit

The pinned source revision is in SIWC_REVISION. The independent helper's package.json and lockfile declare the required upstream local package under source/siwc-helper/vendor/siwc-local, which is **absent** by design.

If you separately qualify for the DevKit license's **Noncommercial Purpose**, review the SIWC terms and need to evaluate the local adapter, obtain the DevKit at that exact revision from OpenAI's repository under its original license and notices; build its packages/local as directed by the upstream docs and place the corresponding licensed files and built outputs in the ignored vendor directory. Then npm ci/test/build can be run locally. This does **not** grant permission to connect arbitrary third-party clients or use the user's plan outside an authorized connected application. Do not use CI credentials for real OAuth sign-in.

The DevKit license allows noncommercial redistribution under specified conditions; a compiled helper containing official DevKit code **cannot** be distributed simply under this repository's Apache-2.0 license. The OpenAI service terms independently constrain what uses are permitted and prohibit some modifications of the SIWC software. Do not turn source reproduction into an unreviewed public binary release.

## CI behavior

.github/workflows/native-build.yml uses:
- macos-15 (ARM64)
- macos-15-intel (x86-64)
- ubuntu-24.04-arm (ARM64)
- ubuntu-24.04 (x86-64)

It uses standard GitHub-hosted runners, read-only repository permissions, no secrets, and no deployment or upload-artifact action. Synthetic results do not establish production account authorization or service compliance.

Read README.md, THIRD_PARTY_LICENSES.md and SECURITY.md before extending the integration.
