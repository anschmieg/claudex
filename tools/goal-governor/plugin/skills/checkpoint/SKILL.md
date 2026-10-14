---
name: checkpoint
description: Record an evidence-backed milestone and actionable next step while working on a long-running project enrolled in the durable goal governor.
---
For any active governed goal, after meaningful progress and **before ending a normal turn**, write the next bounded actionable step plus verification to the durable record.

Use `python3 "$HOME/.local/share/claudex/goal-governor/cli.py" status --thread <uuid>` first.
Then:
`python3 "$HOME/.local/share/claudex/goal-governor/cli.py" checkpoint --thread <uuid> --expected-revision <current> --next-action "<concrete new action>" --evidence "<what was verified>" --artifact "<changed existing workspace file>"`

Evidence is hashed by the CLI from a real, changed, nonsensitive file beneath the project workspace. Never invent evidence; if no concrete artifact or safe work exists, do not fabricate one to perpetuate a loop. Instead call the block or propose-complete operation as appropriate.

Never repeat an ambiguous write, bypass human approval, or spawn a cron polling job. The supervisor continues work only after T3 confirms a successful settled turn and the goal has made verifiable progress.

Evidence variants: `--evidence-kind test_report --artifact <workspace-local-test-report>` accepts a hashed test-result file, and `--evidence-kind user_decision --evidence-ref <client-message-id>` verifies a human-origin T3 decision instead of requiring a source edit. Decisions do not authorize privileged external writes.
