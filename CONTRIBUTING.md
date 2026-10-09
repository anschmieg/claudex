# Contributing

Contributions are welcome for protocol interoperability, native CI, secure local boundaries, tests and documentation. This project is **source-only and experimental**, and the current public name is a placeholder.

- Work on a branch and open a pull request with a focused description and synthetic tests. Never commit real sign-in credentials, copied developer profile files, private user logs or binaries.
- Do not vendor or paste code from OpenAI's noncommercial SIWC DevKit without first reviewing its separate license and any required modification notices. The source-only repo deliberately excludes it.
- Respect each upstream project's license. Distinguish independently authored code from changes to Shunt or any other existing project.
- CI must perform zero OAuth requests and zero paid GPT inference. Test with synthetic tokens and isolated localhost services.
- Never merge a change that makes the SIWC localhost bridge a general-purpose API for unrelated apps, shares a user's subscription, or bypasses provider quotas or security boundaries.
- Verify changes on the four native build targets when possible. Record what is actually tested; do not claim production support from synthetic tests alone.

Contributions to independently authored files are expected to be offered under Apache-2.0 unless a file clearly declares a different upstream license. You must have the necessary rights to submit code. No contributor license agreement or copyright assignment is implied by this file.

For sensitive vulnerabilities, follow SECURITY.md instead of opening a public issue.
