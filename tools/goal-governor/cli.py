#!/usr/bin/env python3
"""User/worker CLI for a goal governed by the independent T3 supervisor."""
from __future__ import annotations
import argparse, importlib.util, json, os, sys
from pathlib import Path
import state

RECOVERY=Path(os.environ.get("CLAUDEX_RECOVERY_PY",
    str(Path.home()/".local/share/claudex/recovery/controller.py")))

def project_for(thread):
    if not RECOVERY.is_file():raise RuntimeError("Claudex recovery module not installed")
    spec=importlib.util.spec_from_file_location("goal_cli_t3_recovery",str(RECOVERY))
    module=importlib.util.module_from_spec(spec)
    sys.modules[spec.name]=module
    spec.loader.exec_module(module)
    with module.db_connect() as db:
        row=db.execute("""SELECT t.project_id,p.workspace_root,s.provider_name,
                          s.provider_instance_id FROM projection_threads t
                          JOIN projection_projects p ON p.project_id=t.project_id
                          JOIN projection_thread_sessions s ON s.thread_id=t.thread_id
                          WHERE t.thread_id=?""",(thread,)).fetchone()
    if not row or row["provider_name"]!="claudeAgent" or row["provider_instance_id"]!="claudex":
        raise ValueError("thread is not Claudex")
    return row

def run():
    parser=argparse.ArgumentParser(description="Durable Goal Governor (opt-in, no loops)")
    subs=parser.add_subparsers(dest="op",required=True)
    create=subs.add_parser("init",help="Enroll existing Claudex thread, initially disabled")
    create.add_argument("--thread",required=True)
    create.add_argument("--workspace",required=True)
    create.add_argument("--title",required=True)
    create.add_argument("--acceptance",action="append",required=True)
    create.add_argument("--next-action",required=True)
    update=subs.add_parser("checkpoint",help="Record progress and verified next step")
    update.add_argument("--thread",required=True)
    update.add_argument("--next-action",required=True)
    update.add_argument("--evidence",required=True)
    update.add_argument("--artifact",required=True)
    update.add_argument("--expected-revision",type=int)
    for command in ("status","enable","disable","resume","pause","block"):
        x=subs.add_parser(command);x.add_argument("--thread",required=True)
        if command=="block":x.add_argument("--reason",required=True)
    review=subs.add_parser("propose-complete")
    review.add_argument("--thread",required=True)
    review.add_argument("--evidence",required=True)
    args=parser.parse_args()
    with state.locked():
        if args.op=="init":
            db=project_for(args.thread)
            if Path(args.workspace).resolve(strict=True)!=Path(db["workspace_root"]).resolve(strict=True):
                raise ValueError("project workspace mismatch")
            obj=state.create(args.thread,db["project_id"],args.workspace,args.title,
                args.acceptance,args.next_action)
        elif args.op=="status":
            obj=state.load(args.thread)
            print(json.dumps({key:obj.get(key) for key in
                ("title","status","auto_enabled","acceptance","revision","next_action",
                 "evidence","artifact","blocked_reason","completion_proposal")},indent=2))
            return
        elif args.op=="checkpoint":
            obj=state.checkpoint(args.thread,args.next_action,args.evidence,args.artifact,
                args.expected_revision)
        elif args.op=="propose-complete":
            obj=state.mark_review(args.thread,args.evidence)
        elif args.op=="block":
            obj=state.state_change(args.thread,"blocked",args.reason)
        elif args.op in ("pause","resume"):
            obj=state.state_change(args.thread,
                {"pause":"paused","resume":"active"}[args.op])
        elif args.op in ("enable","disable"):
            obj=state.enabled(args.thread,args.op=="enable")
        else:
            raise ValueError("unknown operation")
        print(json.dumps({"result":"ok","status":obj["status"],"revision":obj["revision"],
                          "auto_enabled":obj["auto_enabled"],"thread_suffix":obj["thread_id"][-8:]}))

if __name__=="__main__":
    try:run()
    except (ValueError,RuntimeError,OSError,BlockingIOError) as error:
        print(json.dumps({"result":"error","type":type(error).__name__}),file=sys.stderr)
        sys.exit(2)
