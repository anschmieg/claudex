#!/usr/bin/env bash
# Explicit opt-in after the obsolete Claude Code recurring job was removed.
set -euo pipefail
THREAD="${1:?Usage: activate-goal-on-hermes.sh <T3 thread UUID> <deleted-cron-job-id>}"
DELETED_CRON="${2:?Provide the exact removed recurring Claude Code cron job ID}"
[[ "$THREAD" =~ ^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$ ]] || exit 2
[[ "$DELETED_CRON" =~ ^[a-zA-Z0-9_-]{6,24}$ ]] || exit 2
USER_ID="${CLAUDEX_TARGET_USER:-t3}"
HOME_DIR="$(getent passwd "$USER_ID" | cut -d: -f6)"
CLI="$HOME_DIR/.local/share/claudex/goal-governor/cli.py"
SUPERVISOR="$HOME_DIR/.local/share/claudex/goal-governor/supervisor.py"
[[ -f "$CLI" && -f "$SUPERVISOR" ]] || { echo "Install the Goal Governor first" >&2;exit 3; }
sudo -n systemctl --machine="$USER_ID@.host" --user is-active claudex-recovery.timer >/dev/null

# Only the user who removed/verified the exact old job can attest this.
# We do not perform destructive cron operations inside activation.
echo "Operator attests obsolete recurring Claude Code job '$DELETED_CRON' was removed."
WORKSPACE="$(sudo -n runuser -u "$USER_ID" -- env HOME="$HOME_DIR" USER="$USER_ID" /usr/bin/python3 - "$THREAD" <<'PY'
import sqlite3,sys
from pathlib import Path
conn=sqlite3.connect("file:"+str(Path.home()/".t3/userdata/state.sqlite")+"?mode=ro",uri=True)
row=conn.execute("""select p.workspace_root from projection_threads t
join projection_projects p on p.project_id=t.project_id
join projection_thread_sessions s on s.thread_id=t.thread_id
where t.thread_id=? and s.provider_name='claudeAgent' and s.provider_instance_id='claudex'""",
(sys.argv[1],)).fetchone()
if not row or not Path(row[0]).is_dir():sys.exit(2)
print(row[0])
PY
)"
[[ "$WORKSPACE" = /* ]] || { echo "Invalid project" >&2;exit 4; }
STATE="$HOME_DIR/.local/state/claudex-governor/goals/$THREAD.json"
if sudo -n test -f "$STATE";then
  echo "Existing goal retained, not overwriting acceptance criteria."
else
  sudo -n runuser -u "$USER_ID" -- env HOME="$HOME_DIR" USER="$USER_ID" /usr/bin/python3 "$CLI" init \
    --thread "$THREAD" --workspace "$WORKSPACE" \
    --title "Build and verify a functioning Camofox/VPN-backed ChatGPT Responses API" \
    --acceptance "Documented Responses-compatible requests execute end-to-end with a verified model response and safe authentication." \
    --acceptance "Synthetic protocol, concurrency, idempotency, and authentication tests pass reproducibly without disclosing credentials." \
    --acceptance "The service's lifecycle, failure recovery, deployment, and rollback have verified repeatable acceptance evidence." \
    --acceptance "Any privileged browser-adapter or external write is executed only after the required explicit owner authorization." \
    --next-action "Reconstruct current ChatGPT-API implementation state and test coverage, then execute the next independent, authorized implementation or verification task."
fi

# Dry run: no provider command is sent.
sudo -n runuser -u "$USER_ID" -- env HOME="$HOME_DIR" USER="$USER_ID" /usr/bin/python3 "$SUPERVISOR"
# Enable only after a human explicitly requested continuation and confirmed
# the old cron is gone. Neither controller changes provider auth/grant state.
sudo -n runuser -u "$USER_ID" -- env HOME="$HOME_DIR" USER="$USER_ID" /usr/bin/python3 "$CLI" enable --thread "$THREAD"
sudo -n systemctl --machine="$USER_ID@.host" --user enable --now claudex-governor.timer
sudo -n systemctl --machine="$USER_ID@.host" --user is-active claudex-governor.timer
echo "GOAL_GOVERNOR_AUTONOMOUS_CONTINUATION_ACTIVE=PASS"
