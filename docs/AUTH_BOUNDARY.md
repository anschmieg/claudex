# Authentication boundary: threat model and release design

Status: **experimental engineering design, not a security certification or permission to use SIWC**. The public repository omits the official DevKit and compiled SIWC adapter. The existing local transport and launcher are source-only development components.

See [SIWC and security](SIWC_AND_SECURITY.md), [Security policy](../SECURITY.md), and [OpenAI's SIWC Terms](https://openai.com/policies/sign-in-with-chatgpt-terms/) (September 29, 2026).

## Security objective and what currently works

A local launch consists of an interactive Claude Code process, an Anthropic-to-Responses shunt, and a Codex-compatible transport. Each localhost HTTP hop uses a different random 256-bit bearer value. The gateway binds to 127.0.0.1; the transport rejects non-loopback listening and authenticates Responses requests. Secrets are in an owner-restricted private folder and the launcher rotates/revokes them as part of the managed lifecycle.

Current lifecycle regression tests, all using **synthetic credentials**, validate that missing/wrong bearer requests are rejected, two active launchers share a managed daemon safely, logout/last-session exit revokes secrets after the daemon stops, stale tokens are replaced after genuine crash cleanup, and unfamiliar processes are not terminated merely because their PID appears in a file.

An extra fail-closed guard rejects local credential generation, rotation, or claimed revocation when a raw TCP connection can still reach either configured localhost port. It covers a live daemon whose PID file has vanished, a daemon whose HTTP health check is unavailable, or an unrelated process occupying a port. A refused operation preserves existing secrets and does not make a new plan-backed server.

This guard is **not** authentication or an effective defense against hostile processes already running as the same user. A loopback TCP port can be replaced between checks; the raw socket probe cannot distinguish genuine Claudex from an impersonating server. The guard is deliberately conservative and can require user intervention if a port is occupied.

## Adversaries and security claims

| Threat | Current posture | Missing guarantee |
| --- | --- | --- |
| Remote machine without local network/port access | Both hops bind loopback and transport refuses non-loopback address. | Audit externally exposed proxies, port forwarding, local reverse tunnels and unusual network namespaces. |
| Another OS user on the same machine | Random bearer tokens and owner-only files deny simple unauthenticated API calls. | Verify platform ACLs, inherited environment, process inspection, elevated privileges and disk backups. |
| Malicious **same-OS-user** process | **Not isolated.** It may read bearer files, inspect child environments, attach to processes where allowed, or use other user-authorized applications. | Require an OS-enforced application/process identity boundary and prevent access to plan credentials from arbitrary same-user code. |
| Stale PID file, missed cleanup, orphaned listener | Fail-closed process image checks and independent TCP port occupancy veto protect against false token rotation/revocation in tested cases. | Address races and hostile local socket substitution; strengthen daemon ownership and reliability. |
| Legitimate external CLI/agent/IDE using a local gateway | A bearer grants technical HTTP access, **not contractual permission** for another application to use a connected ChatGPT plan. | Separate legal and technical authorization for connected-app scope. |

The current authorization is **bearer-based, not app-bound**. Modes 0600/0700 and random session tokens do not stop a malicious process with the same user privileges from reading secrets; these measures must never be described as protecting against same-user malware.

## Why a same-user Unix socket is insufficient

Unix-domain sockets may provide kernel peer credentials (Linux SO_PEERCRED, macOS getpeereid), but those identify *users/processes*, not a trustworthy application or the user's intent. A connection with the same UID is not proof it came from the authorized Claude Code session. PID and /proc executable checks can be spoofed, raced, or undermined by process injection on some platforms.

Consequently, merely replacing HTTP with a Unix socket or moving the current token into an inherited environment variable does **not** close this release blocker.

## Candidate long-term design (requires review)

1. **Explicit connected-app identity.** Treat the SIWC client as a single specific application with its own name, UI/disclosures and explicit sign-in; do not describe the protocol adapter as a generic plan-backed API.
2. **Privileged credential broker.** Keep OAuth access/refresh tokens within an OS-protected broker process or secure platform credential facility. Never expose upstream tokens to a shim, model tools, child process environment, log, temporary file, or arbitrary local HTTP endpoint.
3. **Enforced per-app boundary.** Assess macOS sandbox/code-signing requirements and Keychain item access controls. On Linux, evaluate a distinct service UID, access-controlled Unix sockets and OS sandboxing/mandatory access control, with suitable UX and installation. Do not rely on UID equality alone. Validate both against same-user adversarial tests.
4. **Request provenance and revocation.** Require an attributable user session and bound application identity. Background automation needs express permission, rate limits, revocation, and observable user controls. Disconnect must invalidate tokens and close any active plan-backed listeners.
5. **Strict connected-app use.** Requests from unrelated tools (including other coding IDEs/clients) cannot use the SIWC entitlement just because they speak compatible HTTP. Use separately authorized API credentials for external clients unless the provider explicitly permits the integration. Technical token checks do not substitute for consent or terms.
6. **No unreviewed upstream changes.** The DevKit is under a noncommercial license. SIWC service terms separately restrict modifying the SIWC software; any proposed modification, redistribution, or new client behavior requires independent terms/licensing assessment before use.

These are design candidates, not implemented properties or evidence of terms compliance. OS-enforced isolation can be complicated by tools that execute arbitrary user code; either constrain the threat model explicitly or avoid claiming such isolation.

## Release gates

- Independent security review of request provenance and the chosen OS-enforced application boundary on macOS and Linux, including same-user malicious-code tests.
- Explicit determination that the *specific* connected application and permissible clients comply with SIWC terms. Do not use account tokens for a general-purpose proxy or another person's activity.
- Legally reviewed redistribution and modification rights for bundled SIWC code and third-party notices.
- Fresh real-account login/refresh/disconnect verification only within a permitted application, with local secure storage, user-consent controls and a privacy notice.
- Session cleanup, orphan handling, token revocation and hostile/denied requests verified on each supported platform; no real credentials or plan usage in public CI.
- Reproducible signed/notarized artifacts, install/upgrade ownership boundaries and a clear supported-platform scope.

**Until these gates are satisfied, Claudex is a public source/CI experiment, not a supported SIWC-enabled binary product.**