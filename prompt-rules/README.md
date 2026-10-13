# Claudex prompt shaping: versioned, fail-closed rules

**Default for the Claudex-owned Shunt route: `selective`.** Set `CLAUDEX_PROMPT_MODE=aggressive` to add the three additional tool-description compression rules; set `CLAUDEX_PROMPT_MODE=off` to restore the upstream Claude Code prompt exactly. **Changing the mode requires restarting the Claudex Shunt gateway** because rules are loaded once per process. The separate legacy `CLAUDEX_GPT_OVERLAY` remains disabled and is not needed for these modes.

The current rule files are independent, reviewed JSON fixtures:

- `01-identity.json`: replace the Claude Agent SDK identity and generic agent description with GPT-compatible coding-agent identity and a short autonomous-error-recovery policy.
- `02-environment.json`: replace a specific Claude-model recommendation block with GPT-backend-neutral instructions; does not touch tool permissions or session context.
- `03-tool-compression.json`: in selective mode, remove Anthropic prompt-cache-specific wakeup heuristics; in aggressive mode, also compact redundant examples in `CronCreate`, `EnterWorktree`, and `Workflow` descriptions. Their safety/authorization constraints and tool schemas remain unchanged.

The same upstream prompt is assembled by whatever Claude Code version is installed. This translator only changes `instructions` and `tools[].description` for the **Claudex-owned `claudex-codex` ChatGPT Responses route**, never messages, tool names, parameter schemas, or other Shunt providers. Every rule must find exactly one intended fragment and its SHA-256 must match. If Anthropic changes the section, the rule is skipped with a warning and the original text passes through. No fuzzy matching, no full-prompt fork, and no automatic edits to unknown text.

## Maintaining upstream compatibility

Capture a fresh synthetic Claude Code request through `experiments/prompt-translation-rig`, compare the diff, and inspect any warning for an unmatched rule. Update only the relevant JSON rule's boundary text or exact-match anchor and SHA-256 after reviewing the new upstream passage. Run `PYTHONDONTWRITEBYTECODE=1 python3 tools/test-prompt-rules.py` against the updated fixture and the pinned Shunt Rust tests. Do not strip or replace new system/security text automatically.

## Test and deployment status

These modes are protocol/compatibility optimizations. Deterministic synthetic tests can verify the exact rewrite and structural invariants, but cannot establish whether the model becomes more autonomous or whether compacted descriptions reduce real-world accuracy. Keep `selective` as the stable baseline; enable `aggressive` explicitly only after testing it in the intended agent workload. Shunt log messages report applied or unmatched rule IDs **without logging prompt bodies or credentials**.

## Verified native HTTP replay (2026-10-13)

Real ARM64 Shunt translated the synthetic Claude Code 2.1.294 request to a local fake Responses backend. The user ran all three deterministic modes: off PASS (0 matched, 0 characters saved), selective PASS (4 rules, 1,108 characters saved), aggressive PASS (7 rules, 2,565 characters saved). All 20 tool definitions retained their names and parameter schemas, and every message matched the baseline. No inference was used. The source test is `tools/test-shunt-http-modes.py`; run it with the locally compiled Shunt using the `--shunt` and `--mode` arguments. Captured requests remain untracked for privacy.
