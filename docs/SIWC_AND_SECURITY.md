# SIWC integration boundary and review checklist

**Development source only.** The separately licensed SIWC DevKit is not present here. A code license, consent to connect an OpenAI account, and permission to use that account's ChatGPT plan are different things.

## Governing sources

- https://openai.com/policies/sign-in-with-chatgpt-terms/ (September 29, 2026)
- https://openai.com/policies/service-terms/
- https://github.com/openai/sign-in-with-chatgpt-devkit/blob/main/LICENSE (Noncommercial v1.0)
- https://github.com/openai/sign-in-with-chatgpt-devkit/blob/main/docs/security.md

Always review the current terms before real-world deployment.

## Permissions and boundaries

1. Use only the user's OpenAI-supported SIWC sign-in flow. Passwords, cookies, manual subscription tokens or undocumented credential reuse are out of scope.
2. Treat the SIWC installation as a specifically connected application, **not a general-purpose API key**. Do not route unrelated client tools, extensions or users through a proxy simply because an HTTP-compatible endpoint exists. This includes third-party IDEs and agent harnesses, unless the integration has separately appropriate authorization.
3. Keep account tokens under the user's local control; never upload or forward to service providers other than via authorized SIWC operations. Require explicit authorization for background tasks and never use one account to satisfy another person's requests.
4. No account splitting, pooling, account rotation to bypass limits, resale, or subscription sharing. Plan eligibility and available models are decided by OpenAI.
5. An eligible user must not be forced to pay this application's developer for their plan benefits. A separately authorized OpenAI API account is a distinct option with its own terms and billing.
6. Follow current DevKit and SIWC service terms for modifications, license notices, permission scopes, trademarks and user privacy.

## Technical gaps to resolve before deployment

- **Same-user bearer theft:** owner-only token files are not a boundary against malicious code running as that same OS user. The current two-hop bearer protocol tests request authentication and cleanup but does not bind permissions to a verified calling application. Design an app-bound IPC broker or comparable OS-enforced identity boundary. The fail-closed TCP listener probe prevents some unsafe crash-recovery rekeys, but does not establish app identity or satisfy this requirement. See [AUTH_BOUNDARY.md](AUTH_BOUNDARY.md).
- **API compatibility versus application scope:** Claude Code and T3 Code are separate software. A generic HTTP adapter does not mean they are automatically covered by the connected application's SIWC permission.
- **OAuth and refresh:** native Linux Secret Service and macOS Keychain tests used synthetic credentials. A real-account login/refresh/disconnect cycle has not been validated across public targets and should be tested only within a permitted connected application.
- **Hosted tool and model limits:** provider policies decide access; CLI flags cannot grant unlimited inference, hosted tools or features the plan does not support.
- **Distribution:** any bundle containing OpenAI DevKit source or compiled code must be reviewed under its noncommercial license, preserve notices and follow applicable redistribution restrictions. Signing, provenance and privacy disclosures require separate review.
- **User privacy:** do not include real prompts or account information in CI. Present required disclosures, user-control mechanisms and appropriate privacy notice before processing personal data.

## Supported CI statements

Public CI can establish that independently authored code compiles and synthetic local requests are authenticated. It **cannot** certify whether the combined application has OpenAI's authorization, whether a third-party client is within the connected-app scope, or whether commercial use is allowed.

The present public repository intentionally has no SIWC bundle or deployable plan-backed service.
