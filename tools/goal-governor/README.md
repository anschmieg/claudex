# Goal Governor for Claudex/T3 Code

Status: implementation prepared; production activation requires an explicit operator step.

This is a Claude Code plugin plus an independent user-level systemd one-shot. No changes to Claudex, Shunt, Claude Code or T3 Code source. The previously deployed failure-recovery timer remains responsible for HTTP errors and crashed turns.

## Components

- plugin/: namespaced Goal Governor skills (start, checkpoint, status) and a read-only SessionStart hook. No forced Stop hook or Claude cron jobs.
- state.py / cli.py: private, atomic, fsynced per-thread goals with acceptance criteria, next action, revision, opt-in status, and changed SHA256 workspace evidence.
- supervisor.py: only continues successfully completed T3 turns with a new evidence-backed checkpoint; idempotent T3 command IDs are persisted before dispatch and recovered after ambiguous responses.
- claudex-governor.service / claudex-governor.timer: independent 90-second external checks, with 6 starts/hour and 24 starts/day. No LLM calls when no eligible work.
- run-governor.sh: offline uv runner using the existing failure recovery controller's private websocket dependency cache.

## Invariants

The goal is disabled by default until the user explicitly enables it. The governor does not resume running, pending, error or failed turns, nor does it interfere with the existing failure supervisor. Explicit user interrupts, pending user input, pending T3 approvals, human messages after the last completed turn and invalid project/provider identity prevent continuation.

Each continuation requires a different next step and a changed nonsensitive workspace evidence artifact. A later normally completed turn with no fresh checkpoint causes the goal to become needs_review, not an endless loop. Completing a project requires proposing independent verification, not merely asserting success.

Never replay a browser/API/sudo write with ambiguous outcome or override explicit human approvals. The pending Camofox adapter grant remains independently protected. An external blocker must be recorded as blocked, which stops autonomous continuation.

User-level plugin is auto-loaded by future Claude Code sessions when installed under ~/.claude/skills/goal-governor. Existing T3 sessions may require /reload-plugins or a new session.

## Staged installation

Run on Apollo (local macOS, not inside ssh):

    bash "$HOME/Documents/ChatGPT Workspace/claudex/publishing/claudex-public-source/tools/goal-governor/deploy-from-apollo.sh"

The installer tests and stages the plugin and independent systemd service for t3, but leaves claudex-governor.timer disabled. First remove and verify the exact obsolete five-minute Claude Code cron job in the original T3 thread (CronList, CronDelete by exact job ID, CronList again). Then enable the goal separately.

On Hermes as the operator, after confirming the obsolete cron is removed:

    bash "$HOME/.local/src/claudex/goal-governor-stage-v1/activate-goal-on-hermes.sh" <thread-id> <removed-cron-job-id>

That activation obtains the existing T3 project workspace from read-only SQLite, seeds conservative acceptance criteria and a first safe actionable step, runs a dry check, then explicitly enables the goal and its systemd timer. It does not grant protected external write approval or restart T3 Code.

## Controls

As t3, use cli.py under ~/.local/share/claudex/goal-governor/: status, checkpoint, pause, resume, block, propose-complete, enable and disable with --thread. Stop the timer independently with systemctl --user disable --now claudex-governor.timer (in t3's systemd user manager).

## Verification

    PYTHONDONTWRITEBYTECODE=1 python3 tools/goal-governor/test_governor.py
    PYTHONDONTWRITEBYTECODE=1 python3 tools/goal-governor/test_integration.py
    claude plugin validate ./tools/goal-governor/plugin

Tests use synthetic goal records and an injected fake T3 RPC. No real model is invoked. A live test of resumed completed turns plus an intentional non-progressing stop is required before production autonomy can be considered fully validated.
