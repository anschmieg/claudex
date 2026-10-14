---
name: tasks
description: Manage independent ready, running, blocked, deferred and completed tasks for a durable Goal Governor objective.
---
Inspect goal: `python3 "$HOME/.local/share/claudex/goal-governor/cli.py" status --thread <uuid>`.

Create a task: `python3 "$HOME/.local/share/claudex/goal-governor/cli.py" add-task --thread <uuid> --id <stable-slug> --title "<actionable work>"`. Dependencies: repeat `--depends <existing-task-id>`.

Move a task: `python3 "$HOME/.local/share/claudex/goal-governor/cli.py" set-task --thread <uuid> --id <task-id> --state <ready|running|blocked|completed|deferred>`. A blocked task requires `--reason`; completed requires truthful `--evidence` and should be paired with verifiable checkpoint evidence where possible.

A blocked browser-maintenance task is not a reason to stop unrelated alpha development. Select another ready independent task. The overall goal should only be blocked when all remaining executable tasks are blocked by real prerequisites. Do not remove or falsify protected task blockers.
