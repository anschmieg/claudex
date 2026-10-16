# Optional Claudex efficiency diagnostics

The [video's seven usage habits](https://www.youtube.com/watch?v=zoIAblD9DZo) motivate an opt-in **advisory** profile. It does not assert that video anecdotes or provider subscription quotas are universal, and does not automatically delete sessions, compact contexts, change models, or restrict permissions.

## Enable

After installing this release, set `CLAUDEX_EFFICIENCY=advisory` before invoking `claudex`. Default is `off`. `strict` currently uses the same advisory reporting and **is not an enforcement guarantee**. The wrapper runs `~/.local/share/claudex/efficiency/profile.py` before executing the installed launcher. It never passes secrets or CLI arguments to the diagnostic, and diagnostic failures do not interrupt the launcher.

For explicit, privacy-preserving measurements, run:

```sh
CLAUDEX_EFFICIENCY=advisory python3 ~/.local/share/claudex/efficiency/profile.py \
  --context-tokens 120000 --idle-minutes 75 --agent-count 5 --delegation-depth 2 --json
```

Nothing is automatically read from conversation histories. Values must be supplied by the caller; an empty preflight does not pretend to measure actual usage. No content, credentials or API tokens are logged.

The following opt-in environment variables set thresholds: `CLAUDEX_EFFICIENCY_SESSION_WARN_TOKENS` (100000), `CLAUDEX_EFFICIENCY_IDLE_WARN_MINUTES` (60), `CLAUDEX_EFFICIENCY_MAX_SUBAGENTS` (4), `CLAUDEX_EFFICIENCY_MAX_DELEGATE_DEPTH` (1), and `CLAUDEX_EFFICIENCY_MAX_EXTERNAL_CALLS` (0). They control warnings, **not provider-side billing caps**.

## Intended habits and existing Claudex features

- Focus sessions by task; preserve the reasoning trail for ongoing work. No automatic clearing.
- Large cold-resume warnings favor a checked, durable handoff over blind compaction. Goal Governor is responsible for preserving outstanding tasks and permissions.
- Avoid unnecessary mid-session model/effort changes. Existing Luna/Sol routing stays unchanged; this profile cannot verify provider cache availability.
- Use the existing `CLAUDEX_PROMPT_MODE=selective|aggressive|off` for separately tested tool-description optimization. Never rewrite unknown system instructions.
- Consolidate related user requirements deliberately rather than shortening them to fragments. This tool does not edit user messages.
- Bound subagents and paid external requests with real system-level controls when available. This diagnostic only reports violations of supplied measurements; **no hard spend limit is applied**.
- Measure observed context/usage and cache statistics at the provider boundary before deciding to upgrade a subscription. Avoid mistaking API list-price estimates for a bill.

## Validation and limitations

`python3 tools/efficiency/test_profile.py` and `python3 tools/efficiency/test_wrapper.py` test disabled defaults, explicit controls, threshold warnings and standard launcher behavior. This release implements the advisory foundation, **not** automatic context estimation, provider quota introspection, enforcement of subagent budgets, live savings measurement, or durable session rotation. Implement those only after identifying reliable event sources and testable provider-specific enforcement points.
