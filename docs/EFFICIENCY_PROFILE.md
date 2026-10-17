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

### Native-first correction — 2026-10-17

The earlier session-generated `--agents` overrides and `agents.py` have
been removed. They could shadow recursively discovered or user-defined agents,
and a global compaction environment variable defeated their worker budgets.

Adaptive launches now remove `CLAUDE_CODE_AUTO_COMPACT_WINDOW` from the
process and private settings environment, set native `autoCompactWindow`,
and pass `--autocompact` for the coordinator (unless overridden by caller).
Non-adaptive sessions retain their 272K environment default. The configured
native agent definitions and their frontmatter are never modified or
duplicated by Claudex. Separate 192K worker compaction is **not claimed**.
The former worker-specific Claudex environment controls are obsolete
and now produce a warning if explicitly set.

Direct `--agent` sessions use their selected agent's model unless the caller
explicitly supplies `--model`. This preserves the existing model hierarchy.

### Mandatory efficiency CI

Fast CI runs the native efficiency unit suite plus real launcher-function
integration tests. Linux x86-64 native CI also runs pinned Claude Code 2.1.300
through patched Shunt into a local fake Responses backend, comparing
`CLAUDEX_PROMPT_MODE=off` against `selective`.

The pinned `o200k_base` tokenizer estimates serialized first-request tokens.
A test fails above 19K estimated tokens, below 100 tokens saved, or when
optimization changes user messages, model routing, tool parameter schemas,
or other protected request fields. The gate also independently reconstructs
all allowed exact-hash prompt-rule changes and rejects any unexpected
system-instruction or tool-description edits. The only ignored volatile field for
equality is `prompt_cache_key`. Baseline synthetic 2.1.294 capture:
14,443 tokens off versus 14,102 selective, saving 341.

These are repeatable synthetic input estimates, **not provider charges**.
Real-model coding quality, cache hit/write cost and actual compaction
must still be benchmarked before production deployment.

### Fixed golden and multi-turn safeguards (2026-10-17)

The second adversarial review identified three false positives in the first
token-cost gate: removing `Read` and `Bash` still passed, adding redundant
instructions to both modes still passed, and silently changing the prompt
cache key still passed. The replacement test now includes:

- **Independent pinned golden:** `tools/efficiency/baselines/claude-2.1.300-shunt.json`
  records all 20 expected tool names (in order), hashes of the critical
  `Agent`, `Bash`, `Read`, `Edit`, and `Write` non-description schemas,
  and SHA-256 hashes of the three separately reviewed prompt-rule files.
  CI never regenerates this golden. Changes require an explicit human review
  of the tool capabilities, safety instructions, and token-cost effects.
- **Fixed first-turn budgets:** 16,000 estimated tokens unoptimized;
  15,600 optimized; at least 100 saved. The source snapshot from Claude Code
  2.1.300 measured 15,415 versus 15,028. These independent limits prevent
  an inflated unoptimized request from concealing increased optimized cost.
- **A deterministic four-request sequence:** the first real native
  Claude Code request is followed through the same Shunt process by three
  synthetic Anthropic request snapshots representing an initial user turn,
  a `Bash` tool call and result, and a follow-up retaining that history.
  Each replay turn must preserve its tool inventory and context content;
  history must grow, and no unreviewed system-prompt/tool-description
  transformations may occur.
- **Cumulative budgets:** replay requests must remain below 2,400 estimated
  tokens apiece; all four requests together must stay below 22,200
  unoptimized and 21,800 optimized, saving at least 100. The locally
  captured older client replay measured 19,541 versus 19,200 across the
  four requests, saving 341.
- **Within-session cache identity:** the three requests belonging to the
  controlled replay session must expose one nonempty, stable
  `prompt_cache_key`. The separate native first request is deliberately not
  treated as the same cache session. The test verifies *key stability*, not
  actual provider cache reads/writes or billing.
- **Negative-test enforcement:** removing tools, mutating a protected tool
  schema, increasing both modes beyond their fixed baselines, omitting a
  tool result, changing a cache key mid-session, or modifying audited prompt
  rule contents must each cause a failing regression test.

The release gate remains **synthetic and non-billing**. It verifies request
shape, deterministic context growth, token estimates, and cache-key
continuity. It does *not* prove that Claude Code autonomously issued and
completed the replayed tools, that the GPT backend honored cache reuse,
or that compaction preserved the quality of a long real coding task.
Those require separate, opt-in provider-backed and session-owner tests.
