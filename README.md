# Claudex

Experimental source code for a local compatibility layer between an Anthropic Messages-style coding-agent interface and the Codex/Responses protocol.

**Status: development source only. No endorsed public product, binary release, installer package, supported SIWC deployment, or entitlement to use a ChatGPT subscription through third-party software.** The source retains the familiar \`claudex\` command and uses **Claudex** as its descriptive project name; this does not assert exclusive rights to that name.

This repository is independently developed. It is **not affiliated with, sponsored, certified, or endorsed by OpenAI or Anthropic**. Claude, Claude Code, ChatGPT, Codex, and related names are mentioned only to identify interoperating products and protocols. You must obtain and follow the applicable terms for any software or service you use.

## What the code does

The experimental runtime comprises a Bash launcher, a patched version of the independently maintained Shunt translator, and a Rust transport using Codex libraries. It runs only on the user's machine, binds the local HTTP hops to loopback, and uses two different random bearer credentials for the separate localhost hops.

The project also contains independently written macOS Keychain and Linux Secret Service credential-encryption adapters for an **optional** Sign in with ChatGPT (SIWC) integration. The official OpenAI DevKit itself is deliberately **not bundled in this public source tree**, nor is the compiled helper that would incorporate it.

Current development test coverage includes macOS and Linux ARM64/x86-64 synthetic CI tests. This does not mean all four systems are supported for end users, that a real account can sign in, or that all model and hosted-tool features are compatible.

## Licensing: read this before using or redistributing anything

Different components have **different rights**. The top-level Apache License 2.0 (LICENSE) covers this project's independently authored code and documentation, to the extent that the contributors own those rights. It **does not** relicense dependencies, third-party code, proprietary applications, service access, or protected product names. See THIRD_PARTY_LICENSES.md and NOTICE.md.

- **Shunt:** upstream source is dual-licensed MIT OR Apache-2.0. This repository carries a patch against an exact Shunt commit, not an unlicensed fork of the upstream source. Retain its applicable license and notices when redistributing modified code.
- **OpenAI Codex:** the build downloads an exact public Codex source revision; its own Apache-2.0 license and notices apply. No user login tokens are supplied in this repository.
- **OpenAI SIWC DevKit:** *Sign-in with ChatGPT DevKit Noncommercial License v1.0*, not Apache-2.0 or an OSI-approved open-source license. The DevKit may be copied/modified/distributed only within that license's **Noncommercial Purpose** limits, with required notices. That definition expressly excludes use for a business, client or employer's commercial advantage, including free services in those contexts. Commercial rights require a separate written agreement with OpenAI. Independently written code that merely interfaces with the DevKit does not automatically acquire those restrictions, but the DevKit itself does.
- **Claude Code and T3 Code:** separate products; neither is included nor licensed by this repository. Their own licenses, terms and trademarks continue to apply.

This repository does **not** represent the combined optional SIWC runtime as unrestricted open-source software. The DevKit license text is reproduced under auth/SIWC-DEVKIT-LICENSE for reference; its program code and the compiled integration are excluded. Do not assume that source availability implies permission to operate a service or to use third-party subscription plans.

Official references: [SIWC DevKit license](https://github.com/openai/sign-in-with-chatgpt-devkit/blob/main/LICENSE), [SIWC terms (September 29, 2026)](https://openai.com/policies/sign-in-with-chatgpt-terms/), [Shunt project](https://github.com/pleaseai/shunt), [Codex project](https://github.com/openai/codex).

## SIWC service rules and why this is not an approved connection

A software copyright license and permission to use ChatGPT-plan benefits are **separate**. Using SIWC requires compliance with OpenAI's SIWC Terms, other applicable service terms, and usage policies. In particular:

- Authenticate only with OpenAI's supported sign-in flow and explicit user authorization; **never** solicit passwords, session cookies or manually extracted tokens.
- Keep authentication tokens in local, user-controlled storage; do not upload, relay, pool, resell or share them. Separate users must not consume one user's plan.
- Plan-backed requests must arise from the account holder's activity or an **expressly authorized** background automation, on a user-controlled runtime.
- SIWC authorizes use for the **connected application only**. It is **not** a general-purpose OpenAI API for unrelated clients, remote services or arbitrary tools. The existence of a loopback proxy does not grant permission to connect T3 Code or other external clients to a SIWC-backed plan. Obtain separate authorization or an appropriate API arrangement for such integrations.
- Access to eligible plan benefits through SIWC must not require payment to the developer or a paid upgrade of this app. No model entitlement, extra quota or access to other OpenAI services is implied.
- Do not modify or misuse the SIWC software contrary to the service terms, circumvent service limits, or imply OpenAI sponsorship. The DevKit copyright license and SIWC service terms must both be respected.

**Current compliance gap:** the experimental launcher stores randomly generated local bearer credentials in owner-only files. Processes already running as the same OS user may be able to read those files. The launcher additionally refuses to rotate or revoke bearer values while either configured loopback TCP port is still occupied, even if its PID file was lost. This prevents a specific crash-recovery failure, **not** same-user credential theft. The app's historical general-purpose local protocol endpoints and third-party-client support also require explicit connected-application scope review. For these reasons **do not distribute or operate the SIWC-backed integration as a general-purpose subscription gateway**. Published source is for review and development, not a claim of terms compliance. See docs/SIWC_AND_SECURITY.md and the detailed [authentication-boundary threat model](docs/AUTH_BOUNDARY.md).

Use a **separately authorized API credential** for independent tools rather than treating a consumer ChatGPT subscription as an API key.

## Model-specific Codex reasoning defaults

Claudex resolves implicit reasoning effort from the installed, authenticated Codex CLI's
`app-server` `model/list` endpoint, specifically `defaultReasoningEffort` and
`supportedReasoningEfforts`. It caches only nonsecret model metadata (six-hour TTL).
When the installed Codex CLI is older than a new GPT model, a recent Codex-provider
snapshot from T3 Code can supply that model's default. Missing metadata is **not**
replaced with a guessed, hardcoded GPT default. Caller-provided `--effort` always wins.

Use `claudex reasoning-defaults` to inspect discovered values, or `claudex sync-t3`
to synchronize the *default reasoning options* of existing Claudex custom models
in `~/.t3/userdata/settings.json`. The sync makes a private backup, preserves other
provider settings and existing model selections, and requires a T3 provider refresh
for a running service. Set `CLAUDEX_USE_CODEX_DEFAULT_EFFORT=0` to disable implicit
CLI injection temporarily. A candidate GPT-specific appended instruction file exists as an
**opt-in experiment** at `prompts/gpt-execution-overlay.md` (`CLAUDEX_GPT_OVERLAY=1`).
It is disabled by default pending selective prompt-replacement experiments. See [GPT harness alignment](docs/GPT_HARNESS_ALIGNMENT.md)
for the instruction comparison and recommended optional GPT instruction supplement.

## Versioned prompt optimization

Claudex's patched Shunt can selectively replace **exact fingerprinted** Claude-specific instructions while preserving upstream Claude Code updates, tool schemas, permissions and user/project context. The default `CLAUDEX_PROMPT_MODE=selective` applies four reviewed rules. Set `CLAUDEX_PROMPT_MODE=aggressive` to additionally compact three lengthy tool-description examples, or `CLAUDEX_PROMPT_MODE=off` for byte-for-byte upstream passthrough. The mode takes effect when the Claudex Shunt process starts. Rules are independent JSON files in [`prompt-rules/`](prompt-rules/README.md); unmatched rules fail closed, preserve the upstream text and emit only a diagnostic rule ID. The previous additive `CLAUDEX_GPT_OVERLAY` remains opt-in and is not needed for this mode.

Measured against a synthetic real Claude Code 2.1.294 capture, selective saved 1,108 characters (3.26%) and aggressive saved 2,565 characters (7.54%) of combined system instructions and tool descriptions. These are **character** savings, not verified model-context token reductions or inference-quality guarantees. Synthetic regression tests cover matching, identity, preserved permissions and tool schemas. Different upstream Claude Code versions may legitimately match fewer rules until reviewed.

## Building and testing the source

The version pins in SHUNT_REVISION, CODEX_REVISION and SIWC_REVISION identify upstream commits used for the experimental code. Builds must use a compatible supported Rust toolchain, Git and Python 3.9+; Node.js 22+ is used for credential-adapter unit tests.

On a supported host:

~~~bash
bash tools/build-pinned-runtime.sh
node --test source/siwc-helper/keychain-store.test.mjs source/siwc-helper/secret-service-store.test.mjs
python3 tools/test-local-auth.py
PYTHONDONTWRITEBYTECODE=1 python3 tools/test-launcher-concurrency.py
~~~

The native build script checks out the pinned Shunt and Codex revisions, applies the patch, and builds executables. These tests use fake credentials and local-only HTTP. They perform **no real OAuth or model inference**.

The full fresh-install test additionally needs a test-only helper placeholder, prepared by CI; see BUILDING.md. Do not run install.sh as an end-user installer from this checkout: the excluded SIWC runtime bundle is not present. Official DevKit integration is deliberately an **explicit, manual noncommercial-only workflow**; its source is never fetched by public CI.

The public GitHub Actions workflow uses standard runners on macOS ARM64/Intel and Linux ARM64/x86-64 with read-only permissions. It runs tests and audits, **not deployments, tags, releases, package publishing, account sign-in or paid-model requests**. It does not upload binary release artifacts.

## Data and security

No credentials, profiles, private Git history, local logs, compiled binaries, user environments or SSH/API keys are distributed. Tests create disposable local state and synthetic tokens. Actual source builds may access the network to download pinned public dependencies. Developers should review dependencies and isolate test accounts and file permissions.

A local loopback listener does not provide isolation from arbitrary processes under the same operating-system account. Same-user bearer isolation, background-use authorization, model feature compatibility, actual Keychain/Secret Service login and signing/notarization remain open work.

Please avoid posting real credentials, profile files, access tokens or private model responses in public issues. See SECURITY.md.

## Project scope

This is a fresh-history **public source and CI development repository**, not the original private development workspace. Other independent projects use **Claudex** for similar Claude Code/Codex interoperability (including [BeamoTech/Claudex](https://github.com/BeamoTech/Claudex) and [johnlindquist/claudex](https://github.com/johnlindquist/claudex)). This project is unaffiliated with them. The descriptive name is **not claimed as an exclusive trademark**, and no formal trademark clearance is implied.

Read BUILDING.md, THIRD_PARTY_LICENSES.md, NOTICE.md, SECURITY.md, and docs/SIWC_AND_SECURITY.md before contributing or reusing the code.

**Not legal advice.** Licenses, service terms and trademarks can change. Publishing these notices cannot cure a service-terms violation, missing rights or an insecure authentication design. Independent legal and security review remains advisable before enabling the optional plan-backed runtime for other users.


Optional efficiency diagnostics: see [docs/EFFICIENCY_PROFILE.md](docs/EFFICIENCY_PROFILE.md). Disabled by default (`CLAUDEX_EFFICIENCY=off`); advisory opt-in does not change model routing or enforce external spending caps.
