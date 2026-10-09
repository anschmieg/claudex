# Third-party license and permitted-use inventory

This inventory separates **source-code copyright licenses** from **service-use permissions**. It is not a substitute for the complete license texts or for legal review. The notices here are intended to accompany the project's own Apache-2.0 license; they do not expand any third party's grant.

| Component | Present in this Git checkout? | Governing license and conditions |
| --- | --- | --- |
| Independently written launcher, installer, transport adapter, storage adapters, tests and tooling | Yes | Apache License 2.0 (root LICENSE), to the extent contributors own rights |
| Shunt project and portions covered by our patch | Pin and patch only; upstream source fetched during build | Upstream MIT OR Apache-2.0. Retain original notices. Upstream licenses are copied under licenses/shunt/ |
| OpenAI Codex libraries | Pin only; upstream source fetched during build | Upstream Apache-2.0 and applicable third-party licenses/notices, copied under licenses/codex/ |
| OpenAI Sign-in with ChatGPT DevKit (@siwc/local) | **No.** Neither source nor bundled runtime is committed | Sign-in with ChatGPT DevKit Noncommercial License v1.0. Source and compiled redistribution permitted **only for Noncommercial Purposes**, with specified notices; no commercial rights. See auth/SIWC-DEVKIT-LICENSE and [upstream](https://github.com/openai/sign-in-with-chatgpt-devkit/blob/main/LICENSE). |
| Optional npm/Cargo dependencies | Resolved externally when building | Their individual licenses and notices. Review generated dependency inventory when assembling a distributable binary. |
| Claude Code, T3 Code and other separate client applications | No | Their respective proprietary or open-source licenses, service terms and trademarks. Not licensed, bundled, endorsed or maintained here. |
| ChatGPT plan access through SIWC | No access rights granted by any source license | [Sign in with ChatGPT Terms](https://openai.com/policies/sign-in-with-chatgpt-terms/) and other OpenAI terms; requires an independently permitted application integration. |

## What Apache-2.0 does and does not cover

The root LICENSE applies only to code to which its contributors may grant that license. It does **not** apply to the official SIWC DevKit, to a bundled DevKit derivative, to unaffiliated upstream programs, to user tokens, to software/services you haven't obtained permission to use, or to third-party trademarks.

The original Shunt patch contains context lines from its permissively licensed upstream source. Distributing or modifying Shunt in full must preserve Shunt's own applicable copyright notices. Neither its upstream text nor OpenAI Codex libraries become the exclusive property of this project.

## Special SIWC license and service-term limitations

The official DevKit license defines noncommercial use narrowly. Not charging money is **not sufficient**: commercial advantage for a business, client or employer is excluded, regardless of whether a fee is charged. Redistribution requires including the license, preserving notices and marking modifications; modifications distributed as a Modified Work must satisfy the same noncommercial license.

The SIWC **service terms are separate**. The terms limit requests to the connected application and prohibit turning a subscription into a general-purpose API for unrelated tools. They also require token security, local user control, authorization for background tasks, prohibition of cross-user usage or pooling, and a free path for an eligible user to use plan-backed functionality. The terms prohibit altering/amending SIWC software in connection with service use; the copyright license's modification grant does not itself authorize use of a modified integration against the SIWC service. Resolve any ambiguity with the rightsholder before redistributing or operating such a version.

The optional SIWC helper in source/siwc-helper/ is **independently authored integration code**, not a copy of the official DevKit. Its package-lock references a deliberately missing vendor directory. Obtaining and using the DevKit is a separate, affirmative act subject to its license and terms. The public CI does not download or build it.

## Trademark and independence notice

OpenAI, ChatGPT, Codex and associated marks are the property of their respective owners. Anthropic, Claude and Claude Code are associated with Anthropic. Their names appear solely for technical identification; there is no sponsorship or endorsement. The descriptive project and shell-command name **Claudex** is shared with unrelated community projects and is not claimed as an exclusive trademark. This does not imply trademark clearance or affiliation with any similarly named project.

## Sources and current scope

- [OpenAI DevKit license](https://github.com/openai/sign-in-with-chatgpt-devkit/blob/main/LICENSE) (v1.0)
- [OpenAI Sign in with ChatGPT Terms](https://openai.com/policies/sign-in-with-chatgpt-terms/) (September 29, 2026)
- [OpenAI service terms](https://openai.com/policies/service-terms/)
- [Shunt](https://github.com/pleaseai/shunt)
- [OpenAI Codex](https://github.com/openai/codex)

This inventory documents the current source checkout and **does not certify legal compliance** for an eventual compiled application or distribution.
