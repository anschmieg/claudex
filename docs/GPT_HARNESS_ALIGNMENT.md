# GPT models in Claude Code: instruction alignment

## Evidence (2026-10-12 deterministic capture)

See `experiments/prompt-translation-rig/FINDINGS.md` in the development workspace for the raw-capture investigation. In a controlled no-inference test of real Claude Code 2.1.294 and Claudex's Shunt translator, the 5,857-character top-level system text was passed **unchanged** into the Responses `instructions` field. Nineteen ordinary tool schemas matched exactly; `WebSearch` intentionally became the Responses native web-search tool. Claude Code's environment message was passed as a Responses developer message. The test did not establish model-behavior parity.

### Claude Code's effective instructions

- Tell the agent it is an interactive coding agent using the Claude Code / Claude Agent SDK harness.
- Define **real** tool names and control rules: Read, Edit, Bash, subagents, permissions, hooks, session reminders and filesystem/memory conventions.
- Emphasize permission-mode boundaries and the handling of denied tool calls; the particular captured prompt did **not** include the same explicit "persist until solved" paragraph as Codex's base instructions.
- Contain substantial dynamic session context: current workspace, user/project instructions, skills and agent availability. Individual sessions may load additional Claude Code prompt fragments, so the capture is not a universal Claude Code template.

### Codex CLI's public base instructions

See [OpenAI's default Codex instructions](https://github.com/openai/codex/blob/main/codex-rs/protocol/src/prompts/base_instructions/default.md). In addition to tool/sandbox-specific directions, they explicitly:

- Encourage autonomous completion of the user's task within a turn instead of stopping at the first recoverable error.
- Direct the agent to use available tools, verify work and be clear about genuine blockers.
- Describe Codex's own shell/patch/plan tools, sandbox approvals, and task-execution conventions; these should **not** be copied literally into Claude Code, which has different tools and permission semantics.

## Recommendation: small additive GPT-focused instruction layer

Keep the Claude Code system/harness instructions, schemas, actual permission constraints, and project-level guidance. Add a concise **high-priority, user-configurable behavioral supplement** (e.g. appended via Claude Code's supported `--append-system-prompt` mechanism) to improve GPT's execution discipline. Do **not** replace Claude Code's instructions with Codex's full prompt or present unavailable Codex tools to the model.

Proposed draft (not automatically installed by Claudex):

> Work autonomously until the user's requested deliverable is complete or progress genuinely requires new authorization or input. When an ordinary tool fails, diagnose its cause using available *authorized* tools and pursue safe, relevant alternatives; a failed Read call does not necessarily mean Bash diagnostics are prohibited. Distinguish permission-denied results from explicit user refusals, and never bypass access restrictions, tool deny rules, or approval requirements. Preserve user-specified review checkpoints. Verify changes or state precisely before declaring completion. Report actual unresolved blockers with the concrete steps already attempted, without inventing success.

This is a candidate for **A/B testing**, not a proven universal prompt. Avoid adding large amounts of boilerplate that displace actual task context. A useful future test would run identical sandboxed tasks with and without the supplement at equal model/reasoning effort and observe autonomous error recovery and permission compliance.

## Codex model-specific reasoning defaults

Independently of the instruction strategy, Claudex now supports dynamically resolving implicit reasoning levels from Codex's `app-server` `model/list` metadata via `tools/codex-reasoning-defaults.py` (packaged as `codex-reasoning-defaults.py`). Explicit `--effort` values are preserved. For T3 Code, `claudex sync-t3` updates **the custom model's default picker option**, not arbitrary existing thread overrides. No model/effort table is hardcoded. Cache lifetime is six hours; a Codex-derived T3 provider snapshot is a secondary source when an older Codex binary does not list a newly released model. Re-run `claudex sync-t3` after Codex metadata updates or when T3's custom model list changes, then refresh T3 providers.

## Prompt shaping maintenance decision (2026-10-13)

The separate `prompts/gpt-execution-overlay.md` is a **test-only opt-in baseline** (`CLAUDEX_GPT_OVERLAY=1`); it is not enabled automatically. Appending preserves compatibility but also leaves potentially inconsistent upstream model identity and can add context. A future surgical transformer should identify stable, specific Claude-model assumptions in the *live* Anthropic system-text blocks, replace only those verified fragments with GPT-oriented equivalents, and optionally trim proven redundant text. Upstream tool schemas, tool/permission policies, and session context must pass through unchanged. Keep each replacement in its own versioned rule with exact match counts and a baseline diff; if upstream wording changes, skip and report rather than applying a speculative regex. Test translated Responses requests for role/tool parity before enabling production. Avoid wholesale system prompt forks or broad tool-description trimming without A/B tests.

### Measured context sizes and the proposed pruning boundary

The synthetic actual-client Claude Code 2.1.294 capture contains **5,857 characters** of top-level system text (including a **62-character** Claude-Agent-SDK identity line), **8,462 characters** of additional dynamic environment/session instructions, **28,488 characters** of tool descriptions, and **16,743 characters** of tool input schemas (20 tools). These are character counts, not exact token counts. Tool descriptions and schemas account for most of the measured prompt material.

Therefore the sensible order is: first, exact-anchored identity/assumption rewrites; second, removal of demonstrably duplicated, nonessential explanatory prose; third, controlled A/B trials of tool-description compaction. Keep Claude Code's actual permission controls, hooks, tool name/argument contracts and any user/project instructions intact. Use a declarative file per rule group, with testable exact-match counts and safe passthrough on upstream wording changes. Never fork the entire upstream prompt or broadly regex-strip tool-related language.
