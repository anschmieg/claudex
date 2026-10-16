# Claudex adaptive-efficiency QA — 2026-10-16

Tested source: `1c67212`, branch
`review/adaptive-efficiency-hardening-20261016`.
All tests use synthetic credentials. **No actual GPT/Anthropic inference,
production deployment, session restart, or user conversation replay.**

## Verified

| Scope | Result | Evidence |
| --- | --- | --- |
| Efficiency regressions | PASS — 58/58 | `python3 -m unittest discover -s tools/efficiency -p 'test_*.py'` |
| Prompt regression | PASS — 7/7 | `python3 tools/test-prompt-rules.py` |
| Security/public-source audit | PASS | `python3 tools/audit-public-source.py` |
| Bash launcher and installer syntax | PASS | `bash -n claudex && bash -n install.sh` |
| Existing Claude/Shunt protocol fixtures | PASS — 102/102 | `python3 experiments/prompt-translation-rig/analyze.py` |
| Actual Claudex launcher function (mock Claude transport) | PASS — 8/8 cases | `python3 tools/efficiency/launcher_integration_probe.py` |
| Claude Code 2.1.294 Linux ARM64 native CLI startup | PASS — 3 synthetic API requests | Isolated HOME, local fake Anthropic server |
| Claude Code 2.1.300 Linux ARM64 native CLI startup | PASS — model request + normal stream events | Isolated HOME, local fake Anthropic server, `--agents` containing `autoCompactWindow` |
| Claude Code 2.1.300 → patched Shunt → fake Responses | PASS — 5 inbound, 5 outbound requests | Synthetic tool-cycle response HTTP 200; GPT alias correctly maps `gpt-6.1-sol[1m]` → `gpt-6.1-sol` |
| New native Read schema | PASS — `allow_large` available | Captured Claude Code 2.1.300 Anthropic tool schema, including through patched Shunt |
| Direct synthetic `gpt-fast` selection | PASS with precedence detail | Without explicit main `--model`, routed to Luna; explicit main `--model Sol` took precedence for that top-level agent |

The **launcher integration** test uses the actual committed Bash
`launch()` and settings-merge code; only the external Claude executable
and runtime lifecycle helpers are stubbed. Its cases verify adaptive new/old
client gating, off-mode invariance, caller `--agents`, SDK settings merge,
invalid worker budget rejection, project agent precedence, and optional
read-guard wiring.

**Native-client protocol tests use a fake backend intentionally returning
HTTP 400**, so the Claude CLI exits 1 after reaching it; this is an expected
negative response, not a successful coding task. The Shunt synthetic
tool-cycle fixture returns 200 and translates successfully.

Local macOS native CLI tests are independently blocked by the sandbox
at `/tmp/claude-501` (even after scoped access approval). Linux native
binaries on Hermes were therefore used in isolated temporary directories
without connecting to running T3 Code/Claudex sessions.

## Not verified / release blockers

- Actual auto-compaction triggers at 192K, 256K, 272K or 384K tokens.
- Actual *subagent* compaction at 192K during a working delegated task;
  accepting `--agents` alone does not prove runtime compaction.
- Actual `Read(allow_large)` execution with a large file; the tool schema
  and gateway translation, not runtime file-return behavior, were verified.
- Durable conversation state and coding-quality preservation after compaction.
- Cache hit/write lifetimes and provider-specific request costs.
- Latency, cost and coding quality comparisons from matched live model tasks.
- Full Claude Agent SDK/T3 session-owner lifecycle under active tool calls,
  approvals, crashes and concurrent user inputs.

Upgrading a production client or claiming cost improvement therefore remains
unjustified. Use a staged opt-in real inference environment with available
capacity for remaining end-to-end and comparative tests.

## Safety and follow-up

No production session was restarted or changed. Installed Claude Code
2.1.294 on Apollo remains intact. The staged 2.1.300 test client is separate.
The failed macOS smoke runs did not reach any network endpoint; on Hermes,
all model calls went exclusively to synthetic localhost endpoints.

For future verification, rerun the launcher integration probe and regressions
before any release. Then run matched representative coding tasks with
explicit compaction windows and telemetry, confirming `compact_boundary`
events, retained task information, cost, cache behavior and quality.
