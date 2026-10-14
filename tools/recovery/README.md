# Claudex durable recovery controller (T3 Code)

This is an **independent supervisor**, not a recurring Claude Code agent task. It is a Python 3 systemd-user oneshot, invoked by a timer every ~60 seconds. It does **not** patch Shunt, Claude Code or T3 Code, and does **not** write to T3's SQLite database.

## What it does

- Reads the existing T3 Code projection SQLite in **read-only** mode for an **explicitly enrolled** ClaudeAgent/Claudex thread.
- Only considers newly settled failed turns with evidence of a transient transport/API/stream failure. Successful turns, routine tool calls and five-minute cron checks never trigger dispatch.
- Requires the same project/provider, no pending T3 user-input or approval request, no user interruption, and no newer user message.
- Recovering an apparently running turn additionally requires a stopped provider, >15 minutes without completion, >3 minutes without activity, and **no active Claudex lease** anywhere for that user. It never kills an agent or interrupts a running turn.
- Persists an intent with a **stable deterministic commandId and messageId before network dispatch**. If a transport timeout makes acceptance ambiguous, it checks T3's command receipts/messages and resends **the same idempotent command**, never a new one. A rejected receipt blocks further automatic attempts.
- Limits each failure chain to **two successful resumptions**, with short backoff. Once an agent succeeds, no further work is triggered. No recursive monitoring prompts or agent cron jobs are created.
- Injects a narrowly worded continuation into the **original T3 thread** through T3 Code's authenticated local WebSocket RPC. The agent must reconcile ambiguous writes read-only and honor approval gates; the controller never directly replays browser/sudo/API mutations.
- Detects existing manual approvals as a hard block. **External browser-controller grants remain subject to their own explicit human approval.** This supervisor does not authorize, alter or retry those protected operations.

**Existing Claude Code cron jobs are separate.** The old durable */5 job must be identified using `CronList` in the original thread and removed by its *exact job ID* using `CronDelete`. Do not delete unrelated schedules. This controller does not modify Claude Code's scheduler internals.

This is reliable failure-triggered continuation, *not* a general AI goal governor: a short successful turn is not automatically judged "incomplete". That requires a separate durable acceptance policy rather than repeatedly prompting an LLM.

## Controls

Install the verified `controller.py` to `~/.local/share/claudex/recovery/controller.py`, and the service/timer files to `~/.config/systemd/user/`. Run as the same Unix user that owns T3 Code. The installer uses **`uv run --with websockets==16.0`** with the target user's system Python and a user-owned uv cache at `~/.local/state/claudex-recovery/uv-cache`. It prefetches the pinned package once, then both the authenticated read-only check and systemd one-shot run with **`uv --offline`**, so a future network outage cannot cause a dependency download. No persistent `.venv`, pip installation, system Python modification, or T3 Code runtime change is needed. If uv is unavailable or the package cannot be prefetched, the installer stops **before enabling the timer**, preserving the existing enrollment.

- `python3 controller.py --enroll-thread <T3_THREAD_UUID>`: explicitly enroll exactly one existing Claudex thread and establish a UTC starting point. Historic failures cannot trigger replay. Refuses existing configuration.
- `python3 controller.py --status`: safe local status only.
- `python3 controller.py --once`: **dry run**; no T3 dispatch or ledger updates.
- `python3 controller.py --probe-auth`: one authenticated read-only T3 Code HTTP probe using a 2-minute ephemeral access token. No token is logged or saved.
- `python3 controller.py --once --live`: one gated recovery evaluation; only sends a command for an eligible failure after enrollment.
- `touch ~/.local/state/claudex-recovery/pause`: stop automatic recovery without touching T3 Code or Claudex.
- `rm ~/.local/state/claudex-recovery/pause`: opt back in only after reviewing state.
- `systemctl --user disable --now claudex-recovery.timer`: disable the independent systemd timer.

The service is memory/CPU capped. Only whitelisted **state transitions** appear in journal; no prompts, browser tokens, bearer secrets or raw tool outputs are logged. Recovery intents, config and ledger are mode 0600 under a mode-0700 user-owned directory. No polling turn is created while T3 is healthy.

## Testing

Run `PYTHONDONTWRITEBYTECODE=1 python3 tools/recovery/test_controller.py` and `python3 tools/recovery/test_transport.py` in the source checkout. Tests use synthetic SQLite and mock T3 RPC; no tokens or model inference.

The source package includes `deploy-from-apollo.sh`, which stages only these files and runs the guarded `install-on-hermes.sh`. For compatibility with T3 Code, `--probe-auth` must pass on the actual host before enabling `claudex-recovery.timer`. The real T3 command sender is based on T3 Code's authenticated `orchestration.dispatchCommand` WebSocket RPC `thread.turn.start`, with idempotent command/message identifiers; initial test against an injected fake server is mandatory. As T3 updates, do not use an unverified command schema in production.

## Rollback and scope

Do not delete history or mutate the browser-controller's pending-operation records. Disable the timer, move the private recovery config to a backup location, and retain the state ledger for forensic recovery. Existing T3 threads, Claudex binaries, credentials and source trees are unchanged. The current release enrolls one thread at a time; other threads require explicit enrollment and a reviewed upgrade to multiple-goal configuration.
