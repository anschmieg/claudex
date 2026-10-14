---
name: status
description: Inspect a durable Goal Governor project's acceptance criteria, progress, next action, or explain why automatic continuation is paused.
---
Check the goal: `python3 "$HOME/.local/share/claudex/goal-governor/cli.py" status --thread <uuid>`.
For an external blocker, explicitly pause continuation using:
`python3 "$HOME/.local/share/claudex/goal-governor/cli.py" block --thread <uuid> --reason "<precise condition requiring intervention>"`.

If all criteria appear satisfied, request independent verification rather than declaring a goal complete:
`python3 "$HOME/.local/share/claudex/goal-governor/cli.py" propose-complete --thread <uuid> --evidence "<test and acceptance evidence>"`.

User controls: `pause`, `resume`, `enable`, and `disable` with `--thread <uuid>`. Never silently re-enable disabled goals.

Automatic sync: the external governor tracks new T3 client-origin user messages by ID.
If status shows pending intent IDs, read the latest user instructions from this conversation and call:
`python3 "$HOME/.local/share/claudex/goal-governor/cli.py" reconcile --thread <uuid> --message-id <pending-id> --title "<revised goal>" --priority "<next concrete action>" --acceptance "<new criterion>"`.
Only change acceptance criteria when the user actually changed the goal. Never remove immutable authorization constraints.
Use `add-task --thread <uuid> --id <slug> --title "<task>"` and `set-task --thread <uuid> --id <slug> --state blocked --reason "<precise gate>"`; independent ready tasks remain executable.
Use `set-task ... --state completed --evidence "<verified result>"` once tested.
Do not blindly set the entire goal blocked while any independent task is ready.

The `sync` CLI command imports new client-origin instructions from the T3 thread; it never interprets them as privileged approvals.
