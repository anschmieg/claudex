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

Set `CLAUDEX_EFFICIENCY=adaptive` before starting a **new** Claudex session.
The installed Claude Code v2.1.294 supports
`CLAUDE_CODE_AUTO_COMPACT_WINDOW` (100K–1M tokens) and a
`[1m]` context suffix. **It does not expose supported arbitrary 256K/512K
model-context variants.** The tiers below are therefore *compaction budgets*,
not true per-model context capacities. Claudex still uses its existing
1M-capable GPT routing. No runtime model switch or forced context expansion
is claimed.

| Opt-in budget tier | Nominal planning budget | Native compact threshold |
| --- | ---: | ---: |
| `small` | 256K | 192K |
| `medium` (**default**) | 512K | 256K |
| `large` | 1M | 768K |

The 256K medium default is deliberately below the previous non-adaptive
272K threshold (384K was 41% higher). It is a **trial value**, not a
measured efficiency optimum; the tiers are budgets, not actual model windows.
It replaces the earlier 64K Claudex adaptive setting (which is below the
client's documented 100K minimum); the existing **non-adaptive** Claudex
configuration remains at 272K.

Select `CLAUDEX_EFFICIENCY_CONTEXT_TIER=small|medium|large` before launch.
`CLAUDEX_EFFICIENCY_TARGET_TOKENS` overrides the tier threshold with an
integer from 100000 through 1000000. For known whole-file work at launch,
`CLAUDEX_EFFICIENCY_LARGE_READ=1` raises the threshold to at least 768K
(or the explicit `CLAUDEX_EFFICIENCY_LARGE_READ_TOKENS` value). These
settings operate through the **session-private** Claude Code settings plus
the launcher environment and do not alter stored conversation state.

Example:

```sh
CLAUDEX_EFFICIENCY=adaptive CLAUDEX_EFFICIENCY_CONTEXT_TIER=medium claudex
# For a new large-read session:
CLAUDEX_EFFICIENCY=adaptive CLAUDEX_EFFICIENCY_LARGE_READ=1 claudex
```

### Large reads

Adaptive mode **no longer denies whole-file `Read` calls by default**.
A complete read can be cheaper and more informative than repeated restricted
reads when the task needs the entire file. The old native PreToolUse read
guard remains available only through
`CLAUDEX_EFFICIENCY_READ_GUARD=deny`; the default is `off`.
It denies unexpectedly large whole-file reads (160KB threshold) and
requests chunks. This guard does *not* expand the context. Existing
unbounded reads in a running session are not intercepted for tier expansion.

`tools/efficiency/read_budget.py` is still a **prototype**: selecting an
expanded target does not change a running Claude Code session. Actual live
tier switching requires a verified Claude Code model-metadata mechanism and
session-owner coordination; an arbitrary `[256k]` or `[512k]` suffix
must not be treated as native support.

### Deliberate compaction and cost

Interactive Claude Code can execute `/compact`; an Agent SDK session owner
can issue a supported slash command and observe a `compact_boundary`.
Neither grants Claudex authority to inject `/compact` into an active T3
Code or interactive session. Adaptive sessions explicitly set `idleCompaction: false` in private
settings to avoid applying Anthropic one-hour cache TTL assumptions to the
GPT backend. No autonomous idle compaction is enabled: the
owner-specific atomic lock, activity/approval checks, provider cache TTL and
verified dispatch/completion are still missing. The existing
`tools/efficiency/lifecycle.py` remains a fail-closed offline prototype.
Do not run timer-based compaction on incomplete information.

### Verification and rollout

```sh
python3 -m unittest discover -s tools/efficiency -p 'test_*.py' -v
python3 tools/test-prompt-rules.py
python3 tools/audit-public-source.py
bash -n claudex
```

The budget policy, configuration writes and rollback are covered by tests.
**Real live auto-compaction thresholds, task quality, provider cache reuse,
large-context coding, model switching and cost savings are not yet
measured.** Do not infer a cost reduction from selecting a smaller threshold.

To roll back for a **new** session, unset `CLAUDEX_EFFICIENCY` or set it
to `off` (original 272K non-adaptive configuration). An already-running
Claude Code process keeps its launch-time settings; no restart or mutation
of existing sessions is attempted. Reinstall only when ready to deploy
the committed source.

### Adversarial review improvements (2026-10-16)

**Native worker budgets (Claude Code 2.1.296+):** Upstream
[v2.1.296](https://github.com/anthropics/claude-code/releases/tag/v2.1.296)
supports a per-subagent `autoCompactWindow` property in agent frontmatter
and `--agents` JSON, plus the `Read(allow_large)` escape hatch.
In adaptive mode, Claudex now supplies `--agents` overrides only for
**unchanged, Claudex-owned** definitions, with the original prompts,
models and effort settings and a default worker budget of 192K tokens
(capped at the coordinator threshold). No user/agent files are mutated.
Custom, project-scoped, edited, symlinked or unowned definitions are left alone. An
explicit caller `--agents` flag is never overwritten or merged. Installed
Claude Code 2.1.294 retains its current worker behavior; it cannot use
this feature. This support is unit-tested but awaits a real >=2.1.296
CLI and T3 Code integration test.

Set `CLAUDEX_EFFICIENCY_WORKER_COMPACTION=off` to suppress worker overrides,
or `CLAUDEX_EFFICIENCY_WORKER_TARGET_TOKENS` to choose a worker budget
between 100K and the coordinator threshold. The default is `auto`
(version-gated). These are compaction thresholds, not strict ceilings.

**Idle compaction:** Upstream
[v2.1.299](https://github.com/anthropics/claude-code/releases/tag/v2.1.299)
introduced/documented terminal idle compaction for Anthropic's one-hour
prompt cache. The GPT backend cache TTL remains unverified; adaptive
launches therefore explicitly disable idle compaction only in their
session-private settings. No untrusted background timers or session-owner
writes are enabled.

**Read-budget correctness:** `read_budget.py` rejects an estimated read
that exceeds its expanded budget rather than representing it as
accommodated. It remains an offline planning prototype, not live context
expansion. The optional legacy Read hook now quotes paths containing
spaces or shell metacharacters.

**Compare observed usage:** Record the same coding workload with
`--output-format stream-json --verbose` at 192K, 256K, 272K and
384K (same model, effort, repository, task and permissions). Protect raw
captures: they may contain private conversation and tool data. Then run:

```sh
python3 tools/efficiency/compare_telemetry.py \
  baseline=baseline.jsonl small=small.jsonl \
  medium=medium.jsonl old_adaptive=384k.jsonl
```

The comparator emits *only aggregate observed* token counters, cache
coverage, and compact-boundary counts. It deduplicates repeated assistant
message IDs and discards all text. These counters alone **do not** prove
provider charges, savings, task quality, or cached-context integrity.
Compare task results and timing separately, and validate actual billing
and provider cache behavior before endorsing a threshold.

**Release gate:** All tests and audits must pass, followed by real
opt-in CLI and T3 integration tests on 2.1.294 and staged >=2.1.296,
including `Read(allow_large)`, subagent compaction, existing user
`--agents`, authentication, and session resumes. No running services
are changed or restarted by this branch.
