---
name: reconcile
description: Reconcile natural-language user goal or priority changes from the current T3 Code thread with durable Goal Governor goals, tasks and acceptance criteria.
---
When a human updates the project goal in the T3 Code conversation, synchronize automatically without requesting a second goal-management prompt.

Call `python3 "$HOME/.local/share/claudex/goal-governor/cli.py" sync --thread <current-t3-thread-uuid>` to detect genuine client-origin user messages (not scheduled/agent messages). Then inspect the goal with `status --thread <uuid>`.

For every new relevant `pending_message_ids` item, compare the actual conversation message against the existing durable goal. If priorities or acceptance changed, use:
`python3 "$HOME/.local/share/claudex/goal-governor/cli.py" reconcile --thread <uuid> --message-id <id> --title "<revised title>" --priority "<safe next action>" --acceptance "<testable criterion>"`

If a message was not a goal change, mark it reviewed by calling `reconcile --thread <uuid> --message-id <id>` without replacing acceptance. Create explicit ready tasks for new independent work before marking reconciliation complete. Never remove immutable safety constraints, reinterpret authorizations, or start protected external writes. A blocked task stays blocked until its own prerequisites are actually met. Do not create cron loops.
