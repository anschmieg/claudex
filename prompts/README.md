# Claudex prompt customization — independent upstream-compatible files

`gpt-execution-overlay.md` is an **experimental, additive baseline** only.
It is deliberately **disabled by default**; set `CLAUDEX_GPT_OVERLAY=1` to compare
behavior, or set `CLAUDEX_GPT_OVERLAY_FILE` to point at an independently edited
regular file. The launcher leaves Claude Code's native system prompt untouched,
retains existing caller/SDK append-system-prompt values, and refuses symlinked
overlay files. Nothing in this directory replaces tool schemas or user security
controls. Disable via `CLAUDEX_GPT_OVERLAY=0`.

## Why not make an enormous merged system prompt?

In the captured real Claude Code 2.1.294 request, the top-level instructions
were about 5,857 characters, additional environment/session instructions 8,462
characters, and the 20 tools' descriptions plus schemas 45,231 characters.
The literal Claude Agent SDK identity sentence was only 62 characters.
Removing that identity is conceptually worthwhile but not a meaningful context
saving; the largest cost and regression risk are in tool descriptions.

Our long-term target is **selective, declarative replacement**, not cumulative
append-only boilerplate and not a monolithic copied prompt. A future translation-
boundary transformer should load one small ruleset file per concern, match known
upstream snippets exactly, replace only designated model-identity/behavior
sections, and optionally compact tool prose *only with proven invariants*.
It should preserve original upstream instructions everywhere else, including
new text introduced by Anthropic. Unknown text remains untouched.

Rules must be independently testable with `experiments/prompt-translation-rig/`
and support three outcomes: verified match and safe replacement; no match with
unmodified passthrough plus diagnostic; unexpected multiple matches with fail-
closed unmodified passthrough. Do not fuzzy-match unknown security instructions.
Measure token counts and behavior before enabling aggressive compression.

See `docs/GPT_HARNESS_ALIGNMENT.md` for the evidence and design rationale.
