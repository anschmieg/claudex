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

## Adaptive native compaction (opt-in)

Set `CLAUDEX_EFFICIENCY=adaptive` before launching Claudex to use Claude Code native auto-compaction after 64,000 context tokens, instead of 272,000. Configure `CLAUDEX_EFFICIENCY_TARGET_TOKENS` (16,000–272,000). For a known large-read task at launch, `CLAUDEX_EFFICIENCY_LARGE_READ=1` expands the budget (default 192,000; override with `CLAUDEX_EFFICIENCY_LARGE_READ_TOKENS`). Defaults and advisory mode remain unchanged. This does not automatically detect mid-turn reads.

Idle pre-cache-expiry compaction is not implemented: no verified safe programmatic compact interface and cache TTL for the GPT backend were established. Do not claim an idle timer or savings.

## Lifecycle controller prototype (not yet activated)

`tools/efficiency/lifecycle.py` provides deterministic pre-expiry idle compaction eligibility: requires verified session ownership, known cache TTL, inactivity, no pending user interaction, no active tools, sufficient context, a safety buffer and a cooldown. It never issues `/compact` by itself; live dispatch remains disabled pending a trustworthy same-session API and atomic lease. `tools/efficiency/read_budget.py` selects expanded budgets for recognized large reads, but the running Claude Code process cannot be changed safely by rewriting its environment mid-turn. Dynamic expansion is not wired yet. Both components are covered by synthetic tests.


## Adaptive Read hook (opt-in, active)

Adaptive launches now attach a native Claude Code `PreToolUse` hook for `Read` to the **session-private** settings. If a file exceeds 160,000 bytes and the requested read has no explicit bounded range, the hook denies only that invocation and tells Claude Code to use `Read(offset=..., limit=150)`. Existing bounded reads, all other tool calls and permission settings pass unchanged. The hook does **not** expand an already running model context; this is preventive chunking. It does not introspect file contents or disclose the file path in diagnostic output. This is a conservative enforcement layer, not a verified automatic mid-turn window resize.

Idle cache-expiry compaction remains unactivated because Claude Code currently does not expose a documented, safe programmatic idle compaction dispatch interface. The lifecycle controller rejects attempts without verified ownership and TTL; enabling a blind timer would be unsafe.
