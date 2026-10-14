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
