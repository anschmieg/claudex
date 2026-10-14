#!/usr/bin/env python3
"""Read-only SessionStart hook. No remote calls, model tokens, or goal mutations."""
import json,os,sys
from pathlib import Path

def main():
    try:
        event=json.load(sys.stdin)
        if not isinstance(event,dict) or event.get("hook_event_name")!="SessionStart":return
        cwd=event.get("cwd")
        if not isinstance(cwd,str):return
        root=Path(os.environ.get("CLAUDEX_GOAL_HOME",str(Path.home()/".local/state/claudex-governor")))/"goals"
        if not root.is_dir() or root.is_symlink():return
        relevant=[]
        for file in root.glob("*.json"):
            if file.is_symlink() or file.stat().st_size>100000:continue
            try:
                d=json.loads(file.read_text())
                if d.get("workspace")==str(Path(cwd).resolve()) and d.get("auto_enabled") and d.get("status")=="active":
                    relevant.append(d)
            except (ValueError,OSError):continue
        if len(relevant)!=1:return
        goal=relevant[0]
        # Hook output is bounded and never discloses original user prompts.
        message=("Durable Goal Governor active (rev %d). Work on the existing goal. "
                 "Inspect it with the goal-governor status skill. Before ending "
                 "a productive turn, record an evidence-backed checkpoint with "
                 "a DIFFERENT next step using the CLI. Do not create /loop, "
                 "CronCreate or ScheduleWakeup. Block explicitly on approvals; "
                 "propose completion only after verification.")%goal["revision"]
        print(message[:650])
    except (OSError,ValueError,TypeError,KeyError):pass

if __name__=="__main__":main()
