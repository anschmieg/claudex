---
name: start
description: Enroll a durable autonomous project goal for an existing T3 Code Claudex thread. Only when the user explicitly requests continuous goal management.
disable-model-invocation: true
---
Enroll a concrete goal with verifiable acceptance criteria and the **same existing T3 thread**, never a new thread.

Use the separately installed executable:
`python3 "$HOME/.local/share/claudex/goal-governor/cli.py" init --thread <uuid> --workspace <absolute-workspace> --title "<goal>" --acceptance "<criterion>" --acceptance "<criterion>" --next-action "<first meaningful action>"`

Enrollment is initially disabled. Show the user the goals and acceptance criteria; enable continued turns **only with explicit user authorization**:
`python3 "$HOME/.local/share/claudex/goal-governor/cli.py" enable --thread <uuid>`

The independent timer is responsible for continuation, **not this skill**. Do not create CronCreate, /loop, or ScheduleWakeup jobs. Maintain all existing privileged browser operations and approvals unchanged.
