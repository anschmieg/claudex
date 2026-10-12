# Security policy — experimental source

This is an experimental source repository, **not a security-audited release**. Do not use the optional SIWC-backed transport as a general-purpose subscription gateway.

## Current security limitations

The launcher binds local interfaces to loopback and authenticates both hops with random bearer values, but the bearer values are stored in owner-only files. This does not prevent another process running under the *same* operating-system user from obtaining them. A future broker or equivalent application-bound authorization boundary is required before broad release. The experimental lifecycle now fails closed when either loopback TCP port is occupied but both managed PID files are absent. This protects against false token rotation/revocation after partial daemon failure; it does not identify or restrict hostile same-user processes. See docs/AUTH_BOUNDARY.md.

The source runtime is not signed or notarized. Authentication against real user accounts, actual Linux keyring behavior in desktop sessions, token refresh under service outages, and permission boundaries have not been comprehensively independently audited. Synthetic tests use disposable profiles and fake tokens.

The SIWC terms prohibit general-purpose API access for unrelated clients using a connected application's plan. If you are developing T3 Code, Claude Code, plugins or other tools, do not connect them to a user's SIWC entitlement based solely on the existence of the localhost service. Use independently authorized APIs or obtain any necessary permission.

## Handling sensitive information

Do not post credentials, ChatGPT profile state, account emails, session cookies, API keys, real prompt/response logs, filesystem home paths or machine identifiers in public issues. The CI tests never require these. Store local credentials only in user-controlled OS-backed facilities and guard test config and logs.

For vulnerability reports, prefer GitHub's private vulnerability reporting when enabled. If it is not enabled, avoid public exploit details and contact repository maintainers through a private channel; do not place sensitive material in public issues.

No formal security support or response-time guarantee is provided at this development stage.
